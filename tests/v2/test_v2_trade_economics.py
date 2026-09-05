"""Independent trade-economics golden tests."""

import pytest

from portfolio.v2_trade_economics import calculate_trade_economics


def test_long_pnl_and_fees():
    x = calculate_trade_economics(direction="long", entry_price=100, exit_price=110, size=2, fee_rate=0.001)
    assert x.gross_pnl == pytest.approx(20)
    assert x.entry_fee == pytest.approx(0.2)
    assert x.exit_fee == pytest.approx(0.22)
    assert x.net_pnl == pytest.approx(19.58)


def test_short_pnl_is_directionally_correct():
    x = calculate_trade_economics(direction="short", entry_price=110, exit_price=100, size=2, fee_rate=0.001)
    assert x.gross_pnl == pytest.approx(20)
    assert x.net_pnl == pytest.approx(19.58)


def test_loss_remains_a_loss_after_fees():
    x = calculate_trade_economics(direction="long", entry_price=100, exit_price=90, size=2, fee_rate=0.001)
    assert x.gross_pnl == pytest.approx(-20)
    assert x.net_pnl == pytest.approx(-20.38)


def test_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        calculate_trade_economics(direction="long", entry_price=0, exit_price=100, size=1, fee_rate=0.001)
    with pytest.raises(ValueError):
        calculate_trade_economics(direction="long", entry_price=100, exit_price=100, size=1, fee_rate=-0.1)
