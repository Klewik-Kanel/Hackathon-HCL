# University Student Services Assistant (NSUT)

HCLTech Future Ready AI Engineer Hackathon, 6 October 2026.

An assistant that answers NSUT B.Tech students' academic questions using
official university documents and the student's own (synthetic) records.
Every factual answer is cited; every number comes from deterministic code;
when the sources don't contain the answer, it says so.

**Team:** Kaustubh, Nikshit, Subham, Mohit

## Quick start

```bash
# 1. AI model on the host (one time)
ollama serve                       # leave running
ollama pull qwen2.5:7b-instruct

# 2. Everything else
cp .env.example .env
docker compose up --build
```

- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs
- Chat UI: http://localhost:8501

Full instructions and troubleshooting: [docs/SETUP.md](docs/SETUP.md)

## Stack

| Layer | Choice |
| --- | --- |
| UI | Streamlit |
| API | FastAPI + Uvicorn, Pydantic v2 |
| Orchestration | LangGraph |
| Vector store | ChromaDB (persisted to `data/chroma`) |
| Structured data | SQLite (`data/app.db`) |
| Embeddings | sentence-transformers, BAAI/bge-small-en-v1.5 |
| LLM | Ollama, qwen2.5:7b-instruct, on the host |
| Packaging | Docker + docker compose |

No cloud LLM is used. A cloud fallback, if added later, will sit behind a
configuration switch and be disclosed here.

## Repository layout

```
app/          API and core logic (config, models, llm client, ...)
ui/           Streamlit chat UI (talks to the API over HTTP only)
prompts/      Versioned prompt templates
scripts/      Setup check, ingestion, student data generation and loading
data/         Documents, source register, students; Chroma and SQLite at runtime
eval/         Evaluation questions, runner and report
tests/        pytest suite (runs without the model: MOCK_LLM)
docs/         Setup guide, data card, sample audits
```

## Status

- [x] Phase 0: project skeleton, Docker, AI client with JSON validation and mock mode, `/health`
- [ ] Phase 1: documents, rule registry, synthetic students
- [ ] Phase 2: first cited answer through `/ask`
- [ ] Phase 3: tools, precedence, guard, audit, live ingestion
- [ ] Phase 4: testing and evaluation
- [ ] Phase 5: packaging and documentation
