from __future__ import annotations

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig, ExitReason
from engine.strategy import Signal, StrategyBase


class Signals(StrategyBase):
    def __init__(self, mapping: dict[int, Signal]):
        self.mapping = mapping

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        out = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        for i, signal in self.mapping.items():
            out.iloc[i] = signal
        return out


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_golden_long_trade_with_fee_and_slippage() -> None:
    # Signal on bar 0 executes at bar 1 open=100.
    # 0.1% entry slippage => 100.10.
    # Signal on bar 2 executes at bar 3 open=110.
    # 0.1% exit slippage => 109.89.
    # size=2, fee=0.1% per side.
    data = bars([
        (99, 101, 98, 100),
        (100, 102, 99, 101),
        (109, 111, 108, 110),
        (110, 112, 109, 110),
    ])
    cfg = EngineConfig(position_size=2, fee_rate=0.001, slippage_pct=0.001)
    trade = BacktestExecutor(cfg).run(
        data, Signals({0: Signal.BUY, 2: Signal.EXIT})
    )[0]

    entry = 100 * 1.001
    exit_ = 110 * 0.999
    entry_fee = entry * 2 * 0.001
    exit_fee = exit_ * 2 * 0.001
    gross = (exit_ - entry) * 2
    expected_net = gross - entry_fee - exit_fee

    assert trade.entry_price == pytest.approx(entry)
    assert trade.exit_price == pytest.approx(exit_)
    assert trade.entry_fee == pytest.approx(entry_fee)
    assert trade.exit_fee == pytest.approx(exit_fee)
    assert trade.gross_pnl == pytest.approx(gross)
    assert trade.net_pnl == pytest.approx(expected_net)
    assert trade.exit_reason == ExitReason.SIGNAL


def test_stop_gap_is_conservative_and_not_optimistic() -> None:
    # Entry=100, stop=98. The next bar gaps to 90, so the modeled fill is 90.
    data = bars([
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (90, 91, 89, 90),
    ])
    cfg = EngineConfig(stop_loss_pct=0.02, fee_rate=0, slippage_pct=0)
    trade = BacktestExecutor(cfg).run(data, Signals({0: Signal.BUY}))[0]
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == pytest.approx(90)


def test_causal_strategy_cannot_see_future_rows() -> None:
    from engine.strategy import CausalStrategyBase

    seen_lengths: list[int] = []

    class Probe(CausalStrategyBase):
        def generate_signal(self, history: pd.DataFrame) -> Signal:
            seen_lengths.append(len(history))
            return Signal.HOLD

    data = bars([
        (100, 101, 99, 100),
        (101, 102, 100, 101),
        (102, 103, 101, 102),
    ])
    BacktestExecutor().run(data, Probe())
    assert seen_lengths == [1, 2, 3]
