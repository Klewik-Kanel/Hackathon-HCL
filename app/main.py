"""FastAPI entry point: the API contract from the brief, section 6.

At this stage (setup phase) only /health is fully working. The other
endpoints exist with their final request/response shapes and return
HTTP 501 until their modules are built, so the UI and the tests can be
written against the real contract from the start.
"""

from __future__ import annotations

import sqlite3

from fastapi import FastAPI, Header, HTTPException

from app import llm
from app.config import settings
from app.models import AskRequest, AskResponse

app = FastAPI(
    title="University Student Services Assistant",
    version="0.1.0",
    description="Grounded answers from NSUT documents and student records.",
)


def _check_sqlite() -> dict:
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "path": str(settings.sqlite_path)}
    except sqlite3.Error as exc:
        return {"status": "down", "detail": str(exc)}


def _check_vector_store() -> dict:
    try:
        import chromadb  # imported here so /health still works if it is missing

        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        count = client.get_or_create_collection("documents").count()
        return {"status": "ok", "chunks": count}
    except Exception as exc:  # noqa: BLE001 - report any failure as "down"
        return {"status": "down", "detail": str(exc)[:200]}


@app.get("/health")
def health() -> dict:
    """Readiness of every dependency: API, vector store, SQLite and LLM."""
    parts = {
        "api": {"status": "ok"},
        "vector_store": _check_vector_store(),
        "sqlite": _check_sqlite(),
        "llm": llm.health(),
    }
    overall = "ok" if all(p["status"] == "ok" for p in parts.values()) else "degraded"
    return {"status": overall, **parts}


@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, x_student_id: str | None = Header(default=None)) -> AskResponse:
    raise HTTPException(status_code=501, detail="Not built yet (Phase 2)")


@app.post("/ingest")
def ingest() -> dict:
    raise HTTPException(status_code=501, detail="Not built yet (Phase 3)")


@app.get("/audit/{trace_id}")
def audit(trace_id: str) -> dict:
    raise HTTPException(status_code=501, detail="Not built yet (Phase 3)")


@app.get("/sources")
def sources() -> list[dict]:
    raise HTTPException(status_code=501, detail="Not built yet (Phase 2)")
