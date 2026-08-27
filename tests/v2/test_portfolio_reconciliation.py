"""Golden tests for V2 portfolio-to-ledger reconciliation."""

from dataclasses import replace

import pytest

from engine.models import BacktestTrade, ExitReason
from portfolio.v2_reconciliation import reconcile_trades


def trade(number, net=10.0, gross=12.0, entry_fee=1.0, exit_fee=1.0):
    return BacktestTrade(
        trade_number=number,
        direction="Long",
        entry_time=__import__("datetime").datetime(2026, 1, 1),
        exit_time=__import__("datetime").datetime(2026, 1, 2),
        entry_bar=1,
        exit_bar=2,
        entry_price=100.0,
        exit_price=112.0,
        size=1.0,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        entry_slippage=0.0,
        exit_slippage=0.0,
        gross_pnl=gross,
        net_pnl=net,
        exit_reason=ExitReason.SIGNAL,
        holding_period=1,
    )


def test_multiple_trades_reconcile_to_ending_equity():
    result = reconcile_trades(
        [trade(1, net=10), trade(2, net=-4), trade(3, net=6)],
        starting_equity=1000,
    )
    assert result.realized_net_pnl == pytest.approx(12)
    assert result.ending_equity == pytest.approx(1012)


def test_negative_pnl_is_preserved():
    result = reconcile_trades([trade(1, net=-25, gross=-23, entry_fee=1, exit_fee=1)], 1000)
    assert result.realized_net_pnl == pytest.approx(-25)
    assert result.ending_equity == pytest.approx(975)


def test_invalid_trade_ledger_is_rejected():
    bad = trade(1, net=10, gross=12, entry_fee=1, exit_fee=1)
    bad = replace(bad, net_pnl=11)
    with pytest.raises(ValueError, match="ledger invariant"):
        reconcile_trades([bad], 1000)


def test_invalid_starting_equity_is_rejected():
    with pytest.raises(ValueError):
        reconcile_trades([], -1)
