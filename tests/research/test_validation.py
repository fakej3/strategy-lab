"""Tests for research.validation — extended OHLCV data validation."""
from __future__ import annotations

import pandas as pd
import pytest

from research.validation import ValidationWarning, validate_bars_extended


def _make_bars(n: int = 10, freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "open"  : 100.0,
        "high"  : 101.0,
        "low"   :  99.0,
        "close" : 100.0,
        "volume": 1_000.0,
    }, index=idx)


# ── Empty bars ─────────────────────────────────────────────────────────────────

class TestEmptyBars:
    def test_empty_returns_no_warnings(self):
        bars = _make_bars(0)
        assert validate_bars_extended(bars) == []


# ── Duplicate timestamps ───────────────────────────────────────────────────────

class TestDuplicateTimestamps:
    def test_duplicate_raises(self):
        bars = _make_bars(5)
        # Force duplicate
        bars = pd.concat([bars, bars.iloc[[0]]])
        with pytest.raises(ValueError, match="Duplicate timestamps"):
            validate_bars_extended(bars)


# ── Ascending order ────────────────────────────────────────────────────────────

class TestTimestampOrder:
    def test_unsorted_warns(self):
        bars = _make_bars(5)
        bars = bars.iloc[::-1]  # reverse
        warnings = validate_bars_extended(bars)
        codes = [w.code for w in warnings]
        assert "unsorted_timestamps" in codes

    def test_sorted_no_order_warning(self):
        bars     = _make_bars(10)
        warnings = validate_bars_extended(bars)
        codes    = [w.code for w in warnings]
        assert "unsorted_timestamps" not in codes


# ── Non-positive prices ────────────────────────────────────────────────────────

class TestNonPositivePrices:
    def test_zero_close_raises(self):
        bars = _make_bars(5)
        bars.iloc[2, bars.columns.get_loc("close")] = 0.0
        with pytest.raises(ValueError, match="close"):
            validate_bars_extended(bars)

    def test_negative_open_raises(self):
        bars = _make_bars(5)
        bars.iloc[1, bars.columns.get_loc("open")] = -10.0
        with pytest.raises(ValueError, match="open"):
            validate_bars_extended(bars)

    def test_positive_prices_no_error(self):
        bars = _make_bars(5)
        warnings = validate_bars_extended(bars)
        assert all(w.code != "negative_price" for w in warnings)


# ── Negative volume ────────────────────────────────────────────────────────────

class TestVolumeChecks:
    def test_negative_volume_raises(self):
        bars = _make_bars(5)
        bars.iloc[0, bars.columns.get_loc("volume")] = -1.0
        with pytest.raises(ValueError, match="volume"):
            validate_bars_extended(bars)

    def test_nan_volume_warns(self):
        bars = _make_bars(5)
        bars.iloc[2, bars.columns.get_loc("volume")] = float("nan")
        warnings = validate_bars_extended(bars)
        codes = [w.code for w in warnings]
        assert "volume_nan" in codes

    def test_zero_volume_allowed(self):
        bars = _make_bars(5)
        bars["volume"] = 0.0
        # zero volume is fine (thinly traded, not negative)
        validate_bars_extended(bars)


# ── Missing bars ───────────────────────────────────────────────────────────────

class TestMissingBars:
    def test_gap_warns(self):
        bars = _make_bars(10, freq="1h")
        # Drop bar index 5 to create a gap
        bars = bars.drop(bars.index[5])
        warnings = validate_bars_extended(bars)
        codes = [w.code for w in warnings]
        assert "missing_bars" in codes

    def test_complete_series_no_missing_warning(self):
        bars     = _make_bars(10, freq="1h")
        warnings = validate_bars_extended(bars)
        codes    = [w.code for w in warnings]
        assert "missing_bars" not in codes


# ── ValidationWarning ──────────────────────────────────────────────────────────

class TestValidationWarning:
    def test_str_representation(self):
        w = ValidationWarning(code="test_code", message="a test message")
        assert "test_code" in str(w)
        assert "a test message" in str(w)

    def test_frozen_immutable(self):
        w = ValidationWarning(code="x", message="y")
        with pytest.raises(Exception):
            w.code = "z"


# ── Missing bars guard: unsorted data ─────────────────────────────────────────

class TestMissingBarsUnsorted:
    def test_unsorted_data_no_missing_bars_warning(self):
        # Reversed data triggers unsorted_timestamps but must NOT also produce
        # spurious missing_bars warnings caused by running the gap check on
        # non-monotonic data.
        bars     = _make_bars(10, freq="1h")
        bars     = bars.iloc[::-1]  # reverse
        warnings = validate_bars_extended(bars)
        codes    = [w.code for w in warnings]
        assert "unsorted_timestamps" in codes
        assert "missing_bars" not in codes


# ── No warnings on clean data ─────────────────────────────────────────────────

class TestCleanData:
    def test_clean_data_returns_empty_list(self):
        bars     = _make_bars(20, freq="1D")
        warnings = validate_bars_extended(bars)
        assert warnings == []
