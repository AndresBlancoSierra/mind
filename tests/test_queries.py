"""Tests for search query generation."""

from __future__ import annotations

from mind.queries import QueryGenerator


def test_generates_base_intents(settings):
    gen = QueryGenerator(settings)
    intents = gen.generate("Cybersecurity")
    queries = [i.query for i in intents]
    assert "Cybersecurity curriculum" in queries
    assert "Cybersecurity degree curriculum" in queries
    assert "Cybersecurity syllabus" in queries
    assert "Cybersecurity course syllabus" in queries
    assert "Cybersecurity university courses" in queries


def test_generates_site_and_filetype(settings):
    gen = QueryGenerator(settings)
    intents = gen.generate("Cybersecurity")
    groups = {i.group for i in intents}
    assert "site" in groups and "filetype" in groups
    assert any("site:.edu" in i.query for i in intents)
    assert any("filetype:pdf" in i.query for i in intents)


def test_generates_colombia_queries(settings):
    gen = QueryGenerator(settings)
    intents = gen.generate("Cybersecurity")
    co = [i for i in intents if i.country == "CO"]
    assert co, "expected Colombia-specific queries"
    assert any("Colombia" in i.query for i in co)
    assert any("site:.edu.co" in i.query for i in co)


def test_colombia_disabled(settings):
    settings.search.include_colombia = False
    gen = QueryGenerator(settings)
    intents = gen.generate("Cybersecurity")
    assert not [i for i in intents if i.country == "CO"]


def test_empty_topic(settings):
    gen = QueryGenerator(settings)
    assert gen.generate("   ") == []


def test_synonyms(settings):
    gen = QueryGenerator(settings)
    assert gen.topics("Cybersecurity") == [
        "Cybersecurity",
        "cyber security",
        "information security",
    ]
    assert gen.topics("Machine Learning") == ["Machine Learning", "ml"]


def test_no_duplicate_queries(settings):
    gen = QueryGenerator(settings)
    queries = [i.query for i in gen.generate("Cybersecurity")]
    assert len(queries) == len(set(queries))
