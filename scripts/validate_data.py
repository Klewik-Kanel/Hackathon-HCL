"""Validate student data CSVs against the Annex C schema and logical rules.

    python scripts/validate_data.py --dir data/students
    python scripts/validate_data.py --dir test_students/ --out report.json

Checks
------
errors (row is rejected by the loader):
  - required columns present, required values non-empty
  - student_id format S + 4 digits; numbers parse
  - classes_held > 0 and 0 <= classes_attended <= classes_held
  - marks are non-negative and internal + external <= max_marks
  - total_marks = internal_marks + external_marks
  - result is PASS, FAIL, ABSENT or DETAINED; exam_type REGULAR/SUPPLEMENTARY
  - every student_id / course_code referenced exists
  - semester 1-10, CGPA 0-10, active_backlogs >= 0
warnings (row is loaded but reported):
  - result does not match the marks under the pass rules
  - active_backlogs does not match the number of uncleared courses
  - course programme differs from the student's programme

Pass thresholds come from data/rule_registry.csv (clauses 12.7, Table 1,
Table 5), not from constants here.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa",
                 "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks",
                "external_marks", "total_marks", "max_marks", "result"],
}
RESULTS = {"PASS", "FAIL", "ABSENT", "DETAINED"}
EXAM_TYPES = {"REGULAR", "SUPPLEMENTARY"}
SID_RE = re.compile(r"^S\d{4}$")


def _pass_rules(rule_file: Path) -> dict[str, float]:
    wanted = {"min_ese_pct_per_component": 30.0, "ese_max_marks_theory": 50.0, "min_marks_grade_d_absolute": 35.0}
    if rule_file.exists():
        with rule_file.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["parameter"] in wanted and row["source_doc_id"] == "NSUT-BTECH-REG-2019":
                    wanted[row["parameter"]] = float(row["value"])
    return wanted


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(fh)]


def _int(v: str) -> int | None:
    try:
        return int(float(v))
    except ValueError:
        return None


def validate_dir(folder: Path, rule_file: Path | None = None, known_students: set[str] | None = None,
                 known_courses: set[str] | None = None) -> dict:
    """Return {"tables": {...rows}, "errors": [...], "warnings": [...], "bad_rows": {table: set(idx)}}."""
    rules = _pass_rules(rule_file or Path(os.getenv("DATA_DIR", ROOT / "data")) / "rule_registry.csv")
    tables = {name: read_csv(folder / f"{name}.csv") for name in REQUIRED}
    errors: list[dict] = []
    warnings: list[dict] = []
    bad: dict[str, set[int]] = {name: set() for name in REQUIRED}

    def err(table: str, i: int, msg: str) -> None:
        errors.append({"table": table, "row": i + 2, "error": msg})  # +2: header + 1-based
        bad[table].add(i)

    def warn(table: str, i: int, msg: str) -> None:
        warnings.append({"table": table, "row": i + 2, "warning": msg})

    for name, rows in tables.items():
        if rows:
            missing = [c for c in REQUIRED[name] if c not in rows[0]]
            if missing:
                errors.append({"table": name, "row": 1, "error": f"missing columns {missing}"})
                bad[name] = set(range(len(rows)))
                continue
        for i, row in enumerate(rows):
            for col in REQUIRED[name]:
                if row.get(col, "") == "" and col not in {"internal_marks", "external_marks", "total_marks"}:
                    err(name, i, f"{col} is empty")

    students = {r["student_id"]: r for i, r in enumerate(tables["students"]) if i not in bad["students"]}
    courses = {r["course_code"]: r for i, r in enumerate(tables["courses"]) if i not in bad["courses"]}
    all_students = set(students) | (known_students or set())
    all_courses = set(courses) | (known_courses or set())

    for i, r in enumerate(tables["students"]):
        if i in bad["students"]:
            continue
        if not SID_RE.match(r["student_id"]):
            err("students", i, f"student_id {r['student_id']!r} is not S + 4 digits")
        sem, back = _int(r["current_semester"]), _int(r["active_backlogs"])
        try:
            cgpa = float(r["cgpa"])
        except ValueError:
            cgpa = -1
        if sem is None or not 1 <= sem <= 10:
            err("students", i, f"current_semester {r['current_semester']} not in 1-10")
        if not 0 <= cgpa <= 10:
            err("students", i, f"cgpa {r['cgpa']} not in 0-10")
        if back is None or back < 0:
            err("students", i, f"active_backlogs {r['active_backlogs']} must be >= 0")
        if _int(r["batch_year"]) is None:
            err("students", i, "batch_year is not a year")

    for i, r in enumerate(tables["attendance"]):
        if i in bad["attendance"]:
            continue
        held, att = _int(r["classes_held"]), _int(r["classes_attended"])
        if r["student_id"] not in all_students:
            err("attendance", i, f"unknown student {r['student_id']}")
        if r["course_code"] not in all_courses:
            err("attendance", i, f"unknown course {r['course_code']}")
        if held is None or held <= 0:
            err("attendance", i, "classes_held must be > 0")
        elif att is None or att < 0 or att > held:
            err("attendance", i, f"classes_attended {r['classes_attended']} not within 0..{held}")
        if r["student_id"] in students and r["course_code"] in courses and \
                courses[r["course_code"]]["programme"] != students[r["student_id"]]["programme"]:
            warn("attendance", i, "course belongs to a different programme")

    uncleared: dict[str, dict[str, tuple]] = {}
    for i, r in enumerate(tables["results"]):
        if i in bad["results"]:
            continue
        if r["student_id"] not in all_students:
            err("results", i, f"unknown student {r['student_id']}")
        if r["course_code"] not in all_courses:
            err("results", i, f"unknown course {r['course_code']}")
        if r["result"] not in RESULTS:
            err("results", i, f"result {r['result']!r} not in {sorted(RESULTS)}")
        if r["exam_type"] not in EXAM_TYPES:
            err("results", i, f"exam_type {r['exam_type']!r} not in {sorted(EXAM_TYPES)}")
        internal, external = _int(r["internal_marks"] or "0"), _int(r["external_marks"] or "0")
        total, max_m = _int(r["total_marks"] or "0"), _int(r["max_marks"])
        if None in (internal, external, total, max_m) or max_m <= 0:
            err("results", i, "marks must be numbers and max_marks > 0")
            continue
        if internal < 0 or external < 0 or internal + external > max_m:
            err("results", i, f"marks out of range: {internal}+{external} > {max_m}")
        if total != internal + external:
            err("results", i, f"total_marks {total} != internal {internal} + external {external}")
        if r["result"] in {"PASS", "FAIL"}:
            scale = max_m / 100
            ese_ok = external >= rules["min_ese_pct_per_component"] / 100 * rules["ese_max_marks_theory"] * scale
            total_ok = total >= rules["min_marks_grade_d_absolute"] * scale
            expected = "PASS" if ese_ok and total_ok else "FAIL"
            if r["result"] != expected:
                warn("results", i, f"result {r['result']} but marks imply {expected}")
        if r["result"] == "ABSENT" and external != 0:
            warn("results", i, "ABSENT but external_marks is not 0")
        uncleared.setdefault(r["student_id"], {})[r["course_code"]] = (r["exam_session"], r["result"])

    for i, r in enumerate(tables["students"]):
        if i in bad["students"]:
            continue
        n = sum(1 for _, res in uncleared.get(r["student_id"], {}).values() if res != "PASS")
        if r["student_id"] in uncleared and _int(r["active_backlogs"]) != n:
            warn("students", i, f"active_backlogs {r['active_backlogs']} but {n} uncleared course(s) in results")

    return {"tables": tables, "errors": errors, "warnings": warnings, "bad_rows": bad}


def summary(report: dict) -> dict:
    return {
        "rows": {k: len(v) for k, v in report["tables"].items()},
        "errors": report["errors"],
        "warnings": report["warnings"],
        "ok": not report["errors"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate student CSVs (Annex C)")
    parser.add_argument("--dir", type=Path, default=ROOT / "data" / "students")
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args(argv)
    result = summary(validate_dir(args.dir))
    print(f"Rows: {result['rows']}")
    print(f"Errors: {len(result['errors'])}  Warnings: {len(result['warnings'])}")
    for e in result["errors"][:30]:
        print(f"  ERROR   {e['table']} row {e['row']}: {e['error']}")
    for w in result["warnings"][:30]:
        print(f"  WARNING {w['table']} row {w['row']}: {w['warning']}")
    out = args.out or args.dir / "validation_report.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"Report written to {out}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
