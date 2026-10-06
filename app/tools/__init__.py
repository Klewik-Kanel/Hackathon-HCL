"""Deterministic tools: every authoritative number comes from here.

Rules for every tool (brief R5 and R7):
- ``student_id`` comes from the request context (``ToolContext``), never
  from the LLM. The LLM can only choose WHICH tool and the course.
- every threshold is read from the rule registry via ``get_rule``;
  no threshold is written in this code.
- every result lists the rule_ids it used, so the answer can cite them.
"""

from __future__ import annotations

from app.tools.academic import (
    check_backlog_path,
    check_course_pass,
    check_degree_status,
    check_exam_eligibility,
    check_placement_eligibility,
    get_attendance,
    get_results,
    get_student_profile,
)
from app.tools.base import ToolContext

TOOLS = {
    "get_student_profile": get_student_profile,
    "get_attendance": get_attendance,
    "check_exam_eligibility": check_exam_eligibility,
    "get_results": get_results,
    "check_course_pass": check_course_pass,
    "check_backlog_path": check_backlog_path,
    "check_placement_eligibility": check_placement_eligibility,
    "check_degree_status": check_degree_status,
}

# Shown to the planner LLM so it knows what it may call.
TOOL_DESCRIPTIONS = {
    "get_student_profile": "programme, batch, semester, CGPA, active backlogs. args: none",
    "get_attendance": "classes held/attended and % per course. args: course_code (optional)",
    "check_exam_eligibility": "can the student sit the exam given attendance rules. args: course_code",
    "get_results": "marks and results per course. args: course_code (optional)",
    "check_course_pass": "did the student pass a course and why. args: course_code",
    "check_backlog_path": "options for clearing failed courses (re-registration, summer). args: course_code (optional)",
    "check_placement_eligibility": "placement eligibility from backlogs. args: assume_pass (list of course codes, for what-if)",
    "check_degree_status": "CGPA against degree and division thresholds. args: none",
}


def run_tool(name: str, ctx: ToolContext, args: dict | None = None):
    from app.models import ToolResult

    func = TOOLS.get(name)
    if func is None:
        return ToolResult(tool=name, ok=False, error=f"unknown tool {name}")
    args = {k: v for k, v in (args or {}).items() if k != "student_id"}  # never from the LLM
    try:
        return func(ctx, **args)
    except TypeError as exc:  # LLM passed an argument the tool does not take
        return ToolResult(tool=name, ok=False, error=f"bad arguments: {exc}")


__all__ = ["TOOLS", "TOOL_DESCRIPTIONS", "ToolContext", "run_tool"]
