"""The real-LLM code path, with a scripted stand-in for Ollama.

Checks that the grounding guards work: an answer citing an id that was
not retrieved, or quoting a number that is not in the evidence, is
rejected and replaced by the template answer, and the error is audited.
"""

import dataclasses
from datetime import date

import pytest

from app import audit, graph, llm
from app.config import settings


@pytest.fixture
def real_llm_mode(monkeypatch):
    monkeypatch.setattr(graph, "settings", dataclasses.replace(settings, mock_llm=False))
    yield
    llm.set_mock_handler(None)


def _handler(compose_reply):
    def handler(schema, prompt):
        if schema.__name__ == "Plan":
            return {"category": "policy_fact", "course": None, "needs_docs": True, "tools": [],
                    "assumptions": [], "ambiguous": False, "clarification_question": None}
        handler.compose_prompts.append(prompt)
        return compose_reply(prompt)
    handler.compose_prompts = []
    return handler


def test_grounded_answer_is_accepted(real_llm_mode):
    def reply(prompt):
        first_id = prompt.split('<evidence id="')[1].split('"')[0]
        return {"answer": "You need at least 75% attendance in each subject.",
                "explanation": "Clause 11.2 applies.", "cited_ids": [first_id], "insufficient": False}
    h = _handler(reply)
    llm.set_mock_handler(h)
    r = graph.answer_question("What is the minimum attendance required to appear for end-semester exams?",
                              None, date(2026, 10, 6))
    assert r.answer.startswith("You need at least 75%")
    assert r.citations[0].section == "11.2"
    # Evidence is fenced and labelled as data in the prompt.
    assert "<evidence id=" in h.compose_prompts[0]
    assert audit.get(r.trace_id)["llm_calls"] == 2


def test_invented_number_and_unknown_citation_are_rejected(real_llm_mode):
    def reply(prompt):
        return {"answer": "You need 90% attendance.", "explanation": "", "cited_ids": ["made-up-id"],
                "insufficient": False}
    llm.set_mock_handler(_handler(reply))
    r = graph.answer_question("What is the minimum attendance required to appear for end-semester exams?",
                              None, date(2026, 10, 6))
    assert "90%" not in r.answer and "75" in r.answer          # template answer used instead
    assert any("grounding" in e for e in audit.get(r.trace_id)["errors"])


def test_model_saying_insufficient_gives_not_found(real_llm_mode):
    llm.set_mock_handler(_handler(lambda p: {"answer": "", "explanation": "", "cited_ids": [],
                                              "insufficient": True}))
    r = graph.answer_question("What does clause 11.4 say about committee relaxation?", None, date(2026, 10, 6))
    assert r.answer_type.value == "not_found"


def test_broken_model_falls_back_to_keyword_planner(real_llm_mode):
    def broken(schema, prompt):
        raise llm.LLMError("invalid JSON twice")
    llm.set_mock_handler(broken)
    r = graph.answer_question("Am I eligible for the end-semester exam in CS301?", "S1002", date(2026, 10, 6))
    assert r.answer_type.value == "calculated"
    errors = audit.get(r.trace_id)["errors"]
    assert any("fallback" in e for e in errors) and any("template" in e for e in errors)
