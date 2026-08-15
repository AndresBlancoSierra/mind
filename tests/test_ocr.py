"""OCR tests (require tesseract installed).

Marked `ocr` so they can be skipped with `-m "not ocr"`.
"""

from __future__ import annotations

import pytest

from mind.ocr import TesseractOCRProvider, get_ocr_provider, ocr_and_rebuild

pytestmark = pytest.mark.ocr


@pytest.fixture()
def ocr_settings(settings):
    settings.ocr.enabled = True
    settings.ocr.engine = "tesseract"
    return settings


def _tesseract_available() -> bool:
    return TesseractOCRProvider().available()


def test_tesseract_provider_available_or_skipped():
    if not _tesseract_available():
        pytest.skip("tesseract not installed")


def test_get_ocr_provider(ocr_settings):
    provider = get_ocr_provider(ocr_settings)
    assert provider.id == "tesseract"


def test_ocr_rebuilds_scanned_pdf(ocr_settings, fixtures_dir):
    if not _tesseract_available():
        pytest.skip("tesseract not installed")
    result = ocr_and_rebuild(fixtures_dir / "scanned_pdf.pdf", ocr_settings)
    assert result.status == "ok"
    assert result.method == "ocr"
    assert result.text
    assert "syllabus" in result.text.lower()
    assert result.page_count == 1
    assert "CYBERSECURITY SYLLABUS" in result.markdown


def test_ocr_unavailable_marks_ocr_required(ocr_settings, monkeypatch, fixtures_dir):
    class BrokenProvider:
        id = "broken"

        def available(self) -> bool:
            return False

        def ocr_pdf(self, path):
            raise AssertionError("should not be called")

    monkeypatch.setattr("mind.ocr.get_ocr_provider", lambda settings: BrokenProvider())
    result = ocr_and_rebuild(fixtures_dir / "scanned_pdf.pdf", ocr_settings)
    assert result.status == "ocr_required"
    assert result.error == "ocr_engine_unavailable"
