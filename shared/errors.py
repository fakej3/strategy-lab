"""Centralised exception hierarchy for the Strategy Research Lab.

All public exceptions raised by any Lab subsystem descend from LabError so
callers (including the Trading Bot) can catch them with a single clause.

Hierarchy
---------
LabError
├── DataError          — market data fetch / store failures
├── IntegrityError     — OHLCV data quality failures (audit_bars)
├── ResearchError      — backtesting / analysis failures
├── ValidationError    — parameter or input validation failures
├── AutomationError    — pipeline orchestration failures
└── ConfigurationError — bad or missing configuration values
"""
from __future__ import annotations


class LabError(Exception):
    """Base exception for all Strategy Research Lab errors."""


class DataError(LabError):
    """Raised when market data cannot be fetched, cached, or stored."""


class IntegrityError(LabError):
    """Raised when OHLCV data fails the integrity audit."""


class ResearchError(LabError):
    """Raised when a backtest, optimisation, or analysis step fails."""


class ValidationError(LabError):
    """Raised when an input value or parameter set is invalid."""


class AutomationError(LabError):
    """Raised when the automated research pipeline encounters a fatal error."""


class ConfigurationError(LabError):
    """Raised when required configuration is missing or malformed."""
