"""Utilities for proving research features are causal.

A feature is causal at timestamp t when appending observations after t cannot
change its value at or before t. This module provides a reusable invariant for
indicator/feature implementations.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def assert_prefix_causal(
    feature_fn: Callable[[pd.DataFrame], pd.Series | pd.DataFrame],
    bars: pd.DataFrame,
    *,
    prefix_lengths: tuple[int, ...] | None = None,
) -> None:
    """Raise if future rows change feature values on an earlier prefix.

    ``feature_fn`` must return a Series/DataFrame indexed by the input bars.
    The comparison uses the same prefix computed once from the prefix and once
    from the complete dataset. NaN/NaN pairs are treated as equal.
    """
    if len(bars) < 3:
        raise ValueError("at least 3 bars are required")
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError("bars must have a unique increasing index")

    lengths = prefix_lengths or tuple(range(2, len(bars)))
    for n in lengths:
        if n < 1 or n >= len(bars):
            raise ValueError(f"prefix length must be in [1, {len(bars) - 1}]")
        prefix = bars.iloc[:n]
        prefix_result = feature_fn(prefix)
        full_result = feature_fn(bars)
        expected = prefix_result.iloc[:n]
        actual = full_result.iloc[:n]
        if isinstance(expected, pd.Series):
            equal = expected.equals(actual)
        else:
            equal = expected.equals(actual)
        if not equal:
            raise AssertionError(
                f"feature is non-causal: appending future rows changed output "
                f"within the first {n} bars"
            )


def trailing_mean(close: pd.Series, window: int) -> pd.Series:
    """Reference causal rolling mean; never uses observations after t."""
    if window < 1:
        raise ValueError("window must be >= 1")
    return close.rolling(window=window, min_periods=window).mean()


def trailing_return(close: pd.Series, periods: int = 1) -> pd.Series:
    """Reference causal return: current close versus prior close."""
    if periods < 1:
        raise ValueError("periods must be >= 1")
    return close.pct_change(periods=periods)
