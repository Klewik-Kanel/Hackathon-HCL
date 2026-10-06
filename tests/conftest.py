"""Test setup: an isolated data folder, offline embeddings, no LLM.

Environment variables are set BEFORE any app module is imported, because
app.config reads them at import time.
"""

from __future__ import annotations

import csv
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="hcl-test-"))
os.environ.update({
    "DATA_DIR": str(TMP),
    "MOCK_LLM": "true",
    "EMBEDDING_MODEL": "hash",       # offline test embedder
    "ABSTAIN_THRESHOLD": "0.12",     # hash similarities are lower than real embeddings
    "EXTRACT_RULES_ON_INGEST": "true",
})

import pytest  # noqa: E402

from app import db, rules  # noqa: E402
from app.ingest import ingest_document, upsert_source  # noqa: E402
from app.models import SourceMetadata  # noqa: E402
from scripts.load_students import load_dir  # noqa: E402

FIXTURE_FILES = {"NSUT-BTECH-REG-2019": ROOT / "tests" / "fixtures" / "btech_reg_fixture.txt"}


def _bootstrap() -> None:
    db.init_db()
    with (ROOT / "data" / "source_register.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        file_name = row.pop("file_name")
        meta = SourceMetadata.model_validate({k: (v or None) if k in {"effective_to", "retrieved_on"} else v
                                              for k, v in row.items()})
        path = FIXTURE_FILES.get(meta.doc_id) or ROOT / "data" / "docs" / file_name
        if path.exists():
            ingest_document(path, meta, extract_rules=False)
        else:
            upsert_source(meta, file_name, 0)
    rules.load_rules_csv(ROOT / "data" / "rule_registry.csv")
    load_dir(ROOT / "data" / "students")


_bootstrap()


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return TMP


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(TMP, ignore_errors=True)
