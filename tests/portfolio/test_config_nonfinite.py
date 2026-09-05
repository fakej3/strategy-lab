"""Adversarial validation tests for portfolio and engine configuration."""
from __future__ import annotations

import math

import pytest

from engine.models import EngineConfig
from portfolio.models import PortfolioConfig


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_portfolio_rejects_nonfinite_starting_capital(value):
    with pytest.raises(ValueError):
        PortfolioConfig(starting_capital=value)


@pytest.mark.parametrize("field", ["position_size", "equity_fraction", "trade_capital", "fraction"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_portfolio_rejects_nonfinite_sizing_parameters(field, value):
    with pytest.raises(ValueError):
        PortfolioConfig(**{field: value})


@pytest.mark.parametrize("field", ["position_size", "fee_rate", "slippage_pct"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_engine_rejects_nonfinite_parameters(field, value):
    with pytest.raises(ValueError):
        EngineConfig(**{field: value})


@pytest.mark.parametrize("field", ["stop_loss_pct", "take_profit_pct"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_engine_rejects_nonfinite_optional_levels(field, value):
    with pytest.raises(ValueError):
        EngineConfig(**{field: value})
