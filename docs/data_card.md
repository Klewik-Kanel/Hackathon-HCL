# Synthetic data card (Annex E)

| Field | Content |
| --- | --- |
| **Purpose** | Test students for personal-data, eligibility, what-if and authorisation questions. Must exercise every boundary in the attendance, pass, backlog and CGPA rules. |
| **Generator** | `scripts/generate_students.py`. Model: Ollama `qwen2.5:7b-instruct`, temperature 0, one call per non-edge student (29 calls, plus retries). The committed CSVs were produced with `--offline` (deterministic stand-in) during the build; **re-run without `--offline` on the demo laptop and update this card with the real counts from `data/students/generation_log.json`.** |
| **Prompts** | `prompts/student_gen_v1.txt` (verbatim, with the course lists and profile filled in per student) |
| **Schema enforcement** | Pydantic model `GenStudent` on every reply; invalid JSON is retried once with the error shown to the model; then the validator `scripts/validate_data.py` checks the CSVs. |
| **Row counts** | 40 students (20 B.Tech CSE, 20 B.Tech ECE; batches 2023 and 2024), 12 courses (6 per programme), 80 attendance rows, 110 result rows |
| **Edge cases** | S1001 exactly 75.00% (30/40) · S1002 74.36% (29/39), one class short · S1003 58.97%, below the 60% floor · S1004 70% with both relaxations used · S1005 failed CS201 by one mark (14/50 = 28% < 30%) · S1006 ABSENT · S1007 DETAINED · S1008 three backlogs · S1009 CGPA exactly 5.00 · S1010 CGPA 8.00 · S1011 CGPA 7.99 |
| **Why edge cases are written by code** | An LLM cannot be relied on to hit 30/40 exactly. The LLM writes names and ordinary records; code writes the boundary values. |
| **Validation results** | `data/students/validation_report.json`: 0 errors, 0 warnings on the committed data. Planted-error test: `tests/test_validate.py`. |
| **What the LLM got wrong** | Recorded automatically in `generation_log.json → llm_errors_fixed` (totals not matching internal + external, results not matching marks, attended > held, missing courses). Fill in from the real run. |
| **Known limitations** | Only 2 programmes and 12 courses; marks are 50 internal + 50 external for every course; CGPA is generated, not computed from grades; no practical components; attendance relaxations stored as a simple count. |
| **Reserved IDs** | S9000–S9999 and course codes starting JDG are left for the judges. |
