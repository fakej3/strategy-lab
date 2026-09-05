"""Known-answer execution semantics tests."""

import pytest
from engine.v2_execution import next_open, protective_exit


def test_next_open_long_slippage_is_adverse():
    assert next_open(100, 0.001) == pytest.approx(100.1)


def test_stop_gap_uses_open_not_impossible_stop_fill():
    fill = protective_exit(raw_open=90, raw_high=95, raw_low=89, stop=95, target=110, slippage_rate=0)
    assert fill.price == pytest.approx(90)
    assert fill.reason == "stop"


def test_stop_and_target_same_bar_uses_conservative_stop():
    fill = protective_exit(raw_open=100, raw_high=110, raw_low=90, stop=95, target=105, slippage_rate=0)
    assert fill.price == pytest.approx(95)
    assert fill.reason == "stop"


def test_target_inside_bar_uses_target_price():
    fill = protective_exit(raw_open=100, raw_high=110, raw_low=99, stop=95, target=105, slippage_rate=0.001)
    assert fill.price == pytest.approx(105 * 0.999)
    assert fill.reason == "target"
