"""Structured, privacy-conscious logging.

Rules:
- Never log document contents or user health data.
- Log IDs and metadata only.
"""
import logging
import sys
from typing import Any

from app.core.config import get_settings

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Quiet noisy libs
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


class LoggerAdapter(logging.LoggerAdapter):
    """Adapter that prefixes structured key=value metadata (ids only, never content)."""

    def process(self, msg: Any, kwargs: dict) -> tuple[str, dict]:
        extra = self.extra or {}
        kv = " ".join(f"{k}={v}" for k, v in extra.items())
        return f"{kv} | {msg}" if kv else str(msg), kwargs
