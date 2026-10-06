"""Deterministic stand-ins for the two LLM steps.

Used in two situations:
1. MOCK_LLM=true: tests and development without Ollama.
2. Safety net: if the real model returns invalid JSON twice, the graph
   falls back to these so the user still gets a correct (if plainer)
   answer instead of an error.

They are deliberately simple keyword rules. They are NOT a replacement for
the model on open-ended questions; they keep the system honest and
available.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app import db
from app.guard import looks_personal
from app.text import overlap


class PlannedTool(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


class Plan(BaseModel):
    category: str = "policy_fact"
    course: str | None = None
    needs_docs: bool = True
    tools: list[PlannedTool] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    clarification_question: str | None = None


class Composed(BaseModel):
    answer: str = ""
    explanation: str = ""
    cited_ids: list[str] = Field(default_factory=list)
    insufficient: bool = False


COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,3})\s?(\d{3})\b", re.IGNORECASE)


def find_course(question: str, programme: str | None) -> str | None:
    m = COURSE_CODE_RE.search(question)
    if m:
        return (m.group(1) + m.group(2)).upper()
    with db.session() as conn:
        sql = "SELECT course_code, course_name FROM courses"
        params: tuple = ()
        if programme:
            sql += " WHERE programme = ?"
            params = (programme,)
        rows = conn.execute(sql, params).fetchall()
    q = question.lower()
    for r in sorted(rows, key=lambda r: -len(r["course_name"])):
        if r["course_name"].lower() in q:
            return r["course_code"]
    return None


def _has(q: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", q) for w in words)


def plan(question: str, student: dict | None) -> Plan:
    q = question.lower()
    personal = looks_personal(question)
    # "Can I take X if I was absent?" with nobody logged in is a general procedure question.
    if student is None and re.search(r"\bif\b", q) and not re.search(r"\b(my|mine)\b", q):
        personal = False
    course = find_course(question, student["programme"] if student else None)
    tools: list[PlannedTool] = []
    assumptions: list[str] = []

    if personal:
        if _has(q, "placement", "placed", "recruit"):
            assume = [course] if course and _has(q, "if i pass", "if i clear", "pass the", "after passing") else []
            if assume:
                assumptions.append(f"Assuming you pass {course}")
            tools.append(PlannedTool(name="check_placement_eligibility", args={"assume_pass": assume}))
            if _has(q, "fail", "backlog", "supplementary", "re-?appear"):
                tools.insert(0, PlannedTool(name="check_backlog_path", args={"course_code": course}))
        elif _has(q, "supplementary", "make-?up", "re-?appear", "backlog", "clear"):
            tools.append(PlannedTool(name="check_backlog_path", args={"course_code": course}))
        elif _has(q, "attendance", "attend", "classes", "shortage"):
            if _has(q, "eligib", "allowed", "sit", "appear", "exam", "detain"):
                tools.append(PlannedTool(name="check_exam_eligibility", args={"course_code": course}))
            else:
                tools.append(PlannedTool(name="get_attendance", args={"course_code": course}))
        elif _has(q, "eligib", "allowed to sit", "can i sit", "appear"):
            tools.append(PlannedTool(name="check_exam_eligibility", args={"course_code": course}))
        elif _has(q, "pass", "fail", "marks", "result", "grade"):
            tools.append(PlannedTool(name="check_course_pass" if course else "get_results",
                                     args={"course_code": course}))
        elif _has(q, "degree", "division", "distinction", "graduate"):
            tools.append(PlannedTool(name="check_degree_status"))
        elif _has(q, "cgpa", "backlog", "semester", "profile"):
            tools.append(PlannedTool(name="get_student_profile"))

    needs_course = {"check_course_pass"}
    ambiguous = any(t.name in needs_course and not t.args.get("course_code") for t in tools)
    vague = _has(q, "the exam", "this course", "the course", "that course", "the subject", "this subject")
    if tools and not course and vague:
        ambiguous = True

    pure_lookup = len(tools) == 1 and tools[0].name in {"get_attendance", "get_results", "get_student_profile"}
    category = ("multi_step" if len(tools) > 1 else
                "personal_eligibility" if tools and tools[0].name.startswith("check") else
                "personal_data" if tools else
                "procedure" if _has(q, "how do i", "how to", "how can i", "procedure", "apply") else
                "policy_fact")
    return Plan(
        category=category, course=course, needs_docs=not pure_lookup, tools=tools,
        assumptions=assumptions, ambiguous=ambiguous,
        clarification_question="Which course do you mean? Please give the course code or name." if ambiguous else None,
    )


def _fmt_tool(tool: str, data: dict) -> str:
    if tool == "check_exam_eligibility" and "result" in data:
        return (f"Your attendance in {data['course_code']} is {data['attendance_pct']}% "
                f"({data['classes_attended']} of {data['classes_held']} classes): "
                f"{data['result'].replace('_', ' ').lower()}, because {data['reason']}.")
    if tool == "get_attendance" and "attendance_pct" in data:
        return (f"Your attendance in {data['course_code']} is {data['attendance_pct']}% "
                f"({data['classes_attended']} of {data['classes_held']} classes).")
    if tool == "check_course_pass" and "passed" in data:
        return (f"{data['course_code']} ({data['exam_session']}): "
                f"{'passed' if data['passed'] else 'not passed'}; {data['reason']}.")
    if tool == "check_backlog_path":
        return " ".join(data.get("options", []))
    if tool == "check_placement_eligibility":
        return (f"Placement: {data['result'].replace('_', ' ').lower()} with "
                f"{data['active_backlogs_after_assumptions']} active backlog(s); the limit is {data['max_allowed']}.")
    if tool in {"get_attendance", "check_exam_eligibility"} and "courses" in data:
        return " ".join(_fmt_tool(tool, c) for c in data["courses"])
    if tool == "get_results" and "courses" in data:
        return "Your latest results: " + "; ".join(
            f"{c['course_code']} {c['result']} ({c['total_marks']}/{c['max_marks']}, {c['exam_session']})"
            for c in data["courses"]) + "."
    if tool == "get_results" and "result" in data:
        return (f"{data['course_code']} ({data['exam_session']}): {data['result']}, "
                f"{data['total_marks']}/{data['max_marks']}.")
    if tool == "get_student_profile":
        return (f"You are in semester {data['current_semester']} of {data['programme']} (batch "
                f"{data['batch_year']}) with a CGPA of {data['cgpa']} and {data['active_backlogs']} active backlog(s).")
    if tool == "check_degree_status":
        return (f"Your CGPA is {data['cgpa']}; the degree needs at least {data['degree_min_cgpa']}. "
                f"Projected: {data['projected_division']}.")
    return json.dumps(data)[:300]


def compose(question: str, evidence: list[dict], tool_results: list[dict], rules_text: list[str],
            assumptions: list[str]) -> Composed:
    """Template answer built only from tool output and the best-matching evidence.

    The clause quoted is the one sharing most words with the question (ties go
    to the earlier one, i.e. the precedence winner). The winning rule's value is
    added only when that clause is the rule's own clause.
    """
    parts = [_fmt_tool(t["tool"], t["data"]) for t in tool_results if t.get("ok")]
    cited = []
    if evidence:
        # The precedence winner's clause gets a head start: it is the authoritative source.
        best = max(evidence, key=lambda e: (overlap(question, e["text"]) + (2 if e.get("winner") else 0),
                                            -evidence.index(e)))
        cited.append(best["id"])
        if not parts:
            text = re.sub(r"\s+", " ", best["text"])
            text = re.sub(r"^[#\s]*[\d.]+\s*", "", text)  # drop the leading clause number
            parts.append(f"According to {best['title']}, clause {best['section']} (page {best['page']}): "
                         f"\"{text[:500]}\"")
            numeric = [r for r in rules_text if best["doc_id"] in r and f"clause {best['section']}," in r
                       and "(= " not in r]
            if numeric:
                parts.append("Rule applied: " + numeric[0].split(" [rule")[0] + ".")
    elif rules_text and not parts:
        parts.append("The rule that applies: " + "; ".join(r.split(" [rule")[0] for r in rules_text) + ".")
    if not parts:
        return Composed(insufficient=True)
    answer = " ".join(parts)
    if assumptions:
        answer += " (" + "; ".join(assumptions) + ".)"
    return Composed(answer=answer, explanation="Answer assembled from the cited clause and the system's records.",
                    cited_ids=cited)


def extract_rules(params: list[str], chunks: list) -> dict:
    """Mock rule extraction: attendance percentages only (for tests)."""
    found = []
    for c in chunks:
        m = re.search(r"(\d{2})\s?%", c.text)
        if m and "attendance" in c.text.lower() and "min_attendance_pct" in params:
            found.append({"parameter": "min_attendance_pct", "operator": ">=", "value": m.group(1),
                          "section": c.section, "quote": c.text[max(0, m.start() - 40): m.end() + 10]})
    return {"rules": found}
