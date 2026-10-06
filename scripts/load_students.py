"""Load student CSVs (Annex C schema) into SQLite. Judges use this.

    python scripts/load_students.py --dir test_students/
    python scripts/load_students.py                      # our data/students

The folder may contain students.csv, courses.csv, attendance.csv,
results.csv (any subset) and optionally attendance_relaxations.csv.
Rows are validated first (scripts/validate_data.py); rows with errors are
skipped and reported, everything else is upserted (re-running is safe).
The same function backs POST /admin/load-students.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from scripts.validate_data import read_csv, validate_dir  # noqa: E402

ORDER = ["students", "courses", "attendance", "results"]
KEYS = {
    "students": ["student_id"],
    "courses": ["course_code"],
    "attendance": ["student_id", "course_code"],
    "results": ["student_id", "course_code", "exam_session", "exam_type"],
}
COLUMNS = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa",
                 "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks",
                "external_marks", "total_marks", "max_marks", "result"],
}


def load_dir(folder: Path) -> dict:
    db.init_db()
    with db.session() as conn:
        known_students = {r[0] for r in conn.execute("SELECT student_id FROM students")}
        known_courses = {r[0] for r in conn.execute("SELECT course_code FROM courses")}
    report = validate_dir(folder, known_students=known_students, known_courses=known_courses)

    loaded = {}
    with db.session() as conn:
        for table in ORDER:
            cols = COLUMNS[table]
            rows = [r for i, r in enumerate(report["tables"][table]) if i not in report["bad_rows"][table]]
            updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in KEYS[table])
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                f"ON CONFLICT ({', '.join(KEYS[table])}) DO UPDATE SET {updates}",
                [[(r.get(c) if r.get(c, "") != "" else None) for c in cols] for r in rows],
            )
            loaded[table] = len(rows)
        relax = read_csv(folder / "attendance_relaxations.csv")
        conn.executemany("INSERT OR REPLACE INTO attendance_relaxations (student_id, count_used) VALUES (?, ?)",
                         [(r["student_id"], int(r["count_used"])) for r in relax])
        loaded["attendance_relaxations"] = len(relax)
    return {"loaded": loaded, "rejected": report["errors"] + [
        {**w, "note": "loaded with warning"} for w in report["warnings"]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Annex C student CSVs into SQLite")
    parser.add_argument("--dir", type=Path, default=settings.data_dir / "students")
    args = parser.parse_args(argv)
    result = load_dir(args.dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
