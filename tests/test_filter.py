"""Tests for the local AI filtering layer."""

from __future__ import annotations

from mind.filter.classifier import build_filter_result, combine
from mind.filter.llm import FakeClassifier, OllamaClassifier, parse_response
from mind.schemas import AiResponse


def _resp(decision: str = "ACCEPT", confidence: float = 0.9) -> AiResponse:
    return AiResponse(
        decision=decision,  # type: ignore[arg-type]
        confidence=confidence,
        document_type="curriculum",
        topic_match="high",
        reason="test",
    )


# ── parse_response / validation ──────────────────────────────────────────────


def test_parse_valid_json():
    r = parse_response(
        '{"decision": "ACCEPT", "confidence": 0.96, '
        '"document_type": "curriculum", "topic_match": "high", "reason": "ok"}'
    )
    assert r is not None
    assert r.decision == "ACCEPT"
    assert r.confidence == 0.96


def test_parse_markdown_fenced_json():
    body = '{"decision": "REJECT", "confidence": 0.8, '
    body += '"document_type": "unrelated", "topic_match": "none", "reason": "nope"}'
    raw = f"```json\n{body}\n```"
    r = parse_response(raw)
    assert r is not None
    assert r.decision == "REJECT"


def test_parse_trailing_commas():
    raw = '{"decision": "REVIEW", "confidence": 0.5, "reason": "x",}'
    r = parse_response(raw)
    assert r is not None
    assert r.decision == "REVIEW"


def test_parse_invalid_decision_normalized_to_review():
    raw = '{"decision": "maybe", "confidence": 0.9, "document_type": "x", "topic_match": "?"}'
    r = parse_response(raw)
    assert r.decision == "REVIEW"
    assert r.document_type == "unknown"
    assert r.topic_match == "none"


def test_parse_not_json():
    assert parse_response("I think this document is relevant") is None


def test_parse_empty():
    assert parse_response("") is None


def test_parse_nan_confidence():
    raw = '{"decision": "ACCEPT", "confidence": "huge", "document_type": "curriculum"}'
    r = parse_response(raw)
    assert r.confidence == 0.0


def test_parse_confidence_clamped():
    raw = '{"decision": "ACCEPT", "confidence": 5}'
    assert parse_response(raw).confidence == 1.0


def test_malformed_response_recovers_to_review(settings):
    cls = OllamaClassifier(settings)

    class BrokenClient:
        def __init__(self, payload):
            pass

    # monkeypatch _ask to always return garbage
    cls._ask = lambda *a, **k: "not json at all"
    result = cls.classify(topic="Cybersecurity", title="X", metadata_text="", excerpt="y")
    assert result is not None
    assert result.decision == "REVIEW"
    assert result.reason == "malformed_model_response"


# ── decision combination ─────────────────────────────────────────────────────


def test_combine_no_embedding_uses_llm(settings):
    assert combine(None, _resp("ACCEPT"), settings) == "ACCEPT"
    assert combine(None, _resp("REJECT"), settings) == "REJECT"


def test_combine_gray_zone_uses_llm(settings):
    assert combine(0.5, _resp("ACCEPT"), settings) == "ACCEPT"
    assert combine(0.5, _resp("REJECT"), settings) == "REJECT"


def test_combine_agree_uses_decision(settings):
    assert combine(0.8, _resp("ACCEPT"), settings) == "ACCEPT"
    assert combine(0.1, _resp("REJECT"), settings) == "REJECT"


def test_combine_conflict_review(settings):
    assert combine(0.8, _resp("REJECT"), settings) == "REVIEW"
    assert combine(0.1, _resp("ACCEPT"), settings) == "REVIEW"


def test_combine_no_ai_response_review(settings):
    assert combine(0.9, None, settings) == "REVIEW"


def test_build_filter_result(settings):
    r = build_filter_result(0.8, "ok", _resp("ACCEPT", 0.95), 1, settings)
    assert r.final_decision == "ACCEPT"
    assert r.similarity == 0.8
    assert r.embedding_stage == "ok"
    assert r.ai_attempts == 1


# ── FakeClassifier ───────────────────────────────────────────────────────────


def test_fake_classifier_relevant():
    cls = FakeClassifier(
        {
            "curriculum": _resp("ACCEPT"),
            "cafeteria": _resp("REJECT", 0.99),
        }
    )
    r = cls.classify(
        topic="Cybersecurity",
        title="Master Curriculum",
        metadata_text="",
        excerpt="courses",
    )
    assert r.decision == "ACCEPT"
    r2 = cls.classify(
        topic="Cybersecurity",
        title="Cafeteria Rules",
        metadata_text="",
        excerpt="food",
    )
    assert r2.decision == "REJECT"


def test_fake_classifier_ambiguous():
    cls = FakeClassifier({})
    r = cls.classify(topic="Cybersecurity", title="Unknown doc", metadata_text="", excerpt="?")
    assert r.decision == "REVIEW"
