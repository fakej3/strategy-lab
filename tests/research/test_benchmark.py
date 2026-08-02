"""Tests for research.benchmark — BuyAndHoldBenchmark and compute_alpha_beta."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.benchmark import BenchmarkResult, BuyAndHoldBenchmark, compute_alpha_beta


def _bars(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="1D", tz="UTC")
    opens  = prices
    closes = prices
    highs  = [p + 1 for p in prices]
    lows   = [p - 1 for p in prices]
    return pd.DataFrame({
        "open" : opens,
        "high" : highs,
        "low"  : lows,
        "close": closes,
        "volume": 1_000.0,
    }, index=idx)


def _equity(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D")
    return pd.Series(values, index=idx, name="equity")


# ── BuyAndHoldBenchmark ────────────────────────────────────────────────────────

class TestBuyAndHoldBenchmark:
    def test_starting_capital_validation(self):
        with pytest.raises(ValueError, match="starting_capital"):
            BuyAndHoldBenchmark(starting_capital=0.0)

    def test_empty_bars_raises(self):
        bench = BuyAndHoldBenchmark(100_000)
        with pytest.raises(ValueError, match="empty"):
            bench.run(_bars([]))

    def test_first_bar_price_zero_raises(self):
        bars = _bars([0.0, 100.0])
        bench = BuyAndHoldBenchmark(100_000)
        with pytest.raises(ValueError):
            bench.run(bars)

    def test_flat_price_flat_equity(self):
        bars   = _bars([100.0] * 10)
        bench  = BuyAndHoldBenchmark(100_000)
        equity = bench.run(bars)
        assert len(equity) == 10
        # All close prices equal open → equity constant
        assert (equity == 100_000.0).all()
        assert equity.name == "bh_equity"

    def test_price_doubles_equity_doubles(self):
        bars   = _bars([100.0, 200.0])
        bench  = BuyAndHoldBenchmark(100_000)
        equity = bench.run(bars)
        # units = 100_000 / 100 = 1000; at 200: 1000 * 200 = 200_000
        assert equity.iloc[-1] == pytest.approx(200_000.0, rel=1e-9)

    def test_equity_length_matches_bars(self):
        bars   = _bars([100.0, 110.0, 120.0, 130.0])
        bench  = BuyAndHoldBenchmark(50_000)
        equity = bench.run(bars)
        assert len(equity) == 4


# ── compute_alpha_beta ─────────────────────────────────────────────────────────

class TestComputeAlphaBeta:
    def _strategy_equity(self) -> pd.Series:
        return _equity([100.0 + i * 0.5 for i in range(100)])

    def _benchmark_equity(self) -> pd.Series:
        return _equity([100.0 + i * 0.3 for i in range(100)])

    def test_returns_benchmark_result_instance(self):
        se = self._strategy_equity()
        be = self._benchmark_equity()
        r  = compute_alpha_beta(se, be)
        assert isinstance(r, BenchmarkResult)

    def test_identical_series_beta_one_alpha_near_zero(self):
        equity = _equity([100.0 + i for i in range(100)])
        r      = compute_alpha_beta(equity, equity.copy())
        assert r.beta == pytest.approx(1.0, rel=1e-6)

    def test_total_returns_computed_correctly(self):
        # Need >= 3 values so pct_change().dropna() gives >= 2 aligned bars
        se = _equity([100.0, 125.0, 150.0])
        be = _equity([100.0, 150.0, 200.0])
        r  = compute_alpha_beta(se, be)
        assert r.strategy_return  == pytest.approx(0.5, rel=1e-9)
        assert r.benchmark_return == pytest.approx(1.0, rel=1e-9)
        assert r.excess_return    == pytest.approx(-0.5, rel=1e-9)

    def test_fewer_than_2_bars_raises(self):
        se = _equity([100.0])
        be = _equity([100.0])
        with pytest.raises(ValueError, match="2 common bars"):
            compute_alpha_beta(se, be)

    def test_correlation_between_neg1_and_1(self):
        se = self._strategy_equity()
        be = self._benchmark_equity()
        r  = compute_alpha_beta(se, be)
        assert -1.0 <= r.correlation <= 1.0

    def test_tracking_error_nonnegative(self):
        se = self._strategy_equity()
        be = self._benchmark_equity()
        r  = compute_alpha_beta(se, be)
        assert r.tracking_error >= 0.0

    def test_uncorrelated_series_near_zero_beta(self):
        idx    = pd.date_range("2024-01-01", periods=100, freq="1D")
        rng    = np.random.default_rng(0)
        strat  = pd.Series(100.0 + rng.standard_normal(100).cumsum(), index=idx)
        rng2   = np.random.default_rng(99)
        bench  = pd.Series(100.0 + rng2.standard_normal(100).cumsum(), index=idx)
        r      = compute_alpha_beta(strat, bench)
        # Loosely check: beta shouldn't be extreme for random-walk series
        assert abs(r.beta) < 5.0
