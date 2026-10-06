# University Student Services Assistant (NSUT)

HCLTech Future Ready AI Engineer Hackathon, 6 October 2026.
**Team:** Kaustubh, Nikshit, Subham, Mohit

An assistant that answers NSUT B.Tech students' academic questions from
official university documents and the student's own (synthetic) records.
Every factual answer is cited to a document, clause, page, version and
effective date; every number comes from deterministic code; when the
sources don't contain the answer, it says so.

## Architecture

```
Streamlit UI ──HTTP──► FastAPI ──► LangGraph workflow (/ask)
                         │          guard → plan(LLM) → retrieve → run_tools → compose(LLM) → finalize
                         │                                  │            │                     │
                         ├─► /ingest ─► ingest.py ─► ChromaDB    SQLite (students, rules)   audit_log
                         └─► /admin/load-students ─► SQLite
Ollama (qwen2.5:7b-instruct) runs on the host; only `plan` and `compose` call it.
```

Design principle: **code decides, the LLM explains.** Identity checks,
which document wins (Annex A), eligibility, answer types and citations
are plain Python. We deliberately did not split the work into several
agents: routing is one classification and the rest is deterministic, so
more agents would add latency and failure points, not capability.

| Module | What it does |
| --- | --- |
| `app/main.py` | API contract: `/ask`, `/ingest`, `/health`, `/audit/{id}`, `/sources`, `/admin/load-students` |
| `app/graph.py` | The workflow, answer-type rules, grounding checks, audit record |
| `app/guard.py` | Identity from `X-Student-Id` only; refuses other students' data |
| `app/llm.py` | Ollama client: JSON mode, schema validation, one retry, token tracking, mock mode |
| `app/fallback.py` | Keyword planner and template answer used in mock mode and when the model fails |
| `app/ingest.py` | PDF/markdown → clause-aware chunks with page numbers → Chroma |
| `app/retrieval.py` | Vector search, labels each hit applicable / upcoming / superseded / out of scope |
| `app/precedence.py` | Annex A resolver: applicability, supersession, authority, recency, unresolved |
| `app/rules.py` | Rule registry access; verified rule extraction from new documents |
| `app/tools/` | Eight deterministic tools (attendance, eligibility, results, pass, backlog path, placement, degree) |

## Quick start

```bash
# 1. AI model on the host (one time)
ollama serve                       # leave running
ollama pull qwen2.5:7b-instruct

# 2. Documents: download the PDFs listed in docs/DATA_SOURCES.md into data/docs/

# 3. Start everything
cp .env.example .env
docker compose up --build
docker compose exec api python scripts/bootstrap.py   # index docs, load rules and students
```

- Chat UI: http://localhost:8501 · API docs: http://localhost:8000/docs · Health: http://localhost:8000/health

Without Docker: see [docs/SETUP.md](docs/SETUP.md).

## Sample requests

```bash
# Policy question (no login)
curl -s localhost:8000/ask -H 'Content-Type: application/json' \
  -d '{"question": "What is the minimum attendance required to appear for end-semester exams?"}'

# Personal eligibility (student S1002)
curl -s localhost:8000/ask -H 'Content-Type: application/json' -H 'X-Student-Id: S1002' \
  -d '{"question": "Am I eligible for the end-semester exam in CS301?"}'

# Same question in the future, after the (synthetic) 80% circular takes effect
curl -s localhost:8000/ask -H 'Content-Type: application/json' -H 'X-Student-Id: S1001' \
  -d '{"question": "Am I eligible for the end-semester exam in CS301?", "as_of_date": "2027-02-01"}'

# Live ingestion
curl -s localhost:8000/ingest -F file=@notice.pdf \
  -F 'metadata={"doc_id":"JD-NOTICE-01","title":"Exam notice","issuer":"Controller of Examinations","authority_level":2,"doc_type":"circular","version":"1","effective_from":"2026-10-01","provenance":"judges","synthetic":"N"}'

# Load judge test students (Annex C CSVs)
python scripts/load_students.py --dir test_students/
curl -s localhost:8000/admin/load-students -F files=@students.csv -F files=@attendance.csv

# Audit record and Source Register
curl -s localhost:8000/audit/<trace_id>
curl -s localhost:8000/sources
```

## Evaluation

```bash
python eval/run_eval.py              # 31 labelled questions -> eval/report.md
python eval/compare_retrieval.py     # chunking x embedding comparison -> eval/retrieval_comparison.md
pytest                               # 45 automated tests, no model needed (MOCK_LLM)
```

## Data and deliverables

| Deliverable | Where |
| --- | --- |
| Source Register | `data/source_register.csv` (download links in `docs/DATA_SOURCES.md`) |
| Rule registry (seed) | `data/rule_registry.csv`, loaded into SQLite `rule_registry` |
| Synthetic documents (2) | `data/docs/ACAD-CIRC-2026-SYN.md`, `data/docs/CSE-FAQ-2026-SYN.md` |
| Synthetic data kit | `prompts/student_gen_v1.txt`, `scripts/generate_students.py`, `scripts/validate_data.py`, `data/students/validation_report.json`, `docs/data_card.md` |
| Evaluation | `eval/questions.jsonl`, `eval/run_eval.py`, `eval/report.md` |
| Sample audit records | `docs/sample_audits/` (`python scripts/export_sample_audits.py`) |
| AI-usage disclosure | `docs/ai_usage.md` |
| Team contributions | `docs/CONTRIBUTIONS.md` |

## Assumptions and limitations

- **No cloud LLM.** Everything runs locally on Ollama. If a cloud fallback is ever added it sits behind `LLM_PROVIDER` and is disclosed here.
- **Rules come from a hand-checked seed**, plus verified extraction from new documents. Extraction only accepts a value that appears verbatim in the cited clause; if extraction finds nothing, the new document is still searchable and citable.
- **Precedence on free text** works through the rule registry: two documents conflict when they set the same rule parameter. Contradictions that never become rule rows are answered from the best-ranked applicable clause, with the precedence status of every hit in the audit.
- **NSUT has no supplementary exams** (Regulations 12.3). The Examination Section has published "make-up examination" results for 2025-26; if a make-up policy document is added, it is ingested like any other document.
- **Placement-policy rule values** are marked "verify" in the seed until checked against the PDF.
- **The Hindi part of the 2020 Gazette** extracts as garbled legacy-font text and is not used.
- The fallback (mock) answers are plainer than the model's; they exist for testing and as a safety net.
