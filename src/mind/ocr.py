"""OCR support for scanned / low-text PDFs.

An ``OCRProvider`` abstraction keeps the pipeline decoupled from the concrete
OCR engine. The built-in provider uses Tesseract through ``pytesseract``:

    PDF
     ↓ rasterize pages with PyMuPDF
     ↓ OCR each page with Tesseract
     ↓ full text

If Tesseract is unavailable the provider reports ``available() == False`` and
the pipeline marks the document as ``ocr_required`` instead of failing.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from mind.config import Settings
from mind.logging import get_logger
from mind.schemas import ExtractionResult, PdfMetadata

log = get_logger("mind.ocr")


class OCRProvider(ABC):
    id: str = "base"

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def ocr_pdf(self, path: Path) -> str:
        """Return the full OCR text of a PDF."""
        raise NotImplementedError


class TesseractOCRProvider(OCRProvider):
    id = "tesseract"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or _load_default()
        self._bin = shutil.which("tesseract")

    def available(self) -> bool:
        if not self._bin:
            return False
        try:
            subprocess.run(
                [self._bin, "--version"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return True
        except Exception:
            return False

    def ocr_pdf(self, path: Path) -> str:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        cfg = self.settings.ocr
        pytesseract.pytesseract.tesseract_cmd = self._bin or "tesseract"
        doc = fitz.open(path)
        try:
            parts: list[str] = []
            for page_index, page in enumerate(doc):
                pix = page.get_pixmap(dpi=cfg.dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img, lang=cfg.lang)
                parts.append(text)
                if page_index % 10 == 0:
                    log.info("OCR page %s/%s", page_index + 1, doc.page_count)
        finally:
            doc.close()
        return "\n\n".join(parts)


def get_ocr_provider(settings: Settings | None = None) -> OCRProvider:
    settings = settings or _load_default()
    if settings.ocr.engine == "tesseract":
        return TesseractOCRProvider(settings)
    raise ValueError(f"Unknown OCR engine: {settings.ocr.engine}")


def ocr_and_rebuild(path: Path, settings: Settings | None = None) -> ExtractionResult:
    """Run OCR on a low-text PDF and return a rebuilt ExtractionResult."""
    settings = settings or _load_default()
    provider = get_ocr_provider(settings)
    if not provider.available():
        log.warning("OCR engine '%s' not available; marking document ocr_required", provider.id)
        return ExtractionResult(
            status="ocr_required",
            method="none",
            error="ocr_engine_unavailable",
        )

    import fitz

    from mind.extract import build_markdown, detect_language

    try:
        doc = fitz.open(path)
        meta_raw = doc.metadata or {}
        page_count = doc.page_count
        doc.close()
    except Exception as exc:
        return ExtractionResult(status="failed", error=f"open_failed: {exc}")

    try:
        text = provider.ocr_pdf(path)
    except Exception as exc:
        log.warning("OCR failed for %s: %s", path, exc)
        return ExtractionResult(status="ocr_required", method="none", error=f"ocr_failed: {exc}")

    text = text.strip()
    if len(text) < settings.pdf.min_text_chars:
        return ExtractionResult(status="ocr_required", method="none", error="ocr_low_text")

    metadata = PdfMetadata(
        title=(meta_raw.get("title") or "").strip(),
        author=(meta_raw.get("author") or "").strip(),
        subject=(meta_raw.get("subject") or "").strip(),
        keywords=(meta_raw.get("keywords") or "").strip(),
        producer=(meta_raw.get("producer") or "").strip(),
        creation_date=(meta_raw.get("creationDate") or "").strip(),
        modification_date=(meta_raw.get("modDate") or "").strip(),
    )
    markdown = build_markdown(metadata, text, method="ocr")
    return ExtractionResult(
        status="ok",
        page_count=page_count,
        text_chars=len(text),
        language=detect_language(text),
        metadata=metadata,
        text=text,
        markdown=markdown,
        method="ocr",
    )


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
