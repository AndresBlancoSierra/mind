"""Tests for PDF validation and text extraction."""

from __future__ import annotations

from pathlib import Path

from mind.extract import build_markdown, detect_language, extract_pdf, validate_pdf
from mind.schemas import PdfMetadata

FIXTURES = Path(__file__).parent / "fixtures"


def test_text_pdf_extraction(settings):
    result = extract_pdf(FIXTURES / "text_pdf.pdf", settings)
    assert result.status == "ok"
    assert result.text_chars > 100
    assert "cybersecurity" in result.text.lower()
    assert result.page_count == 1
    assert result.method == "pdf_text"
    assert result.metadata.title == "Master of Cybersecurity Curriculum"


def test_scanned_pdf_detected(settings):
    result = extract_pdf(FIXTURES / "scanned_pdf.pdf", settings)
    assert result.status == "ocr_required"
    assert result.text_chars == 0
    assert result.method == "none"


def test_empty_pdf(settings):
    result = extract_pdf(FIXTURES / "empty_pdf.pdf", settings)
    assert result.status == "ocr_required"


def test_corrupted_pdf(settings):
    ok, reason = validate_pdf(FIXTURES / "corrupted.pdf", settings)
    assert not ok
    assert reason == "corrupt_pdf"
    result = extract_pdf(FIXTURES / "corrupted.pdf", settings)
    assert result.status == "failed"
    assert result.error == "corrupt_pdf"


def test_missing_file(settings, tmp_path):
    ok, reason = validate_pdf(tmp_path / "nope.pdf", settings)
    assert not ok
    assert reason == "missing_file"


def test_zero_byte_file(settings, tmp_path):
    p = tmp_path / "zero.pdf"
    p.write_bytes(b"")
    ok, reason = validate_pdf(p, settings)
    assert not ok
    assert reason == "empty_pdf"


def test_too_many_pages(settings):
    settings.pdf.max_pages = 0
    result = extract_pdf(FIXTURES / "text_pdf.pdf", settings)
    assert result.status == "failed"
    assert result.error == "too_many_pages"


def test_detect_language():
    assert detect_language("the student program learning course and network security") == "en"
    assert detect_language("el curso de la universidad para estudiantes y programas") == "es"
    assert detect_language("") == "unknown"


def test_headings_detected(settings):
    result = extract_pdf(FIXTURES / "text_pdf.pdf", settings)
    assert any("Program Overview" in h for h in result.headings)
    assert any("Learning Outcomes" in h for h in result.headings)


def test_markdown_structure(settings):
    result = extract_pdf(FIXTURES / "text_pdf.pdf", settings)
    md = result.markdown
    assert md.startswith("# Master of Cybersecurity Curriculum")
    assert "## Content" in md
    assert "Extraction method" in md


def test_markdown_no_fabrication():
    md = build_markdown(PdfMetadata(), "Some body text", [], "pdf_text")
    assert "Metadata: not available" in md
    assert "# Untitled Document" in md
    assert "Author" not in md


def test_original_file_untouched(settings):
    before = (FIXTURES / "text_pdf.pdf").read_bytes()
    extract_pdf(FIXTURES / "text_pdf.pdf", settings)
    assert (FIXTURES / "text_pdf.pdf").read_bytes() == before
