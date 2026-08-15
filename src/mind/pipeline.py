"""MIND Phase 1 discovery pipeline.

Pipeline stages:

    User Topic → Search → Download → Validate → Extract → OCR (if needed)
        → Normalize → Embedding Filter → Local LLM Classification
        → ACCEPT / REVIEW / REJECT

Every stage updates the SQLite index and writes artifacts to the project
filesystem. The pipeline can run synchronously (CLI) or as a background job
(API).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mind.config import Settings, load_settings
from mind.download import Downloader
from mind.extract import extract_pdf, validate_pdf
from mind.filter.classifier import build_filter_result
from mind.filter.embeddings import EmbeddingClient
from mind.filter.llm import OllamaClassifier
from mind.logging import get_logger
from mind.ocr import get_ocr_provider, ocr_and_rebuild
from mind.queries import QueryGenerator
from mind.schemas import StageStatus, utcnow
from mind.search import get_provider
from mind.storage import Storage, project_stats

log = get_logger("mind.pipeline")

STAGES = [
    ("search", "Searching"),
    ("download", "Downloading"),
    ("validate", "Validation"),
    ("extract", "Text Extraction"),
    ("ocr", "OCR (if needed)"),
    ("filter", "Local AI Filtering"),
]

ProgressCallback = Callable[[dict], None]


class PipelineCancelledError(Exception):
    pass


class DiscoveryPipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        llm_classifier=None,
        embed_client=None,
    ):
        self.settings = settings or load_settings()
        self.storage = Storage(self.settings.paths.data_dir)
        self.cancel_event: threading.Event | None = None
        self._llm_classifier = llm_classifier
        self._embed_client = embed_client

    # ── run orchestration ─────────────────────────────────────────────────────

    def run(self, project_slug: str) -> dict:
        project = self.storage.get_project_by_slug(project_slug)
        if not project:
            raise ValueError(f"Unknown project: {project_slug}")

        run_id = self.storage.create_run(project["id"])
        stages = [StageStatus(name=name, label=label) for name, label in STAGES]
        self._persist_run(run_id, project["id"], stages, {})
        self.storage.update_project_status(project["id"], "discovering")
        self._log(
            run_id,
            project["id"],
            "info",
            f"Discovery started for topic '{project['topic']}'",
        )

        try:
            self._run_stage_search(run_id, project, stages)
            self._run_stage_download(run_id, project, stages)
            self._run_stage_validate(run_id, project, stages)
            self._run_stage_extract(run_id, project, stages)
            self._run_stage_ocr(run_id, project, stages)
            self._run_stage_filter(run_id, project, stages)
            stats = project_stats(self.storage, project["id"])
            self.storage.update_run(
                run_id,
                status="completed",
                stages=[s.model_dump(mode="json") for s in stages],
                stats=stats.model_dump(mode="json"),
            )
            self.storage.update_project_status(project["id"], "completed")
            self._log(run_id, project["id"], "info", "Discovery completed.")
            return self.storage.get_run(run_id)  # type: ignore[return-value]
        except PipelineCancelledError:
            self.storage.update_run(
                run_id,
                status="cancelled",
                finished_at=utcnow(),
                stages=[s.model_dump(mode="json") for s in stages],
                stats=project_stats(self.storage, project["id"]).model_dump(mode="json"),
            )
            self.storage.update_project_status(project["id"], "cancelled")
            self._log(run_id, project["id"], "warning", "Discovery cancelled.")
            return self.storage.get_run(run_id)  # type: ignore[return-value]
        except Exception as exc:
            log.exception("Pipeline failed")
            self.storage.update_run(
                run_id,
                status="failed",
                error=str(exc),
                finished_at=utcnow(),
                stages=[s.model_dump(mode="json") for s in stages],
                stats=project_stats(self.storage, project["id"]).model_dump(mode="json"),
            )
            self.storage.update_project_status(project["id"], "failed")
            self._log(run_id, project["id"], "error", f"Discovery failed: {exc}")
            raise

    # ── stage helpers ─────────────────────────────────────────────────────────

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise PipelineCancelledError()

    def _begin_stage(self, stages: list[StageStatus], name: str) -> None:
        for st in stages:
            if st.name == name:
                st.status = "running"
                st.started_at = utcnow()

    def _finish_stage(self, stages: list[StageStatus], name: str) -> None:
        for st in stages:
            if st.name == name:
                st.status = "completed"
                st.finished_at = utcnow()

    def _persist_run(
        self, run_id: int, project_id: int, stages: list[StageStatus], stats: dict
    ) -> None:
        self.storage.update_run(
            run_id,
            stages=json.dumps([s.model_dump(mode="json") for s in stages]),
            stats=json.dumps(stats),
        )

    def _log(self, run_id: int, project_id: int, level: str, message: str) -> None:
        log.info(message)
        self.storage.add_log(run_id, project_id, level, message)

    # ── stage: search ─────────────────────────────────────────────────────────

    def _run_stage_search(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "search")
        self._persist_run(run_id, project["id"], stages, {})
        provider_id = self.settings.search.provider
        if provider_id == "offline":
            provider = get_provider(
                provider_id, fixture_path=self.settings.search.offline_fixture_path
            )
        else:
            provider = get_provider(
                provider_id, timeout_seconds=self.settings.search.timeout_seconds
            )
        if not provider.available():
            raise RuntimeError(f"Search provider '{provider_id}' is not available.")

        generator = QueryGenerator(self.settings)
        found = 0
        queries = []
        for topic_variant in generator.topics(project["topic"]):
            queries.extend(generator.generate(topic_variant))
        for intent in queries[: self.settings.search.max_queries]:
            self._check_cancelled()
            results = provider.search(intent.query, self.settings.search.max_results_per_query)
            for r in results:
                self.storage.add_source(
                    project["id"],
                    url=r.url,
                    title=r.title,
                    snippet=r.snippet,
                    source_domain=r.source_domain,
                    search_query=intent.query,
                    discovered_at=r.discovered_at,
                )
                found += 1
            self._log(
                run_id,
                project["id"],
                "info",
                f"Query {intent.group}: '{intent.query}' → {len(results)} results",
            )
        self.storage.touch_project(project["id"])
        self._finish_stage(stages, "search")
        self._log(run_id, project["id"], "info", f"Search complete: {found} results discovered")

    # ── stage: download ───────────────────────────────────────────────────────

    def _run_stage_download(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "download")
        sources = self.storage.list_sources(
            project["id"], status="discovered", limit=self.settings.project.max_sources
        )
        downloader = Downloader(self.settings)
        done = 0
        with ThreadPoolExecutor(max_workers=self.settings.download.max_workers) as pool:
            futures = {}
            for src in sources:
                self._check_cancelled()
                src_path = self.storage.raw_path(project["slug"], src["id"])
                futures[pool.submit(downloader.download, src["url"], src_path)] = src
            for future in as_completed(futures):
                self._check_cancelled()
                src = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover
                    result = None
                    self.storage.update_source(
                        src["id"], status="failed", rejection_reason=f"download_exception: {exc}"
                    )
                else:
                    if result.status == "ok":
                        self.storage.update_source(
                            src["id"],
                            status="downloaded",
                            file_path=result.file_path,
                            file_hash=result.file_hash,
                            file_size=result.file_size,
                            content_type=result.content_type,
                            http_status=result.http_status,
                        )
                        self._log(run_id, project["id"], "info", f"Downloaded {src['url']}")
                    else:
                        self.storage.update_source(
                            src["id"],
                            status="failed",
                            rejection_reason=result.error,
                            http_status=result.http_status,
                        )
                        self._log(
                            run_id,
                            project["id"],
                            "warning",
                            f"Download failed for {src['url']}: {result.error}",
                        )
                done += 1
                stats = project_stats(self.storage, project["id"]).model_dump(mode="json")
                self._persist_run(run_id, project["id"], stages, stats)
        self._finish_stage(stages, "download")

    # ── stage: validate ───────────────────────────────────────────────────────

    def _run_stage_validate(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "validate")
        sources = self.storage.list_sources(project["id"], status="downloaded")
        for src in sources:
            self._check_cancelled()
            raw = Path(src["file_path"])
            ok, reason = validate_pdf(raw, self.settings)
            if not ok:
                self._move_rejected(project, src, reason)
                continue
            dup = self.storage.get_source_by_file_hash(project["id"], src["file_hash"] or "")
            if dup and dup["id"] != src["id"]:
                self._move_rejected(project, src, "duplicate_hash", status="duplicate")
                self._log(
                    run_id, project["id"], "info", f"Duplicate of source {dup['id']}: {src['url']}"
                )
                continue
            self.storage.update_source(src["id"], status="candidate")
        self._finish_stage(stages, "validate")

    def _move_rejected(
        self, project: dict, src: dict, reason: str, status: str = "rejected_validation"
    ) -> None:
        self.storage.update_source(src["id"], status=status, rejection_reason=reason)
        if self.settings.download.keep_rejected_files and src.get("file_path"):
            raw = Path(src["file_path"])
            if raw.exists():
                dest = self.storage.rejected_path(project["slug"], src["id"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                raw.rename(dest)
                self.storage.update_source(src["id"], file_path=str(dest))

    # ── stage: extract ────────────────────────────────────────────────────────

    def _run_stage_extract(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "extract")
        sources = self.storage.list_sources(project["id"], status="candidate")
        for src in sources:
            self._check_cancelled()
            raw = Path(src["file_path"])
            self.storage.update_source(src["id"], status="extracting")
            result = extract_pdf(raw, self.settings)
            if result.status == "ocr_required":
                self.storage.update_source(
                    src["id"],
                    status="ocr_required",
                    page_count=result.page_count,
                    text_chars=result.text_chars,
                    language=result.language,
                    metadata_json=self._metadata_json(result),
                    extraction_method="none",
                )
                self._log(
                    run_id,
                    project["id"],
                    "info",
                    f"OCR required for source {src['id']} ({result.text_chars} chars)",
                )
                continue
            if result.status == "failed":
                self._move_rejected(project, src, f"extract_failed: {result.error}")
                continue
            self._finalize_extracted(project, src, result)
        self._finish_stage(stages, "extract")

    def _run_stage_ocr(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "ocr")
        sources = self.storage.list_sources(project["id"], status="ocr_required")
        if not sources:
            self._finish_stage(stages, "ocr")
            return
        provider = get_ocr_provider(self.settings)
        if not self.settings.ocr.enabled or not provider.available():
            self._log(
                run_id,
                project["id"],
                "warning",
                "OCR requested but unavailable; leaving documents as ocr_required",
            )
            self._finish_stage(stages, "ocr")
            return
        for src in sources:
            self._check_cancelled()
            raw = Path(src["file_path"])
            self._log(run_id, project["id"], "info", f"Running OCR on source {src['id']}")
            result = ocr_and_rebuild(raw, self.settings)
            if result.status == "ok":
                self._finalize_extracted(project, src, result)
                self._log(
                    run_id,
                    project["id"],
                    "info",
                    f"OCR complete for source {src['id']} ({result.text_chars} chars)",
                )
            else:
                self.storage.update_source(
                    src["id"], status="ocr_required", rejection_reason=result.error
                )
        self._finish_stage(stages, "ocr")

    def _finalize_extracted(self, project: dict, src: dict, result) -> None:
        processed = self.storage.processed_path(project["slug"], src["id"])
        processed.parent.mkdir(parents=True, exist_ok=True)
        processed.write_text(result.markdown, encoding="utf-8")
        meta_path = self.storage.metadata_path(project["slug"], src["id"])
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(self._metadata_json(result), encoding="utf-8")
        self.storage.update_source(
            src["id"],
            status="extracted",
            page_count=result.page_count,
            text_chars=result.text_chars,
            language=result.language,
            extraction_method=result.method,
            metadata_json=self._metadata_json(result),
            processed_path=str(processed),
        )

    @staticmethod
    def _metadata_json(result) -> str:
        return json.dumps(
            {
                "page_count": result.page_count,
                "text_chars": result.text_chars,
                "language": result.language,
                "extraction_method": result.method,
                "metadata": result.metadata.model_dump(mode="json"),
                "headings": result.headings[:80],
            },
            indent=2,
        )

    # ── stage: filter ─────────────────────────────────────────────────────────

    def _run_stage_filter(self, run_id: int, project: dict, stages: list[StageStatus]) -> None:
        self._begin_stage(stages, "filter")
        sources = self.storage.list_sources(project["id"], status="extracted")

        embed_client = self._embed_client
        if embed_client is None and self.settings.embeddings.enabled:
            embed_client = EmbeddingClient(self.settings)
        classifier = self._llm_classifier or OllamaClassifier(self.settings)
        topic = project["topic"]

        for src in sources:
            self._check_cancelled()
            self.storage.update_source(src["id"], status="filtering")
            text = self._source_text(src)
            title = src["title"] or self._title_from_text(text)
            excerpt = text[: self.settings.llm.max_excerpt_chars]
            metadata_text = self._metadata_text(src)

            similarity = None
            embedding_stage = "skipped"
            if embed_client is not None:
                doc_head = f"{title}\n{text[: self.settings.embeddings.max_chars]}"
                sim = embed_client.similarity(topic, doc_head)
                if sim is not None:
                    similarity = round(sim, 4)
                    embedding_stage = "ok"
                else:
                    embedding_stage = "error"

            ai = classifier.classify(
                topic=topic,
                title=title,
                metadata_text=metadata_text,
                excerpt=excerpt,
            )
            result = build_filter_result(
                similarity, embedding_stage, ai, self.settings.llm.max_attempts, self.settings
            )

            final = result.final_decision
            status = {"ACCEPT": "accepted", "REJECT": "rejected", "REVIEW": "review"}[final]
            self.storage.update_source(
                src["id"],
                status=status,
                similarity=similarity,
                embedding_stage=embedding_stage,
                ai_decision=final,
                ai_confidence=ai.confidence if ai else None,
                ai_document_type=ai.document_type if ai else "",
                ai_topic_match=ai.topic_match if ai else "",
                ai_reason=ai.reason if ai else "",
                ai_raw=json.dumps(ai.model_dump(mode="json")) if ai else "",
                ai_attempts=result.ai_attempts,
                note=result.note,
            )
            self._write_result_file(project, src["id"], status, result, title)
            self._log(
                run_id,
                project["id"],
                "info",
                f"Filter [{final}] (sim={similarity}) source {src['id']} '{title}'",
            )
            stats = project_stats(self.storage, project["id"]).model_dump(mode="json")
            self._persist_run(run_id, project["id"], stages, stats)
        self._finish_stage(stages, "filter")

    def _write_result_file(
        self, project: dict, source_id: int, status: str, result, title: str
    ) -> None:
        dest = self.storage.result_path(project["slug"], source_id, status)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_id": source_id,
            "title": title,
            "decision": result.final_decision,
            "confidence": result.ai_response.confidence if result.ai_response else None,
            "document_type": result.ai_response.document_type if result.ai_response else None,
            "topic_match": result.ai_response.topic_match if result.ai_response else None,
            "reason": result.ai_response.reason if result.ai_response else "",
            "similarity": result.similarity,
            "embedding_stage": result.embedding_stage,
            "note": result.note,
            "timestamp": utcnow(),
        }
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _source_text(src: dict) -> str:
        processed = src.get("processed_path")
        if processed and Path(processed).exists():
            return Path(processed).read_text(encoding="utf-8")
        return src.get("snippet") or ""

    def _title_from_text(self, text: str) -> str:
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:150]
        return "Untitled Document"

    def _metadata_text(self, src: dict) -> str:
        parts = []
        if src.get("page_count"):
            parts.append(f"pages: {src['page_count']}")
        if src.get("language"):
            parts.append(f"language: {src['language']}")
        if src.get("source_domain"):
            parts.append(f"source: {src['source_domain']}")
        try:
            data = json.loads(src.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            data = {}
        meta = data.get("metadata", {})
        for key in ("author", "subject", "keywords", "producer"):
            if meta.get(key):
                parts.append(f"{key}: {meta[key]}")
        return "\n".join(parts)
