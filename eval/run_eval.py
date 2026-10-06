"""Run the labelled evaluation set and write eval/report.md.

    python eval/run_eval.py                         # against the running API on :8000
    python eval/run_eval.py --url http://localhost:8000
    python eval/run_eval.py --inprocess             # no server needed (uses FastAPI TestClient)

Method (stated in the report):
- answer correctness: exact match on the expected answer type AND every
  expected string (numbers, dates, labels) appearing in the answer, AND no
  forbidden string appearing. No LLM-as-judge.
- citation accuracy: the expected (doc_id, section) is among the citations.
- abstention accuracy: unanswerable questions return not_found and
  answerable ones do not.
- tool-result correctness: the expected tool ran and its output field has
  exactly the expected value.
- retrieval hit rate: the expected (doc_id, section) is in the retrieved
  top-k, read from the audit record.
- latency and cost: p50/p95 latency, LLM calls and tokens per question,
  read from the audit record.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_client(url: str | None, inprocess: bool):
    if inprocess:
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)
    import httpx

    return httpx.Client(base_url=url, timeout=300)


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


_TOKENS: dict[str, str] = {}


def student_headers(client, student_id: str | None) -> dict:
    """Log in as the test student (demo password) and fall back to the header."""
    if not student_id:
        return {}
    if student_id not in _TOKENS:
        r = client.post("/login", json={"student_id": student_id,
                                        "password": os.getenv("DEMO_PASSWORD", "nsut@123")})
        _TOKENS[student_id] = r.json()["token"] if r.status_code == 200 else ""
    token = _TOKENS[student_id]
    return {"Authorization": f"Bearer {token}"} if token else {"X-Student-Id": student_id}


def evaluate(client, questions: list[dict], top_k: int = 4) -> dict:
    rows = []
    for q in questions:
        headers = student_headers(client, q.get("student_id"))
        started = time.perf_counter()
        r = client.post("/ask", json={"question": q["question"], "as_of_date": q["as_of_date"]}, headers=headers)
        wall = (time.perf_counter() - started) * 1000
        body = r.json()
        audit = client.get(f"/audit/{body['trace_id']}").json() if r.status_code == 200 else {}
        answer = body.get("answer", "")

        type_ok = body.get("answer_type") == q["expected_type"]
        contains_ok = all(s.lower() in answer.lower() for s in q.get("expected_contains", []))
        forbidden_ok = not any(s.lower() in answer.lower() for s in q.get("must_not_contain", []))
        tool_ok = None
        if q.get("expected_tool"):
            t = q["expected_tool"]
            outs = [c["output"] for c in body.get("tools_invoked", []) if c["tool"] == t["name"]]
            tool_ok = any(o.get(t["key"]) == t["value"] for o in outs)
        cite_ok = retrieval_ok = None
        if q.get("expected_doc"):
            want = (q["expected_doc"], q.get("expected_section"))
            cites = {(c["doc_id"], c["section"]) for c in body.get("citations", [])}
            cite_ok = want in cites if want[1] else any(c[0] == want[0] for c in cites)
            retrieved = [(s["doc_id"], s["section"]) for s in audit.get("sources_retrieved", [])[:top_k]]
            retrieval_ok = want in retrieved if want[1] else any(s[0] == want[0] for s in retrieved)
        correct = type_ok and contains_ok and forbidden_ok and (tool_ok is not False)
        rows.append({
            "id": q["id"], "category": q["category"], "expected_type": q["expected_type"],
            "actual_type": body.get("answer_type"), "correct": correct, "type_ok": type_ok,
            "citation_ok": cite_ok, "retrieval_ok": retrieval_ok, "tool_ok": tool_ok,
            "latency_ms": audit.get("latency_ms", round(wall)), "llm_calls": audit.get("llm_calls", 0),
            "tokens": audit.get("tokens_in", 0) + audit.get("tokens_out", 0),
            "answer": answer[:160], "trace_id": body.get("trace_id"),
        })
    return {"rows": rows, "model": rows and client.get("/health").json().get("llm", {}).get("model")}


def summarise(result: dict) -> dict:
    rows = result["rows"]
    unans = [r for r in rows if r["expected_type"] == "not_found"]
    ans = [r for r in rows if r["expected_type"] not in {"not_found", "refused", "clarification_needed"}]
    cites = [r for r in rows if r["citation_ok"] is not None]
    retr = [r for r in rows if r["retrieval_ok"] is not None]
    tools = [r for r in rows if r["tool_ok"] is not None]
    lat = [r["latency_ms"] for r in rows]
    return {
        "answer_correctness": pct(sum(r["correct"] for r in rows), len(rows)),
        "citation_accuracy": pct(sum(r["citation_ok"] for r in cites), len(cites)),
        "abstention_unanswerable": pct(sum(r["actual_type"] == "not_found" for r in unans), len(unans)),
        "false_abstention_on_answerable": pct(sum(r["actual_type"] == "not_found" for r in ans), len(ans)),
        "tool_result_correctness": pct(sum(r["tool_ok"] for r in tools), len(tools)),
        "retrieval_hit_rate": pct(sum(r["retrieval_ok"] for r in retr), len(retr)),
        "refusals_correct": pct(sum(r["actual_type"] == "refused" for r in rows if r["expected_type"] == "refused"),
                                sum(r["expected_type"] == "refused" for r in rows)),
        "latency_p50_ms": round(percentile(lat, 50)),
        "latency_p95_ms": round(percentile(lat, 95)),
        "llm_calls_per_question": round(statistics.mean(r["llm_calls"] for r in rows), 2) if rows else 0,
        "tokens_per_question": round(statistics.mean(r["tokens"] for r in rows)) if rows else 0,
    }


def write_report(result: dict, summary: dict, path: Path) -> None:
    lines = [
        "# Evaluation report", "",
        f"Model: `{result.get('model')}` · Questions: {len(result['rows'])} · "
        f"Generated: {time.strftime('%Y-%m-%d %H:%M')}", "",
        "Method: exact match on answer type, expected strings and tool outputs; citation and retrieval "
        "checked against the labelled (doc_id, section); latency and tokens from the audit log. "
        "No LLM-as-judge.", "",
        "| Metric | Result |", "| --- | --- |",
        *[f"| {k.replace('_', ' ')} | {v} |" for k, v in summary.items()], "",
        "## Per question", "",
        "| ID | Category | Expected | Actual | Correct | Citation | Retrieval | Tool | ms |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    fmt = {True: "yes", False: "**no**", None: "-"}
    for r in result["rows"]:
        lines.append(f"| {r['id']} | {r['category']} | {r['expected_type']} | {r['actual_type']} | "
                     f"{fmt[r['correct']]} | {fmt[r['citation_ok']]} | {fmt[r['retrieval_ok']]} | "
                     f"{fmt[r['tool_ok']]} | {r['latency_ms']} |")
    failures = [r for r in result["rows"] if not r["correct"]]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- **{r['id']}** expected `{r['expected_type']}`, got `{r['actual_type']}`: "
                  f"{r['answer']} (trace `{r['trace_id']}`)" for r in failures]
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--inprocess", action="store_true")
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "report.md")
    args = parser.parse_args(argv)

    questions = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    result = evaluate(make_client(args.url, args.inprocess), questions)
    summary = summarise(result)
    write_report(result, summary, args.out)
    (args.out.with_suffix(".json")).write_text(json.dumps({"summary": summary, **result}, indent=2))
    for k, v in summary.items():
        print(f"{k:<32} {v}")
    print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
