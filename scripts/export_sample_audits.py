"""Export three sample audit records (a deliverable) to docs/sample_audits/.

    python scripts/export_sample_audits.py          # needs the API running on :8000
    python scripts/export_sample_audits.py --inprocess

Asks one question per answer type (calculated, not_found, conflict noted /
retrieved_fact) and saves the response and its audit record side by side.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLES = [
    ("calculated", "Am I eligible for the end-semester exam in CS301?", "S1002", "2026-10-06"),
    ("not_found", "What is the scholarship for studying in Antarctica?", None, "2026-10-06"),
    ("retrieved_fact_with_conflict", "The CSE FAQ says 65% attendance is enough. What is the actual minimum "
                                     "attendance rule?", None, "2026-10-06"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--inprocess", action="store_true")
    args = parser.parse_args(argv)
    if args.inprocess:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
    else:
        import httpx

        client = httpx.Client(base_url=args.url, timeout=300)

    out_dir = ROOT / "docs" / "sample_audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, question, student, as_of in SAMPLES:
        headers = {"X-Student-Id": student} if student else {}
        resp = client.post("/ask", json={"question": question, "as_of_date": as_of}, headers=headers).json()
        record = client.get(f"/audit/{resp['trace_id']}").json()
        (out_dir / f"{name}.json").write_text(json.dumps({"response": resp, "audit": record}, indent=2))
        print(f"{name}: {resp['answer_type']} -> {out_dir / (name + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
