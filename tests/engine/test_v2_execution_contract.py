"""Adversarial tests for the V2 long-only execution contract."""
from __future__ import annotations

import pandas as pd

from engine.executor import BacktestExecutor
from engine.models import EngineConfig, ExitReason
from engine.strategy import CausalStrategyBase, Signal


def _bars(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [1.0] * len(prices),
        },
        index=idx,
    )


class _CausalMap(CausalStrategyBase):
    def __init__(self, mapping: dict[int, Signal]):
        self.mapping = mapping
        self.seen_lengths: list[int] = []

    def generate_signal(self, history: pd.DataFrame) -> Signal:
        self.seen_lengths.append(len(history))
        return self.mapping.get(len(history) - 1, Signal.HOLD)


def test_causal_strategy_never_receives_future_bars() -> None:
    bars = _bars([100, 101, 102, 103])
    strategy = _CausalMap({})
    strategy.generate_signals(bars)
    assert strategy.seen_lengths == [1, 2, 3, 4]


def test_buy_fills_on_next_bar_open() -> None:
    bars = _bars([100, 110, 120])
    strategy = _CausalMap({0: Signal.BUY, 1: Signal.EXIT})
    trade = BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(bars, strategy)[0]
    assert trade.entry_bar == 1
    assert trade.entry_price == 110


def test_sell_never_opens_a_short_position_when_flat() -> None:
    bars = _bars([100, 101, 102])
    strategy = _CausalMap({0: Signal.SELL})
    assert BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(bars, strategy) == []


def test_sell_closes_existing_long_but_does_not_reverse() -> None:
    bars = _bars([100, 110, 120, 130])
    strategy = _CausalMap({0: Signal.BUY, 2: Signal.SELL})
    trades = BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(bars, strategy)
    assert len(trades) == 1
    assert trades[0].direction == "Long"
    assert trades[0].entry_bar == 1
    assert trades[0].exit_reason == ExitReason.SIGNAL


def test_open_position_is_liquidated_at_end_of_data() -> None:
    bars = _bars([100, 110, 125])
    strategy = _CausalMap({0: Signal.BUY})
    trade = BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(bars, strategy)[0]
    assert trade.exit_bar == 2
    assert trade.exit_price == 125
    assert trade.exit_reason == ExitReason.END_OF_DATA
