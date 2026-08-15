"""MIND core data schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceStatus = Literal[
    "discovered",
    "candidate",
    "downloading",
    "downloaded",
    "duplicate",
    "rejected_validation",
    "extracting",
    "extracted",
    "ocr_required",
    "filtering",
    "accepted",
    "review",
    "rejected",
    "failed",
]

AiDecision = Literal["ACCEPT", "REJECT", "REVIEW"]
DocumentType = Literal[
    "curriculum",
    "syllabus",
    "course_description",
    "program_information",
    "unrelated",
    "unknown",
]
TopicMatch = Literal["high", "medium", "low", "none"]

TERMINAL_STATUSES = {"accepted", "review", "rejected"}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SearchResult(BaseModel):
    """A single result returned by a search provider."""

    title: str = ""
    url: str
    snippet: str = ""
    source_domain: str = ""
    search_query: str = ""
    discovered_at: str = Field(default_factory=utcnow)


class QueryIntent(BaseModel):
    """A generated search intent for a topic."""

    query: str
    group: str  # base | site | filetype | colombia
    country: str = ""


class DownloadResult(BaseModel):
    status: Literal["ok", "error"]
    url: str = ""
    file_path: str = ""
    file_hash: str = ""
    file_size: int = 0
    content_type: str = ""
    http_status: int = 0
    error: str = ""


class PdfMetadata(BaseModel):
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    producer: str = ""
    creation_date: str = ""
    modification_date: str = ""


class ExtractionResult(BaseModel):
    """Result of PDF text extraction / normalization."""

    status: Literal["ok", "ocr_required", "failed"]
    error: str = ""
    page_count: int = 0
    text_chars: int = 0
    language: str = "unknown"
    metadata: PdfMetadata = PdfMetadata()
    text: str = ""
    markdown: str = ""
    method: Literal["pdf_text", "ocr", "none"] = "none"
    headings: list[str] = Field(default_factory=list)


class AiResponse(BaseModel):
    """Structured JSON output expected from the local LLM classifier."""

    decision: AiDecision
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    document_type: DocumentType = "unknown"
    topic_match: TopicMatch = "none"
    reason: str = ""


class FilterResult(BaseModel):
    similarity: float | None = None
    embedding_stage: Literal["ok", "skipped", "error"] = "skipped"
    ai_response: AiResponse | None = None
    ai_attempts: int = 0
    final_decision: AiDecision = "REVIEW"
    model_available: bool = True
    note: str = ""


class StageStatus(BaseModel):
    name: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class PipelineStats(BaseModel):
    search_results: int = 0
    candidates: int = 0
    downloaded: int = 0
    valid_pdfs: int = 0
    duplicates_removed: int = 0
    text_extracted: int = 0
    ocr_required: int = 0
    filtered: int = 0
    accepted: int = 0
    review: int = 0
    rejected: int = 0


class ProjectSummary(BaseModel):
    id: int
    slug: str
    topic: str
    status: str
    created_at: str
    updated_at: str
    stats: PipelineStats = PipelineStats()
    run_id: int | None = None
    run_status: str = ""


def to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
