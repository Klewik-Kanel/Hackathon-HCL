"""Generate the synthetic student data set (Annex C schema) with the local LLM.

    python scripts/generate_students.py              # uses Ollama (LLM_MODEL)
    python scripts/generate_students.py --offline    # no model: deterministic stand-in

How it works
------------
1. The course catalogue (12 courses, 2 programmes) is fixed in code.
2. Edge-case students S1001-S1011 are written by code with exact numbers,
   because the brief tests boundaries (exactly 75%, one class short, one
   mark below the pass line, ...). An LLM cannot be trusted to hit 30/40
   exactly.
3. The other 29 students are generated one at a time by the LLM from
   prompts/student_gen_v1.txt, each with a profile (strong/average/weak).
   Every reply is validated with Pydantic; invalid replies are retried once.
4. Logical errors the LLM makes (total != internal + external, result not
   matching the marks, attended > held) are counted in the generation log
   and fixed by code, so the data card can report "what the LLM got wrong".
5. scripts/validate_data.py is then run on the output.

Outputs in data/students/: students.csv, courses.csv, attendance.csv,
results.csv, attendance_relaxations.csv, generation_log.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402

OUT = settings.data_dir / "students"
PROMPT = ROOT / "prompts" / "student_gen_v1.txt"

COURSES = [
    # course_code, course_name, programme, semester, credits
    ("CS201", "Data Structures", "B.Tech CSE", 3, 4),
    ("CS203", "Engineering Mathematics III", "B.Tech CSE", 3, 4),
    ("CS301", "Operating Systems", "B.Tech CSE", 5, 4),
    ("CS303", "Database Management Systems", "B.Tech CSE", 5, 4),
    ("CS401", "Machine Learning", "B.Tech CSE", 7, 4),
    ("CS403", "Compiler Design", "B.Tech CSE", 7, 4),
    ("EC201", "Signals and Systems", "B.Tech ECE", 3, 4),
    ("EC203", "Engineering Mathematics III (ECE)", "B.Tech ECE", 3, 4),
    ("EC301", "Analog Communication", "B.Tech ECE", 5, 4),
    ("EC303", "Microprocessors", "B.Tech ECE", 5, 4),
    ("EC401", "Digital Signal Processing", "B.Tech ECE", 7, 4),
    ("EC403", "VLSI Design", "B.Tech ECE", 7, 4),
]
SESSIONS = {3: "2024-DEC", 5: "2025-DEC"}  # when each semester's exams were held


def plan_for(programme: str, batch: int) -> tuple[int, list[str], dict[str, str]]:
    """(current_semester, attendance courses, {result course: session})."""
    prefix = "CS" if programme.endswith("CSE") else "EC"
    if batch == 2024:  # in semester 5 in Oct 2026; finished semester 3
        return 5, [f"{prefix}301", f"{prefix}303"], {f"{prefix}201": "2025-DEC", f"{prefix}203": "2025-DEC"}
    return 7, [f"{prefix}401", f"{prefix}403"], {  # batch 2023: in semester 7
        f"{prefix}201": "2024-DEC", f"{prefix}203": "2024-DEC",
        f"{prefix}301": "2025-DEC", f"{prefix}303": "2025-DEC"}


class GenAttendance(BaseModel):
    course_code: str
    classes_held: int = Field(ge=1)
    classes_attended: int = Field(ge=0)


class GenResult(BaseModel):
    course_code: str
    internal_marks: int = Field(ge=0, le=50)
    external_marks: int = Field(ge=0, le=50)
    total_marks: int
    result: str


class GenStudent(BaseModel):
    full_name: str
    cgpa: float = Field(ge=0, le=10)
    attendance: list[GenAttendance]
    results: list[GenResult]


def outcome(internal: int, external: int) -> str:
    return "PASS" if external >= 15 and internal + external >= 35 else "FAIL"


# --------------------------------------------------------- edge cases --
def edge_cases() -> list[dict]:
    """Students S1001-S1011: each carries one boundary the brief asks for."""
    def base(sid, name, batch=2024, cgpa=7.2, programme="B.Tech CSE"):
        sem, att, res = plan_for(programme, batch)
        return {"student": {"student_id": sid, "full_name": name, "programme": programme, "batch_year": batch,
                            "current_semester": sem, "cgpa": cgpa, "active_backlogs": 0},
                "attendance": {c: (40, 34) for c in att},
                "results": {c: (s, 38, 34) for c, s in res.items()}, "relaxations": 0, "note": ""}

    cases = []
    s = base("S1001", "Aarav Malhotra"); s["attendance"]["CS301"] = (40, 30)
    s["note"] = "attendance exactly 75.00% in CS301"; cases.append(s)
    s = base("S1002", "Ishita Verma"); s["attendance"]["CS301"] = (39, 29)
    s["note"] = "attendance 74.36% in CS301, one class short of 75%"; cases.append(s)
    s = base("S1003", "Kabir Sethi"); s["attendance"]["CS301"] = (39, 23)
    s["note"] = "attendance 58.97% in CS301, below the 60% floor"; cases.append(s)
    s = base("S1004", "Meera Iyer"); s["attendance"]["CS301"] = (40, 28); s["relaxations"] = 2
    s["note"] = "70% in CS301 with both relaxations already used"; cases.append(s)
    s = base("S1005", "Rohan Bhatia"); s["results"]["CS201"] = ("2025-DEC", 35, 14)
    s["note"] = "failed CS201: external 14/50 = 28%, one mark below 30%"; cases.append(s)
    s = base("S1006", "Tanvi Kulkarni"); s["results"]["CS203"] = ("2025-DEC", 30, 0, "ABSENT")
    s["note"] = "ABSENT in CS203"; cases.append(s)
    s = base("S1007", "Arjun Nair"); s["results"]["CS201"] = ("2025-DEC", 20, 0, "DETAINED")
    s["note"] = "DETAINED (FD) in CS201"; cases.append(s)
    s = base("S1008", "Devika Rao", batch=2023, cgpa=6.1)
    s["results"]["CS201"] = ("2024-DEC", 30, 10); s["results"]["CS203"] = ("2024-DEC", 28, 12)
    s["results"]["CS301"] = ("2025-DEC", 32, 13)
    s["note"] = "three active backlogs (CS201, CS203, CS301)"; cases.append(s)
    s = base("S1009", "Nikhil Chauhan", cgpa=5.00); s["note"] = "CGPA exactly 5.00 (degree minimum)"; cases.append(s)
    s = base("S1010", "Priya Menon", cgpa=8.00); s["note"] = "CGPA exactly 8.00 (distinction boundary)"; cases.append(s)
    s = base("S1011", "Sahil Gupta", cgpa=7.99); s["note"] = "CGPA 7.99, just below distinction"; cases.append(s)
    return cases


# -------------------------------------------------------------- others --
OFFLINE_NAMES = [
    "Ananya Sharma", "Vivaan Kapoor", "Diya Reddy", "Aditya Joshi", "Saanvi Mishra", "Reyansh Pillai",
    "Kavya Desai", "Vihaan Bose", "Aditi Saxena", "Krishna Pandit", "Myra Agarwal", "Ayaan Khanna",
    "Riya Chatterjee", "Shaurya Tiwari", "Anika Dutta", "Atharv Bansal", "Navya Ghosh", "Dhruv Mehta",
    "Ira Banerjee", "Arnav Sinha", "Pari Jain", "Yash Rawat", "Sara Fernandes", "Laksh Arora",
    "Tara Hegde", "Om Prakash Yadav", "Zoya Qureshi", "Neel Kaul", "Avni Thakur",
]


def offline_student(rng: random.Random, name: str, att_courses: list[str], res_courses: dict[str, str],
                    profile: str) -> GenStudent:
    lo, hi = {"strong": (0.85, 0.98), "average": (0.78, 0.92), "weak": (0.70, 0.86)}[profile]
    attendance = []
    for c in att_courses:
        held = rng.randint(36, 48)
        attendance.append(GenAttendance(course_code=c, classes_held=held,
                                        classes_attended=min(held, round(held * rng.uniform(lo, hi)))))
    results = []
    for c in res_courses:
        internal = rng.randint(28, 48) if profile != "weak" else rng.randint(18, 40)
        external = rng.randint(22, 46) if profile != "weak" else rng.randint(10, 36)
        results.append(GenResult(course_code=c, internal_marks=internal, external_marks=external,
                                 total_marks=internal + external, result=outcome(internal, external)))
    cgpa = {"strong": rng.uniform(8.0, 9.5), "average": rng.uniform(6.6, 8.0), "weak": rng.uniform(5.6, 6.8)}[profile]
    return GenStudent(full_name=name, cgpa=round(cgpa, 2), attendance=attendance, results=results)


def llm_student(att_courses: list[str], res_courses: dict[str, str], profile: str,
                usage: llm.LLMUsage) -> GenStudent:
    prompt = (PROMPT.read_text(encoding="utf-8")
              .replace("{attendance_courses}", ", ".join(att_courses))
              .replace("{result_courses}", ", ".join(res_courses))
              .replace("{profile}", profile))
    return llm.complete_json(prompt, "Generate the student now.", GenStudent, usage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="no LLM; deterministic stand-in data")
    parser.add_argument("--count", type=int, default=29, help="non-edge-case students to generate")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    usage = llm.LLMUsage()
    log = {"model": "offline-deterministic" if args.offline else settings.llm_model,
           "temperature": settings.llm_temperature, "prompt_file": str(PROMPT.relative_to(ROOT)),
           "llm_calls": 0, "llm_errors_fixed": [], "invalid_json_retries": 0, "edge_cases": {}}

    students, attendance, results, relax = [], [], [], []

    def add(student: dict, att: dict, res: dict, relaxations: int) -> None:
        backlogs = 0
        for code, row in res.items():
            session, internal, external = row[0], row[1], row[2]
            result = row[3] if len(row) > 3 else outcome(internal, external)
            backlogs += result != "PASS"
            results.append({"student_id": student["student_id"], "course_code": code, "exam_session": session,
                            "exam_type": "REGULAR", "internal_marks": internal, "external_marks": external,
                            "total_marks": internal + external, "max_marks": 100, "result": result})
        for code, (held, attended) in att.items():
            attendance.append({"student_id": student["student_id"], "course_code": code,
                               "classes_held": held, "classes_attended": attended})
        student["active_backlogs"] = backlogs
        students.append(student)
        if relaxations:
            relax.append({"student_id": student["student_id"], "count_used": relaxations})

    for case in edge_cases():
        add(case["student"], case["attendance"], case["results"], case["relaxations"])
        log["edge_cases"][case["student"]["student_id"]] = case["note"]

    profiles = ["strong", "average", "average", "weak"]
    for i in range(args.count):
        sid = f"S{1012 + i}"
        programme = "B.Tech CSE" if i < 9 else "B.Tech ECE"   # 20 CSE, 20 ECE in total
        batch = 2024 if i % 2 == 0 else 2023
        sem, att_courses, res_courses = plan_for(programme, batch)
        profile = profiles[i % len(profiles)]
        if args.offline:
            gen = offline_student(rng, OFFLINE_NAMES[i % len(OFFLINE_NAMES)], att_courses, res_courses, profile)
        else:
            calls_before = usage.calls
            try:
                gen = llm_student(att_courses, res_courses, profile, usage)
            except llm.LLMError as exc:
                print(f"{sid}: LLM failed twice ({exc}); using offline stand-in")
                gen = offline_student(rng, OFFLINE_NAMES[i % len(OFFLINE_NAMES)], att_courses, res_courses, profile)
            log["invalid_json_retries"] += max(0, usage.calls - calls_before - 1)

        att, res = {}, {}
        for a in gen.attendance:
            if a.course_code not in att_courses:
                log["llm_errors_fixed"].append(f"{sid}: unexpected course {a.course_code} dropped")
                continue
            attended = a.classes_attended
            if attended > a.classes_held:
                log["llm_errors_fixed"].append(f"{sid}: attended {attended} > held {a.classes_held}; capped")
                attended = a.classes_held
            att[a.course_code] = (a.classes_held, attended)
        for r in gen.results:
            if r.course_code not in res_courses:
                log["llm_errors_fixed"].append(f"{sid}: unexpected course {r.course_code} dropped")
                continue
            if r.total_marks != r.internal_marks + r.external_marks:
                log["llm_errors_fixed"].append(f"{sid} {r.course_code}: total {r.total_marks} != "
                                               f"{r.internal_marks}+{r.external_marks}; recomputed")
            if r.result != outcome(r.internal_marks, r.external_marks):
                log["llm_errors_fixed"].append(f"{sid} {r.course_code}: result {r.result} inconsistent; recomputed")
            res[r.course_code] = (res_courses[r.course_code], r.internal_marks, r.external_marks)
        for c in att_courses:  # the model skipped a course
            if c not in att:
                log["llm_errors_fixed"].append(f"{sid}: missing attendance for {c}; filled")
                att[c] = (40, 34)
        for c, sess in res_courses.items():
            if c not in res:
                log["llm_errors_fixed"].append(f"{sid}: missing result for {c}; filled")
                res[c] = (sess, 36, 30)
        add({"student_id": sid, "full_name": gen.full_name, "programme": programme, "batch_year": batch,
             "current_semester": sem, "cgpa": round(gen.cgpa, 2), "active_backlogs": 0}, att, res, 0)

    log["llm_calls"] = usage.calls
    OUT.mkdir(parents=True, exist_ok=True)

    def write(name: str, rows: list[dict], cols: list[str]) -> None:
        with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    write("courses", [dict(zip(["course_code", "course_name", "programme", "semester", "credits"], c))
                      for c in COURSES], ["course_code", "course_name", "programme", "semester", "credits"])
    write("students", students, ["student_id", "full_name", "programme", "batch_year", "current_semester",
                                 "cgpa", "active_backlogs"])
    write("attendance", attendance, ["student_id", "course_code", "classes_held", "classes_attended"])
    write("results", results, ["student_id", "course_code", "exam_session", "exam_type", "internal_marks",
                               "external_marks", "total_marks", "max_marks", "result"])
    write("attendance_relaxations", relax, ["student_id", "count_used"])
    (OUT / "generation_log.json").write_text(json.dumps(log, indent=2))
    print(f"Wrote {len(students)} students, {len(attendance)} attendance rows, {len(results)} results to {OUT}")
    print(f"LLM calls: {log['llm_calls']}, LLM errors fixed by code: {len(log['llm_errors_fixed'])}")

    from scripts.validate_data import main as validate  # noqa: E402

    return validate(["--dir", str(OUT)])


if __name__ == "__main__":
    raise SystemExit(main())
