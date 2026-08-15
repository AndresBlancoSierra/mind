"""End-to-end pipeline test using a controlled local dataset.

Uses the offline search provider (fixture with localhost URLs), a local HTTP
server serving the fixture PDFs, a fake LLM classifier and no embeddings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mind.filter.llm import FakeClassifier
from mind.ocr import TesseractOCRProvider
from mind.pipeline import DiscoveryPipeline
from mind.schemas import AiResponse
from mind.storage import Storage, project_stats


def _build_search_fixture(tmp_path, server: str):
    fixture = {
        "cybersecurity curriculum": [
            {
                "title": "Master of Cybersecurity Curriculum",
                "url": f"{server}/text_pdf.pdf",
                "snippet": "Official curriculum of the Master of Cybersecurity program.",
            },
            {
                "title": "Curriculum Mirror (duplicate)",
                "url": f"{server}/redirect.pdf",
                "snippet": "Same content served via a redirect.",
            },
            {
                "title": "University Cafeteria Regulations",
                "url": f"{server}/cafeteria.pdf",
                "snippet": (
                    "Noise result: food service hours, meal plans and cafeteria regulations."
                ),
            },
            {
                "title": "Scanned Document (OCR needed)",
                "url": f"{server}/scanned_pdf.pdf",
                "snippet": "A scanned image document.",
            },
            {
                "title": "Broken Document",
                "url": f"{server}/corrupted.pdf",
                "snippet": "Corrupted pdf.",
            },
        ],
        "cybersecurity syllabus": [
            {
                "title": "Network Security Course Syllabus",
                "url": f"{server}/network_security.pdf",
                "snippet": "Syllabus covering firewalls, IDS/IPS, VPNs and labs.",
            },
        ],
    }
    path = tmp_path / "search.json"
    path.write_text(json.dumps(fixture))
    return str(path)


def _fake_classifier() -> FakeClassifier:
    return FakeClassifier(
        {
            "curriculum": AiResponse(
                decision="ACCEPT",
                confidence=0.96,
                document_type="curriculum",
                topic_match="high",
                reason="master curriculum",
            ),
            "syllabus": AiResponse(
                decision="ACCEPT",
                confidence=0.93,
                document_type="syllabus",
                topic_match="high",
                reason="network security syllabus",
            ),
            "cafeteria": AiResponse(
                decision="REJECT",
                confidence=0.99,
                document_type="unrelated",
                topic_match="none",
                reason="unrelated to cybersecurity",
            ),
            "scanned": AiResponse(
                decision="REVIEW",
                confidence=0.4,
                document_type="unknown",
                topic_match="low",
                reason="insufficient text",
            ),
        }
    )


def test_pipeline_end_to_end(settings, http_server, tmp_path):
    settings.search.offline_fixture_path = _build_search_fixture(tmp_path, http_server)
    settings.project.max_sources = 50
    settings.ocr.enabled = False
    settings.embeddings.enabled = False

    storage = Storage(settings.paths.data_dir)
    project = storage.create_project("Cybersecurity")

    classifier = _fake_classifier()
    pipeline = DiscoveryPipeline(settings, llm_classifier=classifier)
    run = pipeline.run(project["slug"])

    assert run["status"] == "completed"

    # All stage states persisted as completed on the final run record
    stage_states = {st["name"]: st["status"] for st in json.loads(run["stages"])}
    assert set(stage_states) == {"search", "download", "validate", "extract", "ocr", "filter"}
    assert set(stage_states.values()) == {"completed"}

    accepted = storage.list_sources(project["id"], decision="ACCEPT")
    rejected = storage.list_sources(project["id"], decision="REJECT")
    duplicates = storage.list_sources(project["id"], status="duplicate")
    ocr_required = storage.list_sources(project["id"], status="ocr_required")
    rejected_validation = storage.list_sources(project["id"], status="rejected_validation")

    # Curriculum + network security accepted
    titles = [s["title"] for s in accepted]
    assert "Master of Cybersecurity Curriculum" in titles
    assert "Network Security Course Syllabus" in titles
    assert len(accepted) == 2

    # Cafeteria rejected
    assert [s["title"] for s in rejected] == ["University Cafeteria Regulations"]

    # Redirect copy detected as duplicate by file hash
    assert len(duplicates) == 1
    assert duplicates[0]["rejection_reason"] == "duplicate_hash"

    # Scanned stays ocr_required (OCR disabled in this test)
    assert len(ocr_required) == 1

    # Corrupted pdf rejected during validation
    assert len(rejected_validation) == 1
    assert rejected_validation[0]["rejection_reason"] == "corrupt_pdf"

    # Artifacts written
    project_dir = storage.project_dir(project["slug"])
    raw_files = list((project_dir / "sources" / "raw").glob("*.pdf"))
    processed = list((project_dir / "sources" / "processed").glob("*.md"))
    metadata = list((project_dir / "sources" / "metadata").glob("*.json"))
    results = list((project_dir / "results" / "accepted").glob("*.json"))
    rejected_files = list((project_dir / "sources" / "rejected").glob("*.pdf"))
    assert len(raw_files) == 4  # curriculum + cafeteria + scanned + network security
    assert len(processed) == 3  # all valid docs normalized (rejected too, for traceability)
    assert len(metadata) == 3
    assert len(results) == 2
    assert len(rejected_files) == 2  # duplicate + corrupt kept for traceability

    # Accepted result file has decision metadata
    payload = json.loads(results[0].read_text())
    assert payload["decision"] == "ACCEPT"

    stats = project_stats(storage, project["id"])
    assert stats.search_results >= 6
    assert stats.duplicates_removed == 1
    assert stats.accepted == 2
    assert stats.rejected == 1

    # classifier was actually invoked
    assert len(classifier.calls) == 3  # two accepted + one rejected


@pytest.mark.ocr
def test_pipeline_with_ocr_enabled(settings, http_server, tmp_path):
    if not TesseractOCRProvider().available():
        pytest.skip("tesseract not installed")

    fixture = {
        "cybersecurity curriculum": [
            {
                "title": "Scanned Syllabus",
                "url": f"{http_server}/scanned_pdf.pdf",
                "snippet": "A scanned image document needing OCR.",
            },
        ],
    }
    path = tmp_path / "search.json"
    path.write_text(json.dumps(fixture))
    settings.search.offline_fixture_path = str(path)
    settings.project.max_sources = 10
    settings.ocr.enabled = True
    settings.ocr.engine = "tesseract"
    settings.embeddings.enabled = False

    storage = Storage(settings.paths.data_dir)
    project = storage.create_project("Cybersecurity")

    classifier = _fake_classifier()
    pipeline = DiscoveryPipeline(settings, llm_classifier=classifier)
    run = pipeline.run(project["slug"])

    assert run["status"] == "completed"

    sources = storage.list_sources(project["id"])
    assert len(sources) == 1
    src = sources[0]

    # OCR recovered real text and the document flowed through filtering (ACCEPT)
    assert src["status"] == "accepted"
    assert src["ai_decision"] == "ACCEPT"
    assert src["extraction_method"] == "ocr"
    assert src["text_chars"] > 0
    assert src["page_count"] == 1

    processed = Path(src["processed_path"])
    assert processed.exists()
    assert "SYLLABUS" in processed.read_text(encoding="utf-8")
