"""Audit records (brief R10, Annex D): one per /ask response.

Stores what was retrieved, which tools ran with inputs and outputs, which
rules applied, the precedence decision, the model, LLM calls, tokens and
latency. It never stores chain-of-thought, and the question text is
stored with student IDs redacted.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app import db


def new_trace_id() -> str:
    return uuid.uuid4().hex[:8]


def write(record: dict) -> None:
    record.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with db.session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO audit_log (trace_id, created_at, record) VALUES (?, ?, ?)",
            (record["trace_id"], record["timestamp"], json.dumps(record, default=str)),
        )


def get(trace_id: str) -> dict | None:
    with db.session() as conn:
        row = conn.execute("SELECT record FROM audit_log WHERE trace_id = ?", (trace_id,)).fetchone()
    return json.loads(row["record"]) if row else None


def recent(limit: int = 50) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute("SELECT record FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,))
        return [json.loads(r["record"]) for r in rows]
