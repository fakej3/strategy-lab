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


@pytest.mark.parametrize("value", [1.0, 1.000001, 2.0])
def test_fee_rate_must_be_strictly_below_one(value):
    """A >=100% proportional fee can drive funded cash-only equity negative."""
    with pytest.raises(ValueError, match="fee_rate"):
        EngineConfig(fee_rate=value)


@pytest.mark.parametrize("field", ["position_size", "fee_rate"])
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_scalar_execution_parameters_reject_non_finite_values(field, value):
    """NaN/Inf must never enter the execution kernel through config."""
    with pytest.raises(ValueError, match=field):
        EngineConfig(**{field: value})


@pytest.mark.parametrize("field", ["stop_loss_pct", "take_profit_pct"])
@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_optional_execution_parameters_reject_non_finite_values(field, value):
    """Optional risk controls must fail closed rather than propagate NaN/Inf."""
    with pytest.raises(ValueError, match=field):
        EngineConfig(**{field: value})


def test_zero_slippage_remains_valid():
    cfg = EngineConfig(slippage_pct=0.0)
    assert cfg.slippage_pct == 0.0
