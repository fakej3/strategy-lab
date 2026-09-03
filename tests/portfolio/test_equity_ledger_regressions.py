"""Regression tests for portfolio ledger/equity reconciliation."""
from __future__ import annotations

import pandas as pd
import pytest

from portfolio.engine import build_balance_curve, build_equity_curve
from portfolio.models import PortfolioTrade


def _bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=idx,
    )


def _trade(
    *,
    direction: str,
    entry_bar: int,
    exit_bar: int,
    entry_price: float,
    exit_price: float,
    size: float,
    entry_fee: float,
    exit_fee: float,
) -> PortfolioTrade:
    sign = 1.0 if direction == "long" else -1.0
    gross = (exit_price - entry_price) * size * sign
    return PortfolioTrade(
        trade_number=1,
        direction=direction,
        entry_time=pd.Timestamp("2024-01-01", tz="UTC"),
        exit_time=pd.Timestamp("2024-01-01", tz="UTC"),
        entry_bar=entry_bar,
        exit_bar=exit_bar,
        entry_price=entry_price,
        exit_price=exit_price,
        size=size,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage=0.0,
        exit_slippage=0.0,
        gross_pnl=gross,
        net_pnl=gross - entry_fee - exit_fee,
        exit_reason=None,
        holding_period=exit_bar - entry_bar,
        portfolio_equity_at_entry=10_000.0,
    )


def test_long_equity_curve_reconciles_entry_fee_unrealized_and_exit_pnl():
    """Mark-to-market equity must reconcile exactly to the trade ledger."""
    bars = _bars([100.0, 100.0, 110.0, 120.0, 120.0])
    trade = _trade(
        direction="long",
        entry_bar=1,
        exit_bar=3,
        entry_price=100.0,
        exit_price=120.0,
        size=10.0,
        entry_fee=100.0,
        exit_fee=120.0,
    )

    equity = build_equity_curve(bars, [trade], 10_000.0)
    balance = build_balance_curve(bars, [trade], 10_000.0)

    assert equity.tolist() == pytest.approx([10_000.0, 9_900.0, 10_000.0, 9_980.0, 9_980.0])
    assert balance.tolist() == pytest.approx([10_000.0, 10_000.0, 10_000.0, 9_980.0, 9_980.0])
    assert equity.iloc[-1] == pytest.approx(10_000.0 + trade.net_pnl)


def test_short_equity_curve_reconciles_direction_and_fees():
    """Short MTM equity must increase as the marked close falls."""
    bars = _bars([100.0, 100.0, 90.0, 80.0, 80.0])
    trade = _trade(
        direction="short",
        entry_bar=1,
        exit_bar=3,
        entry_price=100.0,
        exit_price=80.0,
        size=10.0,
        entry_fee=100.0,
        exit_fee=80.0,
    )

    equity = build_equity_curve(bars, [trade], 10_000.0)
    balance = build_balance_curve(bars, [trade], 10_000.0)

    assert equity.tolist() == pytest.approx([10_000.0, 9_900.0, 9_990.0, 10_020.0, 10_020.0])
    assert balance.tolist() == pytest.approx([10_000.0, 10_000.0, 10_000.0, 10_020.0, 10_020.0])
    assert equity.iloc[-1] == pytest.approx(10_000.0 + trade.net_pnl)


def test_trade_ledger_net_pnl_reconciles_to_ending_equity():
    """The portfolio result identity is ending equity = capital + sum(net PnL)."""
    bars = _bars([100.0, 100.0, 110.0, 110.0, 110.0, 110.0])
    first = _trade(
        direction="long",
        entry_bar=1,
        exit_bar=2,
        entry_price=100.0,
        exit_price=110.0,
        size=10.0,
        entry_fee=10.0,
        exit_fee=11.0,
    )
    second = _trade(
        direction="long",
        entry_bar=3,
        exit_bar=4,
        entry_price=110.0,
        exit_price=110.0,
        size=10.0,
        entry_fee=11.0,
        exit_fee=11.0,
    )
    second = PortfolioTrade(**{**second.__dict__, "trade_number": 2, "portfolio_equity_at_entry": 10_079.0})

    trades = [first, second]
    equity = build_equity_curve(bars, trades, 10_000.0)
    balance = build_balance_curve(bars, trades, 10_000.0)

    expected_ending = 10_000.0 + sum(t.net_pnl for t in trades)
    assert equity.iloc[-1] == pytest.approx(expected_ending)
    assert balance.iloc[-1] == pytest.approx(expected_ending)
