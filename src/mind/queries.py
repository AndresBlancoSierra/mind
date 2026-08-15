"""Search query generation for a mastery topic.

Given a topic such as ``Cybersecurity`` this module produces multiple search
intents covering academic institutions (international), Colombian
institutions, professional frameworks and different media types.
"""

from __future__ import annotations

from mind.config import Settings
from mind.schemas import QueryIntent


class QueryGenerator:
    """Generates search intents from a topic using configurable templates."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_default()

    def generate(self, topic: str) -> list[QueryIntent]:
        topic = topic.strip()
        if not topic:
            return []

        templates = self.settings.queries
        intents: list[QueryIntent] = []

        for tpl in templates.base:
            intents.append(QueryIntent(query=tpl.format(topic=topic), group="base"))
        for tpl in templates.site:
            intents.append(QueryIntent(query=tpl.format(topic=topic), group="site"))
        for tpl in templates.filetype:
            intents.append(QueryIntent(query=tpl.format(topic=topic), group="filetype"))
        if self.settings.search.include_colombia:
            for tpl in templates.colombia:
                intents.append(
                    QueryIntent(query=tpl.format(topic=topic), group="colombia", country="CO")
                )

        return intents

    def topics(self, topic: str) -> list[str]:
        """Return the topic plus useful synonyms/aliases for search."""
        aliases: dict[str, list[str]] = {
            "cybersecurity": ["cyber security", "information security"],
            "information security": ["cybersecurity", "cyber security"],
            "cyber security": ["cybersecurity", "information security"],
            "artificial intelligence": ["ai", "machine intelligence"],
            "machine learning": ["ml"],
        }
        base = topic.strip()
        out = [base]
        for alias in aliases.get(base.lower(), []):
            if alias.lower() != base.lower() and alias not in out:
                out.append(alias)
        return out


def load_default() -> Settings:
    from mind.config import load_settings

    return load_settings()
