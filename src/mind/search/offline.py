"""Offline search provider backed by static fixtures.

Used by tests and for offline/deterministic demonstration runs. A fixture is a
JSON file mapping a query fragment to a list of results:

.. code-block:: json

    {
      "cybersecurity curriculum": [
        {"title": "...", "url": "...", "snippet": "..."}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mind.schemas import SearchResult
from mind.search.base import SearchProvider, register_provider


@register_provider
class OfflineProvider(SearchProvider):
    id = "offline"

    def __init__(self, fixture_path: str | Path = "tests/fixtures/search_results.json"):
        self.fixture_path = Path(fixture_path)

    def _load(self) -> dict[str, Any]:
        with open(self.fixture_path, encoding="utf-8") as fh:
            return json.load(fh)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not self.available():
            return []
        data = self._load()
        # Match the most specific fixture key that is a substring of the query.
        key = self._best_key(query, list(data))
        if not key:
            return []
        results: list[SearchResult] = []
        for item in data[key][:max_results]:
            url = item.get("url") or ""
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("snippet", ""),
                    source_domain=self._domain(url),
                    search_query=query,
                )
            )
        return results

    @staticmethod
    def _best_key(query: str, keys: list[str]) -> str | None:
        query_words = set(query.lower().split())
        matches = [k for k in keys if set(k.lower().split()).issubset(query_words)]
        if not matches:
            return None
        return max(matches, key=len)

    @staticmethod
    def _domain(url: str) -> str:
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host

    def available(self) -> bool:
        return self.fixture_path.exists()
