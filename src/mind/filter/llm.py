"""Local LLM relevance classifier.

Uses Ollama for inference. The classifier receives a bounded context (title,
metadata, excerpt) and returns structured JSON. Output is validated; malformed
responses trigger a recovery attempt and never crash the pipeline.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

import httpx

from mind.config import Settings
from mind.logging import get_logger
from mind.schemas import AiResponse

log = get_logger("mind.llm")

SYSTEM_PROMPT = """You are MIND, a document relevance classifier for an automated knowledge \
mastery platform. You decide whether a document is relevant to a user's chosen mastery topic.

Return ONLY a single JSON object with exactly these fields:
{
  "decision": "ACCEPT" | "REJECT" | "REVIEW",
  "confidence": <float between 0 and 1>,
  "document_type": "curriculum" | "syllabus" | "course_description"
                 | "program_information" | "unrelated" | "unknown",
  "topic_match": "high" | "medium" | "low" | "none",
  "reason": "<short explanation>"
}

Rules:
- ACCEPT only when the document clearly belongs to the topic's academic material
  (curricula, syllabi, course catalogs, program requirements).
- REJECT when the document is unrelated.
- REVIEW when you cannot decide with sufficient confidence.
- Never include markdown, explanations or text outside the JSON object."""

_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMClassifier(ABC):
    """Interface for the relevance classifier."""

    @abstractmethod
    def classify(
        self, *, topic: str, title: str, metadata_text: str, excerpt: str
    ) -> AiResponse | None:
        """Return a validated response, or ``None`` when the model is unavailable."""
        raise NotImplementedError


class OllamaClassifier(LLMClassifier):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or _load_default()

    @property
    def cfg(self):
        return self.settings.llm

    def classify(
        self, *, topic: str, title: str, metadata_text: str, excerpt: str
    ) -> AiResponse | None:
        user_prompt = self._build_prompt(topic, title, metadata_text, excerpt)
        for attempt in range(1, self.cfg.max_attempts + 1):
            raw = self._ask(user_prompt, reinforce=attempt > 1)
            if raw is None:
                return None
            parsed = parse_response(raw)
            if parsed is not None:
                return parsed
            log.warning(
                "Malformed LLM response (attempt %s/%s): %r",
                attempt,
                self.cfg.max_attempts,
                raw,
            )
        return AiResponse(
            decision="REVIEW",
            confidence=0.0,
            document_type="unknown",
            topic_match="none",
            reason="malformed_model_response",
        )

    def _ask(self, user_prompt: str, reinforce: bool = False) -> str | None:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if reinforce:
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous answer was not valid JSON. "
                    "Answer ONLY with one valid JSON object and nothing else.",
                }
            )
        messages.append({"role": "user", "content": user_prompt})
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": False,
            "think": self.cfg.think,
            "temperature": self.cfg.temperature,
            "options": {"num_predict": 300},
        }
        if self.cfg.format == "json":
            payload["format"] = "json"
        try:
            with httpx.Client(timeout=self.cfg.timeout_seconds) as client:
                resp = client.post(f"{self.cfg.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
            return (data.get("message") or {}).get("content") or ""
        except httpx.HTTPError as exc:
            log.warning("LLM request failed: %s", exc)
            return None
        except Exception as exc:
            log.warning("LLM request failed (unexpected): %s", exc)
            return None

    @staticmethod
    def _build_prompt(topic: str, title: str, metadata_text: str, excerpt: str) -> str:
        lines = [
            f"MASTERY TOPIC: {topic}",
            f"DOCUMENT TITLE: {title or 'Unknown'}",
        ]
        if metadata_text.strip():
            lines.append(f"DOCUMENT METADATA:\n{metadata_text.strip()}")
        if excerpt.strip():
            lines.append(f"DOCUMENT EXCERPT:\n{excerpt.strip()}")
        lines.append("\nClassify this document. Respond with the JSON object only.")
        return "\n".join(lines)


class FakeClassifier(LLMClassifier):
    """Deterministic classifier for tests (no runtime required)."""

    def __init__(self, mapping: dict[str, AiResponse] | None = None):
        self.mapping = mapping or {}
        self.calls: list[dict] = []

    def classify(
        self, *, topic: str, title: str, metadata_text: str, excerpt: str
    ) -> AiResponse | None:
        self.calls.append({"topic": topic, "title": title, "excerpt": excerpt})
        for key, response in self.mapping.items():
            if key.lower() in title.lower() or key.lower() in excerpt.lower():
                return response
        return AiResponse(decision="REVIEW", confidence=0.5, reason="no_mapping_match")


def parse_response(raw: str) -> AiResponse | None:
    """Parse and validate an LLM response into an AiResponse.

    Returns ``None`` when the response cannot be recovered into a valid
    response object.
    """
    if not raw:
        return None
    text = raw.strip()
    match = _RE.search(text)
    candidate = match.group(0) if match else text
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    decision = str(data.get("decision", "REVIEW")).strip().upper()
    if decision not in ("ACCEPT", "REJECT", "REVIEW"):
        decision = "REVIEW"

    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    document_type = str(data.get("document_type", "unknown")).strip().lower()
    allowed_types = {
        "curriculum",
        "syllabus",
        "course_description",
        "program_information",
        "unrelated",
        "unknown",
    }
    if document_type not in allowed_types:
        document_type = "unknown"

    topic_match = str(data.get("topic_match", "none")).strip().lower()
    if topic_match not in ("high", "medium", "low", "none"):
        topic_match = "none"

    return AiResponse(
        decision=decision,
        confidence=confidence,
        document_type=document_type,
        topic_match=topic_match,
        reason=str(data.get("reason", ""))[:500],
    )


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
