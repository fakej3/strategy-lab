"""Institutional-quality performance metrics — no scipy dependency."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class InstitutionalMetrics:
    cagr: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    information_ratio: float
    kelly_fraction: float
    recovery_factor: float
    payoff_ratio: float
    profit_factor: float
    win_rate: float
    avg_trade_pnl: float
    avg_holding_period: float
    avg_r_multiple: float
    total_trades: int
    skewness: float
    kurtosis: float
    downside_volatility: float
    avg_drawdown: float
    max_drawdown_pct: float
    bars_per_year: int


def calculate_research_metrics(equity_curve: pd.Series, trades: Sequence,
                               bars_per_year: int = 252,
                               risk_free_rate: float = 0.0,
                               benchmark_returns: pd.Series | None = None) -> InstitutionalMetrics:
    """Calculate research metrics using explicit, testable conventions.

    Returns are simple per-bar equity returns. Sharpe/Sortino use arithmetic
    excess return annualisation. Sortino uses downside semideviation over all
    observations relative to the per-bar risk-free rate. CAGR is suppressed
    for periods shorter than one year.
    """
    if not isinstance(bars_per_year, int) or isinstance(bars_per_year, bool) or bars_per_year <= 0:
        raise ValueError("bars_per_year must be a positive integer")
    if not math.isfinite(risk_free_rate) or risk_free_rate <= -1:
        raise ValueError("risk_free_rate must be finite and > -1")
    if equity_curve is None or len(equity_curve) < 1:
        raise ValueError("equity_curve must contain at least one observation")
    eq = pd.Series(equity_curve, dtype=float)
    if not np.isfinite(eq.to_numpy()).all():
        raise ValueError("equity_curve must contain only finite values")
    if (eq <= 0).any():
        raise ValueError("equity_curve values must be > 0")

    rf_per_bar = (1.0 + risk_free_rate) ** (1.0 / bars_per_year) - 1.0
    returns = eq.pct_change().dropna()
    finite_returns = returns[np.isfinite(returns)]
    starting, ending = float(eq.iloc[0]), float(eq.iloc[-1])
    n_years = (len(eq) - 1) / bars_per_year
    cagr = (ending / starting) ** (1.0 / n_years) - 1.0 if n_years >= 1.0 else math.nan

    excess = finite_returns - rf_per_bar
    ann_vol = float(finite_returns.std(ddof=1)) * math.sqrt(bars_per_year) if len(finite_returns) >= 2 else 0.0
    mean_excess = float(excess.mean()) if len(excess) else 0.0
    sharpe = mean_excess * bars_per_year / ann_vol if ann_vol > 0 else 0.0

    neg_sq = np.minimum(finite_returns.to_numpy() - rf_per_bar, 0.0) ** 2
    downside_vol_bar = math.sqrt(float(neg_sq.mean())) if len(neg_sq) else 0.0
    ann_downside_vol = downside_vol_bar * math.sqrt(bars_per_year)
    sortino = mean_excess * bars_per_year / ann_downside_vol if ann_downside_vol > 0 else (math.inf if mean_excess > 0 else 0.0)

    rolling_peak = eq.cummax()
    dd_curve = (eq - rolling_peak) / rolling_peak
    max_dd_pct = float(-dd_curve.min())
    neg_dd = dd_curve[dd_curve < 0]
    avg_dd = float(-neg_dd.mean()) if len(neg_dd) else 0.0
    if max_dd_pct > 0 and not math.isnan(cagr):
        trough_idx = dd_curve.idxmin()
        local_peak = float(rolling_peak.loc[trough_idx])
        max_dd_abs = max_dd_pct * local_peak
        calmar = cagr / max_dd_pct
        recovery = (ending - starting) / max_dd_abs if max_dd_abs > 0 else 0.0
    else:
        calmar, recovery = math.nan, 0.0

    if benchmark_returns is not None:
        bm = pd.Series(benchmark_returns, dtype=float)
        aligned_ret, aligned_bm = returns.align(bm, join="inner")
        active = (aligned_ret - aligned_bm).dropna()
        te = float(active.std(ddof=1)) if len(active) >= 2 else 0.0
        ir = float(active.mean() * math.sqrt(bars_per_year) / te) if te > 0 else 0.0
    else:
        ir = 0.0

    trade_list = list(trades)
    total = len(trade_list)
    if total == 0:
        return InstitutionalMetrics(cagr, sharpe, sortino, calmar, ir, 0.0, recovery, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0,
                                    _skewness(returns), _kurtosis(returns), ann_downside_vol, avg_dd, max_dd_pct, bars_per_year)

    pnls = [float(t.net_pnl) for t in trade_list]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    win_rate = len(winners) / total
    avg_trade = float(np.mean(pnls))
    avg_holding = float(np.mean([t.holding_period for t in trade_list]))
    avg_win = float(np.mean(winners)) if winners else 0.0
    avg_loss = float(np.mean(np.abs(losers))) if losers else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else (math.inf if avg_win > 0 else 0.0)
    gross_profit, gross_loss = sum(winners), sum(abs(x) for x in losers)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    kelly = win_rate - (1.0 - win_rate) / payoff if payoff not in (0.0, math.inf) else (win_rate if payoff == math.inf else 0.0)
    kelly = min(kelly, 1.0)
    r_values = []
    for t in trade_list:
        risk = getattr(t, "risk_per_trade", None)
        if risk is not None and math.isfinite(float(risk)) and float(risk) > 0:
            r_values.append(float(t.net_pnl) / float(risk))
    avg_r = float(np.mean(r_values)) if r_values else 0.0

    return InstitutionalMetrics(cagr, sharpe, sortino, calmar, ir, kelly, recovery, payoff, profit_factor, win_rate,
                                avg_trade, avg_holding, avg_r, total, _skewness(returns), _kurtosis(returns),
                                ann_downside_vol, avg_dd, max_dd_pct, bars_per_year)


def _skewness(returns: pd.Series) -> float:
    arr = returns.to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 3:
        return 0.0
    std = arr.std(ddof=1)
    return float(((arr - arr.mean()) ** 3).mean() / std ** 3) if std > 0 else 0.0


def _kurtosis(returns: pd.Series) -> float:
    arr = returns.to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 4:
        return 0.0
    std = arr.std(ddof=1)
    return float(((arr - arr.mean()) ** 4).mean() / std ** 4 - 3.0) if std > 0 else 0.0
