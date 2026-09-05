"""Regression tests for portfolio configuration integrity."""
from __future__ import annotations

import pytest

from portfolio.models import PortfolioConfig, SizingMode


def test_invalid_sizing_mode_fails_closed() -> None:
    """An unknown mode must not silently become FIXED_UNITS."""
    with pytest.raises(ValueError, match="sizing_mode"):
        PortfolioConfig(sizing_mode="not_a_real_mode")


def test_string_sizing_mode_is_normalized_to_enum() -> None:
    """Serialized configuration values may use the enum's string value."""
    cfg = PortfolioConfig(sizing_mode="pct_of_equity")
    assert cfg.sizing_mode is SizingMode.PCT_OF_EQUITY
