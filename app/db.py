"""SQLite schema and connection helper.

Tables marked "Annex C" are fixed by the brief: judges load their own test
students in exactly this shape, so those columns are never renamed or
removed. The other tables are ours.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import settings

SCHEMA = """
-- Annex C ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS students (
    student_id       TEXT PRIMARY KEY CHECK (student_id GLOB 'S[0-9][0-9][0-9][0-9]'),
    full_name        TEXT NOT NULL,
    programme        TEXT NOT NULL,
    batch_year       INTEGER NOT NULL,
    current_semester INTEGER NOT NULL CHECK (current_semester BETWEEN 1 AND 10),
    cgpa             REAL CHECK (cgpa BETWEEN 0 AND 10),
    active_backlogs  INTEGER NOT NULL DEFAULT 0 CHECK (active_backlogs >= 0)
);

CREATE TABLE IF NOT EXISTS courses (
    course_code TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    programme   TEXT NOT NULL,
    semester    INTEGER,
    credits     INTEGER
);

CREATE TABLE IF NOT EXISTS attendance (
    student_id       TEXT NOT NULL REFERENCES students(student_id),
    course_code      TEXT NOT NULL REFERENCES courses(course_code),
    classes_held     INTEGER NOT NULL CHECK (classes_held > 0),
    classes_attended INTEGER NOT NULL CHECK (classes_attended >= 0),
    PRIMARY KEY (student_id, course_code)
);

CREATE TABLE IF NOT EXISTS results (
    student_id     TEXT NOT NULL REFERENCES students(student_id),
    course_code    TEXT NOT NULL REFERENCES courses(course_code),
    exam_session   TEXT NOT NULL,
    exam_type      TEXT NOT NULL,
    internal_marks INTEGER,
    external_marks INTEGER,
    total_marks    INTEGER,
    max_marks      INTEGER,
    result         TEXT NOT NULL,
    PRIMARY KEY (student_id, course_code, exam_session, exam_type)
);

CREATE TABLE IF NOT EXISTS rule_registry (
    rule_id          TEXT PRIMARY KEY,
    description      TEXT NOT NULL,
    parameter        TEXT NOT NULL,
    operator         TEXT NOT NULL,
    value            TEXT NOT NULL,
    scope_programmes TEXT NOT NULL DEFAULT 'ALL',
    scope_batches    TEXT NOT NULL DEFAULT 'ALL',
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    source_doc_id    TEXT NOT NULL,
    source_section   TEXT NOT NULL
);

-- Ours ---------------------------------------------------------------
-- Source Register (Annex B fields) plus the stored file name.
CREATE TABLE IF NOT EXISTS sources (
    doc_id           TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    issuer           TEXT NOT NULL,
    authority_level  INTEGER NOT NULL,
    doc_type         TEXT NOT NULL,
    version          TEXT NOT NULL,
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    supersedes       TEXT NOT NULL DEFAULT '',
    scope_programmes TEXT NOT NULL DEFAULT 'ALL',
    scope_batches    TEXT NOT NULL DEFAULT 'ALL',
    provenance       TEXT NOT NULL,
    retrieved_on     TEXT,
    synthetic        TEXT NOT NULL DEFAULT 'N',
    file_name        TEXT,
    chunks_indexed   INTEGER NOT NULL DEFAULT 0,
    ingested_at      TEXT
);

-- How many attendance relaxations a student has already used (clause 11.5).
CREATE TABLE IF NOT EXISTS attendance_relaxations (
    student_id TEXT PRIMARY KEY REFERENCES students(student_id),
    count_used INTEGER NOT NULL DEFAULT 0
);

-- Student passwords: salted PBKDF2 hashes only (app/auth.py). A student
-- with no row here still uses the demo starting password.
CREATE TABLE IF NOT EXISTS student_credentials (
    student_id TEXT PRIMARY KEY REFERENCES students(student_id),
    salt       TEXT NOT NULL,
    pw_hash    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    trace_id   TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    record     TEXT NOT NULL      -- the full audit record as JSON
);
"""


def connect() -> sqlite3.Connection:
    """Open the app database with rows readable by column name."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """``with session() as conn:`` commits on success, rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they do not exist yet (safe to call every start-up)."""
    with session() as conn:
        conn.executescript(SCHEMA)
