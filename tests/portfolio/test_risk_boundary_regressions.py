"""Regression tests for fail-closed execution boundaries."""
from __future__ import annotations

import math

import pytest

from engine.models import EngineConfig


@pytest.mark.parametrize("value", [1.0, 1.000001, 2.0, math.inf, math.nan])
def test_slippage_must_be_finite_and_strictly_below_one(value):
    """A sell fill at >=100% slippage would be zero/negative and is invalid."""
    with pytest.raises(ValueError, match="slippage_pct"):
        EngineConfig(slippage_pct=value)


def test_zero_slippage_remains_valid():
    cfg = EngineConfig(slippage_pct=0.0)
    assert cfg.slippage_pct == 0.0
