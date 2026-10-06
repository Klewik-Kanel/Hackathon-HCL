"""Turns text into vectors for ChromaDB.

Production uses sentence-transformers with BAAI/bge-small-en-v1.5
(384 dimensions). Why bge-small: it scores higher on retrieval
benchmarks than all-MiniLM-L6-v2 at the same size, and it supports a
"query instruction" that improves question-to-passage matching. The
evaluation compares both (eval/compare_retrieval.py).

EMBEDDING_MODEL=hash selects a tiny deterministic bag-of-words embedder.
It needs no download and exists only so tests run offline; never use it
for the demo.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from app.config import settings

# bge models expect this prefix on queries (not on documents).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class HashEmbedder:
    """Offline test embedder: hashed word counts, L2-normalised."""

    dim = 512

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if len(word) < 2:
                continue
            idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, done once

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model_name.lower() else ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode([self.query_prefix + text], normalize_embeddings=True)[0].tolist()


@lru_cache(maxsize=4)
def get_embedder(model_name: str | None = None):
    """Load the embedder once per process and reuse it."""
    name = model_name or settings.embedding_model
    if name == "hash":
        return HashEmbedder()
    return SentenceTransformerEmbedder(name)
