"""V2 execution-contract tests."""

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import CausalStrategyBase, Signal


class SignalOnFirstBar(CausalStrategyBase):
    def generate_signal(self, history):
        return Signal.BUY if len(history) == 1 else Signal.HOLD


def make_bars(opens, closes, highs=None, lows=None):
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1.0] * len(opens)},
        index=pd.date_range("2026-01-01", periods=len(opens), freq="h"),
    )


def test_causal_strategy_never_receives_future_rows():
    seen_lengths = []

    class InspectingStrategy(CausalStrategyBase):
        def generate_signal(self, history):
            seen_lengths.append(len(history))
            assert len(history) == 1 + len(seen_lengths) - 1
            return Signal.HOLD

    bars = make_bars([100, 101, 102, 103], [100, 101, 102, 103])
    BacktestExecutor().run(bars, InspectingStrategy())
    assert seen_lengths == [1, 2, 3, 4]


def test_signal_on_bar_zero_fills_on_next_bar_not_same_bar():
    bars = make_bars([100, 110, 120], [100, 110, 120])
    trades = BacktestExecutor(EngineConfig(position_size=1, fee_rate=0, slippage_pct=0)).run(
        bars, SignalOnFirstBar()
    )
    assert len(trades) == 1
    assert trades[0].entry_bar == 1
    assert trades[0].entry_price == pytest.approx(110.0)


def test_signal_on_final_bar_does_not_create_future_fill():
    class FinalBarSignal(CausalStrategyBase):
        def generate_signal(self, history):
            return Signal.BUY if len(history) == 3 else Signal.HOLD

    bars = make_bars([100, 110, 120], [100, 110, 120])
    trades = BacktestExecutor(EngineConfig(position_size=1, fee_rate=0, slippage_pct=0)).run(
        bars, FinalBarSignal()
    )
    assert trades == []


def test_trade_net_pnl_matches_gross_minus_costs():
    class EntryExit(CausalStrategyBase):
        def generate_signal(self, history):
            if len(history) == 1:
                return Signal.BUY
            if len(history) == 3:
                return Signal.EXIT
            return Signal.HOLD

    bars = make_bars([100, 100, 110, 110], [100, 100, 110, 110])
    trade = BacktestExecutor(
        EngineConfig(position_size=1, fee_rate=0.01, slippage_pct=0)
    ).run(bars, EntryExit())[0]
    assert trade.net_pnl == pytest.approx(
        trade.gross_pnl - trade.entry_fee - trade.exit_fee
    )


def test_final_open_position_is_liquidated_at_last_close():
    bars = make_bars([100, 100, 110], [100, 100, 110])
    trades = BacktestExecutor(EngineConfig(position_size=1, fee_rate=0, slippage_pct=0)).run(
        bars, SignalOnFirstBar()
    )
    assert len(trades) == 1
    assert trades[0].exit_bar == len(bars) - 1
    assert trades[0].exit_price == pytest.approx(bars.close.iloc[-1])
