"""Identity and privacy checks that run BEFORE any model call (brief R7).

- The student's identity comes only from the X-Student-Id header.
- A question that names another student (ID, roll number or full name)
  is refused, whatever the wording.
- ``redact`` strips student IDs, roll numbers and emails from log text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import db

STUDENT_ID_RE = re.compile(r"\bS\d{4}\b", re.IGNORECASE)
# NSUT-style roll numbers, e.g. 2023UCS1234
ROLL_RE = re.compile(r"\b20\d{2}U[A-Z]{2,3}\d{3,4}\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
OTHER_PERSON_RE = re.compile(
    r"\b(my friend'?s?|my classmate'?s?|my roommate'?s?|someone else'?s?|another student'?s?)\b.*\b"
    r"(attendance|marks|result|cgpa|grade|backlog)s?\b", re.IGNORECASE)

# Words that mark a question about the asker's own record.
PERSONAL_RE = re.compile(
    r"\b(my|mine|am i|did i|can i|have i|do i have|i failed|i passed|i have|i got)\b", re.IGNORECASE)


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    student: dict | None = None


def looks_personal(question: str) -> bool:
    return bool(PERSONAL_RE.search(question))


def check(question: str, student_id: str | None) -> GuardResult:
    student = None
    if student_id:
        student_id = student_id.strip().upper()
        with db.session() as conn:
            row = conn.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
        if row is None:
            return GuardResult(False, f"Student ID {student_id} is not recognised.")
        student = dict(row)

    mentioned = {m.upper() for m in STUDENT_ID_RE.findall(question)}
    if mentioned - ({student_id} if student_id else set()):
        return GuardResult(False, "I can only share your own records, not another student's.", student)
    if ROLL_RE.search(question):
        return GuardResult(False, "I can only share your own records, not another student's.", student)
    if OTHER_PERSON_RE.search(question):
        return GuardResult(False, "I can only share your own records, not another student's.", student)

    # Another student's full name in the question.
    with db.session() as conn:
        names = [r["full_name"] for r in conn.execute(
            "SELECT full_name FROM students WHERE student_id != ?", (student_id or "",))]
    q = question.lower()
    if any(len(n) > 5 and n.lower() in q for n in names):
        return GuardResult(False, "I can only share your own records, not another student's.", student)

    return GuardResult(True, "", student)


def redact(text: str) -> str:
    """For logs: hide IDs, roll numbers and emails."""
    text = STUDENT_ID_RE.sub("S****", text)
    text = ROLL_RE.sub("[roll]", text)
    return EMAIL_RE.sub("[email]", text)
