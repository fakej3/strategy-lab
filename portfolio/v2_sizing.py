"""Canonical V2 risk-based position sizing.

Risk sizing answers a different question from notional allocation: how many
units can be held so that a stop-out loses at most the configured fraction of
account equity, before fees/slippage unless the caller includes those costs
in stop_loss_distance.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PositionSize:
    units: float
    risk_budget: float
    risk_per_unit: float
    notional: float


def size_for_stop(
    *,
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_fraction: float,
    max_notional_fraction: float | None = None,
) -> PositionSize:
    """Return units sized from account risk and stop distance.

    For both long and short positions, risk per unit is the absolute distance
    between entry and stop. This function does not assume leverage or contract
    multipliers; those must be modeled explicitly by a higher-level adapter.
    """
    vals = (equity, entry_price, stop_price, risk_fraction)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValueError("sizing inputs must be finite")
    if equity <= 0 or entry_price <= 0 or stop_price <= 0:
        raise ValueError("equity and prices must be positive")
    if not (0 < risk_fraction <= 1):
        raise ValueError("risk_fraction must be in (0, 1]")
    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit == 0:
        raise ValueError("entry and stop cannot be identical")

    risk_budget = equity * risk_fraction
    units = risk_budget / risk_per_unit
    if max_notional_fraction is not None:
        if not (0 < max_notional_fraction <= 1):
            raise ValueError("max_notional_fraction must be in (0, 1]")
        max_units = equity * max_notional_fraction / entry_price
        units = min(units, max_units)
    return PositionSize(units=units, risk_budget=risk_budget, risk_per_unit=risk_per_unit, notional=units * entry_price)
