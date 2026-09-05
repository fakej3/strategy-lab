"""Portfolio-level reconciliation for Strategy Labs V2.

This module deliberately operates on completed trade records. It is a
reconciliation/audit layer, not a replacement for a full mark-to-market
portfolio engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from engine.models import BacktestTrade


@dataclass(frozen=True)
class Reconciliation:
    starting_equity: float
    realized_net_pnl: float
    ending_equity: float


def reconcile_trades(
    trades: Iterable[BacktestTrade],
    starting_equity: float,
) -> Reconciliation:
    """Reconcile realized trade P&L against starting and ending equity.

    Every trade must satisfy its own ledger equation before its P&L is
    included in the portfolio total.
    """
    if not isfinite(starting_equity) or starting_equity < 0:
        raise ValueError("starting_equity must be finite and >= 0")

    total = 0.0
    for trade in trades:
        expected_net = trade.gross_pnl - trade.entry_fee - trade.exit_fee
        if abs(trade.net_pnl - expected_net) > 1e-9 * max(1.0, abs(expected_net)):
            raise ValueError(
                f"trade {trade.trade_number} violates net P&L ledger invariant"
            )
        total += trade.net_pnl

    ending = starting_equity + total
    return Reconciliation(
        starting_equity=starting_equity,
        realized_net_pnl=total,
        ending_equity=ending,
    )
