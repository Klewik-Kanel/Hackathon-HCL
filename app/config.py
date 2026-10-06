"""Central configuration, read once from environment variables.

Every setting has a safe default so the app starts with no .env file.
Change behaviour by editing .env (copied from .env.example), never by
editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    """Read an environment variable as a boolean ("true"/"1"/"yes" = True)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- LLM (Ollama) --------------------------------------------------
    # Inside Docker the host machine is reachable as host.docker.internal;
    # outside Docker it is plain localhost.
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
    # MOCK_LLM=true replaces every model call with a fixed stub, so the
    # pipeline and tests run without Ollama (brief section 5.1).
    mock_llm: bool = _bool("MOCK_LLM", False)
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "120"))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0"))

    # --- Retrieval -----------------------------------------------------
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    top_k: int = int(os.getenv("TOP_K", "8"))

    # --- Storage -------------------------------------------------------
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "app.db"


settings = Settings()
