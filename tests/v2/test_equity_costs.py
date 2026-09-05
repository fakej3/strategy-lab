"""Golden tests for portfolio equity timing and execution edge cases."""
from __future__ import annotations

import pandas as pd
import pytest

from engine import BacktestExecutor, EngineConfig, ExitReason, Signal, StrategyBase
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
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_signal_is_filled_on_next_bar_not_signal_bar() -> None:
    data = bars(
        (100, 101, 99, 100),
        (123, 124, 122, 123),
        (130, 131, 129, 130),
    )
    trades = BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(
        data, FixedSignals({0: Signal.BUY})
    )
    assert len(trades) == 1
    assert trades[0].entry_bar == 1
    assert trades[0].entry_price == pytest.approx(123)


def test_stop_loss_wins_when_sl_and_tp_both_hit_same_bar() -> None:
    data = bars(
        (100, 100, 100, 100),
        (100, 105, 95, 100),
        (100, 100, 100, 100),
    )
    trades = BacktestExecutor(
        EngineConfig(stop_loss_pct=0.02, take_profit_pct=0.02, fee_rate=0, slippage_pct=0)
    ).run(data, FixedSignals({0: Signal.BUY}))
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS
    assert trades[0].exit_bar == 1
    assert trades[0].exit_price == pytest.approx(98)


def test_gap_through_stop_fills_at_open_not_stop_level() -> None:
    data = bars(
        (100, 100, 100, 100),
        (90, 92, 85, 88),
        (90, 90, 90, 90),
    )
    trades = BacktestExecutor(
        EngineConfig(stop_loss_pct=0.05, fee_rate=0, slippage_pct=0)
    ).run(data, FixedSignals({0: Signal.BUY}))
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.STOP_LOSS
    assert trades[0].exit_price == pytest.approx(90)


def test_end_of_data_liquidation_is_at_final_close() -> None:
    data = bars(
        (100, 100, 100, 100),
        (105, 106, 104, 105),
        (110, 112, 109, 111),
    )
    trades = BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(
        data, FixedSignals({0: Signal.BUY})
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == ExitReason.END_OF_DATA
    assert trades[0].exit_bar == 2
    assert trades[0].exit_price == pytest.approx(111)


def test_equity_curve_accounts_for_entry_fee_while_position_is_open() -> None:
    """Entry costs must reduce marked equity before the trade closes."""
    data = bars(
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 100, 100, 100),
    )
    result = PortfolioEngine(
        PortfolioConfig(starting_capital=1_000, sizing_mode=SizingMode.FIXED_UNITS, position_size=1)
    ).run(data, FixedSignals({0: Signal.BUY}), EngineConfig(fee_rate=0.01, slippage_pct=0))

    assert result.trades[0].entry_fee == pytest.approx(1.0)
    assert result.equity_curve.iloc[1] == pytest.approx(999.0)
    assert result.equity_curve.iloc[2] == pytest.approx(998.0)
    assert result.ending_equity == pytest.approx(998.0)
