"""Shared pytest fixtures for MIND tests."""

from __future__ import annotations

import http.server
import os
import tempfile
import threading
from pathlib import Path

import pytest

# Point all MIND data at a session temp dir BEFORE any mind module is imported.
_TMP_ROOT = tempfile.mkdtemp(prefix="mind-test-")
os.environ["MIND_PATHS__DATA_DIR"] = _TMP_ROOT

from mind.config import Settings  # noqa: E402
from mind.storage import Storage  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def settings(tmp_path) -> Settings:
    s = Settings()
    s.paths.data_dir = tmp_path / "data"
    s.search.provider = "offline"
    s.search.offline_fixture_path = str(FIXTURES / "search_results.json")
    s.embeddings.enabled = False
    s.ocr.enabled = False
    return s


@pytest.fixture()
def storage(settings) -> Storage:
    return Storage(settings.paths.data_dir)


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES


# ── local HTTP server for downloader/pipeline tests ──────────────────────────


class _RedirectHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/redirect.pdf":
            self.send_response(302)
            self.send_header("Location", "/text_pdf.pdf")
            self.end_headers()
            return
        if self.path == "/html-masquerade.pdf":
            body = b"<html><body>not a pdf</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/mislabeled-pdf.pdf":
            # Real PDF served with a text/html content type (misconfigured server).
            body = (Path(__file__).parent / "fixtures" / "text_pdf.pdf").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):  # silence
        pass


@pytest.fixture(scope="session")
def http_server():
    handler = _RedirectHandler
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.chdir(FIXTURES)  # serve the fixtures directory
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join()
