"""Search provider abstraction for MIND discovery.

Providers are registered by id. A provider can be selected through
configuration (``search.provider``) so the application is never coupled to a
single search engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mind.schemas import SearchResult


class SearchProvider(ABC):
    """Interface every search provider must implement."""

    id: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Execute a single query and return normalized results."""
        raise NotImplementedError

    @abstractmethod
    def available(self) -> bool:
        """Return whether the provider can currently be used."""
        raise NotImplementedError


_providers: dict[str, type[SearchProvider]] = {}


def register_provider(cls: type[SearchProvider]) -> type[SearchProvider]:
    _providers[cls.id] = cls
    return cls


def get_provider(provider_id: str, *args, **kwargs) -> SearchProvider:
    if provider_id not in _providers:
        raise ValueError(
            f"Unknown search provider '{provider_id}'. Available providers: {sorted(_providers)}"
        )
    return _providers[provider_id](*args, **kwargs)


def available_providers() -> list[str]:
    return sorted(_providers)
