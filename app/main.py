"""FastAPI entry point: the API contract from the brief, section 6.

Endpoints
---------
POST /ask                  ask a question (X-Student-Id header = logged-in student)
POST /ingest               add a document while running (file + metadata JSON)
GET  /health               status of API, vector store, SQLite and LLM
GET  /audit/{trace_id}     full audit record for one response
GET  /sources              the Source Register
POST /admin/load-students  load judge test students (CSV files in the Annex C schema)
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError

from app import audit, db, llm
from app.config import settings
from app.models import AskRequest, AskResponse, IngestResponse, SourceMetadata

IST = ZoneInfo("Asia/Kolkata")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()  # create tables on first start; existing data is kept
    yield


app = FastAPI(
    title="University Student Services Assistant",
    version="1.0.0",
    description="Grounded, cited answers from NSUT documents and student records.",
    lifespan=lifespan,
)


# --------------------------------------------------------------- health --
def _check_sqlite() -> dict:
    try:
        with db.session() as conn:
            students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            rules = conn.execute("SELECT COUNT(*) FROM rule_registry").fetchone()[0]
        return {"status": "ok", "students": students, "rules": rules}
    except sqlite3.Error as exc:
        return {"status": "down", "detail": str(exc)}


def _check_vector_store() -> dict:
    try:
        from app.vectorstore import collection_name, get_collection

        return {"status": "ok", "collection": collection_name(), "chunks": get_collection().count()}
    except Exception as exc:  # noqa: BLE001 - any failure means "down"
        return {"status": "down", "detail": str(exc)[:200]}


@app.get("/health")
def health() -> dict:
    parts = {
        "api": {"status": "ok"},
        "vector_store": _check_vector_store(),
        "sqlite": _check_sqlite(),
        "llm": llm.health(),
    }
    overall = "ok" if all(p["status"] == "ok" for p in parts.values()) else "degraded"
    return {"status": overall, **parts}


# ------------------------------------------------------------------ ask --
@app.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, x_student_id: str | None = Header(default=None)) -> AskResponse:
    from app.graph import answer_question  # heavy imports load on first use

    as_of = body.as_of_date or datetime.now(IST).date()  # default: today in India
    return answer_question(body.question, x_student_id, as_of)


# --------------------------------------------------------------- ingest --
class IngestMetadata(SourceMetadata):
    rules: list[dict] = []


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)) -> IngestResponse:
    """Multipart upload: the document plus its Source Register fields as JSON."""
    from app import ingest as ingest_mod
    from app import rules as rules_mod

    try:
        meta = IngestMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid metadata: {exc}") from exc
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".md", ".txt"}:
        raise HTTPException(status_code=415, detail="Upload a PDF, .md or .txt file")

    upload_dir = settings.docs_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{meta.doc_id}{suffix}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
    shutil.move(tmp.name, target)

    base = SourceMetadata.model_validate(meta.model_dump(exclude={"rules"}))
    explicit_rules = bool(meta.rules)
    result = ingest_mod.ingest_document(target, base, extract_rules=None if not explicit_rules else False)
    if explicit_rules:
        result.rules_added = rules_mod.add_rules_from_metadata(base, meta.rules)
    return result


# ---------------------------------------------------------- audit, sources --
@app.get("/audit/{trace_id}")
def get_audit(trace_id: str) -> dict:
    record = audit.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown trace_id")
    return record


@app.get("/sources")
def sources() -> list[dict]:
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY authority_level, doc_id")]


# ------------------------------------------------------- student loader --
class LoadReport(BaseModel):
    loaded: dict[str, int]
    rejected: list[dict]


@app.post("/admin/load-students", response_model=LoadReport)
def load_students(files: list[UploadFile] = File(...)) -> LoadReport:
    """Upload students.csv / courses.csv / attendance.csv / results.csv (Annex C schema)."""
    from scripts.load_students import load_dir

    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            (Path(tmp) / Path(f.filename or "file.csv").name).write_bytes(f.file.read())
        report = load_dir(Path(tmp))
    return LoadReport(**report)
