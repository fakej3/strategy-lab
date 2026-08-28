"""Independent tests for canonical risk-based sizing."""

import pytest
from portfolio.v2_sizing import size_for_stop


def test_long_and_short_use_same_absolute_stop_risk():
    long_s = size_for_stop(equity=1000, entry_price=100, stop_price=95, risk_fraction=0.01)
    short_s = size_for_stop(equity=1000, entry_price=100, stop_price=105, risk_fraction=0.01)
    assert long_s.units == pytest.approx(2.0)
    assert short_s.units == pytest.approx(2.0)
    assert long_s.risk_budget == pytest.approx(10)


def test_notional_cap_can_reduce_risk_sized_position():
    s = size_for_stop(equity=1000, entry_price=100, stop_price=99, risk_fraction=0.10, max_notional_fraction=0.20)
    assert s.units == pytest.approx(2.0)
    assert s.notional == pytest.approx(200)


def test_zero_stop_distance_fails_closed():
    with pytest.raises(ValueError):
        size_for_stop(equity=1000, entry_price=100, stop_price=100, risk_fraction=0.01)
