"""Auditable V2 performance statistics.

This module keeps annualisation explicit and uses elapsed calendar time for
CAGR. It is intentionally small; advanced statistics belong in separate,
well-specified modules rather than one overloaded metrics function.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class V2Metrics:
    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float


def _validate_equity(equity: pd.Series) -> pd.Series:
    if not isinstance(equity, pd.Series) or len(equity) < 2:
        raise ValueError("equity_curve must be a pandas Series with at least 2 observations")
    if not isinstance(equity.index, pd.DatetimeIndex):
        raise ValueError("equity_curve must use a DatetimeIndex")
    if equity.index.has_duplicates or not equity.index.is_monotonic_increasing:
        raise ValueError("equity_curve timestamps must be unique and increasing")
    out = pd.to_numeric(equity, errors="coerce").astype(float)
    if not np.isfinite(out.to_numpy()).all():
        raise ValueError("equity_curve contains non-finite values")
    if (out <= 0).any():
        raise ValueError("equity_curve values must remain positive for return metrics")
    return out


def calculate_v2_metrics(
    equity_curve: pd.Series,
    trades=(),
    *,
    annualization: float | None = None,
    risk_free_rate: float = 0.0,
) -> V2Metrics:
    """Calculate a conservative core metric set.

    ``annualization`` is required for Sharpe/Sortino because sampling frequency
    cannot safely be inferred from arbitrary timestamps. CAGR instead uses the
    actual elapsed time between the first and last observations.
    """
    equity = _validate_equity(equity_curve)
    if annualization is not None and annualization <= 0:
        raise ValueError("annualization must be positive")
    if risk_free_rate <= -1:
        raise ValueError("risk_free_rate must be greater than -100%")

    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    elapsed_years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.2425 * 86400)
    cagr = (
        float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / elapsed_years) - 1.0)
        if elapsed_years > 0
        else math.nan
    )

    if annualization is None or len(returns) < 2:
        ann_vol = sharpe = sortino = math.nan
    else:
        rf_period = (1.0 + risk_free_rate) ** (1.0 / annualization) - 1.0
        excess = returns - rf_period
        ann_vol = float(returns.std(ddof=1) * math.sqrt(annualization))
        sharpe = float(excess.mean() * annualization / ann_vol) if ann_vol > 0 else math.nan
        downside = np.minimum(excess.to_numpy(), 0.0)
        downside_dev = float(np.sqrt(np.mean(downside ** 2)) * math.sqrt(annualization))
        sortino = float(excess.mean() * annualization / downside_dev) if downside_dev > 0 else math.nan

    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    max_drawdown = float(-drawdown.min())

    trade_list = list(trades)
    pnls = [float(t.net_pnl) for t in trade_list]
    winners = [p for p in pnls if p > 0]
    losers = [-p for p in pnls if p < 0]
    gross_profit = sum(winners)
    gross_loss = sum(losers)

    return V2Metrics(
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        total_trades=len(pnls),
        win_rate=(len(winners) / len(pnls)) if pnls else math.nan,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else math.nan,
        avg_trade_pnl=(float(np.mean(pnls)) if pnls else math.nan),
    )
