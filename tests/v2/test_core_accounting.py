"""Golden tests for the Strategy Lab V2 core accounting contract.

These tests intentionally use tiny, hand-calculable scenarios. They are not
strategy tests; they protect the accounting/execution layer from regressions.
A failing golden test means we stop and fix the engine before adding research
features.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine import BacktestExecutor, EngineConfig, Signal, StrategyBase
from portfolio import PortfolioConfig, PortfolioEngine, SizingMode


class FixedSignals(StrategyBase):
    def __init__(self, signals: dict[int, Signal]):
        self.signals = signals

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        out = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        for i, signal in self.signals.items():
            out.iloc[i] = signal
        return out


def bars(*rows: tuple[float, float, float, float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close"],
        index=index,
    )


def test_hold_only_is_exactly_flat() -> None:
    data = bars(
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    )
    result = PortfolioEngine(
        PortfolioConfig(starting_capital=1_000, sizing_mode=SizingMode.FIXED_UNITS, position_size=1)
    ).run(data, FixedSignals({}), EngineConfig(fee_rate=0, slippage_pct=0))

    assert result.trades == []
    assert result.ending_equity == pytest.approx(1_000)
    assert result.net_profit == pytest.approx(0)
    assert result.total_return == pytest.approx(0)
    assert result.max_drawdown_pct == pytest.approx(0)


def test_buy_and_hold_has_hand_calculable_pnl() -> None:
    # Signal on bar 0 -> entry at bar 1 open = 100.
    # Position is liquidated at bar 3 close = 110.
    data = bars(
        (90, 95, 89, 92),
        (100, 103, 99, 101),
        (105, 108, 104, 107),
        (109, 112, 108, 110),
    )
    result = PortfolioEngine(
        PortfolioConfig(starting_capital=1_000, sizing_mode=SizingMode.FIXED_UNITS, position_size=2)
    ).run(data, FixedSignals({0: Signal.BUY}), EngineConfig(fee_rate=0, slippage_pct=0))

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(100)
    assert trade.exit_price == pytest.approx(110)
    assert trade.size == pytest.approx(2)
    assert trade.gross_pnl == pytest.approx(20)
    assert trade.net_pnl == pytest.approx(20)
    assert result.ending_equity == pytest.approx(1_020)


def test_round_trip_costs_are_exactly_fees_and_slippage() -> None:
    # Raw entry 100, raw exit 100, 1% slippage and 0.1% fee per side.
    # Entry fill = 101; exit fill = 99.
    # Gross PnL = -2. Fees = 0.101 + 0.099 = 0.2; net = -2.2.
    data = bars(
        (90, 91, 89, 90),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    )
    result = PortfolioEngine(
        PortfolioConfig(starting_capital=1_000, sizing_mode=SizingMode.FIXED_UNITS, position_size=1)
    ).run(
        data,
        FixedSignals({0: Signal.BUY, 2: Signal.EXIT}),
        EngineConfig(fee_rate=0.001, slippage_pct=0.01),
    )

    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(101)
    assert trade.exit_price == pytest.approx(99)
    assert trade.entry_fee == pytest.approx(0.101)
    assert trade.exit_fee == pytest.approx(0.099)
    assert trade.gross_pnl == pytest.approx(-2)
    assert trade.net_pnl == pytest.approx(-2.2)
    assert result.ending_equity == pytest.approx(997.8)


def test_dynamic_percent_equity_sizing_compounds_from_realized_equity() -> None:
    data = bars(
        (100, 100, 100, 100),
        (100, 101, 99, 100),   # first entry at 100
        (110, 111, 109, 110),  # first exit at 110
        (100, 101, 99, 100),   # second entry at 100
        (105, 106, 104, 105),  # second exit at 105
    )
    strategy = FixedSignals({0: Signal.BUY, 1: Signal.EXIT, 2: Signal.BUY, 3: Signal.EXIT})
    result = PortfolioEngine(
        PortfolioConfig(
            starting_capital=1_000,
            sizing_mode=SizingMode.PCT_OF_EQUITY,
            equity_fraction=0.10,
        )
    ).run(data, strategy, EngineConfig(fee_rate=0, slippage_pct=0))

    assert len(result.trades) == 2
    # First trade: 10% of 1000 = $100 / $100 = 1 unit -> +$10.
    assert result.trades[0].size == pytest.approx(1)
    assert result.trades[0].net_pnl == pytest.approx(10)
    assert result.trades[0].portfolio_equity_at_entry == pytest.approx(1_000)
    # Second trade must size from 1010, not the original 1000.
    assert result.trades[1].size == pytest.approx(1.01)
    assert result.trades[1].portfolio_equity_at_entry == pytest.approx(1_010)
    assert result.trades[1].net_pnl == pytest.approx(5.05)
    assert result.ending_equity == pytest.approx(1_015.05)
