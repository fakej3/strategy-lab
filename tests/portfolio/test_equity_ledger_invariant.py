from __future__ import annotations

import pandas as pd
import pytest

from portfolio.engine import build_equity_curve
from portfolio.models import PortfolioTrade


def _trade() -> PortfolioTrade:
    entry_price = 100.0
    exit_price = 110.0
    size = 2.0
    entry_fee = 1.0
    exit_fee = 1.1
    gross_pnl = (exit_price - entry_price) * size
    return PortfolioTrade(
        trade_number=1,
        direction="long",
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


def _independent_ledger(
    closes: list[float], trade: PortfolioTrade, starting_capital: float
) -> list[float]:
    """Reference accounting model, intentionally independent of production code."""
    out: list[float] = []
    cash = starting_capital
    for i, mark in enumerate(closes):
        if i == trade.entry_bar:
            cash -= trade.entry_price * trade.size + trade.entry_fee
        if trade.entry_bar <= i < trade.exit_bar:
            position_value = mark * trade.size
        elif i >= trade.exit_bar:
            position_value = 0.0
        else:
            position_value = 0.0
        if i == trade.exit_bar:
            cash += trade.exit_price * trade.size - trade.exit_fee
        out.append(cash + position_value)
    return out


def test_equity_curve_matches_independent_cash_plus_marked_position_ledger():
    bars = pd.DataFrame({"close": [100.0, 100.0, 105.0, 110.0, 110.0]})
    trade = _trade()

    actual = build_equity_curve(bars, [trade], 1000.0)
    expected = _independent_ledger(bars["close"].tolist(), trade, 1000.0)

    assert actual.tolist() == pytest.approx(expected)


def test_equity_is_not_double_charged_for_fees():
    bars = pd.DataFrame({"close": [100.0, 100.0, 100.0, 110.0]})
    trade = _trade()
    curve = build_equity_curve(bars, [trade], 1000.0)

    expected_final = 1000.0 + trade.gross_pnl - trade.entry_fee - trade.exit_fee
    assert curve.iloc[-1] == pytest.approx(expected_final)


def test_flat_equity_has_zero_marked_position_value():
    bars = pd.DataFrame({"close": [50.0, 51.0, 52.0]})
    curve = build_equity_curve(bars, [], 750.0)
    assert curve.tolist() == pytest.approx([750.0, 750.0, 750.0])
