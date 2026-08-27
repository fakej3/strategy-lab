"""Golden invariants for V2 account state."""

import pytest

from portfolio.v2_accounting import assert_equity_identity, mark_to_market


def test_equity_is_cash_plus_unrealized_pnl():
    state = mark_to_market(950.0, 50.0, 25.0)
    assert state.equity == pytest.approx(975.0)
    assert_equity_identity(state)


def test_realized_pnl_is_not_added_twice():
    state = mark_to_market(1100.0, 100.0, -25.0)
    assert state.equity == pytest.approx(1075.0)


def test_non_finite_account_values_fail_closed():
    with pytest.raises(ValueError):
        mark_to_market(float("nan"), 0.0, 0.0)
    with pytest.raises(ValueError):
        mark_to_market(1000.0, 0.0, float("inf"))
