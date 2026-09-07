"""Independent known-answer tests for core trading accounting.

These tests intentionally calculate expected values from first principles rather
than reusing implementation helpers.  They are regression anchors for execution
and portfolio accounting.
"""
from __future__ import annotations

import math

import pandas as pd

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase


class _EnterThenHold(StrategyBase):
    """Enter on the first eligible bar, then remain flat after exit."""

    def __init__(self, signal: Signal = Signal.BUY):
        self.signal = signal

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        out = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(out) > 0:
            out.iloc[0] = self.signal
        return out


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_known_answer_long_pnl_with_fee_and_slippage() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (110.0, 111.0, 109.0, 110.0),
    ])
    cfg = EngineConfig(position_size=2.0, fee_rate=0.001, slippage_pct=0.01)
    trade = BacktestExecutor(cfg).run(bars, _EnterThenHold())[0]

    expected_entry = 110.0 * 1.01
    expected_exit = 110.0 * 0.99
    expected_gross = (expected_exit - expected_entry) * 2.0
    expected_fees = (expected_entry + expected_exit) * 2.0 * 0.001
    expected_net = expected_gross - expected_fees

    assert math.isclose(trade.entry_price, expected_entry, rel_tol=1e-12)
    assert math.isclose(trade.exit_price, expected_exit, rel_tol=1e-12)
    assert math.isclose(trade.gross_pnl, expected_gross, rel_tol=1e-12)
    assert math.isclose(trade.net_pnl, expected_net, rel_tol=1e-12)


def test_known_answer_stop_gap_is_filled_at_open() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (90.0, 92.0, 89.0, 91.0),
    ])
    cfg = EngineConfig(position_size=1.0, stop_loss_pct=0.05)
    trade = BacktestExecutor(cfg).run(bars, _EnterThenHold())[0]

    # Signal on bar 0 enters at bar 1 open (100).  The next bar gaps through
    # the 95 stop, so the conservative execution price is its open: 90.
    assert trade.entry_bar == 1
    assert trade.exit_bar == 2
    assert math.isclose(trade.entry_price, 100.0, rel_tol=1e-12)
    assert math.isclose(trade.exit_price, 90.0, rel_tol=1e-12)
    assert trade.exit_reason == "STOP_LOSS"


def test_known_answer_no_lookahead_signal_alignment() -> None:
    bars = _bars([
        (10.0, 11.0, 9.0, 10.0),
        (20.0, 21.0, 19.0, 20.0),
        (30.0, 31.0, 29.0, 30.0),
    ])
    trade = BacktestExecutor(EngineConfig()).run(bars, _EnterThenHold())[0]

    # A signal generated on bar 0 must not receive bar 0's close as an entry.
    assert trade.entry_bar == 1
    assert trade.entry_price == 20.0
