"""API tests using FastAPI TestClient.

The api module holds module-level `_settings` / `_storage`; we swap them per
test so every test runs against its own temp data dir.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

import mind.api.main as api  # noqa: E402
from mind.config import Settings
from mind.storage import Storage


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = Settings()
    settings.paths.data_dir = tmp_path / "data"
    settings.search.provider = "offline"
    storage = Storage(settings.paths.data_dir)
    monkeypatch.setattr(api, "_settings", settings)
    monkeypatch.setattr(api, "_storage", storage)
    with TestClient(api.app) as c:
        yield c
    return storage


def _create_project(client, topic="Cybersecurity"):
    resp = client.post("/api/projects", json={"topic": topic})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── health / status ───────────────────────────────────────────────────────────


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "gpu" in body
    assert "runtime" in body


# ── projects CRUD ─────────────────────────────────────────────────────────────


def test_create_project(client):
    body = _create_project(client)
    assert body["slug"] == "cybersecurity"
    assert body["topic"] == "Cybersecurity"
    assert body["status"] == "created"
    assert body["stats"] is not None


def test_create_project_requires_topic(client):
    resp = client.post("/api/projects", json={"topic": "   "})
    assert resp.status_code == 400


def test_create_duplicate_project_conflict(client):
    _create_project(client)
    resp = client.post("/api/projects", json={"topic": "Cybersecurity"})
    assert resp.status_code == 409


def test_list_projects(client):
    _create_project(client, "Cybersecurity")
    _create_project(client, "Machine Learning")
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    slugs = [p["slug"] for p in resp.json()]
    assert slugs == ["machine-learning", "cybersecurity"]  # newest first


def test_get_project(client):
    _create_project(client)
    resp = client.get("/api/projects/cybersecurity")
    assert resp.status_code == 200
    assert resp.json()["topic"] == "Cybersecurity"


def test_get_missing_project_404(client):
    resp = client.get("/api/projects/nope")
    assert resp.status_code == 404


def test_delete_project(client):
    _create_project(client)
    resp = client.delete("/api/projects/cybersecurity")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert client.get("/api/projects/cybersecurity").status_code == 404


def test_delete_missing_project_404(client):
    assert client.delete("/api/projects/nope").status_code == 404


# ── discovery job ─────────────────────────────────────────────────────────────


def test_discover_starts_job(client, monkeypatch):
    created = _create_project(client)

    captured: dict = {}

    class FakePipeline:
        def __init__(self, settings):
            captured["settings"] = settings

        def run(self, slug: str) -> dict:
            captured["slug"] = slug
            return {"status": "completed"}

    monkeypatch.setattr(api, "DiscoveryPipeline", FakePipeline)

    resp = client.post(f"/api/projects/{created['slug']}/discover", params={"offline": "true"})
    assert resp.status_code == 202
    assert resp.json() == {"ok": True, "slug": "cybersecurity"}
    import time

    for _ in range(50):
        if captured.get("slug"):
            break
        time.sleep(0.05)
    assert captured["slug"] == "cybersecurity"
    assert captured["settings"].search.provider == "offline"


def test_discover_missing_project_404(client):
    assert client.post("/api/projects/nope/discover").status_code == 404


# ── progress ──────────────────────────────────────────────────────────────────


def test_progress_idle_when_no_run(client):
    _create_project(client)
    resp = client.get("/api/projects/cybersecurity/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["stages"] == []
    assert body["logs"] == []


def test_progress_missing_project_404(client):
    assert client.get("/api/projects/nope/progress").status_code == 404


# ── sources ───────────────────────────────────────────────────────────────────


def test_sources_empty_for_new_project(client):
    _create_project(client)
    resp = client.get("/api/projects/cybersecurity/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_source_detail_and_file(client, fixtures_dir):
    created = _create_project(client)

    raw_pdf = fixtures_dir / "text_pdf.pdf"
    src_id = api._storage.add_source(
        created["id"],
        url="https://example.edu/curriculum.pdf",
        title="Master Curriculum",
        snippet="A real curriculum.",
        source_domain="example.edu",
    )
    file_path = api._storage.raw_path("cybersecurity", src_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(raw_pdf, file_path)
    api._storage.update_source(
        src_id,
        status="downloaded",
        file_path=str(file_path),
        content_type="application/pdf",
        http_status=200,
    )

    detail = client.get(f"/api/projects/cybersecurity/sources/{src_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "Master Curriculum"
    assert body["status"] == "downloaded"
    assert body["has_processed"] is False

    f = client.get(f"/api/projects/cybersecurity/sources/{src_id}/file")
    assert f.status_code == 200
    assert f.headers["content-type"] == "application/pdf"
    assert f.content.startswith(b"%PDF")


def test_source_missing_project_404(client):
    assert client.get("/api/projects/nope/sources").status_code == 404


# ── frontend index ────────────────────────────────────────────────────────────


def test_index_returns_api_message_or_frontend(client, monkeypatch, tmp_path):
    # Point the frontend dist at a missing dir so the API JSON message is served.
    monkeypatch.setattr(api, "_frontend_dist", tmp_path / "nope")
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"].startswith("MIND API is running")


def test_index_serves_built_frontend(client, monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html>MIND</html>", encoding="utf-8")
    monkeypatch.setattr(api, "_frontend_dist", dist)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"MIND" in resp.content
