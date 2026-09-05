from __future__ import annotations

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig, ExitReason
from engine.strategy import Signal, StrategyBase


class _Signals(StrategyBase):
    def __init__(self, mapping: dict[int, Signal]):
        self.mapping = mapping

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        out = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        for i, signal in self.mapping.items():
            out.iloc[i] = signal
        return out


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h", tz="UTC")
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [1.0] * len(rows)},
        index=index,
    )


def test_entry_and_exit_slippage_are_applied_once_to_fill_prices() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (110.0, 111.0, 109.0, 110.0),
        (120.0, 121.0, 119.0, 120.0),
    ])
    cfg = EngineConfig(fee_rate=0.0, slippage_pct=0.10)
    trade = BacktestExecutor(cfg).run(
        bars, _Signals({0: Signal.BUY, 1: Signal.EXIT})
    )[0]

    # Buy at next open: 110 * 1.10 = 121.
    # Exit at next open: 120 * 0.90 = 108.
    assert trade.entry_price == pytest.approx(121.0)
    assert trade.exit_price == pytest.approx(108.0)
    assert trade.gross_pnl == pytest.approx(-13.0)


def test_gap_down_stop_uses_open_then_sell_slippage() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (90.0, 91.0, 80.0, 85.0),
    ])
    cfg = EngineConfig(stop_loss_pct=0.02, fee_rate=0.0, slippage_pct=0.05)
    trade = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]

    # Stop is 98, but the bar opens at 90: the marketable stop fills at 90,
    # then the normal sell-side slippage is applied: 90 * 0.95 = 85.5.
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == pytest.approx(85.5)


def test_gap_up_take_profit_uses_open_then_sell_slippage() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (110.0, 111.0, 109.0, 110.0),
    ])
    cfg = EngineConfig(take_profit_pct=0.04, fee_rate=0.0, slippage_pct=0.05)
    trade = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]

    # TP is 104, but the bar opens at 110: fill uses the better market open,
    # then the sell-side slippage model applies: 110 * 0.95 = 104.5.
    assert trade.exit_reason == ExitReason.TAKE_PROFIT
    assert trade.exit_price == pytest.approx(104.5)


def test_stop_has_precedence_when_bar_hits_stop_and_target() -> None:
    bars = _bars([
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 110.0, 90.0, 100.0),
    ])
    cfg = EngineConfig(
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        fee_rate=0.0,
        slippage_pct=0.0,
    )
    trade = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]

    # OHLC alone cannot establish intrabar order. The engine's conservative
    # deterministic policy is to give the stop precedence over the target.
    assert trade.exit_reason == ExitReason.STOP_LOSS
    assert trade.exit_price == pytest.approx(98.0)
