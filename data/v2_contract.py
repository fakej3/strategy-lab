"""Validated research-dataset contract for Strategy Labs V2.

Validation is strict and fail-closed. Source-specific normalization and
corporate-action/survivorship handling belong upstream in the data pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DatasetSpec:
    timeframe: str | None = None
    require_contiguous: bool = False
    expected_frequency: str | None = None
    require_positive_volume: bool = False
    require_timezone: bool = True


def validate_research_dataset(
    bars: pd.DataFrame,
    spec: DatasetSpec | None = None,
) -> None:
    """Validate an OHLC(V) research dataset without mutating it.

    The contract is deliberately fail-closed: malformed timestamps, prices,
    volume, ordering, or requested cadence are rejected before research code
    can consume the data.
    """
    spec = spec or DatasetSpec()
    if not isinstance(bars, pd.DataFrame) or len(bars) == 0:
        raise ValueError("dataset must be a non-empty pandas DataFrame")

    required = {"open", "high", "low", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"dataset missing required columns: {sorted(missing)}")

    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("dataset index must be a pandas DatetimeIndex")
    if spec.require_timezone and bars.index.tz is None:
        raise ValueError("dataset timestamps must be timezone-aware")
    if bars.index.has_duplicates:
        raise ValueError("dataset contains duplicate timestamps")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("dataset timestamps must be strictly increasing")

    values = (
        bars[["open", "high", "low", "close"]]
        .apply(pd.to_numeric, errors="coerce")
        .to_numpy(dtype=float)
    )
    if not np.isfinite(values).all():
        raise ValueError("dataset contains non-finite or non-numeric OHLC values")

    # Reject non-positive prices before relationship checks so malformed
    # negative/zero prices receive the more useful contract error.
    if (values <= 0).any():
        raise ValueError("dataset contains non-positive OHLC prices")

    o, h, l, c = values.T
    if (h < l).any() or (o < l).any() or (o > h).any() or (c < l).any() or (c > h).any():
        raise ValueError("dataset contains impossible OHLC relationships")

    if "volume" in bars.columns:
        volume = pd.to_numeric(bars["volume"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(volume).all() or (volume < 0).any():
            raise ValueError("dataset contains invalid volume values")
        if spec.require_positive_volume and (volume <= 0).any():
            raise ValueError(
                "dataset contains zero/non-positive volume where positive volume is required"
            )
    elif spec.require_positive_volume:
        raise ValueError("dataset requires volume, but volume column is missing")

    if spec.require_contiguous:
        if not spec.expected_frequency:
            raise ValueError("expected_frequency is required when require_contiguous=True")

        expected = pd.tseries.frequencies.to_offset(spec.expected_frequency)
        diffs = bars.index.to_series().diff().iloc[1:]

        # DatetimeIndex.diff() yields Timedelta values.  Comparing those to a
        # DateOffset directly is unreliable (and false for common offsets such
        # as 1h), so normalize fixed-width offsets to a Timedelta first.
        try:
            expected_delta = pd.Timedelta(expected)
        except (TypeError, ValueError):
            # Calendar offsets (e.g. month-end) have no single fixed duration;
            # use the offset itself against generated timestamps instead.
            expected_delta = None

        if expected_delta is not None:
            contiguous = diffs.eq(expected_delta).all()
        else:
            expected_index = bars.index[:-1] + expected
            contiguous = expected_index.equals(bars.index[1:])

        if not contiguous:
            raise ValueError(
                f"dataset is not contiguous at expected frequency {spec.expected_frequency}"
            )


def normalize_research_dataset(
    bars: pd.DataFrame,
    spec: DatasetSpec | None = None,
) -> pd.DataFrame:
    """Validate and return a normalized UTC research dataset copy."""
    validate_research_dataset(bars, spec)
    out = bars.copy()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC")
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="raise").astype(float)
    return out
