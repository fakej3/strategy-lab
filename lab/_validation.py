"""Validation facade — wraps research.integrity and research.validation."""
from __future__ import annotations

import pandas as pd

from shared.errors import IntegrityError, ValidationError


class Validation:
    """High-level interface for data validation and integrity checks.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``research.integrity`` or ``research.validation``
    directly.

    Example
    -------
    >>> v = Validation()
    >>> report = v.audit(bars)
    >>> warnings = v.validate(bars)
    """

    def audit(self, bars: pd.DataFrame):
        """Run the full OHLCV integrity audit.

        Performs hard checks (raises on failure) and soft checks (recorded in
        the report). Use this before any backtest to guarantee data quality.

        Args:
            bars: OHLCV DataFrame with DatetimeIndex.

        Returns:
            DataIntegrityReport with integrity_score in [0, 100].

        Raises:
            IntegrityError: on any hard data quality failure.
        """
        try:
            from research.integrity import audit_bars
            return audit_bars(bars)
        except ValueError as exc:
            raise IntegrityError(str(exc)) from exc
        except Exception as exc:
            raise IntegrityError(f"Integrity audit failed: {exc}") from exc

    def assert_integrity(self, bars: pd.DataFrame, min_score: float = 80.0) -> None:
        """Audit bars and raise if the integrity score is below *min_score*.

        Args:
            bars:      OHLCV DataFrame.
            min_score: Minimum acceptable integrity score (0–100).

        Raises:
            IntegrityError: if the score is below *min_score*.
        """
        try:
            from research.integrity import assert_integrity
            assert_integrity(bars, min_score=min_score)
        except ValueError as exc:
            raise IntegrityError(str(exc)) from exc
        except Exception as exc:
            raise IntegrityError(f"Integrity assertion failed: {exc}") from exc

    def validate(self, bars: pd.DataFrame) -> list:
        """Run the extended bar validation and return a list of ValidationWarning.

        This is a lighter-weight check than audit() — it does not raise on
        soft issues but returns them as a list for the caller to inspect.

        Args:
            bars: OHLCV DataFrame.

        Returns:
            List of ValidationWarning (may be empty).

        Raises:
            ValidationError: if a fundamental structural problem is found.
        """
        try:
            from research.validation import validate_bars_extended
            return validate_bars_extended(bars)
        except Exception as exc:
            raise ValidationError(f"Validation failed: {exc}") from exc
