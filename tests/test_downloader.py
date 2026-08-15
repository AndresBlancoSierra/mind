"""Tests for the document downloader."""

from __future__ import annotations

import hashlib

from mind.download import Downloader


def _hash_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_download_success(settings, http_server, tmp_path):
    dest = tmp_path / "doc.pdf"
    result = Downloader(settings).download(f"{http_server}/text_pdf.pdf", dest)
    assert result.status == "ok"
    assert dest.exists()
    assert result.file_hash == _hash_of(dest)
    assert result.file_size == dest.stat().st_size
    assert result.content_type == "application/pdf"
    assert dest.read_bytes()[:4] == b"%PDF"


def test_invalid_url(settings, tmp_path):
    result = Downloader(settings).download("http://127.0.0.1:1/nope.pdf", tmp_path / "x.pdf")
    assert result.status == "error"
    assert "http_error" in result.error
    assert not (tmp_path / "x.pdf").exists()


def test_http_error(settings, http_server, tmp_path):
    result = Downloader(settings).download(f"{http_server}/missing.pdf", tmp_path / "x.pdf")
    assert result.status == "error"
    assert result.http_status == 404
    assert result.error.startswith("http_")


def test_redirect(settings, http_server, tmp_path):
    dest = tmp_path / "r.pdf"
    result = Downloader(settings).download(f"{http_server}/redirect.pdf", dest)
    assert result.status == "ok"
    assert dest.read_bytes()[:4] == b"%PDF"
    assert result.url.endswith("/text_pdf.pdf")


def test_html_masquerade_rejected(settings, http_server, tmp_path):
    dest = tmp_path / "x.pdf"
    result = Downloader(settings).download(f"{http_server}/html-masquerade.pdf", dest)
    assert result.status == "error"
    assert result.error == "not_a_pdf_magic"
    assert not dest.exists()


def test_html_content_type_rejected(settings, http_server, tmp_path):
    result = Downloader(settings).download(f"{http_server}/", tmp_path / "index")
    assert result.status == "error"
    assert "unsupported_content_type" in result.error


def test_mislabeled_pdf_sniffed(settings, http_server, tmp_path):
    # text/html content type but URL ends in .pdf and bytes are a real PDF
    dest = tmp_path / "x.pdf"
    result = Downloader(settings).download(f"{http_server}/mislabeled-pdf.pdf", dest)
    assert result.status == "ok"
    assert dest.read_bytes()[:4] == b"%PDF"


def test_duplicate_file_hash(settings, http_server, tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    ra = Downloader(settings).download(f"{http_server}/text_pdf.pdf", a)
    rb = Downloader(settings).download(f"{http_server}/text_pdf.pdf", b)
    assert ra.file_hash == rb.file_hash
    assert _hash_of(a) == _hash_of(b)
