"""Decision combination logic for the filtering stage.

Combines the embedding similarity hint with the LLM classification:

* No embedding score → the LLM decision is final.
* Embedding score in the gray zone → the LLM decision is final.
* Embedding hint and LLM decision agree → use that decision.
* Embedding hint and LLM decision conflict → REVIEW.
"""

from __future__ import annotations

from mind.config import Settings
from mind.schemas import AiDecision, FilterResult


def combine(
    similarity: float | None,
    ai_response: object,
    settings: Settings | None = None,
) -> str:
    """Combine the embedding hint and the LLM response into a final decision."""
    settings = settings or _load_default()
    cfg = settings.embeddings
    if ai_response is None:
        return "REVIEW"
    llm_decision = ai_response.decision  # type: ignore[attr-defined]

    if similarity is None:
        return llm_decision

    if similarity <= cfg.reject_below:
        hint: AiDecision = "REJECT"
    elif similarity >= cfg.accept_above:
        hint = "ACCEPT"
    else:
        hint = "REVIEW"

    if hint == "REVIEW":
        return llm_decision
    if hint == llm_decision:
        return llm_decision
    return "REVIEW"


def build_filter_result(
    similarity: float | None,
    embedding_stage: str,
    ai_response,
    ai_attempts: int,
    settings: Settings | None = None,
) -> FilterResult:
    settings = settings or _load_default()
    final = combine(similarity, ai_response, settings)
    note = ""
    if similarity is not None and final == "REVIEW":
        note = "embedding_llm_conflict_or_gray_zone"
    return FilterResult(
        similarity=similarity,
        embedding_stage=embedding_stage,
        ai_response=ai_response,
        ai_attempts=ai_attempts,
        final_decision=final,
        model_available=ai_response is not None,
        note=note,
    )


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
