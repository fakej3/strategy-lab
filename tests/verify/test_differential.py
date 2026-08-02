"""Differential engine tests.

Runs every golden scenario through BOTH:
  1. Production engine  (BacktestExecutor via PortfolioEngine, FIXED_UNITS)
  2. Pure-Python reference engine (verify._reference.run_reference)

Both must produce IDENTICAL outputs (within floating-point tolerance) for:
  - Number of trades
  - Per-trade: entry_bar, exit_bar, entry_price, exit_price, gross_pnl, net_pnl,
    entry_fee, exit_fee, holding_period, exit_reason
  - Equity curve at every bar

This test has no hardcoded expected values — it purely checks consistency between
the two independent implementations.  If both agree, the fill mechanics are correct;
if they disagree, one (or both) has a bug.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from verify._reference import run_reference
from verify._scenarios import ALL_SCENARIOS, GoldenScenario


_ABS_TOL = 1e-9
_REL_TOL = 1e-9


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


class FixedStrategy(StrategyBase):
    def __init__(self, sigs: list[str]) -> None:
        self._sigs = sigs

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal(s) for s in self._sigs], index=bars.index)


def _run_production(s: GoldenScenario):
    bars = pd.DataFrame(s.bars, columns=["open", "high", "low", "close"])
    ec   = EngineConfig(
        position_size   = s.position_size,
        fee_rate        = s.fee_rate,
        slippage_pct    = s.slippage_pct,
        stop_loss_pct   = s.stop_loss_pct,
        take_profit_pct = s.take_profit_pct,
    )
    pc = PortfolioConfig(
        starting_capital = s.starting_capital,
        sizing_mode      = SizingMode.FIXED_UNITS,
        position_size    = s.position_size,
    )
    result   = PortfolioEngine(pc).run(bars, FixedStrategy(s.signals), ec)
    eq_list  = result.equity_curve.tolist()
    trades   = result.trades
    return trades, eq_list


def _run_reference(s: GoldenScenario):
    return run_reference(
        bars             = s.bars,
        signals          = s.signals,
        fee_rate         = s.fee_rate,
        slippage_pct     = s.slippage_pct,
        position_size    = s.position_size,
        stop_loss_pct    = s.stop_loss_pct,
        take_profit_pct  = s.take_profit_pct,
        starting_capital = s.starting_capital,
    )


# ── Trade-level differential ───────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_differential_trade_count(scenario: GoldenScenario) -> None:
    prod_trades, _ = _run_production(scenario)
    ref_trades, _  = _run_reference(scenario)
    assert len(prod_trades) == len(ref_trades), (
        f"{scenario.name}: production={len(prod_trades)} trades, "
        f"reference={len(ref_trades)} trades"
    )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_differential_trade_fields(scenario: GoldenScenario) -> None:
    prod_trades, _ = _run_production(scenario)
    ref_trades, _  = _run_reference(scenario)

    for i, (p, r) in enumerate(zip(prod_trades, ref_trades)):
        tag = f"{scenario.name} trade {i}"

        assert p.entry_bar == r.entry_bar, f"{tag}: entry_bar {p.entry_bar}!={r.entry_bar}"
        assert p.exit_bar  == r.exit_bar,  f"{tag}: exit_bar  {p.exit_bar}!={r.exit_bar}"

        assert _close(p.entry_price, r.entry_price), (
            f"{tag}: entry_price {p.entry_price:.12f} != ref {r.entry_price:.12f}"
        )
        assert _close(p.exit_price, r.exit_price), (
            f"{tag}: exit_price {p.exit_price:.12f} != ref {r.exit_price:.12f}"
        )
        assert _close(p.gross_pnl, r.gross_pnl), (
            f"{tag}: gross_pnl {p.gross_pnl:.12f} != ref {r.gross_pnl:.12f}"
        )
        assert _close(p.net_pnl, r.net_pnl), (
            f"{tag}: net_pnl {p.net_pnl:.12f} != ref {r.net_pnl:.12f}"
        )
        assert _close(p.entry_fee, r.entry_fee), (
            f"{tag}: entry_fee {p.entry_fee:.12f} != ref {r.entry_fee:.12f}"
        )
        assert _close(p.exit_fee, r.exit_fee), (
            f"{tag}: exit_fee {p.exit_fee:.12f} != ref {r.exit_fee:.12f}"
        )
        assert p.holding_period == r.holding_period, (
            f"{tag}: holding_period {p.holding_period}!={r.holding_period}"
        )
        assert p.exit_reason.value == r.exit_reason, (
            f"{tag}: exit_reason {p.exit_reason.value!r}!={r.exit_reason!r}"
        )


# ── Equity curve differential ──────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_differential_equity_curve(scenario: GoldenScenario) -> None:
    _, prod_eq = _run_production(scenario)
    _, ref_eq  = _run_reference(scenario)

    assert len(prod_eq) == len(ref_eq), (
        f"{scenario.name}: equity length {len(prod_eq)} != ref {len(ref_eq)}"
    )
    for bar, (p, r) in enumerate(zip(prod_eq, ref_eq)):
        assert _close(p, r), (
            f"{scenario.name} bar {bar}: production equity {p:.12f} != ref {r:.12f}"
        )
