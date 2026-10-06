"""The data validator catches planted errors and the loader skips bad rows."""

import csv
from pathlib import Path

from scripts.validate_data import validate_dir

ROOT = Path(__file__).resolve().parents[1]


def _write(folder: Path, name: str, rows: list[dict]) -> None:
    with (folder / f"{name}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_our_generated_data_is_clean():
    report = validate_dir(ROOT / "data" / "students")
    assert report["errors"] == [] and report["warnings"] == []
    assert len(report["tables"]["students"]) >= 30


def test_planted_errors_are_caught(tmp_path):
    _write(tmp_path, "students", [
        {"student_id": "S9001", "full_name": "Test One", "programme": "B.Tech CSE", "batch_year": "2024",
         "current_semester": "5", "cgpa": "7.5", "active_backlogs": "0"},
        {"student_id": "X12", "full_name": "Bad Id", "programme": "B.Tech CSE", "batch_year": "2024",
         "current_semester": "11", "cgpa": "11", "active_backlogs": "-1"},
    ])
    _write(tmp_path, "courses", [{"course_code": "JDG101", "course_name": "Judge Course", "programme": "B.Tech CSE",
                                  "semester": "5", "credits": "4"}])
    _write(tmp_path, "attendance", [
        {"student_id": "S9001", "course_code": "JDG101", "classes_held": "40", "classes_attended": "41"},
        {"student_id": "S9001", "course_code": "NOPE1", "classes_held": "0", "classes_attended": "0"},
    ])
    _write(tmp_path, "results", [
        {"student_id": "S9001", "course_code": "JDG101", "exam_session": "2026-MAY", "exam_type": "REGULAR",
         "internal_marks": "30", "external_marks": "20", "total_marks": "55", "max_marks": "100", "result": "PASS"},
        {"student_id": "S9001", "course_code": "JDG101", "exam_session": "2025-DEC", "exam_type": "REGULAR",
         "internal_marks": "30", "external_marks": "10", "total_marks": "40", "max_marks": "100", "result": "PASS"},
    ])
    report = validate_dir(tmp_path)
    messages = " | ".join(e["error"] for e in report["errors"])
    assert "not S + 4 digits" in messages
    assert "current_semester" in messages and "cgpa" in messages and "active_backlogs" in messages
    assert "not within 0..40" in messages          # attended > held
    assert "classes_held must be > 0" in messages
    assert "unknown course NOPE1" in messages
    assert "total_marks 55 != internal 30 + external 20" in messages
    assert any("marks imply FAIL" in w["warning"] for w in report["warnings"])  # 10/50 = 20% < 30%
