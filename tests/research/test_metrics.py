"""Tests for research.metrics — InstitutionalMetrics and calculate_research_metrics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.metrics import InstitutionalMetrics, _kurtosis, _skewness, calculate_research_metrics


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _equity(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D")
    return pd.Series(values, index=idx, name="equity")


class _Trade:
    """Minimal trade stub compatible with calculate_research_metrics."""
    def __init__(self, net_pnl: float, holding_period: int = 1):
        self.net_pnl        = net_pnl
        self.holding_period = holding_period

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0


# ── Zero-trade case ────────────────────────────────────────────────────────────

class TestZeroTrades:
    def test_returns_metrics_instance(self):
        eq = _equity([100.0] * 20)
        m  = calculate_research_metrics(eq, [])
        assert isinstance(m, InstitutionalMetrics)

    def test_win_rate_zero(self):
        eq = _equity([100.0] * 20)
        m  = calculate_research_metrics(eq, [])
        assert m.win_rate == 0.0
        assert m.total_trades == 0

    def test_cagr_flat_equity_zero(self):
        eq = _equity([100.0] * 252)
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.cagr == pytest.approx(0.0, abs=1e-9)


# ── CAGR ──────────────────────────────────────────────────────────────────────

class TestCAGR:
    def test_doubles_in_one_year(self):
        # 252 bars: 100 → 200; CAGR = 100%
        eq = _equity([100.0 + i * (100.0 / 251) for i in range(252)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.cagr == pytest.approx(1.0, rel=0.01)

    def test_cagr_negative_when_loss(self):
        eq = _equity([100.0, 80.0])
        m  = calculate_research_metrics(eq, [], bars_per_year=1)
        assert m.cagr < 0.0


# ── Sharpe ratio ───────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_zero_volatility_returns_zero_sharpe(self):
        eq = _equity([100.0] * 20)
        m  = calculate_research_metrics(eq, [])
        assert m.sharpe_ratio == 0.0

    def test_positive_return_positive_sharpe(self):
        eq = _equity([100.0 + i for i in range(100)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.sharpe_ratio > 0.0

    def test_negative_return_negative_sharpe(self):
        eq = _equity([100.0 - i * 0.5 for i in range(50)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.sharpe_ratio < 0.0


# ── Sortino ratio ──────────────────────────────────────────────────────────────

class TestSortinoRatio:
    def test_no_downside_returns_zero(self):
        eq = _equity([100.0 + i for i in range(20)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        # All returns positive → no downside deviation → sortino = 0
        assert m.sortino_ratio == 0.0

    def test_downside_only_gives_negative_sortino(self):
        eq = _equity([100.0 - i for i in range(20)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.sortino_ratio < 0.0


# ── Max drawdown ───────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_monotonic_equity_zero_drawdown(self):
        eq = _equity([100.0 + i for i in range(20)])
        m  = calculate_research_metrics(eq, [])
        assert m.max_drawdown_pct == pytest.approx(0.0, abs=1e-9)

    def test_known_drawdown(self):
        # Peak 200, trough 100 → 50% drawdown
        eq = _equity([100.0, 200.0, 100.0])
        m  = calculate_research_metrics(eq, [])
        assert m.max_drawdown_pct == pytest.approx(0.50, rel=1e-6)


# ── Trade-based metrics ────────────────────────────────────────────────────────

class TestTradeLevelMetrics:
    def _make_trades(self):
        return [_Trade(100.0), _Trade(200.0), _Trade(-50.0), _Trade(-100.0)]

    def test_win_rate(self):
        trades = self._make_trades()
        eq     = _equity([100.0] * 20)
        m      = calculate_research_metrics(eq, trades)
        assert m.win_rate == pytest.approx(0.5, rel=1e-9)

    def test_profit_factor(self):
        trades = self._make_trades()
        eq     = _equity([100.0] * 20)
        m      = calculate_research_metrics(eq, trades)
        # gross profit = 300, gross loss = 150 → PF = 2.0
        assert m.profit_factor == pytest.approx(2.0, rel=1e-6)

    def test_payoff_ratio(self):
        trades = self._make_trades()
        eq     = _equity([100.0] * 20)
        m      = calculate_research_metrics(eq, trades)
        # avg_win = 150, avg_loss = 75 → payoff = 2.0
        assert m.payoff_ratio == pytest.approx(2.0, rel=1e-6)

    def test_total_trades(self):
        trades = self._make_trades()
        eq     = _equity([100.0] * 20)
        m      = calculate_research_metrics(eq, trades)
        assert m.total_trades == 4

    def test_all_losers_payoff_zero(self):
        trades = [_Trade(-100.0), _Trade(-50.0)]
        eq     = _equity([100.0] * 20)
        m      = calculate_research_metrics(eq, trades)
        assert m.payoff_ratio == 0.0

    def test_kelly_fraction_capped_at_one(self):
        # Perfect win rate → Kelly should be 1.0
        trades = [_Trade(100.0)] * 10
        eq     = _equity([100.0 + i for i in range(20)])
        m      = calculate_research_metrics(eq, trades)
        assert m.kelly_fraction <= 1.0


# ── Skewness and kurtosis ──────────────────────────────────────────────────────

class TestSkewnessKurtosis:
    def test_symmetric_returns_near_zero_skew(self):
        # [-1, 0, 1] is perfectly symmetric
        returns = pd.Series([-1.0, 0.0, 1.0])
        assert _skewness(returns) == pytest.approx(0.0, abs=1e-9)

    def test_excess_kurtosis_of_normal_near_zero(self):
        rng     = np.random.default_rng(42)
        arr     = pd.Series(rng.normal(0, 1, 10_000))
        kurtosis = _kurtosis(arr)
        assert abs(kurtosis) < 0.5   # loose bound for sample kurtosis

    def test_short_series_returns_zero(self):
        assert _skewness(pd.Series([1.0, 2.0])) == 0.0
        assert _kurtosis(pd.Series([1.0, 2.0, 3.0])) == 0.0


# ── bars_per_year propagation ─────────────────────────────────────────────────

class TestBarsPerYear:
    def test_bars_per_year_stored(self):
        eq = _equity([100.0] * 10)
        m  = calculate_research_metrics(eq, [], bars_per_year=8760)
        assert m.bars_per_year == 8760

    def test_different_annualisation_changes_sharpe(self):
        eq   = _equity([100.0 + i * 0.1 for i in range(100)])
        m252 = calculate_research_metrics(eq, [], bars_per_year=252)
        m365 = calculate_research_metrics(eq, [], bars_per_year=365)
        # Higher bars_per_year → higher annualised Sharpe
        assert m365.sharpe_ratio > m252.sharpe_ratio
