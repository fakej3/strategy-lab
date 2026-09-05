"""Canonical transaction-to-account state transition for Strategy Labs V2.

Equity is defined from cash plus the marked position value. Long positions
contribute positive market value; short positions contribute a negative
liability. Unrealized P&L is reported separately and must not be added to cash
as a second representation of the position's value.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class V2Position:
    direction: str
    units: float
    entry_price: float


@dataclass(frozen=True)
class V2LedgerState:
    cash: float
    position: V2Position | None
    realized_pnl: float
    fees_paid: float

    @property
    def gross_exposure(self) -> float:
        if self.position is None:
            return 0.0
        return abs(self.position.units * self.position.entry_price)


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(v)) for v in values)


def open_position(state: V2LedgerState, *, direction: str, units: float, fill_price: float, fee: float) -> V2LedgerState:
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    if not _finite(state.cash, state.realized_pnl, state.fees_paid, units, fill_price, fee):
        raise ValueError("state and fill values must be finite")
    if units <= 0 or fill_price <= 0 or fee < 0 or state.position is not None:
        raise ValueError("invalid opening transaction")
    signed_cash_flow = -units * fill_price if direction == "long" else units * fill_price
    return V2LedgerState(
        cash=state.cash + signed_cash_flow - fee,
        position=V2Position(direction, units, fill_price),
        realized_pnl=state.realized_pnl,
        fees_paid=state.fees_paid + fee,
    )


def close_position(state: V2LedgerState, *, fill_price: float, fee: float) -> V2LedgerState:
    if state.position is None:
        raise ValueError("no open position")
    if not _finite(state.cash, state.realized_pnl, state.fees_paid, fill_price, fee):
        raise ValueError("state and fill values must be finite")
    if fill_price <= 0 or fee < 0:
        raise ValueError("invalid closing transaction")
    p = state.position
    direction = 1.0 if p.direction == "long" else -1.0
    gross = (fill_price - p.entry_price) * p.units * direction
    principal = p.entry_price * p.units
    cash_change = principal + gross if p.direction == "long" else -principal + gross
    return V2LedgerState(
        cash=state.cash + cash_change - fee,
        position=None,
        realized_pnl=state.realized_pnl + gross,
        fees_paid=state.fees_paid + fee,
    )


def unrealized_pnl(state: V2LedgerState, mark_price: float) -> float:
    if not _finite(mark_price) or mark_price <= 0:
        raise ValueError("mark_price must be positive and finite")
    if state.position is None:
        return 0.0
    p = state.position
    direction = 1.0 if p.direction == "long" else -1.0
    return (mark_price - p.entry_price) * p.units * direction


def position_market_value(state: V2LedgerState, mark_price: float) -> float:
    if not _finite(mark_price) or mark_price <= 0:
        raise ValueError("mark_price must be positive and finite")
    if state.position is None:
        return 0.0
    p = state.position
    signed_units = p.units if p.direction == "long" else -p.units
    return signed_units * mark_price


def equity(state: V2LedgerState, mark_price: float) -> float:
    """Mark-to-market equity: cash plus signed market value of the position."""
    return state.cash + position_market_value(state, mark_price)
