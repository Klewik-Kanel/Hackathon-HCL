"""Central configuration, read once from environment variables.

Every setting has a safe default so the app starts with no .env file.
Change behaviour by editing .env (copied from .env.example), never by
editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    """Read an environment variable as a boolean ("true"/"1"/"yes" = True)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # --- LLM (Ollama) --------------------------------------------------
    # Inside Docker the host machine is reachable as host.docker.internal;
    # outside Docker it is plain localhost.
    ollama_host: str = field(default_factory=lambda: _env("OLLAMA_HOST", "http://localhost:11434"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen2.5:7b-instruct"))
    # MOCK_LLM=true replaces every model call with deterministic code, so the
    # pipeline and tests run without Ollama (brief section 5.1).
    mock_llm: bool = field(default_factory=lambda: _bool("MOCK_LLM", False))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT_S", "120")))
    llm_temperature: float = field(default_factory=lambda: float(_env("LLM_TEMPERATURE", "0")))

    # --- Retrieval -----------------------------------------------------
    # "hash" = tiny offline embedding used only by tests (no download).
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    chunking: str = field(default_factory=lambda: _env("CHUNKING", "clause"))  # clause | fixed
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "8")))
    evidence_k: int = field(default_factory=lambda: int(_env("EVIDENCE_K", "4")))
    # Below this similarity the best chunk is not trusted -> not_found.
    abstain_threshold: float = field(default_factory=lambda: float(_env("ABSTAIN_THRESHOLD", "0.45")))
    # Extract rules from newly ingested documents with the LLM.
    extract_rules_on_ingest: bool = field(default_factory=lambda: _bool("EXTRACT_RULES_ON_INGEST", True))

    # --- Storage -------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "data")))

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def model_label(self) -> str:
        return "mock" if self.mock_llm else self.llm_model


settings = Settings()
