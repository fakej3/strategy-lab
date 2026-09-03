"""Regression coverage for portfolio sizing, fees, and funding semantics."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from tests.portfolio.test_engine import _bars


class _FixedSignals(StrategyBase):
    def __init__(self, signal_map: dict[int, Signal]):
        self._map = signal_map

    def generate_signals(self, bars):
        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        for i, signal in self._map.items():
            if i < len(signals):
                signals.iloc[i] = signal
        return signals


def test_dynamic_pct_sizing_uses_post_trade_equity():
    """Each dynamic trade must size from equity after prior net PnL and fees."""
    bars = _bars([
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (110, 111, 109, 110),
        (110, 111, 109, 110),
        (120, 121, 119, 120),
    ])
    cfg = PortfolioConfig(
        starting_capital=1_000.0,
        sizing_mode=SizingMode.PCT_OF_EQUITY,
        equity_fraction=0.50,
    )
    ec = EngineConfig(fee_rate=0.01, slippage_pct=0.0)

    result = PortfolioEngine(cfg).run(
        bars,
        _FixedSignals({0: Signal.BUY, 1: Signal.EXIT, 2: Signal.BUY, 3: Signal.EXIT}),
        ec,
    )

    assert len(result.trades) == 2
    first, second = result.trades
    assert first.size == pytest.approx(5.0)
    assert first.net_pnl == pytest.approx(39.5)
    assert first.portfolio_equity_at_entry == pytest.approx(1_000.0)

    post_trade_equity = 1_039.5
    expected_second_size = (post_trade_equity * 0.50) / 110.0
    assert second.portfolio_equity_at_entry == pytest.approx(post_trade_equity)
    assert second.size == pytest.approx(expected_second_size)


def test_full_equity_allocation_with_fees_fails_closed():
    """A 100% allocation cannot silently borrow to pay its entry fee."""
    bars = _bars([
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ])
    cfg = PortfolioConfig(
        starting_capital=1_000.0,
        sizing_mode=SizingMode.PCT_OF_EQUITY,
        equity_fraction=1.0,
    )
    ec = EngineConfig(fee_rate=0.01, slippage_pct=0.0)

    with pytest.raises(ValueError, match="insufficient capital"):
        PortfolioEngine(cfg).run(bars, _FixedSignals({0: Signal.BUY, 1: Signal.EXIT}), ec)


def test_fixed_dollar_allocation_with_fee_overflow_fails_closed():
    """Fixed-dollar sizing must not exceed available capital once fees are added."""
    bars = _bars([
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
    ])
    cfg = PortfolioConfig(
        starting_capital=1_000.0,
        sizing_mode=SizingMode.FIXED_DOLLAR,
        trade_capital=1_000.0,
    )
    ec = EngineConfig(fee_rate=0.01, slippage_pct=0.0)

    with pytest.raises(ValueError, match="insufficient capital"):
        PortfolioEngine(cfg).run(bars, _FixedSignals({0: Signal.BUY, 1: Signal.EXIT}), ec)
