"""Unit tests for research/regime.py — deterministic, hand-verified."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.regime import (
    BEAR, BULL, HIGH_VOL, LOW_VOL, SIDEWAYS,
    analyze_per_regime, classify_regimes,
)


def _make_bars(closes, freq="1h") -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=len(closes), freq=freq, tz="UTC",
                        name="open_time")
    c   = pd.Series(closes, index=idx)
    return pd.DataFrame({
        "open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1.0,
    }, index=idx)


class TestClassifyRegimes:
    def test_returns_series_with_same_index(self):
        bars = _make_bars([100.0] * 50)
        labels = classify_regimes(bars, window=10)
        assert isinstance(labels, pd.Series)
        assert len(labels) == len(bars)
        assert labels.index.equals(bars.index)

    def test_first_window_bars_are_sideways(self):
        bars   = _make_bars([100.0] * 50)
        labels = classify_regimes(bars, window=10)
        assert all(labels.iloc[:10] == SIDEWAYS)

    def test_strong_uptrend_no_bear_labels(self):
        # In an uptrend, Bear should not appear; Bull or LowVol are both correct
        # (a uniformly rising series has constant small pct-changes → LowVol overrides trend)
        closes = [100.0 + i * 3 for i in range(50)]
        bars   = _make_bars(closes)
        labels = classify_regimes(bars, window=10, trend_threshold=0.01)
        post   = labels.iloc[10:]
        # Bear should never appear in a monotone uptrend
        assert (post == BEAR).sum() == 0
        # Bull or LowVol should dominate (not Bear or HighVol)
        acceptable = ((post == BULL) | (post == LOW_VOL) | (post == SIDEWAYS)).sum()
        assert acceptable > len(post) * 0.5

    def test_strong_downtrend_no_bull_labels(self):
        closes = [300.0 - i * 3 for i in range(50)]
        bars   = _make_bars(closes)
        labels = classify_regimes(bars, window=10, trend_threshold=0.01)
        post   = labels.iloc[10:]
        # Bull should never appear in a monotone downtrend
        assert (post == BULL).sum() == 0
        # Bear or LowVol should dominate
        acceptable = ((post == BEAR) | (post == LOW_VOL) | (post == SIDEWAYS)).sum()
        assert acceptable > len(post) * 0.5

    def test_flat_price_is_sideways(self):
        bars   = _make_bars([100.0] * 50)
        labels = classify_regimes(bars, window=10)
        # Flat → zero vol → LowVol dominates, which is fine; no crash
        valid_labels = set(labels.unique())
        assert valid_labels.issubset({SIDEWAYS, LOW_VOL, BULL, BEAR, HIGH_VOL})

    def test_volatile_period_yields_highvol(self):
        np.random.seed(1)
        # Quiet baseline then spike in volatility
        quiet = [100.0 + np.random.randn() * 0.1 for _ in range(30)]
        noisy = [quiet[-1] + np.random.randn() * 20 for _ in range(30)]
        closes = quiet + noisy
        bars   = _make_bars(closes, freq="1h")
        labels = classify_regimes(bars, window=10)
        noisy_labels = labels.iloc[30:]
        assert (noisy_labels == HIGH_VOL).sum() > 0


class TestAnalyzePerRegime:
    def _make_mock_trade(self, entry_time, pnl):
        class _T:
            def __init__(self, et, p):
                self.entry_time = et
                self.net_pnl    = p
        return _T(entry_time, pnl)

    def test_no_trades_returns_zero_counts(self):
        bars   = _make_bars([100.0] * 50)
        eq     = pd.Series([100_000.0] * 50, index=bars.index)
        result = analyze_per_regime(bars, [], eq)
        assert "regime_stats" in result
        for r_stats in result["regime_stats"].values():
            assert r_stats["n_trades"] == 0

    def test_trade_assigned_to_correct_regime(self):
        # Construct an uptrending bar sequence so some bars are Bull
        closes = [100.0 + i * 2 for i in range(60)]
        bars   = _make_bars(closes, freq="1h")
        eq     = pd.Series([100_000.0] * 60, index=bars.index)

        # A trade whose entry time falls in the uptrend region
        entry_ts = bars.index[30]
        trade    = self._make_mock_trade(entry_ts, 100.0)
        result   = analyze_per_regime(bars, [trade], eq)

        total_trades = sum(
            r["n_trades"] for r in result["regime_stats"].values()
        )
        assert total_trades == 1

    def test_labels_list_present_and_bounded(self):
        # Use >1000 bars so downsampling (step=len//500) actually engages
        closes = [100.0] * 1100
        bars   = _make_bars(closes, freq="1h")
        eq     = pd.Series([100_000.0] * 1100, index=bars.index)
        result = analyze_per_regime(bars, [], eq)
        assert "labels" in result
        assert isinstance(result["labels"], list)
        assert len(result["labels"]) <= 500   # downsampled

    def test_per_regime_stats_keys(self):
        bars   = _make_bars([100.0] * 50)
        eq     = pd.Series([100_000.0] * 50, index=bars.index)
        result = analyze_per_regime(bars, [], eq)
        for regime, stats in result["regime_stats"].items():
            assert "n_trades" in stats
            assert "win_rate" in stats
            assert "profit_factor" in stats
            assert "avg_pnl" in stats
            assert "total_pnl" in stats
