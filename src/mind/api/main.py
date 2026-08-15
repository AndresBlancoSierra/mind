"""MIND API server (FastAPI).

Background discovery jobs run in worker threads; the UI polls progress from
the SQLite index. The API serves both JSON and (in production) the built
frontend static files.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from mind import __version__
from mind.config import load_settings
from mind.pipeline import DiscoveryPipeline
from mind.runtime import runtime_report
from mind.storage import Storage, project_stats

app = FastAPI(title="MIND API", version=__version__, description="MIND Phase 1 - discovery API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings = load_settings()
_storage = Storage(_settings.paths.data_dir)

_jobs: dict[int, threading.Thread] = {}
_jobs_lock = threading.Lock()


class CreateProjectRequest(BaseModel):
    topic: str


def _project_payload(project: dict) -> dict:
    run = _storage.get_latest_run(project["id"])
    return {
        "id": project["id"],
        "slug": project["slug"],
        "topic": project["topic"],
        "status": project["status"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "stats": project_stats(_storage, project["id"]).model_dump(mode="json"),
        "run_id": run["id"] if run else None,
        "run_status": run["status"] if run else "",
    }


def _source_payload(src: dict) -> dict:
    view = {
        "id": src["id"],
        "title": src["title"],
        "url": src["url"],
        "snippet": (src["snippet"] or "")[:300],
        "source_domain": src["source_domain"],
        "search_query": src["search_query"],
        "discovered_at": src["discovered_at"],
        "status": src["status"],
        "rejection_reason": src["rejection_reason"],
        "file_size": src["file_size"],
        "content_type": src["content_type"],
        "page_count": src["page_count"],
        "language": src["language"],
        "text_chars": src["text_chars"],
        "extraction_method": src["extraction_method"],
        "similarity": src["similarity"],
        "ai_decision": src["ai_decision"] or "",
        "ai_confidence": src["ai_confidence"],
        "ai_document_type": src["ai_document_type"],
        "ai_topic_match": src["ai_topic_match"],
        "ai_reason": src["ai_reason"],
        "embedding_stage": src["embedding_stage"],
        "note": src["note"],
        "metadata": _parse_json(src["metadata_json"]),
        "has_processed": bool(src["processed_path"] and Path(src["processed_path"]).exists()),
    }
    return view


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ── projects ──────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/status")
def status() -> dict:
    return runtime_report()


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [_project_payload(p) for p in _storage.list_projects()]


@app.post("/api/projects", status_code=201)
def create_project(req: CreateProjectRequest) -> dict:
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    try:
        project = _storage.create_project(topic)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _project_payload(project)


@app.get("/api/projects/{slug}")
def get_project(slug: str) -> dict:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return _project_payload(project)


@app.delete("/api/projects/{slug}")
def delete_project(slug: str) -> dict:
    if not _storage.delete_project(slug):
        raise HTTPException(status_code=404, detail="project not found")
    return {"ok": True}


# ── discovery jobs ────────────────────────────────────────────────────────────


@app.post("/api/projects/{slug}/discover", status_code=202)
def start_discovery(slug: str, offline: bool = Query(False)) -> dict:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    settings = load_settings().model_copy(deep=True)
    if offline:
        settings.search.provider = "offline"

    pipeline = DiscoveryPipeline(settings)

    def runner() -> None:
        try:
            pipeline.run(slug)
        except Exception as exc:  # pragma: no cover - surfaced via run status
            from mind.logging import get_logger

            get_logger("mind.api").error("Job failed for %s: %s", slug, exc)

    t = threading.Thread(target=runner, daemon=True)
    with _jobs_lock:
        t.start()
        _jobs[project["id"]] = t
    return {"ok": True, "slug": slug}


@app.get("/api/projects/{slug}/progress")
def get_progress(slug: str) -> dict:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    run = _storage.get_latest_run(project["id"])
    if not run:
        return {
            "status": "idle",
            "stages": [],
            "stats": project_stats(_storage, project["id"]).model_dump(mode="json"),
            "logs": [],
        }
    return {
        "run_id": run["id"],
        "status": run["status"],
        "current_stage": run["current_stage"],
        "stages": _parse_json(run["stages"]),
        "stats": _parse_json(run["stats"]),
        "error": run["error"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "logs": _storage.list_logs(project["id"], limit=100),
    }


# ── sources ───────────────────────────────────────────────────────────────────


@app.get("/api/projects/{slug}/sources")
def list_sources(
    slug: str,
    status: str | None = None,
    decision: str | None = None,
    q: str | None = None,
    limit: int = Query(200, le=500),
    offset: int = 0,
) -> dict:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    rows = _storage.list_sources(
        project["id"], status=status, decision=decision, q=q, limit=limit, offset=offset
    )
    return {
        "total": len(rows),
        "items": [_source_payload(r) for r in rows],
        "stats": project_stats(_storage, project["id"]).model_dump(mode="json"),
    }


@app.get("/api/projects/{slug}/sources/{source_id}")
def get_source(slug: str, source_id: int) -> dict:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    src = _storage.get_source(source_id)
    if not src or src["project_id"] != project["id"]:
        raise HTTPException(status_code=404, detail="source not found")
    payload = _source_payload(src)
    if src.get("processed_path") and Path(src["processed_path"]).exists():
        payload["content"] = Path(src["processed_path"]).read_text(encoding="utf-8")[:20000]
    return payload


@app.get("/api/projects/{slug}/sources/{source_id}/file")
def source_file(slug: str, source_id: int) -> FileResponse:
    project = _storage.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    src = _storage.get_source(source_id)
    if not src or src["project_id"] != project["id"] or not src.get("file_path"):
        raise HTTPException(status_code=404, detail="source file not found")
    path = Path(src["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="source file missing on disk")
    return FileResponse(path, media_type="application/pdf", filename=f"{source_id}.pdf")


# ── frontend static serving (production build) ────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent.parent.parent / "mind-app" / "dist"


@app.get("/", response_model=None)
def index() -> FileResponse | JSONResponse:
    index_file = _frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "MIND API is running. Frontend not built.", "docs": "/docs"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mind.api.main:app", host=_settings.api.host, port=_settings.api.port)
