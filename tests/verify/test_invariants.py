"""Financial invariant tests.

Verifies that:
1. All golden scenarios pass every financial invariant.
2. Artificially mutated results correctly trigger the expected violation.

Invariants checked:
  I1  ending_equity = starting_capital + net_profit
  I2  peak_equity >= ending_equity
  I3  drawdown in (-1, 0]
  I4  max_drawdown_pct matches drawdown curve minimum
  I5  no NaN / Inf in curves
  I6  equity curve strictly positive
  I7  exposure in [0, 1]
  I8  total_return = (ending - starting) / starting
  I9  per-trade: gross formula, net formula, fees≥0, sizes>0, no NaN
"""
from __future__ import annotations

import copy
import math

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult, PortfolioTrade, SizingMode
from verify._invariants import check_all
from verify._scenarios import ALL_SCENARIOS, GoldenScenario


# ── Helpers ────────────────────────────────────────────────────────────────────

class FixedStrategy(StrategyBase):
    def __init__(self, sigs: list[str]) -> None:
        self._sigs = sigs

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal(s) for s in self._sigs], index=bars.index)


def _run(s: GoldenScenario) -> PortfolioResult:
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
    return PortfolioEngine(pc).run(bars, FixedStrategy(s.signals), ec)


# ── All golden scenarios must pass all invariants ──────────────────────────────

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_invariants_on_golden_scenario(scenario: GoldenScenario) -> None:
    result     = _run(scenario)
    violations = check_all(result)
    assert violations == [], (
        f"{scenario.name} violated invariants:\n"
        + "\n".join(f"  [{v.invariant}] {v.message}" for v in violations)
    )


# ── Mutation tests: artificially break invariants and check detection ──────────

def _clean_result() -> PortfolioResult:
    """A simple, known-good result to mutate in violation tests."""
    from verify._scenarios import S01_WINNER_NO_COSTS
    return _run(S01_WINNER_NO_COSTS)


class TestViolationDetection:

    def test_i1_ending_equity_mismatch(self) -> None:
        r = _clean_result()
        # Break I1 by injecting a wrong net_profit
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity + 100,   # disagrees with net_profit
            peak_equity      = r.peak_equity + 100,
            net_profit       = r.net_profit,             # not updated → mismatch
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve + 100,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I1_ENDING_EQUITY" in names

    def test_i2_peak_below_ending(self) -> None:
        r = _clean_result()
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.ending_equity - 1,  # peak < ending → violation
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I2_PEAK_GE_ENDING" in names

    def test_i3_drawdown_above_zero(self) -> None:
        import numpy as np
        r = _clean_result()
        bad_dd = r.drawdown_curve.copy()
        bad_dd.iloc[0] = 0.05   # positive drawdown → impossible
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = bad_dd,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I3_DD_UPPER" in names

    def test_i3_drawdown_below_minus_one(self) -> None:
        r = _clean_result()
        bad_dd = r.drawdown_curve.copy()
        bad_dd.iloc[1] = -1.5   # below -100%
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = bad_dd,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I3_DD_LOWER" in names

    def test_i5_nan_in_equity(self) -> None:
        r = _clean_result()
        bad_eq = r.equity_curve.copy().astype(float)
        bad_eq.iloc[1] = float("nan")
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = bad_eq,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I5_NAN_EQUITY_CURVE" in names

    def test_i6_zero_equity(self) -> None:
        r = _clean_result()
        bad_eq = r.equity_curve.copy()
        bad_eq.iloc[0] = 0.0
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = bad_eq,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I6_POSITIVE_EQUITY" in names

    def test_i7_exposure_gt_one(self) -> None:
        r = _clean_result()
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = 1.5,   # impossible: > 100%
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I7_EXPOSURE" in names

    def test_i9_gross_pnl_wrong(self) -> None:
        r = _clean_result()
        if not r.trades:
            pytest.skip("no trades to mutate")
        orig = r.trades[0]
        bad_trade = PortfolioTrade(
            trade_number              = orig.trade_number,
            direction                 = orig.direction,
            entry_time                = orig.entry_time,
            exit_time                 = orig.exit_time,
            entry_bar                 = orig.entry_bar,
            exit_bar                  = orig.exit_bar,
            entry_price               = orig.entry_price,
            exit_price                = orig.exit_price,
            size                      = orig.size,
            entry_fee                 = orig.entry_fee,
            exit_fee                  = orig.exit_fee,
            entry_slippage            = orig.entry_slippage,
            exit_slippage             = orig.exit_slippage,
            gross_pnl                 = orig.gross_pnl + 999,  # wrong
            net_pnl                   = orig.net_pnl,
            exit_reason               = orig.exit_reason,
            holding_period            = orig.holding_period,
            portfolio_equity_at_entry = orig.portfolio_equity_at_entry,
        )
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = [bad_trade] + r.trades[1:],
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I9_GROSS_PNL" in names

    def test_i9_net_pnl_wrong(self) -> None:
        r = _clean_result()
        if not r.trades:
            pytest.skip("no trades to mutate")
        orig = r.trades[0]
        bad_trade = PortfolioTrade(
            trade_number              = orig.trade_number,
            direction                 = orig.direction,
            entry_time                = orig.entry_time,
            exit_time                 = orig.exit_time,
            entry_bar                 = orig.entry_bar,
            exit_bar                  = orig.exit_bar,
            entry_price               = orig.entry_price,
            exit_price                = orig.exit_price,
            size                      = orig.size,
            entry_fee                 = orig.entry_fee,
            exit_fee                  = orig.exit_fee,
            entry_slippage            = orig.entry_slippage,
            exit_slippage             = orig.exit_slippage,
            gross_pnl                 = orig.gross_pnl,
            net_pnl                   = orig.net_pnl + 999,  # wrong
            exit_reason               = orig.exit_reason,
            holding_period            = orig.holding_period,
            portfolio_equity_at_entry = orig.portfolio_equity_at_entry,
        )
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = r.total_return,
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = [bad_trade] + r.trades[1:],
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I9_NET_PNL" in names

    def test_i8_total_return_wrong(self) -> None:
        r = _clean_result()
        bad = PortfolioResult(
            starting_capital = r.starting_capital,
            ending_equity    = r.ending_equity,
            peak_equity      = r.peak_equity,
            net_profit       = r.net_profit,
            total_return     = 99.0,   # nonsensical
            max_drawdown_pct = r.max_drawdown_pct,
            max_drawdown_abs = r.max_drawdown_abs,
            exposure_pct     = r.exposure_pct,
            equity_curve     = r.equity_curve,
            balance_curve    = r.balance_curve,
            drawdown_curve   = r.drawdown_curve,
            trades           = r.trades,
        )
        viols = check_all(bad)
        names = {v.invariant for v in viols}
        assert "I8_TOTAL_RETURN" in names

    def test_clean_result_has_no_violations(self) -> None:
        r    = _clean_result()
        viols = check_all(r)
        assert viols == [], f"Unexpected violations: {viols}"
