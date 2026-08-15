"""Tests for the search layer (provider abstraction + offline provider)."""

from __future__ import annotations

import pytest

from mind.search import available_providers, get_provider
from mind.search.offline import OfflineProvider


def test_providers_registered():
    assert "ddg" in available_providers()
    assert "offline" in available_providers()


def test_unknown_provider():
    with pytest.raises(ValueError, match="Unknown search provider"):
        get_provider("does-not-exist")


def test_offline_provider_normalizes(settings):
    provider = OfflineProvider(settings.search.offline_fixture_path)
    assert provider.available()
    results = provider.search("Cybersecurity curriculum", 5)
    assert results
    first = results[0]
    assert first.title
    assert first.url.startswith("http")
    assert first.source_domain
    assert first.search_query == "Cybersecurity curriculum"
    assert first.discovered_at


def test_offline_dedups_by_url_hash(settings):
    provider = OfflineProvider(settings.search.offline_fixture_path)
    storage = __import__("mind.storage", fromlist=["Storage"]).Storage(settings.paths.data_dir)
    project = storage.create_project("Cybersecurity")
    ids = set()
    for _ in range(2):
        for r in provider.search("Cybersecurity curriculum", 5):
            ids.add(
                storage.add_source(
                    project["id"],
                    url=r.url,
                    title=r.title,
                    snippet=r.snippet,
                    source_domain=r.source_domain,
                    search_query=r.search_query,
                )
            )
    assert len(ids) == len(provider.search("Cybersecurity curriculum", 5))


def test_offline_best_key_match():
    provider = OfflineProvider("missing.json")
    keys = ["cybersecurity curriculum", "cafeteria"]
    key = provider._best_key("cybersecurity degree curriculum", keys)
    assert key == "cybersecurity curriculum"
