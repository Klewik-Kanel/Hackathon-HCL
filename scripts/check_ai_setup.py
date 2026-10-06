"""Check that the local AI setup works before building on it.

Run from the project root:

    python scripts/check_ai_setup.py

It checks, in order:
1. Ollama is reachable at OLLAMA_HOST (default http://localhost:11434)
2. the configured model (LLM_MODEL) is pulled
3. the model returns valid structured JSON for a planner-style prompt
4. how long that takes (this laptop's latency, for planning the demo)

Exit code 0 = everything works.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel  # noqa: E402

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402


class PlanCheck(BaseModel):
    """Same shape idea as the real planner: a category plus tools to call."""

    category: str
    course_code: str | None = None
    tools: list[str]


def main() -> int:
    print(f"Ollama host : {settings.ollama_host}")
    print(f"Model       : {settings.llm_model}")

    status = llm.health()
    if status["status"] != "ok":
        print(f"FAIL  Ollama/model: {status.get('detail')}")
        print("      Start Ollama (ollama serve) and pull the model "
              f"(ollama pull {settings.llm_model}).")
        return 1
    print("OK    Ollama is running and the model is pulled")

    system = (
        "You route student questions. Reply with JSON only: "
        '{"category": one of "policy_fact"|"personal_data"|"personal_eligibility", '
        '"course_code": string or null, "tools": list of tool names}. '
        "Available tools: get_attendance, check_exam_eligibility."
    )
    question = "Am I eligible to sit the end-semester exam in CS201?"
    started = time.perf_counter()
    try:
        plan = llm.complete_json(system, question, PlanCheck)
    except llm.LLMError as exc:
        print(f"FAIL  structured output: {exc}")
        return 1
    seconds = time.perf_counter() - started
    print(f"OK    valid JSON in {seconds:.1f}s -> {plan.model_dump()}")
    if seconds > 20:
        print("WARN  slow on this machine; consider LLM_MODEL=qwen2.5:3b-instruct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
