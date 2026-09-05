"""Tests for research.metrics — InstitutionalMetrics and calculate_research_metrics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.metrics import InstitutionalMetrics, _kurtosis, _skewness, calculate_research_metrics


def _equity(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D")
    return pd.Series(values, index=idx, name="equity")


class _Trade:
    def __init__(self, net_pnl: float, holding_period: int = 1):
        self.net_pnl = net_pnl
        self.holding_period = holding_period

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0


class TestInputContract:
    def test_empty_equity_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            calculate_research_metrics(pd.Series(dtype=float), [])

    def test_zero_or_negative_equity_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            calculate_research_metrics(_equity([100.0, 0.0]), [])
        with pytest.raises(ValueError, match="must be > 0"):
            calculate_research_metrics(_equity([100.0, -1.0]), [])

    def test_nonfinite_equity_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            calculate_research_metrics(_equity([100.0, math.nan]), [])
        with pytest.raises(ValueError, match="finite"):
            calculate_research_metrics(_equity([100.0, math.inf]), [])

    @pytest.mark.parametrize("bpy", [0, -1, 252.5, True])
    def test_invalid_bars_per_year_rejected(self, bpy):
        with pytest.raises(ValueError, match="positive integer"):
            calculate_research_metrics(_equity([100.0, 101.0]), [], bars_per_year=bpy)


class TestZeroTrades:
    def test_returns_metrics_instance(self):
        m = calculate_research_metrics(_equity([100.0] * 20), [])
        assert isinstance(m, InstitutionalMetrics)
        assert m.total_trades == 0
        assert m.win_rate == 0.0

    def test_flat_equity_has_zero_risk_metrics(self):
        m = calculate_research_metrics(_equity([100.0] * 20), [])
        assert m.cagr == pytest.approx(0.0)
        assert m.sharpe_ratio == 0.0
        assert m.sortino_ratio == 0.0
        assert m.max_drawdown_pct == 0.0


class TestCAGR:
    def test_doubles_in_one_year(self):
        eq = _equity([100.0 + i * (100.0 / 251) for i in range(252)])
        m = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.cagr == pytest.approx(1.0, rel=0.01)

    def test_short_period_is_not_falsely_annualized(self):
        m = calculate_research_metrics(_equity([100.0, 200.0]), [], bars_per_year=252)
        assert math.isnan(m.cagr)


class TestRatios:
    def test_zero_volatility_sharpe_zero(self):
        m = calculate_research_metrics(_equity([100.0] * 20), [])
        assert m.sharpe_ratio == 0.0

    def test_positive_return_positive_sharpe(self):
        m = calculate_research_metrics(_equity([100.0 + i for i in range(100)]), [], bars_per_year=252)
        assert m.sharpe_ratio > 0.0

    def test_negative_return_negative_sharpe(self):
        m = calculate_research_metrics(_equity([100.0 - i * 0.5 for i in range(50)]), [], bars_per_year=252)
        assert m.sharpe_ratio < 0.0

    def test_no_downside_positive_returns_gives_infinite_sortino(self):
        m = calculate_research_metrics(_equity([100.0 + i for i in range(20)]), [], bars_per_year=252)
        assert m.sortino_ratio == math.inf

    def test_known_sortino_formula(self):
        returns = np.array([-0.01, 0.02, -0.03])
        prices = [100.0]
        for r in returns:
            prices.append(prices[-1] * (1 + r))
        m = calculate_research_metrics(_equity(prices), [], bars_per_year=252)
        downside = math.sqrt(float((np.minimum(returns, 0.0) ** 2).mean())) * math.sqrt(252)
        expected = float(returns.mean()) * 252 / downside
        assert m.sortino_ratio == pytest.approx(expected, rel=1e-6)

    def test_information_ratio_formula(self):
        rng = np.random.default_rng(7)
        n = 100
        strat = rng.normal(0.001, 0.01, n)
        benchmark = rng.normal(0.0005, 0.01, n)
        active = strat - benchmark
        expected = float(active.mean() * math.sqrt(252) / active.std(ddof=1))
        equity = [100.0]
        for r in strat:
            equity.append(equity[-1] * (1 + r))
        idx = pd.date_range("2024-01-01", periods=n + 1, freq="1D")
        bm = pd.Series(benchmark, index=idx[1:])
        m = calculate_research_metrics(pd.Series(equity, index=idx), [], bars_per_year=252, benchmark_returns=bm)
        assert m.information_ratio == pytest.approx(expected, rel=1e-6)


class TestDrawdown:
    def test_monotonic_equity_zero_drawdown(self):
        assert calculate_research_metrics(_equity([100.0 + i for i in range(20)]), []).max_drawdown_pct == pytest.approx(0.0)

    def test_known_drawdown(self):
        assert calculate_research_metrics(_equity([100.0, 200.0, 100.0]), []).max_drawdown_pct == pytest.approx(0.5)


class TestTradeMetrics:
    def test_win_rate_profit_factor_and_payoff(self):
        trades = [_Trade(100), _Trade(200), _Trade(-50), _Trade(-100)]
        m = calculate_research_metrics(_equity([100.0] * 20), trades)
        assert m.win_rate == pytest.approx(0.5)
        assert m.profit_factor == pytest.approx(2.0)
        assert m.payoff_ratio == pytest.approx(2.0)
        assert m.total_trades == 4

    def test_all_losers_payoff_zero(self):
        m = calculate_research_metrics(_equity([100.0] * 20), [_Trade(-100), _Trade(-50)])
        assert m.payoff_ratio == 0.0

    def test_all_winners_have_infinite_payoff_and_full_kelly(self):
        m = calculate_research_metrics(_equity([100.0] * 20), [_Trade(100)] * 10)
        assert m.payoff_ratio == math.inf
        assert m.profit_factor == math.inf
        assert m.kelly_fraction == 1.0


class TestHigherMoments:
    def test_symmetric_returns_zero_skew(self):
        assert _skewness(pd.Series([-1.0, 0.0, 1.0])) == pytest.approx(0.0)

    def test_normal_excess_kurtosis_near_zero(self):
        arr = pd.Series(np.random.default_rng(42).normal(0, 1, 10_000))
        assert abs(_kurtosis(arr)) < 0.5

    def test_short_series_zero(self):
        assert _skewness(pd.Series([1.0, 2.0])) == 0.0
        assert _kurtosis(pd.Series([1.0, 2.0, 3.0])) == 0.0


class TestBarsPerYear:
    def test_value_is_preserved(self):
        assert calculate_research_metrics(_equity([100.0] * 10), [], bars_per_year=8760).bars_per_year == 8760

    def test_annualisation_changes_sharpe(self):
        eq = _equity([100.0 + i * 0.1 for i in range(100)])
        assert calculate_research_metrics(eq, [], bars_per_year=365).sharpe_ratio > calculate_research_metrics(eq, [], bars_per_year=252).sharpe_ratio
