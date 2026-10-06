"""Every edge-case student gets exactly the expected tool result."""

from datetime import date

from app.tools import ToolContext, run_tool

TODAY = date(2026, 10, 6)


def tool(name, sid, as_of=TODAY, **args):
    return run_tool(name, ToolContext(student_id=sid, as_of=as_of), args)


def test_exactly_75_is_eligible():
    r = tool("check_exam_eligibility", "S1001", course_code="CS301")
    assert r.data["attendance_pct"] == 75.0 and r.data["result"] == "ELIGIBLE"
    assert "ATT-MIN-01" in r.rule_ids


def test_one_class_short_needs_relaxation():
    r = tool("check_exam_eligibility", "S1002", course_code="CS301")
    assert r.data["attendance_pct"] == 74.36
    assert r.data["classes_short"] == 1
    assert r.data["result"] == "ELIGIBLE_WITH_RELAXATION"


def test_below_floor_not_eligible_with_fd_consequence():
    r = tool("check_exam_eligibility", "S1003", course_code="Operating Systems")
    assert r.data["result"] == "NOT_ELIGIBLE" and "FD" in r.data["consequence"]
    assert "ATT-FLOOR-01" in r.rule_ids


def test_relaxation_cap_reached():
    r = tool("check_exam_eligibility", "S1004", course_code="CS301")
    assert r.data["result"] == "NOT_ELIGIBLE" and r.data["relaxations_used"] == 2


def test_threshold_follows_the_date():
    # From 2027 the synthetic circular raises the minimum to 80%, so 75% is no longer enough.
    r = tool("check_exam_eligibility", "S1001", as_of=date(2027, 2, 1), course_code="CS301")
    assert r.data["minimum_pct"] == 80 and r.data["result"] != "ELIGIBLE"
    assert "ATT-MIN-02" in r.rule_ids


def test_fail_by_one_mark_on_ese():
    r = tool("check_course_pass", "S1005", course_code="CS201")
    assert r.data["passed"] is False and r.data["ese_pct"] == 28.0
    assert r.data["consistent_with_rules"] is True


def test_absent_and_detained():
    assert "Ab grade" in tool("check_course_pass", "S1006", course_code="CS203").data["reason"]
    assert "FD grade" in tool("check_course_pass", "S1007", course_code="CS201").data["reason"]


def test_no_supplementary_exam_at_nsut():
    r = tool("check_backlog_path", "S1005", course_code="CS201")
    assert r.data["supplementary_exam_available"] is False
    assert r.data["failed_courses"][0]["course_code"] == "CS201"
    assert "SUPP-EXAM-01" in r.rule_ids


def test_placement_what_if():
    now = tool("check_placement_eligibility", "S1008")
    assert now.data["active_backlogs_now"] == 3 and now.data["result"] == "NOT_ELIGIBLE"
    after = tool("check_placement_eligibility", "S1008", assume_pass=["CS201"])
    assert after.data["active_backlogs_after_assumptions"] == 2 and after.data["result"] == "ELIGIBLE"
    assert after.assumptions


def test_cgpa_boundaries():
    assert tool("check_degree_status", "S1009").data["meets_degree_cgpa"] is True
    assert "DISTINCTION" in tool("check_degree_status", "S1010").data["projected_division"]
    assert tool("check_degree_status", "S1011").data["projected_division"] == "FIRST DIVISION"


def test_llm_cannot_pass_a_student_id():
    r = run_tool("get_attendance", ToolContext(student_id="S1001", as_of=TODAY),
                 {"student_id": "S1007", "course_code": "CS301"})
    assert r.data["classes_attended"] == 30  # still S1001's record


def test_unknown_course_is_an_error_not_a_guess():
    assert tool("get_attendance", "S1001", course_code="Quantum Basket Weaving").ok is False
