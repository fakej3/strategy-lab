from __future__ import annotations

import pandas as pd
import pytest

from portfolio.engine import build_equity_curve
from portfolio.models import PortfolioTrade


def _short_trade() -> PortfolioTrade:
    entry_price = 100.0
    exit_price = 90.0
    size = 2.0
    entry_fee = 1.0
    exit_fee = 0.9
    gross_pnl = (entry_price - exit_price) * size
    return PortfolioTrade(
        trade_number=1,
        direction="Short",
        entry_time=pd.Timestamp("2026-01-02", tz="UTC"),
        exit_time=pd.Timestamp("2026-01-04", tz="UTC"),
        entry_bar=1,
        exit_bar=3,
        entry_price=entry_price,
        exit_price=exit_price,
        size=size,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage=0.0,
        exit_slippage=0.0,
        gross_pnl=gross_pnl,
        net_pnl=gross_pnl - entry_fee - exit_fee,
        exit_reason="signal",
        holding_period=2,
        portfolio_equity_at_entry=1000.0,
    )


def test_short_equity_rises_when_mark_price_falls() -> None:
    bars = pd.DataFrame({"close": [100.0, 100.0, 95.0, 90.0, 90.0]})
    trade = _short_trade()

    actual = build_equity_curve(bars, [trade], 1000.0)

    # At entry: cash = 1000 + 200 proceeds - 1 fee; liability = 200.
    # During the short, equity = 999 + (100 - mark) * 2.
    assert actual.iloc[1] == pytest.approx(999.0)
    assert actual.iloc[2] == pytest.approx(1009.0)
    assert actual.iloc[3] == pytest.approx(1017.1)
    assert actual.iloc[-1] == pytest.approx(1017.1)


def test_unknown_trade_direction_fails_closed() -> None:
    bars = pd.DataFrame({"close": [100.0, 100.0, 100.0]})
    trade = _short_trade()
    object.__setattr__(trade, "direction", "mystery")

    with pytest.raises(ValueError, match="unsupported trade direction"):
        build_equity_curve(bars, [trade], 1000.0)
