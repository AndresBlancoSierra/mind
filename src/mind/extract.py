"""PDF validation, text extraction and normalized Markdown generation.

The original PDF is never modified. Processing produces:

* extracted plain text,
* document metadata,
* a best-effort list of headings,
* a normalized Markdown representation,
* a lightweight language heuristic (en/es/other).
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from mind.config import Settings
from mind.logging import get_logger
from mind.schemas import ExtractionResult, PdfMetadata

log = get_logger("mind.extract")

_EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "have",
    "are",
    "was",
    "will",
    "your",
    "you",
    "they",
    "their",
    "there",
    "what",
    "which",
    "such",
    "these",
    "those",
    "about",
    "into",
    "more",
    "other",
    "than",
    "then",
    "course",
    "student",
    "students",
    "program",
    "learning",
}
_ES_STOPWORDS = {
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "y",
    "o",
    "u",
    "en",
    "que",
    "un",
    "una",
    "con",
    "por",
    "para",
    "este",
    "esta",
    "como",
    "más",
    "al",
    "lo",
    "su",
    "sus",
    "curso",
    "estudiante",
    "programa",
    "aprendizaje",
    "universidad",
    "créditos",
}


def validate_pdf(path: Path, settings: Settings | None = None) -> tuple[bool, str]:
    """Basic traditional validation of a PDF file.

    Returns ``(ok, reason)``. When ``ok`` is ``False``, ``reason`` is one of
    ``corrupt_pdf``, ``empty_pdf``, ``too_many_pages`` or ``too_small``.
    """
    settings = settings or _load_default()
    try:
        size = path.stat().st_size
    except OSError:
        return False, "missing_file"
    if size == 0:
        return False, "empty_pdf"
    if size < 16:
        return False, "too_small"

    try:
        doc = fitz.open(path)
    except Exception:
        return False, "corrupt_pdf"
    try:
        page_count = doc.page_count
    finally:
        doc.close()
    if page_count <= 0:
        return False, "empty_pdf"
    if page_count > settings.pdf.max_pages:
        return False, "too_many_pages"
    return True, "ok"


def detect_language(text: str) -> str:
    """Heuristic language detection for en/es/other based on stopwords."""
    tokens = re.findall(r"[a-záéíóúñü]+", text[:20000].lower())
    if not tokens:
        return "unknown"
    en = sum(1 for t in tokens if t in _EN_STOPWORDS)
    es = sum(1 for t in tokens if t in _ES_STOPWORDS)
    total = len(tokens)
    en_ratio, es_ratio = en / total, es / total
    if en_ratio >= 0.05 and en_ratio >= es_ratio:
        return "en"
    if es_ratio >= 0.05:
        return "es"
    return "unknown"


_HEADING_RE = re.compile(
    r"^(?!.*[.;,!?]$)"
    r"(?=[A-ZÀ-Þ0-9])"
    r"^.{3,90}$"
)


def detect_headings(pages_text: list[str]) -> list[str]:
    """Best-effort heading detection.

    A line is considered a heading candidate when it starts with an uppercase
    letter or digit, is 3-90 chars long, and does not end in sentence
    punctuation. This is a heuristic; it is not guaranteed to be accurate.
    """
    headings: list[str] = []
    for page in pages_text:
        for line in page.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) > 90 or len(line) < 3:
                continue
            if _HEADING_RE.match(line):
                headings.append(line)
    return headings[:200]


def extract_pdf(path: Path, settings: Settings | None = None) -> ExtractionResult:
    """Extract text + metadata from a PDF and build a normalized Markdown."""
    settings = settings or _load_default()
    ok, reason = validate_pdf(path, settings)
    if not ok:
        return ExtractionResult(status="failed", error=reason)

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return ExtractionResult(status="failed", error=f"open_failed: {exc}")

    try:
        meta_raw = doc.metadata or {}
        metadata = PdfMetadata(
            title=(meta_raw.get("title") or "").strip(),
            author=(meta_raw.get("author") or "").strip(),
            subject=(meta_raw.get("subject") or "").strip(),
            keywords=(meta_raw.get("keywords") or "").strip(),
            producer=(meta_raw.get("producer") or "").strip(),
            creation_date=(meta_raw.get("creationDate") or "").strip(),
            modification_date=(meta_raw.get("modDate") or "").strip(),
        )
        page_count = doc.page_count
        pages_text: list[str] = []
        for page in doc:
            pages_text.append(page.get_text("text"))
    finally:
        doc.close()

    full_text = "\n\n".join(pages_text).strip()
    text_chars = len(full_text)

    if text_chars < settings.pdf.min_text_chars:
        return ExtractionResult(
            status="ocr_required",
            page_count=page_count,
            text_chars=text_chars,
            language=detect_language(full_text),
            metadata=metadata,
            text=full_text,
            method="none",
        )

    headings = detect_headings(pages_text)
    markdown = build_markdown(metadata, full_text, headings, method="pdf_text")

    return ExtractionResult(
        status="ok",
        page_count=page_count,
        text_chars=text_chars,
        language=detect_language(full_text),
        metadata=metadata,
        text=full_text,
        markdown=markdown,
        method="pdf_text",
        headings=headings,
    )


def build_markdown(
    metadata: PdfMetadata,
    text: str,
    headings: list[str] | None = None,
    method: str = "pdf_text",
) -> str:
    """Build the normalized Markdown representation of a document.

    Only facts actually present in the extracted content are written. Unknown
    fields are left as "Unknown".
    """
    title = metadata.title or "Untitled Document"
    lines = [
        f"# {title}",
        "",
        "---",
        "",
        f"- **Extraction method**: {method}",
    ]
    for label, value in (
        ("Author", metadata.author),
        ("Subject", metadata.subject),
        ("Keywords", metadata.keywords),
        ("Producer", metadata.producer),
    ):
        if value:
            lines.append(f"- **{label}**: {value}")
    if not any(getattr(metadata, f) for f in ("author", "subject", "keywords", "producer")):
        lines.append("- Metadata: not available in the original PDF.")

    if headings:
        lines += ["", "## Detected Headings"]
        for h in headings[:80]:
            lines.append(f"- {h}")

    lines += ["", "## Content", ""]
    lines.append(text.strip())
    return "\n".join(lines).strip() + "\n"


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
