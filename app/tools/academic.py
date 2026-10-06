"""The eight academic tools. Pure code over SQLite + the rule registry."""

from __future__ import annotations

import math

from app import db
from app.models import ToolResult
from app.rules import RuleNotFound, rule_bool, rule_number
from app.tools.base import ToolContext, pct, resolve_course

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def _session_key(session: str) -> tuple[int, int]:
    """'2026-MAY' -> (2026, 5) so sessions sort in time order."""
    year, _, month = session.partition("-")
    return (int(year) if year.isdigit() else 0, MONTHS.get(month.upper()[:3], 0))


def _fail(tool: str, msg: str) -> ToolResult:
    return ToolResult(tool=tool, ok=False, error=msg)


def _latest_results(ctx: ToolContext) -> dict[str, dict]:
    """Latest result per course (a later PASS clears an earlier FAIL)."""
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT r.*, c.course_name, c.credits FROM results r "
            "LEFT JOIN courses c ON c.course_code = r.course_code WHERE r.student_id = ?",
            (ctx.student_id,))]
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: _session_key(r["exam_session"])):
        latest[r["course_code"]] = r
    return latest


# ------------------------------------------------------------- profile --
def get_student_profile(ctx: ToolContext) -> ToolResult:
    p = ctx.profile()
    return ToolResult(tool="get_student_profile", data={
        "programme": p["programme"], "batch_year": p["batch_year"],
        "current_semester": p["current_semester"], "cgpa": p["cgpa"],
        "active_backlogs": p["active_backlogs"],
    })


# ---------------------------------------------------------- attendance --
def get_attendance(ctx: ToolContext, course_code: str | None = None) -> ToolResult:
    code = resolve_course(ctx, course_code)
    if course_code and not code:
        return _fail("get_attendance", f"course '{course_code}' not found")
    sql = ("SELECT a.course_code, c.course_name, a.classes_held, a.classes_attended "
           "FROM attendance a LEFT JOIN courses c ON c.course_code = a.course_code WHERE a.student_id = ?")
    params: list = [ctx.student_id]
    if code:
        sql += " AND a.course_code = ?"
        params.append(code)
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(sql, params)]
    if code and not rows:
        return _fail("get_attendance", f"no attendance record for {code}")
    for r in rows:
        r["attendance_pct"] = pct(r["classes_attended"], r["classes_held"])
    data = rows[0] if code else {"courses": rows}
    return ToolResult(tool="get_attendance", data=data)


def _relaxations_used(ctx: ToolContext) -> int:
    with db.session() as conn:
        row = conn.execute("SELECT count_used FROM attendance_relaxations WHERE student_id = ?",
                           (ctx.student_id,)).fetchone()
    return int(row["count_used"]) if row else 0


def _eligibility_for(ctx: ToolContext, row: dict, assume_pct: float | None) -> tuple[dict, list[str]]:
    r_min = ctx.rule("min_attendance_pct")
    r_dean = ctx.rule("max_relaxation_dean_pct")
    r_comm = ctx.rule("max_relaxation_committee_pct")
    r_floor = ctx.rule("absolute_min_attendance_pct")
    r_cap = ctx.rule("max_relaxations_per_programme")
    minimum, dean, comm = rule_number(r_min), rule_number(r_dean), rule_number(r_comm)
    floor, cap = rule_number(r_floor), int(rule_number(r_cap))

    held, attended = row["classes_held"], row["classes_attended"]
    p = assume_pct if assume_pct is not None else pct(attended, held)
    used = _relaxations_used(ctx)
    classes_short = max(0, math.ceil(minimum / 100 * held - 1e-9) - attended)
    rule_ids = [r_min.rule_id]

    if p >= minimum:
        result, why = "ELIGIBLE", f"{p}% meets the {minimum:g}% minimum"
    elif p < floor:
        result, why = "NOT_ELIGIBLE", f"{p}% is below the absolute floor of {floor:g}% even after relaxation"
        rule_ids.append(r_floor.rule_id)
    elif used >= cap:
        result, why = "NOT_ELIGIBLE", f"below {minimum:g}% and relaxation already used {used} of {cap} times"
        rule_ids.append(r_cap.rule_id)
    elif p >= minimum - dean:
        result, why = "ELIGIBLE_WITH_RELAXATION", (
            f"{p}% is below {minimum:g}% but within the Dean's relaxation of up to {dean:g}%; "
            "supporting documents must reach the HoD within 7 days of resuming studies")
        rule_ids += [r_dean.rule_id, r_cap.rule_id]
    elif p >= minimum - dean - comm:
        result, why = "ELIGIBLE_WITH_COMMITTEE_RELAXATION", (
            f"{p}% needs the Dean's relaxation plus a further {comm:g}% on a committee's recommendation")
        rule_ids += [r_dean.rule_id, r_comm.rule_id, r_cap.rule_id]
    else:
        result, why = "NOT_ELIGIBLE", f"{p}% is below what relaxation allows"
        rule_ids.append(r_floor.rule_id)

    data = {
        "course_code": row["course_code"], "course_name": row.get("course_name"),
        "classes_held": held, "classes_attended": attended, "attendance_pct": p,
        "minimum_pct": minimum, "classes_short": classes_short,
        "relaxations_used": used, "relaxations_allowed": cap,
        "result": result, "reason": why,
    }
    if result == "NOT_ELIGIBLE":
        data["consequence"] = "FD grade (fail due to detention); the course must be registered again"
    return data, rule_ids


