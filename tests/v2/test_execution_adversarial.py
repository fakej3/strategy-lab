"""End-to-end adversarial tests for the V2 execution boundary."""

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig, ExitReason
from engine.strategy import CausalStrategyBase, Signal


def make_bars(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC"))


class BuyFirst(CausalStrategyBase):
    def generate_signal(self, history):
        return Signal.BUY if len(history) == 1 else Signal.HOLD


class BuyThenExit(CausalStrategyBase):
    def generate_signal(self, history):
        if len(history) == 1:
            return Signal.BUY
        if len(history) == 3:
            return Signal.EXIT
        return Signal.HOLD


def test_executor_enforces_causal_slice_end_to_end():
    bars = make_bars([
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        {"open": 200, "high": 201, "low": 199, "close": 200, "volume": 1},
        {"open": 300, "high": 301, "low": 299, "close": 300, "volume": 1},
    ])

    class Probe(BuyFirst):
        def __init__(self):
            self.ends = []
        def generate_signal(self, history):
            self.ends.append(history.index[-1])
            return super().generate_signal(history)

    strategy = Probe()
    BacktestExecutor(EngineConfig(position_size=1, slippage_pct=0)).run(bars, strategy)
    assert strategy.ends == list(bars.index)


def test_gap_through_stop_uses_gap_open_not_stale_stop():
    bars = make_bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        {"open": 80, "high": 82, "low": 79, "close": 81, "volume": 1},
    ])
    trade = BacktestExecutor(EngineConfig(
        position_size=1, stop_loss_pct=0.10, slippage_pct=0, fee_rate=0
    )).run(bars, BuyFirst())[0]
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_bar == 2
    assert trade.exit_price == pytest.approx(80.0)


def test_same_candle_stop_and_target_uses_documented_stop_priority():
    bars = make_bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
        {"open": 100, "high": 120, "low": 80, "close": 100, "volume": 1},
    ])
    trade = BacktestExecutor(EngineConfig(
        position_size=1, stop_loss_pct=0.10, take_profit_pct=0.10,
        slippage_pct=0, fee_rate=0
    )).run(bars, BuyFirst())[0]
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == pytest.approx(90.0)


def test_exit_signal_cannot_fill_on_signal_bar():
    bars = make_bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1},
        {"open": 105, "high": 105, "low": 105, "close": 105, "volume": 1},
        {"open": 110, "high": 110, "low": 110, "close": 110, "volume": 1},
        {"open": 115, "high": 115, "low": 115, "close": 115, "volume": 1},
    ])
    trade = BacktestExecutor(EngineConfig(position_size=1, slippage_pct=0, fee_rate=0)).run(
        bars, BuyThenExit()
    )[0]
    assert trade.entry_bar == 1
    assert trade.exit_bar == 3
    assert trade.exit_price == pytest.approx(115.0)
