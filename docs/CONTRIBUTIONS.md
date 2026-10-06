# Team contribution statement

Each member owns, commits and can explain the files below. AI assistance
is disclosed in `docs/ai_usage.md`.

| Member | Role | Files owned |
| --- | --- | --- |
| Kaustubh | Integration lead: workflow, API, LLM client, guard, audit, packaging | `app/main.py`, `app/graph.py`, `app/llm.py`, `app/fallback.py`, `app/guard.py`, `app/audit.py`, `app/models.py`, `app/config.py`, `app/text.py`, `prompts/plan_v1.txt`, `prompts/compose_v1.txt`, `Dockerfile`, `docker-compose.yml`, `scripts/bootstrap.py`, `scripts/check_ai_setup.py`, `scripts/export_sample_audits.py`, `tests/test_api.py`, `tests/test_llm_path.py`, `README.md`, `docs/SETUP.md`, `docs/ai_usage.md` |
| Nikshit | Documents, ingestion and retrieval | `app/ingest.py`, `app/retrieval.py`, `app/embeddings.py`, `app/vectorstore.py`, `data/source_register.csv`, `data/docs/*`, `scripts/ingest_all.py`, `eval/compare_retrieval.py`, `tests/test_ingest.py`, `tests/fixtures/`, `docs/DATA_SOURCES.md` |
| Subham | Rules, precedence and tools | `app/precedence.py`, `app/rules.py`, `app/tools/`, `app/db.py`, `data/rule_registry.csv`, `prompts/extract_rules_v1.txt`, `scripts/load_rules.py`, `tests/test_precedence.py`, `tests/test_tools.py` |
| Mohit | Synthetic data, evaluation and UI | `scripts/generate_students.py`, `scripts/validate_data.py`, `scripts/load_students.py`, `prompts/student_gen_v1.txt`, `data/students/`, `eval/questions.jsonl`, `eval/run_eval.py`, `ui/`, `tests/test_validate.py`, `docs/data_card.md` |

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