def check_exam_eligibility(ctx: ToolContext, course_code: str | None = None,
                           assume_attendance_pct: float | None = None) -> ToolResult:
    att = get_attendance(ctx, course_code)
    if not att.ok:
        return ToolResult(tool="check_exam_eligibility", ok=False, error=att.error)
    rows = [att.data] if course_code else att.data["courses"]
    try:
        out, rule_ids = [], []
        for row in rows:
            data, ids = _eligibility_for(ctx, row, assume_attendance_pct)
            out.append(data)
            rule_ids += [i for i in ids if i not in rule_ids]
    except RuleNotFound as exc:
        return _fail("check_exam_eligibility", str(exc))
    assumptions = ([f"Assumed attendance of {assume_attendance_pct}%"]
                   if assume_attendance_pct is not None else [])
    data = out[0] if course_code else {"courses": out}
    return ToolResult(tool="check_exam_eligibility", data=data, rule_ids=rule_ids, assumptions=assumptions)


# ------------------------------------------------------------- results --
def get_results(ctx: ToolContext, course_code: str | None = None) -> ToolResult:
    code = resolve_course(ctx, course_code)
    if course_code and not code:
        return _fail("get_results", f"course '{course_code}' not found")
    latest = _latest_results(ctx)
    if code:
        if code not in latest:
            return _fail("get_results", f"no result for {code}")
        return ToolResult(tool="get_results", data=latest[code])
    return ToolResult(tool="get_results", data={"courses": list(latest.values())})


def check_course_pass(ctx: ToolContext, course_code: str) -> ToolResult:
    res = get_results(ctx, course_code)
    if not res.ok:
        return ToolResult(tool="check_course_pass", ok=False, error=res.error)
    r = res.data
    try:
        ese_rule = ctx.rule("min_ese_pct_per_component")
        ese_max_rule = ctx.rule("ese_max_marks_theory")
        agg_rule = ctx.rule("min_marks_grade_d_absolute")
    except RuleNotFound as exc:
        return _fail("check_course_pass", str(exc))
    scale = (r["max_marks"] or 100) / 100
    ese_max = rule_number(ese_max_rule) * scale
    data = {"course_code": r["course_code"], "course_name": r.get("course_name"),
            "exam_session": r["exam_session"], "recorded_result": r["result"]}
    if r["result"] in {"ABSENT", "DETAINED"}:
        data.update(passed=False, reason=(
            "absent from the end-semester exam (Ab grade)" if r["result"] == "ABSENT"
            else "detained for shortage of attendance (FD grade)"))
        return ToolResult(tool="check_course_pass", data=data, rule_ids=[])
    ese_pct = pct(r["external_marks"] or 0, ese_max)
    ese_ok = ese_pct >= rule_number(ese_rule)
    total_ok = (r["total_marks"] or 0) >= rule_number(agg_rule) * scale
    data.update(
        internal_marks=r["internal_marks"], external_marks=r["external_marks"],
        total_marks=r["total_marks"], max_marks=r["max_marks"],
        ese_pct=ese_pct, ese_min_pct=rule_number(ese_rule),
        passed=r["result"] == "PASS",
        reason=("meets the end-semester and aggregate minimums" if ese_ok and total_ok else
                f"end-semester score {ese_pct}% is below the {rule_number(ese_rule):g}% minimum" if not ese_ok else
                f"total {r['total_marks']} is below the {rule_number(agg_rule) * scale:g} needed for grade D"),
        consistent_with_rules=(r["result"] == "PASS") == (ese_ok and total_ok),
    )
    return ToolResult(tool="check_course_pass", data=data,
                      rule_ids=[ese_rule.rule_id, ese_max_rule.rule_id, agg_rule.rule_id])


