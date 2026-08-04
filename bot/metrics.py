"""Performance metrics for the paper trading bot.

Delegates to ``research.metrics.calculate_research_metrics`` where possible
so the bot and backtester produce comparable statistics.  Falls back to simple
calculations when the Research Lab is unavailable or the trade list is too short.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

log = logging.getLogger("strategy_lab.bot.metrics")


@dataclass
class BotMetrics:
    """Snapshot of bot performance metrics."""

    n_trades:      int
    n_winners:     int
    n_losers:      int
    win_rate:      float | None   # 0.0 – 1.0
    profit_factor: float | None   # gross_profit / abs(gross_loss)
    net_pnl:       float
    gross_profit:  float
    gross_loss:    float          # negative or zero
    max_drawdown:  float          # fraction (0.0 → 1.0)
    sharpe:        float | None
    sortino:       float | None
    calmar:        float | None
    total_fees:    float
    avg_trade_pnl: float | None


def compute_metrics(
    equity_curve: list[float],
    trades: list[dict],            # from position manager (closed positions)
    bars_per_year: float = 8760.0, # for hourly bars
) -> BotMetrics:
    """Compute full performance metrics from equity curve and trade list.

    Tries to delegate to Research Lab for CAGR/Sharpe/Sortino/Calmar.
    Falls back gracefully if the curve is too short.

    Args:
        equity_curve: List of equity values (chronological).
        trades: List of closed position dicts with ``realized_pnl``.
        bars_per_year: Annualisation factor (8760 for 1h, 365 for 1d).
    """
    # Basic trade stats
    n_trades = len(trades)
    pnls = [t.get("realized_pnl", 0.0) for t in trades]
    winners = [p for p in pnls if p > 0]
    losers  = [p for p in pnls if p <= 0]

    n_winners = len(winners)
    n_losers  = len(losers)
    gross_profit = sum(winners)
    gross_loss   = sum(losers)
    net_pnl      = gross_profit + gross_loss

    win_rate = n_winners / n_trades if n_trades > 0 else None
    loss_abs = abs(gross_loss)
    profit_factor = gross_profit / loss_abs if loss_abs > 0 else None
    avg_trade_pnl = net_pnl / n_trades if n_trades > 0 else None
    total_fees    = sum(
        (t.get("entry_fee", 0.0) or 0.0) + (t.get("exit_fee", 0.0) or 0.0)
        for t in trades
    )

    # Drawdown from equity curve
    max_dd = _max_drawdown(equity_curve)

    # Sharpe / Sortino from returns
    sharpe  = None
    sortino = None
    calmar  = None

    if len(equity_curve) >= 30:
        try:
            from research.metrics import calculate_research_metrics
            # Build minimal pandas Series for the lab function
            eq = pd.Series(equity_curve)
            # Build minimal trade list compatible with the research layer
            lab_trades = _to_lab_trades(trades)
            stats = calculate_research_metrics(eq, lab_trades, bars_per_year)
            sharpe  = stats.get("sharpe_ratio")
            sortino = stats.get("sortino_ratio")
            calmar  = stats.get("calmar_ratio")
        except Exception as exc:
            log.debug("Research metrics unavailable: %s", exc)
            sharpe, sortino, calmar = _simple_ratios(equity_curve, bars_per_year, max_dd)
    elif len(equity_curve) >= 5:
        sharpe, sortino, calmar = _simple_ratios(equity_curve, bars_per_year, max_dd)

    return BotMetrics(
        n_trades=n_trades,
        n_winners=n_winners,
        n_losers=n_losers,
        win_rate=win_rate,
        profit_factor=profit_factor,
        net_pnl=net_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        max_drawdown=max_dd,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        total_fees=total_fees,
        avg_trade_pnl=avg_trade_pnl,
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _max_drawdown(equity: list[float]) -> float:
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _simple_ratios(
    equity: list[float],
    bars_per_year: float,
    max_dd: float,
) -> tuple[float | None, float | None, float | None]:
    """Simplified Sharpe / Sortino / Calmar when Research Lab unavailable."""
    if len(equity) < 5:
        return None, None, None

    returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]
    if not returns:
        return None, None, None

    n = len(returns)
    mean_r = sum(returns) / n
    var = sum((r - mean_r) ** 2 for r in returns) / n
    std = math.sqrt(var) if var > 0 else None

    sharpe = None
    if std and std > 0:
        sharpe = (mean_r / std) * math.sqrt(bars_per_year)

    downside_var = sum(min(r, 0) ** 2 for r in returns) / n
    downside_std = math.sqrt(downside_var) if downside_var > 0 else None
    sortino = None
    if downside_std and downside_std > 0:
        sortino = (mean_r / downside_std) * math.sqrt(bars_per_year)

    calmar = None
    if max_dd > 0 and len(equity) >= 2 and equity[0] > 0:
        total_return = (equity[-1] - equity[0]) / equity[0]
        # Annualise: periods / bars_per_year * total_return
        ann_return = total_return * (bars_per_year / len(returns))
        calmar = ann_return / max_dd

    return sharpe, sortino, calmar


def _to_lab_trades(trades: list[dict]) -> list[Any]:
    """Convert position-manager dicts to minimal objects for research layer."""
    from engine.models import BacktestTrade, ExitReason
    import pandas as pd
    result = []
    for i, t in enumerate(trades):
        try:
            result.append(BacktestTrade(
                trade_number=i + 1,
                direction="Long" if t.get("direction") == "long" else "Short",
                entry_time=pd.Timestamp(t.get("opened_at", "2000-01-01")),
                exit_time=pd.Timestamp(t.get("closed_at", "2000-01-01")),
                entry_bar=i,
                exit_bar=i + 1,
                entry_price=t.get("entry_price", 0.0),
                exit_price=t.get("exit_price", 0.0),
                size=t.get("size", 1.0),
                entry_fee=t.get("entry_fee", 0.0),
                exit_fee=t.get("exit_fee", 0.0),
                entry_slippage=0.0,
                exit_slippage=0.0,
                gross_pnl=t.get("realized_pnl", 0.0),
                net_pnl=t.get("realized_pnl", 0.0),
                exit_reason=ExitReason.SIGNAL,
                holding_period=1,
            ))
        except Exception:
            pass
    return result
