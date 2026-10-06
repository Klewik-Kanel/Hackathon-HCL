"""Shared helpers for the tools."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from app import db, rules
from app.models import Rule


@dataclass
class ToolContext:
    student_id: str
    as_of: date
    # Filled from the students table on first use.
    _profile: dict | None = None

    def conn(self) -> sqlite3.Connection:
        return db.connect()

    def profile(self) -> dict:
        if self._profile is None:
            with db.session() as conn:
                row = conn.execute("SELECT * FROM students WHERE student_id = ?", (self.student_id,)).fetchone()
            if row is None:
                raise LookupError(f"Unknown student {self.student_id}")
            self._profile = dict(row)
        return self._profile

    def rule(self, parameter: str) -> Rule:
        """Threshold that applies to THIS student on THIS date."""
        p = self.profile()
        return rules.get_rule(parameter, self.as_of, p["programme"], p["batch_year"])


def resolve_course(ctx: ToolContext, course: str | None) -> str | None:
    """Accept 'CS201', 'cs 201' or 'Data Structures'; return a course_code or None."""
    if not course:
        return None
    code = re.sub(r"\s+", "", course).upper()
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM courses WHERE course_code = ?", (code,)).fetchone():
            return code
        row = conn.execute(
            "SELECT course_code FROM courses WHERE lower(course_name) = lower(?) AND programme = ?",
            (course.strip(), ctx.profile()["programme"]),
        ).fetchone()
        if row:
            return row["course_code"]
        row = conn.execute(
            "SELECT course_code FROM courses WHERE lower(course_name) LIKE lower(?) AND programme = ?",
            (f"%{course.strip()}%", ctx.profile()["programme"]),
        ).fetchone()
    return row["course_code"] if row else None


def pct(part: float, whole: float) -> float:
    return round(part * 100.0 / whole, 2) if whole else 0.0
