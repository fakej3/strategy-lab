"""Unit tests for research/rolling.py — formula verification and edge cases."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.rolling import compute_rolling_metrics, _bisect_left, _bisect_right


def _eq(values) -> pd.Series:
    idx = pd.date_range("2022-01-01", periods=len(values), freq="1h", tz="UTC",
                        name="open_time")
    return pd.Series(values, index=idx, dtype=float)


def _trade(exit_bar: int, pnl: float):
    class _T:
        def __init__(self, eb, p):
            self.exit_bar = eb
            self.net_pnl  = p
    return _T(exit_bar, pnl)


class TestBisect:
    def test_bisect_left_empty(self):
        assert _bisect_left([], 5, key=lambda x: x) == 0

    def test_bisect_left_finds_correct_position(self):
        lst = [1, 3, 5, 7, 9]
        assert _bisect_left(lst, 5, key=lambda x: x) == 2

    def test_bisect_right_finds_correct_position(self):
        lst = [1, 3, 5, 5, 7]
        assert _bisect_right(lst, 5, key=lambda x: x) == 4


class TestComputeRollingMetrics:
    def test_too_short_equity_returns_empty(self):
        eq     = _eq([100_000.0] * 5)
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        assert result["timestamps"] == []
        assert result["sharpe"] == []

    def test_output_lengths_match(self):
        n  = 50
        eq = _eq([100_000.0 + i * 10 for i in range(n)])
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        expected_len = n - 10
        assert len(result["timestamps"])   == expected_len
        assert len(result["sharpe"])       == expected_len
        assert len(result["sortino"])      == expected_len
        assert len(result["cagr"])         == expected_len
        assert len(result["drawdown"])     == expected_len
        assert len(result["win_rate"])     == expected_len
        assert len(result["profit_factor"]) == expected_len
        assert len(result["expectancy"])   == expected_len

    def test_rolling_sharpe_sign(self):
        # Equity falling → negative mean return → negative Sharpe
        values = [100_000.0 - i * 100 for i in range(30)]
        eq     = _eq(values)
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        # All windows have negative mean return → Sharpe should be negative
        assert all(sh <= 0 for sh in result["sharpe"])

    def test_rolling_sharpe_positive_for_rising_equity(self):
        # Add noise to avoid degenerate zero-std case
        np.random.seed(0)
        values = [100_000.0 + i * 100 + np.random.randn() * 5 for i in range(30)]
        eq     = _eq(values)
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        # Mostly positive mean returns → mostly positive Sharpe
        pos_count = sum(1 for sh in result["sharpe"] if sh > 0)
        assert pos_count > len(result["sharpe"]) * 0.5

    def test_no_trades_gives_none_for_trade_metrics(self):
        eq     = _eq([100_000.0 + i for i in range(30)])
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        assert all(v is None for v in result["win_rate"])
        assert all(v is None for v in result["profit_factor"])
        assert all(v is None for v in result["expectancy"])

    def test_trades_in_window_computed_correctly(self):
        eq = _eq([100_000.0 + i for i in range(30)])
        # Two winning trades in window [0,10], one losing trade
        trades = [
            _trade(exit_bar=5,  pnl=100.0),
            _trade(exit_bar=8,  pnl=50.0),
            _trade(exit_bar=7,  pnl=-20.0),
        ]
        result = compute_rolling_metrics(eq, trades, bars_per_year=8760, window=10)
        # First output corresponds to bars 0..10
        # win_rate = 2/3 ≈ 0.6667
        assert result["win_rate"][0] == pytest.approx(2 / 3, abs=1e-4)
        # PF = (100+50) / 20 = 7.5
        assert result["profit_factor"][0] == pytest.approx(7.5, abs=1e-4)
        # expectancy = (100+50-20)/3 ≈ 43.333
        assert result["expectancy"][0] == pytest.approx(130 / 3, abs=1e-3)

    def test_drawdown_zero_when_equity_rises(self):
        # Monotonically rising equity → max drawdown in window = 0
        eq     = _eq([100_000.0 + i * 100 for i in range(30)])
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        assert all(dd == pytest.approx(0.0, abs=1e-6) for dd in result["drawdown"])

    def test_default_window_computed_from_bars_per_year(self):
        eq     = _eq([100_000.0 + i for i in range(200)])
        result = compute_rolling_metrics(eq, [], bars_per_year=8760)
        expected_window = max(20, 8760 // 52)  # = 168
        assert result["window"] == expected_window

    def test_all_keys_present(self):
        eq     = _eq([100_000.0 + i for i in range(50)])
        result = compute_rolling_metrics(eq, [], bars_per_year=8760, window=10)
        for k in ("window", "timestamps", "sharpe", "sortino", "cagr",
                  "drawdown", "win_rate", "profit_factor", "expectancy"):
            assert k in result
