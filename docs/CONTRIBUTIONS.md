# Team contribution statement

Each member owns, commits and can explain the files below. AI assistance
is disclosed in `docs/ai_usage.md`.

| Member | Role | Files owned |
| --- | --- | --- |
| Kaustubh | Integration lead: workflow, API, LLM client, guard, audit, packaging | `app/main.py`, `app/graph.py`, `app/llm.py`, `app/fallback.py`, `app/guard.py`, `app/audit.py`, `app/models.py`, `app/config.py`, `app/text.py`, `prompts/plan_v1.txt`, `prompts/compose_v1.txt`, `Dockerfile`, `docker-compose.yml`, `scripts/bootstrap.py`, `scripts/check_ai_setup.py`, `scripts/export_sample_audits.py`, `app/auth.py`, `scripts/run_local.sh`, `tests/test_api.py`, `tests/test_llm_path.py`, `tests/test_auth.py`, `README.md`, `docs/SETUP.md`, `docs/ai_usage.md` |
| Nikshit | Documents, ingestion and retrieval | `app/ingest.py`, `app/retrieval.py`, `app/embeddings.py`, `app/vectorstore.py`, `data/source_register.csv`, `data/docs/*`, `scripts/ingest_all.py`, `eval/compare_retrieval.py`, `tests/test_ingest.py`, `tests/fixtures/`, `docs/DATA_SOURCES.md` |
| Subham | Rules, precedence and tools | `app/precedence.py`, `app/rules.py`, `app/tools/`, `app/db.py`, `data/rule_registry.csv`, `prompts/extract_rules_v1.txt`, `scripts/load_rules.py`, `tests/test_precedence.py`, `tests/test_tools.py` |
| Mohit | Synthetic data, evaluation and UI | `scripts/generate_students.py`, `scripts/validate_data.py`, `scripts/load_students.py`, `prompts/student_gen_v1.txt`, `data/students/`, `eval/questions.jsonl`, `eval/run_eval.py`, `ui/`, `tests/test_validate.py`, `docs/data_card.md` |

## What we did in each part (not just the AI)

AI wrote first drafts (see `docs/ai_usage.md`). These are the decisions,
checks and work each of us did on our part. Each member: keep this
accurate and add anything you did that is missing.

**Kaustubh: workflow, API, login, packaging**
- Compared the use cases (UC1 vs UC2 and the three non-AI ones) and chose UC1, the student services assistant, because NSUT's regulations and placement policies are public.
- Directed the design document: build plan, data pipeline, phases and the four-way split of work.
- Set up Docker and Ollama with `qwen2.5:7b-instruct` on the laptop and ran the app end to end.
- Found that an old Docker container on port 8000 was answering "501: Not built yet", which led to the one-command launcher `scripts/run_local.sh`.
- Asked for and tested student password login (`app/auth.py`) and plain-text labels in the UI.
- Merged everyone's parts and pushed the integrated version.

**Nikshit: documents, ingestion, retrieval**
- Owns the Source Register: each NSUT document's issuer, authority level, version and dates.
- Owns the choice to keep one page per form-feed in the `.txt` copies, so citations point to the right page of the PDF.
- Committed and pushed the ingestion and retrieval part (6 October 2026).
- Before judging: check clause 11.2 is on page 18 and 12.3 on page 19 of the regulations in the chat answers.
- _Add here what you reviewed or changed._

**Subham: rules, precedence, tools**
- Owns the Annex A precedence order (applicability, supersession, authority, recency, else conflict) and the rule registry.
- Placement rules in the registry match the real policy: Dream is 13 LPA and above (2024-25, p.5), A+ is above 8 LPA (2020-21, rule 4), final-year students may drop up to 8 credits of backlogs for placement CGPA (p.11).
- Committed and pushed the rules, precedence and tools part (6 October 2026).
- Before judging: check every row of `data/rule_registry.csv` against its page.
- _Add here what you reviewed or changed._

**Mohit: student data, evaluation, UI**
- Owns the edge-case students S1001-S1011 that sit exactly on each rule boundary (75.00% attendance, one mark below pass, CGPA 7.99 vs 8.00).
- Owns the 31-question evaluation set and the Streamlit chat UI.
- Committed and pushed the data, evaluation and UI part (6 October 2026).
- Before judging: run `python scripts/generate_students.py` with Ollama on, so the student data is really LLM-generated, and update `docs/data_card.md`.
- _Add here what you reviewed or changed._

## Signed declaration of original work

We declare that this submission is our team's own work, that all AI
assistance and open-source libraries are disclosed, and that no real
student personal data is used anywhere in the system.

| Name | Signature | Date |
| --- | --- | --- |
| Kaustubh | | |
| Nikshit | | |
| Subham | | |
| Mohit | | |
