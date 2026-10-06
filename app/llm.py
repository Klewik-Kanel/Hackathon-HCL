"""Thin client for the local LLM (Ollama).

Why this module exists
----------------------
Small local models (7-8B) sometimes return broken JSON. Every caller in
the app needs the same protection, so it lives here once:

1. ask Ollama for JSON output (``format: "json"``, temperature 0),
2. validate the reply against a Pydantic schema,
3. on failure, retry ONCE with the validation error shown to the model,
4. if it still fails, raise ``LLMError`` so the caller can fall back.

It also records calls and tokens for the audit log (brief R10), and has a
MOCK mode so the rest of the system can be tested without a model.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the model is unreachable or keeps returning invalid output."""


@dataclass
class LLMUsage:
    """Running totals for one request, copied into the audit record."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = field(default_factory=lambda: "mock" if settings.mock_llm else settings.llm_model)


# A mock handler receives the schema class and the prompt, and returns a dict.
MockHandler = Callable[[type[BaseModel], str], dict]
_mock_handler: MockHandler | None = None


def set_mock_handler(handler: MockHandler | None) -> None:
    """Tests and MOCK_LLM mode plug in canned answers here."""
    global _mock_handler
    _mock_handler = handler


def _chat(system: str, user: str) -> tuple[str, dict]:
    """One raw call to Ollama's /api/chat. Returns (content, raw_response)."""
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": settings.llm_temperature},
    }
    try:
        resp = httpx.post(
            f"{settings.ollama_host}/api/chat",
            json=payload,
            timeout=settings.llm_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:  # network down, model missing, timeout
        raise LLMError(f"Ollama request failed: {exc}") from exc
    data = resp.json()
    return data.get("message", {}).get("content", ""), data


def complete_json(
    system: str,
    user: str,
    schema: type[T],
    usage: LLMUsage | None = None,
    max_attempts: int = 2,
) -> T:
    """Ask the model for JSON matching ``schema`` and return a validated object.

    ``max_attempts=2`` means: first try, plus one retry that includes the
    validation error. More retries rarely help a small model and cost time.
    """
    usage = usage or LLMUsage()

    if settings.mock_llm or _mock_handler is not None:
        if _mock_handler is None:
            raise LLMError("MOCK_LLM is on but no mock handler is registered")
        usage.calls += 1
        return schema.model_validate(_mock_handler(schema, user))

    prompt = user
    last_error = ""
    for _ in range(max_attempts):
        started = time.perf_counter()
        content, raw = _chat(system, prompt)
        usage.calls += 1
        usage.latency_ms += int((time.perf_counter() - started) * 1000)
        usage.tokens_in += int(raw.get("prompt_eval_count", 0) or 0)
        usage.tokens_out += int(raw.get("eval_count", 0) or 0)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)[:500]
            prompt = (
                f"{user}\n\nYour previous reply was not valid. Error:\n{last_error}\n"
                "Reply again with ONLY a JSON object matching the required fields."
            )
    raise LLMError(f"Model returned invalid JSON twice: {last_error}")


def health() -> dict:
    """Report whether Ollama is reachable and the configured model is pulled."""
    if settings.mock_llm:
        return {"status": "ok", "model": "mock", "detail": "MOCK_LLM=true"}
    try:
        resp = httpx.get(f"{settings.ollama_host}/api/tags", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return {"status": "down", "model": settings.llm_model, "detail": str(exc)}
    names = {m.get("name", "") for m in resp.json().get("models", [])}
    if settings.llm_model in names or f"{settings.llm_model}:latest" in names:
        return {"status": "ok", "model": settings.llm_model}
    return {
        "status": "down",
        "model": settings.llm_model,
        "detail": f"model not pulled; run: ollama pull {settings.llm_model}",
    }
