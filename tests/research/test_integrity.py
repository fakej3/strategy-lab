"""Tests for research.integrity — DataIntegrityReport and audit_bars."""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest

from research.integrity import audit_bars, assert_integrity, DataIntegrityReport


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_bars(n: int = 100, start: str = "2024-01-01", freq: str = "1h") -> pd.DataFrame:
    """Build a clean, perfectly consistent OHLCV DataFrame."""
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC", name="open_time")
    close_vals = [100.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame(
        {
            "open"  : [v - 0.5 for v in close_vals],
            "high"  : [v + 1.0 for v in close_vals],
            "low"   : [v - 1.0 for v in close_vals],
            "close" : close_vals,
            "volume": 1000.0,
        },
        index=idx,
    )
    return df


# ── Happy path ────────────────────────────────────────────────────────────────

def test_clean_data_passes():
    bars = _make_bars(200)
    report = audit_bars(bars, symbol="BTCUSDT", interval="1h")
    assert report.passed
    assert report.integrity_score == pytest.approx(100.0)
    assert report.hard_failures == []
    assert report.nan_bars == 0
    assert report.zero_volume_bars == 0
    assert report.doji_bars == 0
    assert report.total_bars == 200


def test_summary_string_pass():
    bars = _make_bars(50)
    report = audit_bars(bars, symbol="TEST", interval="4h")
    summary = report.summary()
    assert "PASS" in summary
    assert "TEST/4h" in summary


def test_to_dict_shape():
    bars = _make_bars(10)
    d = audit_bars(bars).to_dict()
    for key in ("symbol", "interval", "total_bars", "integrity_score",
                "passed", "hard_failures", "warnings",
                "missing_bars", "nan_bars", "zero_volume_bars", "doji_bars"):
        assert key in d


# ── Hard failures ─────────────────────────────────────────────────────────────

def test_empty_raises():
    with pytest.raises(ValueError, match="Empty"):
        audit_bars(pd.DataFrame(columns=["open", "high", "low", "close"]))


def test_missing_column_raises():
    bars = _make_bars(20)
    bars = bars.drop(columns=["close"])
    with pytest.raises(ValueError, match="'close' missing"):
        audit_bars(bars)


def test_duplicate_timestamps_raise():
    bars = _make_bars(10)
    bars = pd.concat([bars, bars.iloc[[0]]])
    with pytest.raises(ValueError, match="Duplicate"):
        audit_bars(bars)


def test_non_monotonic_raises():
    bars = _make_bars(10)
    bars = bars.iloc[::-1]  # reverse order
    with pytest.raises(ValueError, match="strictly ascending"):
        audit_bars(bars)


def test_negative_price_raises():
    bars = _make_bars(20)
    bars.iloc[5, bars.columns.get_loc("close")] = -1.0
    bars.iloc[5, bars.columns.get_loc("low")]   = -2.0
    with pytest.raises(ValueError, match="Non-positive"):
        audit_bars(bars)


def test_zero_price_raises():
    bars = _make_bars(20)
    bars.iloc[3, bars.columns.get_loc("open")] = 0.0
    with pytest.raises(ValueError, match="Non-positive"):
        audit_bars(bars)


def test_negative_volume_raises():
    bars = _make_bars(20)
    bars.iloc[2, bars.columns.get_loc("volume")] = -5.0
    with pytest.raises(ValueError, match="Negative volume"):
        audit_bars(bars)


def test_high_less_than_low_raises():
    bars = _make_bars(20)
    bars.iloc[0, bars.columns.get_loc("high")] = bars.iloc[0]["low"] - 1.0
    with pytest.raises(ValueError, match="high < low"):
        audit_bars(bars)


def test_open_outside_hl_raises():
    bars = _make_bars(20)
    bars.iloc[0, bars.columns.get_loc("open")] = bars.iloc[0]["high"] + 5.0
    with pytest.raises(ValueError, match="Open price outside"):
        audit_bars(bars)


def test_close_outside_hl_raises():
    bars = _make_bars(20)
    bars.iloc[0, bars.columns.get_loc("close")] = bars.iloc[0]["low"] - 5.0
    with pytest.raises(ValueError, match="Close price outside"):
        audit_bars(bars)


# ── Soft issues and scoring ───────────────────────────────────────────────────

def test_nan_price_deducts_score():
    bars = _make_bars(100)
    bars.iloc[0, bars.columns.get_loc("close")] = float("nan")
    bars.iloc[0, bars.columns.get_loc("high")]  = float("nan")
    report = audit_bars(bars)
    assert report.nan_bars >= 1
    assert report.integrity_score < 100.0
    assert any("NaN" in w for w in report.warnings)


def test_zero_volume_deducts_score():
    bars = _make_bars(100)
    for i in range(20):   # 20% zero volume
        bars.iloc[i, bars.columns.get_loc("volume")] = 0.0
    report = audit_bars(bars)
    assert report.zero_volume_bars == 20
    assert report.integrity_score < 100.0


def test_missing_bars_deducts_score():
    bars = _make_bars(200)
    # Drop 10 bars in the middle to create a gap
    bars = pd.concat([bars.iloc[:50], bars.iloc[60:]])
    report = audit_bars(bars)
    assert report.missing_bars > 0
    assert report.integrity_score < 100.0
    assert any("missing" in w.lower() for w in report.warnings)


def test_doji_bars_flagged_at_high_rate():
    bars = _make_bars(100)
    # Make 15 doji bars (15% > 10% threshold)
    for i in range(15):
        bars.iloc[i, bars.columns.get_loc("high")] = bars.iloc[i]["low"]
        bars.iloc[i, bars.columns.get_loc("open")] = bars.iloc[i]["low"]
        bars.iloc[i, bars.columns.get_loc("close")]= bars.iloc[i]["low"]
    report = audit_bars(bars)
    assert report.doji_bars == 15
    assert any("doji" in w.lower() for w in report.warnings)


def test_score_capped_at_zero():
    """Extreme missing data should not produce a negative score."""
    bars = _make_bars(10)
    # Add 5 NaN rows to get large NaN fraction
    bars2 = bars.copy()
    for c in ["open", "high", "low", "close"]:
        bars2.iloc[0, bars2.columns.get_loc(c)] = float("nan")
        bars2.iloc[1, bars2.columns.get_loc(c)] = float("nan")
        bars2.iloc[2, bars2.columns.get_loc(c)] = float("nan")
    report = audit_bars(bars2)
    assert report.integrity_score >= 0.0


# ── Threshold and assert_integrity ───────────────────────────────────────────

def test_threshold_fail():
    bars = _make_bars(200)
    # Create gaps to lower score
    bars = pd.concat([bars.iloc[:10], bars.iloc[110:]])
    report = audit_bars(bars, threshold=99.0)
    # The score will be < 99 due to missing bars
    assert not report.passed


def test_assert_integrity_pass():
    bars = _make_bars(200)
    report = assert_integrity(bars, symbol="X", interval="1h", threshold=80.0)
    assert report.passed


def test_assert_integrity_raises_on_fail():
    bars = _make_bars(200)
    bars = pd.concat([bars.iloc[:10], bars.iloc[110:]])
    with pytest.raises(ValueError, match="Data integrity check failed"):
        assert_integrity(bars, threshold=99.9)


# ── No volume column ─────────────────────────────────────────────────────────

def test_no_volume_column_still_passes():
    bars = _make_bars(50)
    bars = bars.drop(columns=["volume"])
    report = audit_bars(bars)
    assert report.passed
    assert report.zero_volume_bars == 0


# ── Future timestamps ─────────────────────────────────────────────────────────

def _make_future_bars(n: int = 10) -> pd.DataFrame:
    """Build bars with timestamps 30 days in the future."""
    future_start = datetime.now(timezone.utc) + timedelta(days=30)
    idx = pd.date_range(future_start, periods=n, freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        index=idx,
    )


def test_future_timestamps_generates_warning():
    # Regression: future timestamps were silently ignored
    bars = _make_future_bars(5)
    report = audit_bars(bars, symbol="BTCUSDT", interval="1h")
    warning_text = " ".join(report.warnings)
    assert "future" in warning_text.lower()


def test_future_timestamps_deducts_score():
    bars = _make_future_bars(10)
    report = audit_bars(bars, symbol="BTCUSDT", interval="1h")
    assert report.integrity_score < 100.0


def test_historical_timestamps_no_future_warning():
    bars = _make_bars(50)
    report = audit_bars(bars)
    assert not any("future" in w.lower() for w in report.warnings)