def check_backlog_path(ctx: ToolContext, course_code: str | None = None) -> ToolResult:
    """What a student can do about failed courses (NSUT: re-register, no supplementary)."""
    latest = _latest_results(ctx)
    failed = [r for r in latest.values() if r["result"] != "PASS"]
    if course_code:
        code = resolve_course(ctx, course_code)
        failed = [r for r in failed if r["course_code"] == code]
    try:
        supp = ctx.rule("supplementary_exam_available")
    except RuleNotFound as exc:
        return _fail("check_backlog_path", str(exc))
    try:
        summer = ctx.rule("min_registrations_summer_semester")
        summer_text = f"Or take it in a summer semester, which runs only if at least {rule_number(summer):g} students register."
    except RuleNotFound:  # e.g. two sources disagree; say so instead of failing the whole answer
        summer = None
        summer_text = "A summer semester may also be possible; the minimum class size is unclear in current sources."
    if rule_bool(supp):
        options = [f"A supplementary/make-up examination is available ({supp.source_doc_id} {supp.source_section})."]
    else:
        options = [
            "There is no supplementary examination; the course must be registered again.",
            "Re-register in a subsequent year when the course is offered.",
            summer_text,
            "An elective (not a core/foundation course) may be replaced by a different elective.",
        ]
    data = {
        "failed_courses": [{"course_code": r["course_code"], "course_name": r.get("course_name"),
                            "result": r["result"], "exam_session": r["exam_session"]} for r in failed],
        "supplementary_exam_available": rule_bool(supp),
        "options": options,
    }
    return ToolResult(tool="check_backlog_path", data=data,
                      rule_ids=[supp.rule_id] + ([summer.rule_id] if summer else []))


# ------------------------------------------------------ placement, degree --
def check_placement_eligibility(ctx: ToolContext, assume_pass: list[str] | None = None) -> ToolResult:
    latest = _latest_results(ctx)
    failed = {code for code, r in latest.items() if r["result"] != "PASS"}
    assumptions, cleared = [], set()
    for course in assume_pass or []:
        code = resolve_course(ctx, course)
        if code in failed:
            cleared.add(code)
            assumptions.append(f"Assuming you pass {code} when you take it again")
        elif code:
            assumptions.append(f"{code} is not an active backlog, so passing it changes nothing")
    backlogs = int(ctx.profile()["active_backlogs"])
    effective = max(0, backlogs - len(cleared))
    try:
        limit_rule = ctx.rule("max_active_backlogs_placement")
    except RuleNotFound as exc:
        return _fail("check_placement_eligibility", str(exc))
    limit = int(rule_number(limit_rule))
    eligible = effective <= limit
    return ToolResult(tool="check_placement_eligibility", data={
        "active_backlogs_now": backlogs, "active_backlogs_after_assumptions": effective,
        "max_allowed": limit, "result": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
        "note": ("Under the placement policy, a final-year B.Tech student can drop up to this many "
                 "active-backlog subjects (at most 8 credits) when placement CGPA is computed; each "
                 "company also sets its own CGPA and backlog criteria."),
    }, rule_ids=[limit_rule.rule_id], assumptions=assumptions)


def check_degree_status(ctx: ToolContext) -> ToolResult:
    p = ctx.profile()
    try:
        r_deg = ctx.rule("min_cgpa_degree")
        r_first = ctx.rule("min_cgpa_first_division")
        r_dist = ctx.rule("min_cgpa_distinction")
    except RuleNotFound as exc:
        return _fail("check_degree_status", str(exc))
    cgpa = float(p["cgpa"])
    ever_failed = any(r["result"] != "PASS" for r in _latest_results(ctx).values())
    if cgpa >= rule_number(r_dist) and not ever_failed:
        division = "FIRST DIVISION WITH DISTINCTION (if every course is cleared in the first attempt)"
    elif cgpa >= rule_number(r_first):
        division = "FIRST DIVISION"
    elif cgpa >= rule_number(r_deg):
        division = "SECOND DIVISION"
    else:
        division = "below the degree minimum"
    return ToolResult(tool="check_degree_status", data={
        "cgpa": cgpa, "degree_min_cgpa": rule_number(r_deg),
        "meets_degree_cgpa": cgpa >= rule_number(r_deg),
        "projected_division": division,
        "active_backlogs": p["active_backlogs"],
    }, rule_ids=[r_deg.rule_id, r_first.rule_id, r_dist.rule_id],
        assumptions=["Projection uses the current CGPA; the final CGPA uses the best 162 credits"])
