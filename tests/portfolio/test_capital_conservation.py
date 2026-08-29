"""Adversarial tests for cash-only portfolio funding and accounting."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import _validate_entry_funding
from portfolio.models import PortfolioConfig, SizingMode
from portfolio.engine import PortfolioEngine


class _BuyThenExit(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(signals) >= 3:
            signals.iloc[0] = Signal.BUY
            signals.iloc[1] = Signal.EXIT
        return signals


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0, 110.0],
            "high": [101.0, 101.0, 111.0, 111.0],
            "low": [99.0, 99.0, 109.0, 109.0],
            "close": [100.0, 100.0, 110.0, 110.0],
            "volume": [1.0] * 4,
        },
        index=idx,
    )


def test_funding_rejects_position_larger_than_cash() -> None:
    with pytest.raises(ValueError, match="insufficient capital"):
        _validate_entry_funding(1_000.0, 100.0, 11.0, 0.001)


def test_funding_allows_position_when_notional_and_fee_fit() -> None:
    _validate_entry_funding(1_000.0, 100.0, 9.0, 0.001)


def test_fixed_units_portfolio_fails_closed_on_insufficient_capital() -> None:
    cfg = PortfolioConfig(starting_capital=1_000.0, position_size=11.0)
    with pytest.raises(ValueError, match="insufficient capital"):
        PortfolioEngine(cfg).run(_bars(), _BuyThenExit(), EngineConfig(fee_rate=0.001, slippage_pct=0.0))


def test_fixed_dollar_portfolio_fails_closed_on_insufficient_capital() -> None:
    cfg = PortfolioConfig(
        starting_capital=1_000.0,
        sizing_mode=SizingMode.FIXED_DOLLAR,
        trade_capital=1_001.0,
    )
    with pytest.raises(ValueError, match="insufficient capital"):
        PortfolioEngine(cfg).run(_bars(), _BuyThenExit(), EngineConfig(fee_rate=0.001, slippage_pct=0.0))


def test_equity_is_conserved_after_a_funded_trade() -> None:
    cfg = PortfolioConfig(starting_capital=1_000.0, position_size=5.0)
    result = PortfolioEngine(cfg).run(
        _bars(), _BuyThenExit(), EngineConfig(fee_rate=0.001, slippage_pct=0.0)
    )
    trade = result.trades[0]
    assert trade.entry_price * trade.size + trade.entry_fee <= cfg.starting_capital
    assert result.ending_equity == pytest.approx(cfg.starting_capital + trade.net_pnl)
    assert result.net_profit == pytest.approx(trade.net_pnl)
