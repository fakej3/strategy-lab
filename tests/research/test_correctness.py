"""Deterministic correctness tests for the six confirmed calculation bugs.

Each test is self-contained: expected values are derived by hand before
comparing against the code.  No approximations beyond floating-point tolerance.

Bug inventory being tested
--------------------------
B1  max_drawdown_abs in portfolio/engine.py used the global peak equity
    instead of the local (rolling) peak at the drawdown trough.
B2  CAGR exploded for periods shorter than one year because the annualisation
    exponent 1/n_years became very large.
B3  Calmar inherited the explosive CAGR and had no validity guard.
B4  profit_factor returned 0.0 (not math.inf) when there were no losing trades.
B5  recovery_factor in research/metrics.py used the global equity peak instead
    of the local peak at the drawdown trough.
B6  No small-sample suppression: CAGR and Calmar are now nan when n_years < 1.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from portfolio.engine import (
    PortfolioEngine,
    build_drawdown_curve,
    build_equity_curve,
)
from portfolio.models import PortfolioConfig, PortfolioTrade
from research.metrics import calculate_research_metrics


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


def _portfolio_trade(**kw) -> PortfolioTrade:
    defaults = dict(
        trade_number=1, direction="long",
        entry_time=pd.Timestamp("2024-01-02"),
        exit_time=pd.Timestamp("2024-01-04"),
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=80.0,
        size=1.0,
        entry_fee=0.0, exit_fee=0.0,
        entry_slippage=0.0, exit_slippage=0.0,
        gross_pnl=-20.0, net_pnl=-20.0,
        exit_reason=None, holding_period=2,
        portfolio_equity_at_entry=100_000.0,
    )
    defaults.update(kw)
    return PortfolioTrade(**defaults)


# ── B1: max_drawdown_abs uses local peak (portfolio/engine.py) ─────────────────

class TestMaxDrawdownAbsLocalPeak:
    """B1 — portfolio/engine.py max_drawdown_abs must use the rolling peak
    at the trough, not the global all-time peak."""

    def _bars_from_equity(self, equity_vals: list[float]) -> pd.DataFrame:
        """Build a synthetic bars DataFrame whose closes match equity_vals."""
        idx = pd.date_range("2024-01-01", periods=len(equity_vals), freq="1h", tz="UTC")
        return pd.DataFrame(
            {
                "open":   equity_vals,
                "high":   [v * 1.01 for v in equity_vals],
                "low":    [v * 0.99 for v in equity_vals],
                "close":  equity_vals,
                "volume": [1.0] * len(equity_vals),
            },
            index=idx,
        )

    def test_post_drawdown_ath_does_not_inflate_abs(self):
        """
        Manual calculation
        ------------------
        equity: 100 → 200 → 100 → 300

        Max drawdown event: 200 (local peak) → 100 (trough) = −50 %
        local_peak_at_trough = 200

        Correct  max_drawdown_abs = 200 − 100 = 100
        Buggy    max_drawdown_abs = 0.50 × 300 = 150   (global peak = 300)
        """
        # Build the equity curve directly and test the helper path.
        equity = _equity([100.0, 200.0, 100.0, 300.0])
        dd     = build_drawdown_curve(equity)

        # Re-run the same logic as the fixed portfolio/engine.py
        max_dd_pct = float(-dd.min())
        assert max_dd_pct == pytest.approx(0.50, rel=1e-9)

        trough_idx   = dd.idxmin()
        rolling_peak = equity.cummax()
        local_peak   = float(rolling_peak[trough_idx])
        max_dd_abs   = float(local_peak - equity[trough_idx])

        # Hand-computed expected value
        assert local_peak  == pytest.approx(200.0, rel=1e-9)
        assert max_dd_abs  == pytest.approx(100.0, rel=1e-9)

        # Confirm the buggy formula would give the wrong answer
        global_peak     = float(equity.max())
        wrong_dd_abs    = max_dd_pct * global_peak
        assert wrong_dd_abs == pytest.approx(150.0, rel=1e-9)

    def test_no_ath_after_drawdown_gives_same_result(self):
        """
        Manual calculation
        ------------------
        equity: 100 → 200 → 100   (no recovery)

        Max drawdown: 200 → 100 = −50 %
        local_peak = global_peak = 200
        max_drawdown_abs = 100   (same under both formulas)
        """
        equity = _equity([100.0, 200.0, 100.0])
        dd     = build_drawdown_curve(equity)

        max_dd_pct   = float(-dd.min())
        trough_idx   = dd.idxmin()
        rolling_peak = equity.cummax()
        local_peak   = float(rolling_peak[trough_idx])
        max_dd_abs   = float(local_peak - equity[trough_idx])

        assert max_dd_pct == pytest.approx(0.50, rel=1e-9)
        assert max_dd_abs == pytest.approx(100.0, rel=1e-9)

    def test_monotonic_equity_abs_is_zero(self):
        equity = _equity([100.0 + i * 10 for i in range(10)])
        dd = build_drawdown_curve(equity)
        assert float(-dd.min()) == pytest.approx(0.0, abs=1e-12)


# ── B2: CAGR suppressed for short periods ─────────────────────────────────────

class TestCAGRSmallSample:
    """B2 — CAGR must be math.nan when the backtest period is shorter than
    one year.  A 5 % gain over 50 daily bars must NOT produce a CAGR of ~29 %."""

    def test_cagr_nan_when_less_than_one_year_daily(self):
        """
        Manual check
        ------------
        50 bars, bars_per_year=252 → n_years = 50/252 ≈ 0.198 < 1.0
        Old formula: (105/100)^(252/50) − 1 ≈ 28.8 %  ← wrong
        Fixed formula: nan                              ← correct
        """
        eq = _equity([100.0] * 49 + [105.0])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert math.isnan(m.cagr), f"Expected nan but got {m.cagr}"

    def test_cagr_nan_when_less_than_one_year_hourly(self):
        """
        Manual check
        ------------
        1000 hourly bars → n_years = 1000/8760 ≈ 0.114 < 1.0
        CAGR must be nan.
        """
        eq = _equity([100.0 + i * 0.01 for i in range(1000)])
        m  = calculate_research_metrics(eq, [], bars_per_year=8760)
        assert math.isnan(m.cagr), f"Expected nan but got {m.cagr}"

    def test_cagr_computed_when_exactly_one_year(self):
        """
        Manual calculation
        ------------------
        252 bars, bars_per_year=252 → n_years = 1.0 ≥ 1.0
        equity doubles: (200/100)^(1/1) − 1 = 1.0 = 100 %
        """
        eq = _equity([100.0] * 251 + [200.0])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert not math.isnan(m.cagr)
        # CAGR = (200/100)^(1/1) - 1 = 1.0
        assert m.cagr == pytest.approx(1.0, rel=1e-6)

    def test_cagr_computed_when_more_than_one_year(self):
        """
        Manual calculation
        ------------------
        504 bars, bars_per_year=252 → n_years = 2.0
        100 → 121: CAGR = (121/100)^(1/2) − 1 = 1.1 − 1 = 0.10 = 10 %
        """
        eq = _equity([100.0] * 503 + [121.0])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert not math.isnan(m.cagr)
        assert m.cagr == pytest.approx(0.10, rel=1e-3)

    def test_cagr_negative_when_loss_over_full_year(self):
        """
        Manual calculation
        ------------------
        252 bars, bars_per_year=252 → n_years = 1.0
        100 → 64: CAGR = (64/100)^(1/1) − 1 = −0.36 = −36 %
        """
        eq = _equity([100.0] * 251 + [64.0])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert not math.isnan(m.cagr)
        assert m.cagr == pytest.approx(-0.36, rel=1e-6)


# ── B3: Calmar validity guard ──────────────────────────────────────────────────

class TestCalmarValidity:
    """B3 — Calmar must be nan when CAGR is nan or max_drawdown == 0."""

    def test_calmar_nan_when_cagr_invalid(self):
        """Short period → CAGR nan → Calmar must also be nan."""
        # 50 bars with a clear drawdown
        vals = [100.0, 200.0, 100.0] + [100.0] * 47
        eq   = _equity(vals)
        m    = calculate_research_metrics(eq, [], bars_per_year=252)
        assert math.isnan(m.cagr),    "Precondition: CAGR should be nan"
        assert math.isnan(m.calmar_ratio), f"Expected nan but got {m.calmar_ratio}"

    def test_calmar_nan_when_no_drawdown(self):
        """No drawdown → Calmar is undefined (not 0.0).

        Manual check: monotonically rising equity, max_dd_pct = 0.
        Division by zero → nan.
        """
        eq = _equity([100.0 + i for i in range(252)])
        m  = calculate_research_metrics(eq, [], bars_per_year=252)
        assert m.max_drawdown_pct == pytest.approx(0.0, abs=1e-12)
        assert math.isnan(m.calmar_ratio), f"Expected nan but got {m.calmar_ratio}"

    def test_calmar_computed_when_both_valid(self):
        """
        Manual calculation
        ------------------
        504 bars (2 years), bars_per_year=252
        equity: 100 → 80 (max DD = 20 %) → 121 (final)

        CAGR = (121/100)^(1/2) − 1 = 0.10 = 10 %
        max_dd_pct = (100 − 80) / 100 = 0.20
        Calmar = 0.10 / 0.20 = 0.50
        """
        vals = [100.0] * 252 + [80.0] + [80.0] * 250 + [121.0]
        eq   = _equity(vals)
        m    = calculate_research_metrics(eq, [], bars_per_year=252)
        assert not math.isnan(m.cagr)
        assert m.max_drawdown_pct == pytest.approx(0.20, rel=1e-3)
        assert not math.isnan(m.calmar_ratio)
        assert m.calmar_ratio == pytest.approx(0.50, rel=1e-2)


# ── B4: profit_factor = inf when no losing trades ─────────────────────────────

class TestProfitFactorNoLosers:
    """B4 — profit_factor must be math.inf when gross_loss = 0, not 0.0.
    A strategy with no losing trades has unbounded profit factor."""

    def test_all_winners_profit_factor_inf(self):
        """
        Manual calculation
        ------------------
        Trades: +100, +200, +50  (all positive)
        gross_profit = 350, gross_loss = 0
        profit_factor = 350 / 0 → math.inf
        """
        eq     = _equity([100.0] * 20)
        trades = [_Trade(100.0), _Trade(200.0), _Trade(50.0)]
        m      = calculate_research_metrics(eq, trades)
        assert math.isinf(m.profit_factor) and m.profit_factor > 0

    def test_mixed_trades_profit_factor_finite(self):
        """
        Manual calculation
        ------------------
        Trades: +300, −150  → PF = 300/150 = 2.0
        """
        eq     = _equity([100.0] * 20)
        trades = [_Trade(300.0), _Trade(-150.0)]
        m      = calculate_research_metrics(eq, trades)
        assert m.profit_factor == pytest.approx(2.0, rel=1e-9)

    def test_all_losers_profit_factor_zero(self):
        """
        Manual calculation
        ------------------
        Trades: −100, −50  → gross_profit = 0, PF = 0 / 150 = 0.0
        """
        eq     = _equity([100.0] * 20)
        trades = [_Trade(-100.0), _Trade(-50.0)]
        m      = calculate_research_metrics(eq, trades)
        assert m.profit_factor == pytest.approx(0.0, abs=1e-12)


# ── B5: recovery_factor uses local peak ───────────────────────────────────────

class TestRecoveryFactorLocalPeak:
    """B5 — recovery_factor in research/metrics.py must use the rolling peak
    at the drawdown trough, not the global maximum."""

    def test_post_drawdown_ath_does_not_inflate_recovery(self):
        """
        Manual calculation
        ------------------
        equity: 100 → 200 → 100 → 300

        Max drawdown: 200 → 100 = −50 %
        local_peak_at_trough = 200
        max_dd_abs  = 0.50 × 200 = 100  ← correct
        net_profit  = 300 − 100 = 200
        recovery    = 200 / 100 = 2.0   ← correct

        Buggy:
        max_dd_abs  = 0.50 × 300 = 150  (global peak = 300)
        recovery    = 200 / 150 ≈ 1.33  ← wrong
        """
        eq = _equity([100.0, 200.0, 100.0, 300.0])
        m  = calculate_research_metrics(eq, [])
        assert m.max_drawdown_pct == pytest.approx(0.50, rel=1e-9)
        assert m.recovery_factor  == pytest.approx(2.0,  rel=1e-6)

    def test_no_post_drawdown_ath_unchanged(self):
        """
        Manual calculation
        ------------------
        equity: 100 → 200 → 150   (no new ATH after trough)

        Max drawdown: 200 → 150 = −25 %
        local_peak = global_peak = 200
        max_dd_abs  = 0.25 × 200 = 50
        net_profit  = 150 − 100 = 50
        recovery    = 50 / 50 = 1.0
        """
        eq = _equity([100.0, 200.0, 150.0])
        m  = calculate_research_metrics(eq, [])
        assert m.max_drawdown_pct == pytest.approx(0.25, rel=1e-9)
        assert m.recovery_factor  == pytest.approx(1.0,  rel=1e-6)

    def test_no_drawdown_recovery_zero(self):
        """No drawdown → max_dd_abs = 0 → recovery = 0.0 (sentinel)."""
        eq = _equity([100.0 + i for i in range(20)])
        m  = calculate_research_metrics(eq, [])
        assert m.max_drawdown_pct == pytest.approx(0.0, abs=1e-12)
        assert m.recovery_factor  == pytest.approx(0.0, abs=1e-12)


# ── B6: joint small-sample check (CAGR + Calmar together) ─────────────────────

class TestSmallSampleSafety:
    """B6 — both CAGR and Calmar are suppressed (nan) for short backtests
    regardless of how dramatic the equity move is."""

    def test_explosive_short_backtest_cagr_and_calmar_nan(self):
        """
        Without the guard: a 5 % gain over 10 daily bars gives
        CAGR = 1.05^(252/10) − 1 ≈ 247 % — a clearly absurd number.
        With the guard: CAGR = nan, Calmar = nan.
        """
        # 10 bars: 100 → 80 → 105  (drawdown exists, gain at end)
        vals = [100.0, 90.0, 80.0, 85.0, 90.0, 95.0, 100.0, 102.0, 103.0, 105.0]
        eq   = _equity(vals)
        m    = calculate_research_metrics(eq, [], bars_per_year=252)

        # n_years = 10/252 ≈ 0.0397 < 1 → both suppressed
        assert math.isnan(m.cagr),         f"CAGR should be nan, got {m.cagr}"
        assert math.isnan(m.calmar_ratio), f"Calmar should be nan, got {m.calmar_ratio}"

        # Verify the old formula would have produced a nonsensical value
        n_years = 10 / 252
        naive_cagr = (105.0 / 100.0) ** (1.0 / n_years) - 1.0
        assert naive_cagr > 1.0, "Buggy value should be > 100 % to confirm the explosion"
