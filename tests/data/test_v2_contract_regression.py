"""Regression tests for V2 dataset validation edge cases."""
from __future__ import annotations

import pandas as pd
import pytest

from data.v2_contract import DatasetSpec, normalize_research_dataset, validate_research_dataset


def _bars(index: pd.DatetimeIndex) -> pd.DataFrame:
    # Object/string input is intentional: pandas 3.x is stricter about
    # assigning strings into pre-existing numeric columns.
    return pd.DataFrame(
        {
            "open": ["100", "101", "102"],
            "high": ["101", "102", "103"],
            "low": ["99", "100", "101"],
            "close": ["100.5", "101.5", "102.5"],
            "volume": ["10", "11", "12"],
        },
        index=index,
    )


def test_normalize_accepts_numeric_strings_and_returns_float_utc() -> None:
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="Asia/Kolkata")
    out = normalize_research_dataset(_bars(idx), DatasetSpec(require_positive_volume=True))

    assert str(out.index.tz) == "UTC"
    assert all(pd.api.types.is_float_dtype(out[c]) for c in out.columns)
    assert out.index.is_monotonic_increasing


def test_contiguous_hourly_dataset_is_accepted() -> None:
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    validate_research_dataset(
        _bars(idx),
        DatasetSpec(require_contiguous=True, expected_frequency="1h"),
    )


def test_missing_hour_is_rejected() -> None:
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-01 00:00", tz="UTC"),
            pd.Timestamp("2026-01-01 01:00", tz="UTC"),
            pd.Timestamp("2026-01-01 03:00", tz="UTC"),
        ]
    )
    with pytest.raises(ValueError, match="not contiguous"):
        validate_research_dataset(
            _bars(idx),
            DatasetSpec(require_contiguous=True, expected_frequency="1h"),
        )


def test_non_positive_prices_fail_before_relationship_check() -> None:
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    bars = _bars(idx)
    bars.loc[idx[0], "open"] = "0"

    with pytest.raises(ValueError, match="non-positive OHLC prices"):
        validate_research_dataset(bars)
