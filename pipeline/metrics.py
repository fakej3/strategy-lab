"""
Core metric calculations for closed trade lists.

All calculations are self-contained and operate on a list of Trade objects.
No external dependencies — standard library only.
"""
from __future__ import annotations

import math
from typing import Optional

from .models import Metrics, ParseError, Trade


def calculate_metrics(trades: list[Trade], profit_unit: str) -> Metrics:
    """
    Calculate the full set of performance metrics from a list of closed trades.

    Args:
        trades:      List of completed Trade objects (entry + exit pairs).
        profit_unit: '%' or '$', used only for labelling in the output.

    Returns:
        A fully populated Metrics instance.

    Raises:
        ParseError: if the trades list is empty.
    """
    if not trades:
        raise ParseError("Cannot calculate metrics: no trades provided.")

    profits = [t.profit for t in trades]

    winning = [p for p in profits if p > 0]
    losing  = [p for p in profits if p < 0]

    total_trades     = len(profits)
    winning_trades   = len(winning)
    losing_trades    = len(losing)
    breakeven_trades = total_trades - winning_trades - losing_trades

    gross_profit = sum(winning)
    gross_loss   = abs(sum(losing))  # stored as positive
    net_profit   = gross_profit - gross_loss

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

    win_rate  = winning_trades / total_trades
    loss_rate = 1.0 - win_rate

    avg_win  = gross_profit / winning_trades if winning_trades > 0 else 0.0
    avg_loss = gross_loss   / losing_trades  if losing_trades  > 0 else 0.0

    risk_reward = avg_win / avg_loss if avg_loss > 0 else math.inf

    largest_win  = max(winning, default=0.0)
    largest_loss = abs(min(losing, default=0.0))

    max_consecutive_wins, max_consecutive_losses = _consecutive_streaks(profits)

    avg_trade  = net_profit / total_trades
    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

    max_drawdown = _calculate_max_drawdown(profits)

    return_over_max_drawdown = (
        net_profit / max_drawdown if max_drawdown > 0 else math.inf
    )

    return Metrics(
        total_trades              = total_trades,
        winning_trades            = winning_trades,
        losing_trades             = losing_trades,
        breakeven_trades          = breakeven_trades,
        profit_unit               = profit_unit,
        net_profit                = net_profit,
        gross_profit              = gross_profit,
        gross_loss                = gross_loss,
        profit_factor             = profit_factor,
        win_rate                  = win_rate,
        avg_win                   = avg_win,
        avg_loss                  = avg_loss,
        risk_reward               = risk_reward,
        largest_win               = largest_win,
        largest_loss              = largest_loss,
        max_consecutive_wins      = max_consecutive_wins,
        max_consecutive_losses    = max_consecutive_losses,
        avg_trade                 = avg_trade,
        expectancy                = expectancy,
        max_drawdown              = max_drawdown,
        return_over_max_drawdown  = return_over_max_drawdown,
    )


# ── Internal helpers ───────────────────────────────────────────────────────────

def _consecutive_streaks(profits: list[float]) -> tuple[int, int]:
    """Return (max_consecutive_wins, max_consecutive_losses)."""
    max_wins = max_losses = 0
    cur_wins = cur_losses = 0

    for p in profits:
        if p > 0:
            cur_wins  += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins   = 0
        else:
            cur_wins   = 0
            cur_losses = 0

        max_wins   = max(max_wins,   cur_wins)
        max_losses = max(max_losses, cur_losses)

    return max_wins, max_losses


def _calculate_max_drawdown(profits: list[float]) -> float:
    """
    Calculate the maximum drawdown magnitude from the equity curve.

    Builds a cumulative profit series starting from 0, tracks the running
    peak, and returns the largest peak-to-trough decline observed.
    The result is in the same unit as the input profits (% or $).
    """
    if not profits:
        return 0.0

    peak        = 0.0
    max_dd      = 0.0
    cumulative  = 0.0

    for p in profits:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd
