"""MIND storage: SQLite index + per-project filesystem layout.

Layout under ``data_dir/``:

    data/
    ├── mind.db                          # SQLite index
    └── projects/
        └── <slug>/
            ├── project.json
            ├── sources/
            │   ├── raw/<source_id>.pdf
            │   ├── processed/<source_id>.md
            │   ├── metadata/<source_id>.json
            │   └── rejected/<source_id>.pdf     # kept for traceability
            └── results/
                ├── accepted/<source_id>.json
                ├── review/<source_id>.json
                └── rejected/<source_id>.json

The SQLite database is the primary queryable index; the filesystem preserves
every original artifact (raw PDFs, normalized Markdown, per-source metadata
and decision files).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

from mind.logging import get_logger
from mind.schemas import PipelineStats, utcnow

log = get_logger("mind.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL,
    title TEXT DEFAULT '',
    snippet TEXT DEFAULT '',
    source_domain TEXT DEFAULT '',
    search_query TEXT DEFAULT '',
    discovered_at TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'discovered',
    rejection_reason TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    file_hash TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    content_type TEXT DEFAULT '',
    http_status INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '',
    page_count INTEGER DEFAULT 0,
    language TEXT DEFAULT 'unknown',
    text_chars INTEGER DEFAULT 0,
    extraction_method TEXT DEFAULT 'none',
    similarity REAL,
    ai_decision TEXT DEFAULT '',
    ai_confidence REAL,
    ai_document_type TEXT DEFAULT '',
    ai_topic_match TEXT DEFAULT '',
    ai_reason TEXT DEFAULT '',
    ai_raw TEXT DEFAULT '',
    ai_attempts INTEGER DEFAULT 0,
    processed_path TEXT DEFAULT '',
    embedding_stage TEXT DEFAULT 'skipped',
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(project_id, url_hash);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(project_id, status);
CREATE INDEX IF NOT EXISTS idx_sources_decision ON sources(project_id, ai_decision);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL DEFAULT 'pending',
    current_stage TEXT DEFAULT '',
    stages TEXT DEFAULT '[]',
    stats TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    started_at TEXT DEFAULT '',
    finished_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pipeline_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER DEFAULT 0,
    project_id INTEGER DEFAULT 0,
    level TEXT DEFAULT 'info',
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")[:60] or "project"


class Storage:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "mind.db"
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    # ── connection helpers ────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.executescript(SCHEMA)
            conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn().execute(sql, params)
            self._conn().commit()
            return cur

    def _query_one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self._conn().execute(sql, params).fetchone()
        return dict(row) if row else None

    def _query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        rows = self._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── projects ──────────────────────────────────────────────────────────────

    def create_project(self, topic: str) -> dict:
        slug = slugify(topic)
        existing = self._query_one("SELECT * FROM projects WHERE slug=?", (slug,))
        if existing:
            raise ValueError(
                f"Project '{slug}' already exists. Use a distinct topic or delete it first."
            )
        now = utcnow()
        self._execute(
            "INSERT INTO projects (slug, topic, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (slug, topic, "created", now, now),
        )
        self._write_project_json(slug, topic, now)
        return self.get_project_by_slug(slug)  # type: ignore[return-value]

    def get_project_by_slug(self, slug: str) -> dict | None:
        return self._query_one("SELECT * FROM projects WHERE slug=?", (slug,))

    def get_project(self, project_id: int) -> dict | None:
        return self._query_one("SELECT * FROM projects WHERE id=?", (project_id,))

    def list_projects(self) -> list[dict]:
        return self._query_all("SELECT * FROM projects ORDER BY created_at DESC")

    def touch_project(self, project_id: int) -> None:
        self._execute("UPDATE projects SET updated_at=? WHERE id=?", (utcnow(), project_id))

    def update_project_status(self, project_id: int, status: str) -> None:
        self._execute(
            "UPDATE projects SET status=?, updated_at=? WHERE id=?",
            (status, utcnow(), project_id),
        )

    def delete_project(self, slug: str) -> bool:
        project = self.get_project_by_slug(slug)
        if not project:
            return False
        self._execute("DELETE FROM pipeline_logs WHERE project_id=?", (project["id"],))
        self._execute("DELETE FROM pipeline_runs WHERE project_id=?", (project["id"],))
        self._execute("DELETE FROM sources WHERE project_id=?", (project["id"],))
        self._execute("DELETE FROM projects WHERE id=?", (project["id"],))
        shutil.rmtree(self.project_dir(slug), ignore_errors=True)
        return True

    def _write_project_json(self, slug: str, topic: str, now: str) -> None:
        d = self.project_dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / "project.json").write_text(
            json.dumps({"slug": slug, "topic": topic, "created_at": now}, indent=2)
        )

    # ── sources ───────────────────────────────────────────────────────────────

    def add_source(
        self,
        project_id: int,
        url: str,
        title: str = "",
        snippet: str = "",
        source_domain: str = "",
        search_query: str = "",
        discovered_at: str = "",
    ) -> int:
        from hashlib import sha256

        url_hash = sha256(url.encode()).hexdigest()
        existing = self._query_one(
            "SELECT id FROM sources WHERE project_id=? AND url_hash=?",
            (project_id, url_hash),
        )
        if existing:
            return int(existing["id"])
        cur = self._execute(
            "INSERT INTO sources (project_id, url, url_hash, title, snippet, source_domain, "
            "search_query, discovered_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                project_id,
                url,
                url_hash,
                title,
                snippet,
                source_domain,
                search_query,
                discovered_at or utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def update_source(self, source_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "rejection_reason",
            "file_path",
            "file_hash",
            "file_size",
            "content_type",
            "http_status",
            "metadata_json",
            "page_count",
            "language",
            "text_chars",
            "extraction_method",
            "similarity",
            "ai_decision",
            "ai_confidence",
            "ai_document_type",
            "ai_topic_match",
            "ai_reason",
            "ai_raw",
            "ai_attempts",
            "processed_path",
            "embedding_stage",
            "note",
            "title",
            "snippet",
        }
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        values = [fields[c] for c in cols] + [source_id]
        self._execute(f"UPDATE sources SET {sets} WHERE id=?", tuple(values))

    def get_source(self, source_id: int) -> dict | None:
        return self._query_one("SELECT * FROM sources WHERE id=?", (source_id,))

    def get_source_by_file_hash(self, project_id: int, file_hash: str) -> dict | None:
        return self._query_one(
            "SELECT * FROM sources WHERE project_id=? AND file_hash=? LIMIT 1",
            (project_id, file_hash),
        )

    def list_sources(
        self,
        project_id: int,
        status: str | None = None,
        decision: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        sql = "SELECT * FROM sources WHERE project_id=?"
        params: list = [project_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        if decision:
            sql += " AND ai_decision=?"
            params.append(decision.upper())
        if q:
            sql += " AND (title LIKE ? OR url LIKE ? OR snippet LIKE ?)"
            like = f"%{q}%"
            params += [like, like, like]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self._query_all(sql, tuple(params))

    def count_sources(self, project_id: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for status, _ in (
            ("discovered", None),
            ("candidate", None),
            ("downloaded", None),
            ("duplicate", None),
            ("rejected_validation", None),
            ("extracted", None),
            ("ocr_required", None),
            ("accepted", None),
            ("review", None),
            ("rejected", None),
            ("failed", None),
        ):
            row = (
                self._conn()
                .execute(
                    "SELECT COUNT(*) AS n FROM sources WHERE project_id=? AND status=?",
                    (project_id, status),
                )
                .fetchone()
            )
            counts[status] = int(row["n"])
        return counts

    # ── pipeline runs ─────────────────────────────────────────────────────────

    def create_run(self, project_id: int) -> int:
        cur = self._execute(
            "INSERT INTO pipeline_runs (project_id, status, started_at) VALUES (?,?,?)",
            (project_id, "running", utcnow()),
        )
        return int(cur.lastrowid)

    def update_run(self, run_id: int, **fields: Any) -> None:
        allowed = {"status", "current_stage", "stages", "stats", "error", "finished_at"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        values = []
        for c in cols:
            v = fields[c]
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            values.append(v)
        values.append(run_id)
        self._execute(f"UPDATE pipeline_runs SET {sets} WHERE id=?", tuple(values))

    def get_run(self, run_id: int) -> dict | None:
        return self._query_one("SELECT * FROM pipeline_runs WHERE id=?", (run_id,))

    def get_latest_run(self, project_id: int) -> dict | None:
        return self._query_one(
            "SELECT * FROM pipeline_runs WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,),
        )

    def add_log(self, run_id: int, project_id: int, level: str, message: str) -> None:
        self._execute(
            "INSERT INTO pipeline_logs (run_id, project_id, level, message, created_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, project_id, level, message, utcnow()),
        )

    def list_logs(self, project_id: int, limit: int = 200) -> list[dict]:
        return self._query_all(
            "SELECT * FROM pipeline_logs WHERE project_id=? ORDER BY id DESC LIMIT ?",
            (project_id, limit),
        )

    # ── filesystem helpers ────────────────────────────────────────────────────

    def project_dir(self, slug: str) -> Path:
        return self.data_dir / "projects" / slug

    def raw_dir(self, slug: str) -> Path:
        return self.project_dir(slug) / "sources" / "raw"

    def processed_dir(self, slug: str) -> Path:
        return self.project_dir(slug) / "sources" / "processed"

    def metadata_dir(self, slug: str) -> Path:
        return self.project_dir(slug) / "sources" / "metadata"

    def rejected_dir(self, slug: str) -> Path:
        return self.project_dir(slug) / "sources" / "rejected"

    def results_dir(self, slug: str, decision: str) -> Path:
        dir_name = {
            "ACCEPT": "accepted",
            "REJECT": "rejected",
            "REVIEW": "review",
        }.get(decision.upper(), decision.lower())
        return self.project_dir(slug) / "results" / dir_name

    def raw_path(self, slug: str, source_id: int) -> Path:
        return self.raw_dir(slug) / f"{source_id}.pdf"

    def processed_path(self, slug: str, source_id: int) -> Path:
        return self.processed_dir(slug) / f"{source_id}.md"

    def metadata_path(self, slug: str, source_id: int) -> Path:
        return self.metadata_dir(slug) / f"{source_id}.json"

    def rejected_path(self, slug: str, source_id: int) -> Path:
        return self.rejected_dir(slug) / f"{source_id}.pdf"

    def result_path(self, slug: str, source_id: int, decision: str) -> Path:
        return self.results_dir(slug, decision) / f"{source_id}.json"


def project_stats(storage: Storage, project_id: int) -> PipelineStats:
    counts = storage.count_sources(project_id)

    with_file = {
        "downloaded",
        "candidate",
        "extracted",
        "ocr_required",
        "accepted",
        "review",
        "rejected",
        "duplicate",
        "rejected_validation",
    }
    valid = {"candidate", "extracted", "ocr_required", "accepted", "review", "rejected"}
    extracted = {"extracted", "accepted", "review", "rejected"}

    def total(statuses: set[str]) -> int:
        return sum(counts[s] for s in statuses if s in counts)

    return PipelineStats(
        search_results=sum(counts.values()),
        candidates=total(valid),
        downloaded=total(with_file),
        valid_pdfs=total(valid),
        duplicates_removed=counts.get("duplicate", 0),
        text_extracted=total(extracted),
        ocr_required=counts.get("ocr_required", 0),
        filtered=counts.get("accepted", 0) + counts.get("review", 0) + counts.get("rejected", 0),
        accepted=counts.get("accepted", 0),
        review=counts.get("review", 0),
        rejected=counts.get("rejected", 0),
    )
