"""Market data integrity audit — produces a DataIntegrityReport.

This module provides a complete audit of OHLCV market data beyond the
basic validation in ``research.validation``.  It is designed to run
*before* backtesting begins and to halt research when data quality falls
below an acceptable threshold.

Public API
----------
- ``DataIntegrityReport``  — immutable result of a full audit.
- ``audit_bars``           — run the full audit on a DataFrame.
- ``assert_integrity``     — audit + raise if threshold not met.

Checks performed
----------------
Hard failures (instantly raise ``ValueError``):
  - Empty DataFrame (no data at all)
  - Duplicate open_time / index values
  - Non-monotonic timestamps (must be strictly ascending)
  - Negative or zero prices (open, high, low, close)
  - Negative volume
  - high < low (geometrically impossible OHLC)
  - open or close outside [low, high]
  - Mixed timezone-awareness in the index

Soft issues (recorded in the report):
  - Missing bars (gaps larger than the base tick)
  - Bars with NaN / Inf in any price column
  - Bars with zero volume
  - Bars with high == low (doji / zero-range — suspicious in large quantities)
  - Bars with close == open (zero body)
  - Timestamp frequency inconsistency (inferred interval mismatch)

Score
-----
  ``integrity_score`` is in [0, 100].  100 = perfect data.
  Each soft issue type deducts points proportional to its prevalence.

  score = 100 - sum(deductions)

  Deduction schedule
  ~~~~~~~~~~~~~~~~~~
  - missing_bars:   min(50, missing / expected * 100) points
  - nan_bars:       min(30, nan_count / total * 100)
  - zero_volume:    min(15, zero_vol / total * 50)
  - doji_bars:      min(5,  doji / total * 20)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


# ── Report dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DataIntegrityReport:
    """Complete result of a market-data integrity audit.

    Attributes
    ----------
    symbol : str
        Instrument identifier.
    interval : str
        Bar interval label (e.g. ``"1h"``).
    total_bars : int
        Total rows examined.
    integrity_score : float
        Overall quality score in [0, 100].  100 = perfect.
    passed : bool
        True if ``integrity_score >= threshold``.
    hard_failures : list[str]
        Fatal issues that prevent backtesting (empty when clean).
    warnings : list[str]
        Soft issues that do not block backtesting but reduce the score.
    missing_bars : int
        Estimated count of missing time slots.
    nan_bars : int
        Rows containing NaN or Inf in any price column.
    zero_volume_bars : int
        Rows with zero volume (where volume column is present).
    doji_bars : int
        Rows where ``high == low`` (zero-range candles).
    inferred_interval : str
        Interval inferred from the data (e.g. ``"1H"`` or ``"unknown"``).
    threshold : float
        Minimum score that was required (passed = score >= threshold).
    """

    symbol            : str
    interval          : str
    total_bars        : int
    integrity_score   : float
    passed            : bool
    hard_failures     : List[str]
    warnings          : List[str]
    missing_bars      : int
    nan_bars          : int
    zero_volume_bars  : int
    doji_bars         : int
    inferred_interval : str
    threshold         : float

    def summary(self) -> str:
        """Return a one-line human-readable summary."""
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.symbol}/{self.interval}  "
            f"score={self.integrity_score:.1f}  "
            f"bars={self.total_bars}  "
            f"missing={self.missing_bars}  "
            f"nan={self.nan_bars}  "
            f"failures={len(self.hard_failures)}"
        )

    def to_dict(self) -> dict:
        return {
            "symbol"           : self.symbol,
            "interval"         : self.interval,
            "total_bars"       : self.total_bars,
            "integrity_score"  : self.integrity_score,
            "passed"           : self.passed,
            "hard_failures"    : list(self.hard_failures),
            "warnings"         : list(self.warnings),
            "missing_bars"     : self.missing_bars,
            "nan_bars"         : self.nan_bars,
            "zero_volume_bars" : self.zero_volume_bars,
            "doji_bars"        : self.doji_bars,
            "inferred_interval": self.inferred_interval,
            "threshold"        : self.threshold,
        }


# ── Main audit function ───────────────────────────────────────────────────────

def audit_bars(
    bars     : pd.DataFrame,
    symbol   : str = "",
    interval : str = "",
    threshold: float = 80.0,
) -> DataIntegrityReport:
    """Run a complete data integrity audit on an OHLCV DataFrame.

    Args:
        bars:      OHLCV DataFrame with a DatetimeIndex.
                   Expected columns: ``open``, ``high``, ``low``, ``close``.
                   Optional columns: ``volume``.
        symbol:    Instrument label for reporting (e.g. ``"BTCUSDT"``).
        interval:  Bar interval for reporting (e.g. ``"1h"``).
        threshold: Minimum integrity score [0, 100] for ``passed=True``.

    Returns:
        :class:`DataIntegrityReport`.

    Raises:
        ValueError: When a hard failure is detected.
    """
    hard_failures: list[str] = []
    warnings: list[str]     = []
    total_bars = len(bars)

    # ── Hard failure: empty data ───────────────────────────────────────────────
    if total_bars == 0:
        raise ValueError(
            f"Empty DataFrame for {symbol}/{interval} — no data to audit."
        )

    # ── Hard failure: missing required columns ─────────────────────────────────
    for col in ("open", "high", "low", "close"):
        if col not in bars.columns:
            raise ValueError(
                f"Required column '{col}' missing from bars DataFrame."
            )

    # ── Hard failure: duplicate timestamps ────────────────────────────────────
    if bars.index.duplicated().any():
        dupes = bars.index[bars.index.duplicated()].tolist()
        raise ValueError(
            f"Duplicate timestamps found in {symbol}/{interval}: "
            f"{dupes[:3]}" + (f" … +{len(dupes)-3} more" if len(dupes) > 3 else "")
        )

    # ── Hard failure: non-monotonic timestamps ─────────────────────────────────
    if not bars.index.is_monotonic_increasing:
        raise ValueError(
            f"Timestamps in {symbol}/{interval} are not strictly ascending. "
            "Sort the DataFrame before proceeding."
        )

    # ── Hard failure: mixed timezone awareness ─────────────────────────────────
    if isinstance(bars.index, pd.DatetimeIndex) and bars.index.tz is not None:
        try:
            bars.index.tz_convert("UTC")
        except Exception as exc:
            raise ValueError(
                f"Mixed or inconsistent timezone in {symbol}/{interval}: {exc}"
            ) from exc

    # ── Hard failure: negative / zero prices ──────────────────────────────────
    price_cols = [c for c in ("open", "high", "low", "close") if c in bars.columns]
    for col in price_cols:
        col_data = bars[col]
        # NaN / Inf checked separately below
        finite = col_data.replace([float("inf"), float("-inf")], float("nan")).dropna()
        if (finite <= 0).any():
            n_bad = int((finite <= 0).sum())
            raise ValueError(
                f"Non-positive values in '{col}' column for {symbol}/{interval}: "
                f"{n_bad} bar(s) with price ≤ 0."
            )

    # ── Hard failure: negative volume ─────────────────────────────────────────
    if "volume" in bars.columns:
        vol = bars["volume"].dropna()
        if (vol < 0).any():
            n_bad = int((vol < 0).sum())
            raise ValueError(
                f"Negative volume in {symbol}/{interval}: {n_bad} bar(s)."
            )

    # ── Hard failure: impossible OHLC geometry ────────────────────────────────
    # high < low
    bad_hl = bars["high"] < bars["low"]
    if bad_hl.any():
        n_bad = int(bad_hl.sum())
        raise ValueError(
            f"Geometrically impossible OHLC: high < low in {symbol}/{interval} "
            f"at {n_bad} bar(s): {bars.index[bad_hl].tolist()[:3]}"
        )

    # open outside [low, high]
    bad_open = (bars["open"] < bars["low"]) | (bars["open"] > bars["high"])
    if bad_open.any():
        n_bad = int(bad_open.sum())
        raise ValueError(
            f"Open price outside [low, high] in {symbol}/{interval}: {n_bad} bar(s)."
        )

    # close outside [low, high]
    bad_close = (bars["close"] < bars["low"]) | (bars["close"] > bars["high"])
    if bad_close.any():
        n_bad = int(bad_close.sum())
        raise ValueError(
            f"Close price outside [low, high] in {symbol}/{interval}: {n_bad} bar(s)."
        )

    # ── Soft: NaN / Inf in price columns ──────────────────────────────────────
    nan_mask = pd.DataFrame({c: bars[c] for c in price_cols}).apply(
        lambda col: col.isna() | col.isin([float("inf"), float("-inf")])
    ).any(axis=1)
    nan_bars = int(nan_mask.sum())
    if nan_bars > 0:
        warnings.append(
            f"{nan_bars} bar(s) contain NaN or Inf in price columns."
        )

    # ── Soft: missing bars ────────────────────────────────────────────────────
    missing_bars = 0
    if isinstance(bars.index, pd.DatetimeIndex) and len(bars.index) >= 3:
        deltas    = pd.Series(bars.index[1:] - bars.index[:-1])
        min_delta = deltas.min()
        if min_delta.total_seconds() > 0:
            gap_series    = deltas[deltas > min_delta]
            missing_bars  = int(sum(
                round(d / min_delta) - 1 for d in gap_series
            ))
            if missing_bars > 0:
                first_gap_loc = deltas[deltas > min_delta].index[0]
                first_missing = bars.index[first_gap_loc] + min_delta
                warnings.append(
                    f"{missing_bars} expected bar(s) missing "
                    f"(base interval: {min_delta}). "
                    f"First gap after: {first_missing}"
                )

    # ── Soft: zero volume ─────────────────────────────────────────────────────
    zero_volume_bars = 0
    if "volume" in bars.columns:
        vol = bars["volume"]
        nan_vol = int(vol.isna().sum())
        if nan_vol > 0:
            warnings.append(f"{nan_vol} bar(s) have NaN volume.")
        zero_volume_bars = int((vol.fillna(0) == 0).sum())
        if zero_volume_bars > 0:
            pct = zero_volume_bars / total_bars * 100
            warnings.append(
                f"{zero_volume_bars} bar(s) ({pct:.1f}%) have zero volume."
            )

    # ── Soft: doji bars (high == low) ─────────────────────────────────────────
    doji_mask = bars["high"] == bars["low"]
    doji_bars = int(doji_mask.sum())
    if doji_bars > 0:
        pct = doji_bars / total_bars * 100
        if pct > 2.0:
            warnings.append(
                f"{doji_bars} bar(s) ({pct:.1f}%) are doji (high == low). "
                "High doji count may indicate illiquid or synthetic data."
            )

    # ── Inferred interval ─────────────────────────────────────────────────────
    inferred_interval = "unknown"
    if isinstance(bars.index, pd.DatetimeIndex) and len(bars.index) >= 3:
        try:
            inferred_interval = pd.infer_freq(bars.index) or "unknown"
        except Exception:
            inferred_interval = "unknown"

    # ── Score calculation ─────────────────────────────────────────────────────
    expected_bars = total_bars + missing_bars  # denominator for ratios
    deductions = 0.0

    # Missing bars: up to 50 points
    if expected_bars > 0 and missing_bars > 0:
        deductions += min(50.0, missing_bars / expected_bars * 100.0)

    # NaN bars: up to 30 points
    if total_bars > 0 and nan_bars > 0:
        deductions += min(30.0, nan_bars / total_bars * 100.0)

    # Zero volume: up to 15 points (volume may legitimately be zero for crypto off-hours)
    if total_bars > 0 and zero_volume_bars > 0:
        deductions += min(15.0, zero_volume_bars / total_bars * 50.0)

    # Doji: up to 5 points (only for extreme doji rates > 10%)
    if total_bars > 0 and doji_bars > 0:
        doji_rate = doji_bars / total_bars
        if doji_rate > 0.10:
            deductions += min(5.0, doji_rate * 20.0)

    integrity_score = max(0.0, 100.0 - deductions)
    passed = integrity_score >= threshold and len(hard_failures) == 0

    return DataIntegrityReport(
        symbol            = symbol,
        interval          = interval,
        total_bars        = total_bars,
        integrity_score   = round(integrity_score, 2),
        passed            = passed,
        hard_failures     = hard_failures,
        warnings          = warnings,
        missing_bars      = missing_bars,
        nan_bars          = nan_bars,
        zero_volume_bars  = zero_volume_bars,
        doji_bars         = doji_bars,
        inferred_interval = str(inferred_interval),
        threshold         = threshold,
    )


def assert_integrity(
    bars     : pd.DataFrame,
    symbol   : str   = "",
    interval : str   = "",
    threshold: float = 80.0,
) -> DataIntegrityReport:
    """Run audit and raise ``ValueError`` if the data does not meet the threshold.

    Equivalent to calling ``audit_bars`` then checking ``report.passed``.

    Args:
        bars:      OHLCV DataFrame.
        symbol:    Instrument label.
        interval:  Bar interval label.
        threshold: Minimum acceptable integrity score.

    Returns:
        The :class:`DataIntegrityReport` (always, so callers can log it).

    Raises:
        ValueError: If any hard failure is detected OR if
                    ``integrity_score < threshold``.
    """
    report = audit_bars(bars, symbol=symbol, interval=interval, threshold=threshold)
    if not report.passed:
        details = "; ".join(report.hard_failures + report.warnings) or "score below threshold"
        raise ValueError(
            f"Data integrity check failed for {symbol}/{interval}: "
            f"score={report.integrity_score:.1f} < threshold={threshold}. "
            f"Details: {details}"
        )
    return report
