# Data sources: where to get each document

Save every file into `data/docs/` with **exactly** the file name below
(the Source Register looks them up by name), then run
`python scripts/bootstrap.py`.

Before using a file, check two things: you can select text in the PDF (it
is not a scanned image), and it contains no student names or roll numbers.

| Save as | Document | Where |
| --- | --- | --- |
| `NSUT-BTECH-REG-2019.pdf` | Regulations for B.Tech Programmes 2019-I(A), 23 pages | https://www.nsut.ac.in/en/act-statutes-ordinances → Regulations → "B.Tech Regulations" (Google Drive → Download) |
| `NSUT-ORD-II-2019.pdf` | Ordinance-II for UG and PG programmes, revised 29.10.2019 | Same page → Regulations → "Ordinance for Undergraduate and Post-Graduate Programmes" |
| `NSUT-TNP-POL-2024.pdf` | Training and Placement Policy 2024-25 | https://tnpnsut-files.s3.ap-south-1.amazonaws.com/Placement_Policy_2024_25_final_b6588b530d.pdf |
| `NSUT-TNP-POL-2020.pdf` | Placement Policies 2020-21 (older version) | https://nsut.kartikbhalla.dev/downloads/placement-policy.pdf (unofficial host; noted in the register) |
| `NSUT-ADM-CIRC-2025-164.pdf` | B.Tech first-semester schedule and fee circular, 23.07.2025 | https://cdnbbsr.s3waas.gov.in/s3e45823afe1e5120cec11fc4c379a0c67/uploads/2025/07/2025072696.pdf |

Already in the repo (synthetic, marked `synthetic: Y`):
`ACAD-CIRC-2026-SYN.md` (80% attendance from 2027, supersedes clause 11.2)
and `CSE-FAQ-2026-SYN.md` (lower-authority "65% is enough", plus a hidden
instruction to test prompt-injection resistance).

## Worth adding from the NSUT IMS notices portal

https://www.imsnsit.org/imsnsit/notifications.php → pick the Department →
Submit. The notice links only open in a normal browser.

| Notice | Department | Why |
| --- | --- | --- |
| Notification regarding attendance (15-09-2026) | ACADEMIC SECTION | A real attendance circular; if it changes the 75% rule it is a genuine conflict and can replace our synthetic circular |
| Academic/activity calendar, Jul–Dec 2026 | ACADEMIC SECTION | Dates for exam and semester questions |
| Annual fee structure of 2023 / 2024 enrolled | ACADEMIC SECTION | Fee tables by batch |
| Notification regarding year back students (25-08-2026) | ACADEMIC SECTION | Promotion rules |
| Any make-up examination notice | EXAMINATION SECTION | The 2025-26 make-up exam results suggest a policy newer than clause 12.3 |

To add one: append a row to `data/source_register.csv` (authority level
per Annex A: regulations 1, official circulars 2, department notices 3,
FAQs 4, unofficial 5), save the file into `data/docs/`, and re-run
`python scripts/bootstrap.py` (or upload it through the UI / `POST /ingest`).

**Never use** detention lists, result lists, seating plans or anything else
containing real student names or roll numbers.
