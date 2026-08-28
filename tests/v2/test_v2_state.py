"""Independent accounting invariants for the V2 transaction state model."""

import pytest

from portfolio.v2_state import V2LedgerState, equity, open_position, close_position, unrealized_pnl


def initial():
    return V2LedgerState(cash=1000.0, position=None, realized_pnl=0.0, fees_paid=0.0)


def test_long_round_trip_preserves_capital_minus_fees():
    s = open_position(initial(), direction="long", units=2, fill_price=100, fee=1)
    assert s.cash == pytest.approx(799)
    assert equity(s, 100) == pytest.approx(999)
    s = close_position(s, fill_price=110, fee=1)
    assert s.position is None
    assert s.cash == pytest.approx(1018)
    assert s.realized_pnl == pytest.approx(20)
    assert s.fees_paid == pytest.approx(2)


def test_short_round_trip_has_correct_sign():
    s = open_position(initial(), direction="short", units=2, fill_price=100, fee=1)
    assert equity(s, 100) == pytest.approx(999)
    assert equity(s, 90) == pytest.approx(1019)
    s = close_position(s, fill_price=90, fee=1)
    assert s.position is None
    assert s.cash == pytest.approx(1018)
    assert s.realized_pnl == pytest.approx(20)


def test_open_position_mark_to_market_changes_equity_not_cash():
    s = open_position(initial(), direction="long", units=2, fill_price=100, fee=1)
    assert s.cash == pytest.approx(799)
    assert unrealized_pnl(s, 105) == pytest.approx(10)
    assert equity(s, 105) == pytest.approx(1009)


def test_invalid_second_open_and_close_without_position_fail():
    s = open_position(initial(), direction="long", units=1, fill_price=100, fee=0)
    with pytest.raises(ValueError):
        open_position(s, direction="long", units=1, fill_price=100, fee=0)
    with pytest.raises(ValueError):
        close_position(initial(), fill_price=100, fee=0)
