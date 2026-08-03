"""Shared utilities for the Strategy Research Lab and Trading Bot.

Everything in this package is importable by both the Research Lab internals
and the Trading Bot (via lab/). No package outside of shared/ should be
imported from here to keep this layer dependency-free.
"""
from .errors import (
    AutomationError,
    ConfigurationError,
    DataError,
    IntegrityError,
    LabError,
    ResearchError,
    ValidationError,
)
from .logging import get_logger, setup_logging

__all__ = [
    # errors
    "LabError",
    "DataError",
    "IntegrityError",
    "ResearchError",
    "ValidationError",
    "AutomationError",
    "ConfigurationError",
    # logging
    "get_logger",
    "setup_logging",
]
