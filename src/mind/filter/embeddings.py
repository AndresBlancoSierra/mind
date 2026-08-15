"""Local embedding relevance filter using the Ollama embeddings API.

No GPU-bound embedding library (e.g. sentence-transformers) is required: the
embedding model runs inside Ollama. The model is configurable and the
thresholds are configurable and must be calibrated with real data.
"""

from __future__ import annotations

import math

import httpx

from mind.config import Settings
from mind.logging import get_logger

log = get_logger("mind.embeddings")


class EmbeddingClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or _load_default()

    @property
    def cfg(self):
        return self.settings.embeddings

    def _embed(self, text: str) -> list[float] | None:
        try:
            with httpx.Client(timeout=self.cfg.timeout_seconds) as client:
                resp = client.post(
                    f"{self.cfg.base_url}/api/embed",
                    json={"model": self.cfg.model, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
            vectors = data.get("embeddings")
            if vectors:
                return vectors[0]
            return None
        except Exception as exc:
            log.warning("Embedding request failed: %s", exc)
            return None

    def similarity(self, topic: str, document_text: str) -> float | None:
        """Cosine similarity between the topic and a document excerpt.

        Returns ``None`` when embeddings are unavailable (e.g. the model is
        not installed in Ollama) so the caller can skip the stage gracefully.
        """
        topic_vec = self._embed(topic)
        doc_vec = self._embed(document_text[: self.cfg.max_chars])
        if not topic_vec or not doc_vec:
            return None
        return _cosine(topic_vec, doc_vec)


def _cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
