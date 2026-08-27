"""Validated research-dataset contract for Strategy Labs V2.

This module deliberately stays small: it validates structural/time-series
properties, while source-specific normalization and survivorship/corporate-
action handling belong upstream in the data pipeline.
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


def validate_research_dataset(bars: pd.DataFrame, spec: DatasetSpec | None = None) -> None:
    """Fail closed when a research dataset violates its declared contract."""
    spec = spec or DatasetSpec()
    required = {"open", "high", "low", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"dataset missing required columns: {sorted(missing)}")
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("dataset index must be a pandas DatetimeIndex")
    if bars.index.has_duplicates:
        raise ValueError("dataset contains duplicate timestamps")
    if not bars.index.is_monotonic_increasing:
        raise ValueError("dataset timestamps must be strictly increasing")
    if len(bars) == 0:
        raise ValueError("dataset must contain at least one bar")

    values = bars[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("dataset contains non-finite or non-numeric OHLC values")

    o, h, l, c = values.T
    if (h < l).any() or (o < l).any() or (o > h).any() or (c < l).any() or (c > h).any():
        raise ValueError("dataset contains impossible OHLC relationships")
    if (o <= 0).any() or (h <= 0).any() or (l <= 0).any() or (c <= 0).any():
        raise ValueError("dataset contains non-positive prices")

    if "volume" in bars.columns:
        volume = pd.to_numeric(bars["volume"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(volume).all() or (volume < 0).any():
            raise ValueError("dataset contains invalid volume values")
        if spec.require_positive_volume and (volume <= 0).any():
            raise ValueError("dataset contains zero/non-positive volume where positive volume is required")
    elif spec.require_positive_volume:
        raise ValueError("dataset requires volume, but volume column is missing")

    if spec.require_contiguous:
        if not spec.expected_frequency:
            raise ValueError("expected_frequency is required when require_contiguous=True")
        expected = pd.tseries.frequencies.to_offset(spec.expected_frequency)
        diffs = bars.index.to_series().diff().iloc[1:]
        if not (diffs == expected).all():
            raise ValueError(
                f"dataset is not contiguous at expected frequency {spec.expected_frequency}"
            )
