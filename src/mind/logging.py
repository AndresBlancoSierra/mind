"""Logging setup for MIND (uses loguru)."""

from __future__ import annotations

import sys

from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )


def get_logger(name: str):
    return logger.bind(module=name)
