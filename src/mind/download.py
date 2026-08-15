"""Robust PDF downloader.

Download behavior:

* Follows redirects safely (bounded by httpx).
* Validates HTTP status and response content type.
* Sniffs the ``%PDF`` magic bytes before accepting a file.
* Enforces a configurable size limit.
* Computes a SHA-256 hash of the file content.
* Never overwrites existing files (unique ids are assigned upstream).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx

from mind.config import Settings
from mind.logging import get_logger
from mind.schemas import DownloadResult

log = get_logger("mind.download")

_MAGIC_PDF = b"%PDF-"
_PDF_RE = re.compile(rb"^%PDF-\d")


class DownloadError(Exception):
    pass


class Downloader:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or _load_default()

    def download(self, url: str, dest: Path) -> DownloadResult:
        """Download ``url`` to ``dest`` and validate that it is a PDF."""
        cfg = self.settings.download
        try:
            with (
                httpx.Client(
                    follow_redirects=True,
                    timeout=httpx.Timeout(cfg.timeout_seconds, connect=cfg.connect_timeout_seconds),
                    headers={"User-Agent": cfg.user_agent},
                ) as client,
                client.stream("GET", url) as resp,
            ):
                return self._process_stream(resp, dest)
        except httpx.HTTPError as exc:
            return DownloadResult(status="error", url=url, error=f"http_error: {exc}")
        except OSError as exc:
            return DownloadResult(status="error", url=url, error=f"os_error: {exc}")

    def _process_stream(self, resp: httpx.Response, dest: Path) -> DownloadResult:
        url = str(resp.request.url)
        if resp.status_code >= 400:
            return DownloadResult(
                status="error",
                url=url,
                error=f"http_{resp.status_code}",
                http_status=resp.status_code,
            )
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if not self._accepts(content_type, url):
            return DownloadResult(
                status="error",
                url=url,
                content_type=content_type,
                http_status=resp.status_code,
                error=f"unsupported_content_type: {content_type or 'unknown'}",
            )

        max_bytes = int(self.settings.download.max_size_mb * 1024 * 1024)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        hasher = hashlib.sha256()
        size = 0
        header = b""
        try:
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise DownloadError(f"too_large: exceeded {max_bytes} bytes")
                    if len(header) < len(_MAGIC_PDF):
                        header += chunk
                    hasher.update(chunk)
                    fh.write(chunk)
        except (DownloadError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            return DownloadResult(
                status="error",
                url=url,
                error=str(exc),
                http_status=resp.status_code,
            )

        if not _PDF_RE.match(header):
            tmp.unlink(missing_ok=True)
            return DownloadResult(
                status="error",
                url=url,
                content_type=content_type,
                http_status=resp.status_code,
                error="not_a_pdf_magic",
            )
        if size == 0:
            tmp.unlink(missing_ok=True)
            return DownloadResult(status="error", url=url, error="empty_file")

        tmp.rename(dest)
        return DownloadResult(
            status="ok",
            url=url,
            file_path=str(dest),
            file_hash=hasher.hexdigest(),
            file_size=size,
            content_type=content_type or "application/pdf",
            http_status=resp.status_code,
        )

    def _accepts(self, content_type: str, url: str = "") -> bool:
        accepted = self.settings.download.accept_content_types
        if not content_type or content_type == "application/octet-stream":
            return True  # allow magic-byte sniffing to decide
        if content_type in accepted:
            return True
        # Some servers serve real PDFs as text/html; trust the magic bytes when
        # the URL clearly points at a PDF file.
        return bool(
            content_type == "text/html" and url.rstrip("/").lower().endswith(".pdf")
        )


def is_pdf_bytes(data: bytes) -> bool:
    return bool(_PDF_RE.match(data[:16]))


def _load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
