"""V2 execution-contract tests.

These tests define the behavior the backtest engine must expose to research:
causal execution timing, deterministic exits, and trade-ledger accounting.
"""

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import Signal


class SignalOnFirstBar:
    """Minimal strategy: emits one long entry on the first bar."""

    def generate_signals(self, bars):
        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(signals):
            signals.iloc[0] = Signal.BUY
        return signals


def make_bars(opens, closes, highs=None, lows=None):
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes,
         "volume": [1.0] * len(opens)},
        index=pd.date_range("2026-01-01", periods=len(opens), freq="h"),
    )


def test_signal_on_bar_zero_fills_on_next_bar_not_same_bar():
    bars = make_bars([100, 110, 120], [100, 110, 120])
    trades = BacktestExecutor(EngineConfig(position_size=1)).run(
        bars, SignalOnFirstBar()
    )
    assert len(trades) == 1
    assert trades[0].entry_bar == 1
    assert trades[0].entry_price == pytest.approx(110.0 * (1 + 0.0005))


def test_signal_on_final_bar_does_not_create_future_fill():
    class FinalBarSignal:
        def generate_signals(self, bars):
            signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
            signals.iloc[-1] = Signal.BUY
            return signals

    bars = make_bars([100, 110, 120], [100, 110, 120])
    trades = BacktestExecutor(EngineConfig(position_size=1)).run(
        bars, FinalBarSignal()
    )
    assert trades == []


def test_trade_net_pnl_matches_gross_minus_costs():
    bars = make_bars([100, 100, 110, 110], [100, 100, 110, 110])

    class EntryExit:
        def generate_signals(self, bars):
            s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
            s.iloc[0] = Signal.BUY
            s.iloc[2] = Signal.EXIT
            return s

    trade = BacktestExecutor(
        EngineConfig(position_size=1, fee_rate=0.01, slippage_pct=0)
    ).run(bars, EntryExit())[0]

    expected = trade.gross_pnl - trade.entry_fee - trade.exit_fee
    assert trade.net_pnl == pytest.approx(expected)


def test_final_open_position_is_liquidated_at_last_close():
    bars = make_bars([100, 100, 110], [100, 100, 110])
    trades = BacktestExecutor(EngineConfig(position_size=1)).run(
        bars, SignalOnFirstBar()
    )
    assert len(trades) == 1
    assert trades[0].exit_bar == len(bars) - 1
    assert trades[0].exit_price == pytest.approx(110.0 * (1 - 0.0005))
