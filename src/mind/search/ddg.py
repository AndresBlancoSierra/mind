"""DuckDuckGo search provider.

Uses the ``ddgs`` package (successor of ``duckduckgo-search``). No API key or
paid service is required.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from mind.schemas import SearchResult
from mind.search.base import SearchProvider, register_provider

log = logging.getLogger("mind.search.ddg")


@register_provider
class DuckDuckGoProvider(SearchProvider):
    id = "ddg"

    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds

    def _client(self):
        from ddgs import DDGS

        return DDGS(timeout=self.timeout_seconds)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            raw = list(self._client().text(query, max_results=max_results, safesearch="off"))
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("DuckDuckGo search failed for %r: %s", query, exc)
            return []
        return [self._normalize(r, query) for r in raw]

    def _normalize(self, raw: dict, query: str) -> SearchResult:
        url = raw.get("href") or raw.get("url") or ""
        return SearchResult(
            title=(raw.get("title") or "").strip(),
            url=url,
            snippet=(raw.get("body") or "").strip(),
            source_domain=self._domain(url),
            search_query=query,
        )

    @staticmethod
    def _domain(url: str) -> str:
        try:
            host = urlparse(url).netloc
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""

    def available(self) -> bool:
        try:
            import ddgs  # noqa: F401

            return True
        except ImportError:
            return False
