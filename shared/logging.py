"""Centralised logging for the Strategy Research Lab.

Usage
-----
    from shared.logging import get_logger, setup_logging

    setup_logging(level="INFO", log_file="logs/research.log")
    log = get_logger(__name__)
    log.info("pipeline started")

All Lab packages should obtain loggers through get_logger() rather than
calling logging.getLogger() directly, so that the root lab logger
(``strategy_lab``) controls formatting and handlers for the entire system.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

_ROOT_LOGGER = "strategy_lab"


def get_logger(name: str) -> logging.Logger:
    """Return a child of the root lab logger.

    Args:
        name: typically ``__name__`` of the calling module.

    Returns:
        A Logger whose records propagate to the root lab handler.
    """
    if name.startswith(_ROOT_LOGGER):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}")


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = False,
) -> None:
    """Configure the root lab logger.

    Should be called once at application startup (research.py, serve.py, etc.).
    Subsequent calls update the configuration in place — safe to call again.

    Args:
        level:       Standard Python log level string (DEBUG, INFO, WARNING, …).
        log_file:    Optional path to write logs to; directory is created if absent.
        json_format: Emit structured JSON instead of the human-readable format.
    """
    root = logging.getLogger(_ROOT_LOGGER)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        _add_handler(root, sys.stderr, json_format)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        _configure_handler(file_handler, json_format)
        root.addHandler(file_handler)


# ── Internal helpers ───────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_HUMAN_FMT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_DATE_FMT  = "%Y-%m-%dT%H:%M:%S"


def _configure_handler(handler: logging.Handler, json_format: bool) -> None:
    if json_format:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_HUMAN_FMT, datefmt=_DATE_FMT))


def _add_handler(
    logger: logging.Logger,
    stream: object,
    json_format: bool,
) -> None:
    handler = logging.StreamHandler(stream)  # type: ignore[arg-type]
    _configure_handler(handler, json_format)
    logger.addHandler(handler)
