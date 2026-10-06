"""Setup-phase tests: they run without Ollama, Chroma or Docker."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import llm
from app.main import app
from app.models import AnswerType, AskResponse

client = TestClient(app)


def test_health_reports_every_dependency():
    body = client.get("/health").json()
    for part in ("api", "vector_store", "sqlite", "llm"):
        assert part in body
        assert body[part]["status"] in {"ok", "down"}
    assert body["api"]["status"] == "ok"
    assert body["sqlite"]["status"] == "ok"


def test_unbuilt_endpoints_return_501_not_500():
    resp = client.post("/ask", json={"question": "What is the minimum attendance?"})
    assert resp.status_code == 501


def test_ask_rejects_empty_question():
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_answer_types_match_the_brief():
    assert {t.value for t in AnswerType} == {
        "retrieved_fact", "calculated", "not_found",
        "clarification_needed", "refused", "conflict_flagged",
    }


def test_response_model_example_from_brief_validates():
    # The sample response in the brief, section 6.1, must fit our model.
    AskResponse.model_validate({
        "trace_id": "7f3c2a9e",
        "answer": "You are eligible to appear in the end-semester exam for CS201.",
        "answer_type": "calculated",
        "citations": [{"doc_id": "ACAD-REG-2024", "title": "Academic Regulations",
                       "section": "7.2", "page": 14, "version": "3.1",
                       "effective_from": "2024-07-01"}],
        "tools_invoked": [{"tool": "get_attendance", "input": {"course_code": "CS201"},
                           "output": {"classes_held": 40, "classes_attended": 31,
                                      "attendance_pct": 77.5}}],
        "applied_rules": [{"rule_id": "ATT-MIN-01", "value": ">= 75%",
                           "source_doc_id": "ACAD-REG-2024"}],
        "conflicts_detected": [],
        "explanation": "Your attendance in CS201 is 77.5%, above the 75% minimum.",
        "as_of_date": "2026-10-06",
    })


class _Plan(BaseModel):
    category: str
    tools: list[str]


def test_mock_llm_returns_validated_object():
    llm.set_mock_handler(lambda schema, prompt: {"category": "policy_fact", "tools": []})
    try:
        usage = llm.LLMUsage()
        plan = llm.complete_json("sys", "What is the minimum attendance?", _Plan, usage)
        assert plan.category == "policy_fact"
        assert usage.calls == 1
    finally:
        llm.set_mock_handler(None)
