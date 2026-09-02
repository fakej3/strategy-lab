"""Regression tests for fail-closed portfolio/execution boundaries."""
from __future__ import annotations

import math

import pytest

from engine.models import EngineConfig
from portfolio.engine import _compute_size
from portfolio.models import SizingMode


@pytest.mark.parametrize("value", [1.0, 1.000001, 2.0, math.inf, math.nan])
def test_slippage_must_be_finite_and_strictly_below_one(value):
    """A sell fill at >=100% slippage would be zero/negative and is invalid."""
    with pytest.raises(ValueError, match="slippage_pct"):
        EngineConfig(slippage_pct=value)


def test_zero_slippage_remains_valid():
    cfg = EngineConfig(slippage_pct=0.0)
    assert cfg.slippage_pct == 0.0


def test_unknown_sizing_mode_fails_closed_in_internal_sizer():
    with pytest.raises(ValueError, match="unsupported sizing mode"):
        _compute_size(
            equity=10_000.0,
            entry_price=100.0,
            sizing_mode="not-a-real-mode",
            equity_fraction=0.1,
            trade_capital=1_000.0,
            fraction=0.25,
        )
