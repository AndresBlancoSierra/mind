"""MIND configuration.

Settings are loaded from YAML files. Precedence (lowest to highest):

1. Defaults defined in this module (``Settings.model_config``).
2. The project ``config/settings.yaml`` file.
3. ``MIND_CONFIG`` environment variable pointing to a YAML file.
4. Environment variables prefixed with ``MIND_`` (e.g. ``MIND_LLM__MODEL``).

The resolved settings are available through :func:`load_settings`.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "settings.yaml"


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    """Root directory for all MIND data (SQLite database + project files)."""


class SearchConfig(BaseModel):
    provider: str = "ddg"
    """Search provider id. Built-in: ``ddg`` (DuckDuckGo), ``offline`` (fixtures)."""

    max_results_per_query: int = 10
    max_queries: int = 20
    timeout_seconds: float = 20.0
    include_colombia: bool = True
    offline_fixture_path: str = "tests/fixtures/search_results.json"


class QueryTemplatesConfig(BaseModel):
    base: list[str] = Field(
        default_factory=lambda: [
            "{topic} curriculum",
            "{topic} degree curriculum",
            "{topic} degree program",
            "{topic} syllabus",
            "{topic} course syllabus",
            "{topic} university courses",
            "{topic} course catalog",
            "{topic} program requirements",
            "{topic} course descriptions",
            "{topic} master program",
        ]
    )
    site: list[str] = Field(
        default_factory=lambda: [
            "site:.edu {topic} curriculum",
            "site:.edu {topic} syllabus",
        ]
    )
    filetype: list[str] = Field(
        default_factory=lambda: [
            "filetype:pdf {topic} curriculum",
            "filetype:pdf {topic} syllabus",
        ]
    )
    colombia: list[str] = Field(
        default_factory=lambda: [
            "{topic} plan de estudios universidad Colombia",
            "{topic} pensum universidad Colombia",
            "{topic} currículo universidad Colombia",
            "pregrado {topic} Colombia",
            "maestría {topic} Colombia",
            "site:.edu.co {topic}",
            "{topic} programa académico universidad Colombia",
        ]
    )


class DownloadConfig(BaseModel):
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_size_mb: float = 50.0
    accept_content_types: list[str] = Field(default_factory=lambda: ["application/pdf"])
    max_workers: int = 4
    user_agent: str = (
        "MIND/0.1 (automated learning research; local-first) https://github.com/anomalyco/opencode"
    )
    keep_rejected_files: bool = True
    """Keep the original file of documents rejected during validation."""


class PdfConfig(BaseModel):
    min_text_chars: int = 50
    """Below this many extracted characters a PDF is treated as needing OCR."""

    max_pages: int = 200
    """Maximum number of pages accepted for processing."""


class OcrConfig(BaseModel):
    enabled: bool = True
    engine: str = "tesseract"
    lang: str = "eng"
    dpi: int = 200
    """Rendering resolution used for rasterizing pages before OCR."""


class EmbeddingsConfig(BaseModel):
    enabled: bool = True
    runtime: str = "ollama"
    model: str = "nomic-embed-text"
    base_url: str = "http://localhost:11434"
    accept_above: float = 0.70
    reject_below: float = 0.30
    max_chars: int = 1000
    """Character budget of document text sent to the embedding model."""
    timeout_seconds: float = 60.0


class LLMConfig(BaseModel):
    runtime: str = "ollama"
    model: str = "llama3.2:3b"
    base_url: str = "http://localhost:11434"
    format: str = "json"
    temperature: float = 0.0
    max_excerpt_chars: int = 3000
    """Character budget of document text sent to the LLM classifier."""
    max_attempts: int = 2
    """Number of LLM attempts before falling back to REVIEW."""
    think: bool = False
    """Disable chain-of-thought output. Required for qwen3 to emit clean JSON."""
    timeout_seconds: float = 180.0
    decision_confidence_threshold: float = 0.6
    """Below this confidence, a strong embedding hint overrides the LLM vote."""


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001
    """The WHO? sibling project uses port 8000; MIND uses 8001 to avoid clashes."""


class CliConfig(BaseModel):
    max_discover_sources: int = 40
    """Cap on the number of source documents processed by one discovery run."""


class ProjectConfig(BaseModel):
    """Defaults applied when a new project is created from a topic."""

    max_sources: int = 60
    """Cap on candidate source documents kept for a project."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIND_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    paths: PathsConfig = PathsConfig()
    search: SearchConfig = SearchConfig()
    queries: QueryTemplatesConfig = QueryTemplatesConfig()
    download: DownloadConfig = DownloadConfig()
    pdf: PdfConfig = PdfConfig()
    ocr: OcrConfig = OcrConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    llm: LLMConfig = LLMConfig()
    api: ApiConfig = ApiConfig()
    cli: CliConfig = CliConfig()
    project: ProjectConfig = ProjectConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        yaml_path = cls.model_config.get("yaml_file") or os.environ.get(
            "MIND_CONFIG", str(DEFAULT_CONFIG_PATH)
        )
        sources = [init_settings, env_settings, dotenv_settings]
        if Path(yaml_path).exists():
            sources.append(YamlConfigSettingsSource(settings_cls))
        sources.append(file_secret_settings)
        return tuple(sources)


_settings_cache: Settings | None = None


def load_settings() -> Settings:
    """Return the cached application settings."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings()
    return _settings_cache
