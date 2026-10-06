"""Chunking, re-ingestion and live ingestion."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ingest import chunk_clauses, read_pages
from app.main import app
from app.vectorstore import get_collection

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "btech_reg_fixture.txt"
client = TestClient(app)


def test_clause_chunks_keep_section_and_page():
    chunks = chunk_clauses(read_pages(FIXTURE))
    by_section = {c.section: c for c in chunks}
    assert by_section["11.2"].page == 2
    assert "75%" in by_section["11.2"].text
    assert by_section["12.3"].page == 3
    assert by_section["15.1"].heading.startswith("15")


def test_table_of_contents_is_skipped():
    chunks = chunk_clauses(read_pages(FIXTURE))
    assert not any("....." in c.text for c in chunks)


def test_markdown_clauses_are_chunked():
    chunks = chunk_clauses(read_pages(ROOT / "data" / "docs" / "ACAD-CIRC-2026-SYN.md"))
    assert {"1.1", "1.2", "1.3"} <= {c.section for c in chunks}


def _meta(doc_id: str, **extra) -> str:
    base = {"doc_id": doc_id, "title": "Exam Cell Notice on Make-up Examinations",
            "issuer": "Controller of Examinations", "authority_level": 2, "doc_type": "circular",
            "version": "1", "effective_from": "2026-08-01", "provenance": "test", "synthetic": "Y"}
    return json.dumps({**base, **extra})


NOTICE = ("# Make-up examinations\n\n## 1. Make-up examination\n\n"
          "1.1 Students who were absent from the end-semester examination on medical grounds may take a "
          "make-up examination within 30 days of the result.\n")


def test_live_ingest_is_used_immediately_and_reingest_is_idempotent():
    files = {"file": ("makeup.md", NOTICE.encode(), "text/markdown")}
    r = client.post("/ingest", files=files, data={"metadata": _meta("JD-TEST-MAKEUP")})
    assert r.status_code == 200, r.text
    assert r.json()["chunks_indexed"] >= 1
    first = get_collection().get(where={"doc_id": "JD-TEST-MAKEUP"})["ids"]

    files = {"file": ("makeup.md", NOTICE.encode(), "text/markdown")}
    client.post("/ingest", files=files, data={"metadata": _meta("JD-TEST-MAKEUP")})
    assert get_collection().get(where={"doc_id": "JD-TEST-MAKEUP"})["ids"] == first  # no duplicates

    ans = client.post("/ask", json={"question": "Can I take a make-up examination if I was absent on medical grounds?",
                                    "as_of_date": "2026-10-06"}).json()
    assert any(c["doc_id"] == "JD-TEST-MAKEUP" for c in ans["citations"]), ans
    assert any(s["doc_id"] == "JD-TEST-MAKEUP" for s in client.get("/sources").json())


def test_ingest_rejects_bad_metadata_and_file_types():
    files = {"file": ("x.md", b"text", "text/markdown")}
    assert client.post("/ingest", files=files, data={"metadata": "{not json"}).status_code == 422
    files = {"file": ("x.exe", b"MZ", "application/octet-stream")}
    assert client.post("/ingest", files=files, data={"metadata": _meta("JD-X")}).status_code == 415
