"""Strict V2 cash/equity accounting primitives.

The goal is to make cash, realized P&L, unrealized P&L and equity explicit.
This module is intentionally independent of the legacy portfolio engine so
its invariants can be tested before integration.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class V2AccountState:
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    equity: float


def mark_to_market(cash: float, realized_pnl: float, unrealized_pnl: float) -> V2AccountState:
    """Return an account state satisfying equity = cash + unrealized P&L.

    ``realized_pnl`` is retained as an audit field; it should already be
    reflected in cash by the caller. Keeping it separate prevents accidentally
    adding realized P&L twice when constructing an equity curve.
    """
    values = (cash, realized_pnl, unrealized_pnl)
    if not all(map(lambda x: isinstance(x, (int, float)) and x == x and abs(x) != float("inf"), values)):
        raise ValueError("account values must be finite numbers")
    return V2AccountState(
        cash=float(cash),
        realized_pnl=float(realized_pnl),
        unrealized_pnl=float(unrealized_pnl),
        equity=float(cash + unrealized_pnl),
    )


def assert_equity_identity(state: V2AccountState, tolerance: float = 1e-9) -> None:
    """Fail if the stored equity is inconsistent with cash + unrealized P&L."""
    expected = state.cash + state.unrealized_pnl
    if abs(state.equity - expected) > tolerance * max(1.0, abs(expected)):
        raise ValueError("equity identity violated")
