"""Golden accounting tests — deterministic scenarios with hand-calculated values.

Every assertion in this file corresponds to an explicitly computed expected
value derived from the engine's documented fill formulas.  No expected value
is inferred from production code output.

Tolerance: 1e-9 relative + 1e-9 absolute for all float comparisons.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from verify._scenarios import ALL_SCENARIOS, GoldenScenario


# ── Helpers ────────────────────────────────────────────────────────────────────

def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


class FixedSignalStrategy(StrategyBase):
    def __init__(self, signals: list[str]) -> None:
        self._sigs = signals

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal(s) for s in self._sigs], index=bars.index)


def _run_scenario(s: GoldenScenario):
    """Run a GoldenScenario through PortfolioEngine with FIXED_UNITS sizing."""
    bars_df = pd.DataFrame(s.bars, columns=["open", "high", "low", "close"])

    engine_cfg = EngineConfig(
        position_size   = s.position_size,
        fee_rate        = s.fee_rate,
        slippage_pct    = s.slippage_pct,
        stop_loss_pct   = s.stop_loss_pct,
        take_profit_pct = s.take_profit_pct,
    )
    port_cfg = PortfolioConfig(
        starting_capital = s.starting_capital,
        sizing_mode      = SizingMode.FIXED_UNITS,
        position_size    = s.position_size,
    )
    strategy = FixedSignalStrategy(s.signals)
    return PortfolioEngine(port_cfg).run(bars_df, strategy, engine_cfg)


# ── Parameterised golden tests ─────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_trade_count(scenario: GoldenScenario) -> None:
    result = _run_scenario(scenario)
    assert len(result.trades) == len(scenario.expected_trades), (
        f"{scenario.name}: expected {len(scenario.expected_trades)} trade(s), "
        f"got {len(result.trades)}"
    )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_equity_curve(scenario: GoldenScenario) -> None:
    if not scenario.expected_equity:
        pytest.skip("no expected equity defined")
    result = _run_scenario(scenario)
    eq = result.equity_curve.tolist()
    assert len(eq) == len(scenario.expected_equity), (
        f"{scenario.name}: equity length {len(eq)} != {len(scenario.expected_equity)}"
    )
    for bar, (got, exp) in enumerate(zip(eq, scenario.expected_equity)):
        assert _close(got, exp), (
            f"{scenario.name} bar {bar}: equity={got:.10f} != expected={exp:.10f}"
        )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_trade_prices(scenario: GoldenScenario) -> None:
    result = _run_scenario(scenario)
    for i, (trade, exp) in enumerate(zip(result.trades, scenario.expected_trades)):
        tag = f"{scenario.name} trade {i}"
        assert trade.entry_bar == exp.entry_bar,        f"{tag}: entry_bar"
        assert trade.exit_bar  == exp.exit_bar,         f"{tag}: exit_bar"
        assert _close(trade.entry_price, exp.entry_price), (
            f"{tag}: entry_price {trade.entry_price:.10f} != {exp.entry_price}"
        )
        assert _close(trade.exit_price, exp.exit_price), (
            f"{tag}: exit_price {trade.exit_price:.10f} != {exp.exit_price}"
        )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_trade_pnl(scenario: GoldenScenario) -> None:
    result = _run_scenario(scenario)
    for i, (trade, exp) in enumerate(zip(result.trades, scenario.expected_trades)):
        tag = f"{scenario.name} trade {i}"
        assert _close(trade.gross_pnl, exp.gross_pnl), (
            f"{tag}: gross_pnl {trade.gross_pnl:.10f} != {exp.gross_pnl}"
        )
        assert _close(trade.net_pnl, exp.net_pnl), (
            f"{tag}: net_pnl {trade.net_pnl:.10f} != {exp.net_pnl}"
        )
        assert _close(trade.entry_fee, exp.entry_fee), (
            f"{tag}: entry_fee {trade.entry_fee:.10f} != {exp.entry_fee}"
        )
        assert _close(trade.exit_fee, exp.exit_fee), (
            f"{tag}: exit_fee {trade.exit_fee:.10f} != {exp.exit_fee}"
        )


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_trade_timing(scenario: GoldenScenario) -> None:
    result = _run_scenario(scenario)
    for i, (trade, exp) in enumerate(zip(result.trades, scenario.expected_trades)):
        tag = f"{scenario.name} trade {i}"
        assert trade.holding_period == exp.holding_period, (
            f"{tag}: holding_period {trade.holding_period} != {exp.holding_period}"
        )
        assert trade.exit_reason.value == exp.exit_reason, (
            f"{tag}: exit_reason {trade.exit_reason.value!r} != {exp.exit_reason!r}"
        )


# ── Scenario-specific critical checks ─────────────────────────────────────────

class TestCriticalMechanics:
    """Targeted tests for each fill mechanic variant."""

    def test_s01_winner_ending_equity(self) -> None:
        from verify._scenarios import S01_WINNER_NO_COSTS
        result = _run_scenario(S01_WINNER_NO_COSTS)
        assert _close(result.ending_equity, 10015.0), \
            f"ending_equity={result.ending_equity}"
        assert _close(result.net_profit, 15.0)
        assert _close(result.total_return, 0.0015)

    def test_s02_loser_max_drawdown(self) -> None:
        from verify._scenarios import S02_LOSER_NO_COSTS
        result = _run_scenario(S02_LOSER_NO_COSTS)
        assert result.ending_equity < result.starting_capital, "should be a loss"
        assert result.max_drawdown_pct > 0, "must have a positive drawdown"
        # drawdown_curve must be <= 0 everywhere
        assert (result.drawdown_curve <= 1e-9).all()

    def test_s03_fees_both_sides(self) -> None:
        from verify._scenarios import S03_FEES_ONLY
        result = _run_scenario(S03_FEES_ONLY)
        t = result.trades[0]
        assert _close(t.entry_fee, 0.1), f"entry_fee={t.entry_fee}"
        assert _close(t.exit_fee,  0.11), f"exit_fee={t.exit_fee}"
        assert _close(t.net_pnl,   9.79), f"net_pnl={t.net_pnl}"

    def test_s04_slippage_fills(self) -> None:
        from verify._scenarios import S04_SLIPPAGE_ONLY
        result = _run_scenario(S04_SLIPPAGE_ONLY)
        t = result.trades[0]
        assert _close(t.entry_price, 100.1),  f"entry fill should include slippage"
        assert _close(t.exit_price,  109.89), f"exit fill should deduct slippage"

    def test_s05_sl_same_bar_holding_zero(self) -> None:
        from verify._scenarios import S05_SL_ENTRY_BAR
        result = _run_scenario(S05_SL_ENTRY_BAR)
        t = result.trades[0]
        assert t.holding_period == 0, "SL on entry bar → holding_period=0"
        assert t.entry_bar == t.exit_bar == 1, "entry and exit at bar 1"
        assert t.exit_reason.value == "stop_loss"

    def test_s06_gap_down_fills_at_open_not_sl(self) -> None:
        from verify._scenarios import S06_SL_GAP_DOWN
        result = _run_scenario(S06_SL_GAP_DOWN)
        t = result.trades[0]
        # Bar2 opens at 90 which is below SL=95 → fill at 90, not 95
        assert _close(t.exit_price, 90.0), \
            f"gap-down: fill should be at bar_open=90, got {t.exit_price}"

    def test_s07_tp_fills_at_tp_level(self) -> None:
        from verify._scenarios import S07_TP_EXACT
        result = _run_scenario(S07_TP_EXACT)
        t = result.trades[0]
        # bar opens at 105 < TP=110 → fill at TP=110
        assert _close(t.exit_price, 110.0), \
            f"TP exact: fill should be at TP=110, got {t.exit_price}"
        assert t.exit_reason.value == "take_profit"

    def test_s08_tp_gap_fills_at_open(self) -> None:
        from verify._scenarios import S08_TP_GAP_UP
        result = _run_scenario(S08_TP_GAP_UP)
        t = result.trades[0]
        # bar opens at 125 > TP=110 → fill at open=125 (better price)
        assert _close(t.exit_price, 125.0), \
            f"gap-up TP: fill should be at bar_open=125, got {t.exit_price}"

    def test_s09_end_of_data_last_close(self) -> None:
        from verify._scenarios import S09_END_OF_DATA
        result = _run_scenario(S09_END_OF_DATA)
        t = result.trades[0]
        # last bar close=108
        assert _close(t.exit_price, 108.0)
        assert t.exit_reason.value == "end_of_data"

    def test_s10_no_trades_flat_equity(self) -> None:
        from verify._scenarios import S10_NO_TRADES
        result = _run_scenario(S10_NO_TRADES)
        assert len(result.trades) == 0
        assert (result.equity_curve == result.starting_capital).all()
        assert result.max_drawdown_pct == 0.0

    def test_s11_sl_wins_over_tp(self) -> None:
        from verify._scenarios import S11_SL_TP_SAME_BAR_SL_WINS
        result = _run_scenario(S11_SL_TP_SAME_BAR_SL_WINS)
        t = result.trades[0]
        assert t.exit_reason.value == "stop_loss", "SL must win over TP"
        assert _close(t.exit_price, 95.0)

    def test_s12_two_trades_equity_compounds(self) -> None:
        from verify._scenarios import S12_TWO_TRADES_COMPOUNDING
        result = _run_scenario(S12_TWO_TRADES_COMPOUNDING)
        assert len(result.trades) == 2
        assert _close(result.ending_equity, 10025.0)
        assert _close(result.net_profit, 25.0)

    def test_s14_exit_fills_next_bar_not_current(self) -> None:
        from verify._scenarios import S14_EXIT_FILLS_NEXT_BAR
        result = _run_scenario(S14_EXIT_FILLS_NEXT_BAR)
        t = result.trades[0]
        # EXIT at bar1; fill at bar2.open=200, NOT bar1.close=105
        assert _close(t.exit_price, 200.0)
        assert t.exit_bar == 2

    def test_s15_duplicate_buy_ignored(self) -> None:
        from verify._scenarios import S15_BUY_WHILE_IN_POSITION
        result = _run_scenario(S15_BUY_WHILE_IN_POSITION)
        assert len(result.trades) == 1, "second BUY should be ignored"

    def test_s16_exit_when_flat_ignored(self) -> None:
        from verify._scenarios import S16_EXIT_WHEN_FLAT
        result = _run_scenario(S16_EXIT_WHEN_FLAT)
        assert len(result.trades) == 0, "EXIT with no position should produce no trade"

    def test_s17_flat_market_zero_pnl(self) -> None:
        from verify._scenarios import S17_FLAT_MARKET
        result = _run_scenario(S17_FLAT_MARKET)
        t = result.trades[0]
        assert _close(t.net_pnl, 0.0)
        assert not t.is_winner
        assert not t.is_loser

    def test_s18_large_position_linear_scaling(self) -> None:
        from verify._scenarios import S18_LARGE_POSITION
        result = _run_scenario(S18_LARGE_POSITION)
        t = result.trades[0]
        assert t.size == 100.0
        assert _close(t.gross_pnl, 1000.0), "gross scales linearly with size"

    def test_s20_fees_scale_with_size(self) -> None:
        from verify._scenarios import S20_SIZE_2_FEES
        result = _run_scenario(S20_SIZE_2_FEES)
        t = result.trades[0]
        assert _close(t.entry_fee, 0.2),  "entry_fee = price*size*rate = 100*2*0.001"
        assert _close(t.exit_fee,  0.22), "exit_fee  = price*size*rate = 110*2*0.001"
        assert _close(t.net_pnl,  19.58)
