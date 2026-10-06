"""ChromaDB access, persisted to disk so restarts never re-ingest.

We always pass our own embeddings to Chroma (``embedding_function=None``),
so Chroma never downloads a model of its own and the vectors always come
from app/embeddings.py.

One collection per (embedding model, chunking strategy). That lets the
evaluation compare configurations side by side without them overwriting
each other.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.config import settings


def collection_name(model: str | None = None, chunking: str | None = None) -> str:
    model = model or settings.embedding_model
    chunking = chunking or settings.chunking
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")[:40]
    return f"docs-{slug}-{chunking}"


@lru_cache(maxsize=1)
def _client():
    import chromadb

    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection(model: str | None = None, chunking: str | None = None):
    return _client().get_or_create_collection(
        name=collection_name(model, chunking),
        embedding_function=None,
        metadata={"hnsw:space": "cosine"},  # similarity = 1 - distance
    )


def clean_metadata(meta: dict) -> dict:
    """Chroma only stores str/int/float/bool; turn None into "" and dates into text."""
    out = {}
    for key, value in meta.items():
        if value is None:
            out[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            out[key] = value
        else:
            out[key] = str(value)
    return out
