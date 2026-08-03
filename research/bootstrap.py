"""Bootstrap confidence intervals for key strategy performance metrics."""
from __future__ import annotations

from typing import Any

import numpy as np


def bootstrap_confidence_intervals(
    pnls: list[float],
    starting_capital: float = 100_000.0,
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compute bootstrap CIs for key metrics using per-trade PnL list.

    Uses ``np.random.default_rng`` for reproducible, vectorised resampling.
    Returns 5th, 50th, 95th percentiles for each metric.

    Metrics:
      - total_return:  sum(pnls) / starting_capital
      - trade_sharpe:  mean(pnls) / std(pnls)  (trade-level, no annualisation)
      - win_rate:      fraction of positive pnls
      - profit_factor: gross_profit / gross_loss
      - expectancy:    mean(pnls)
      - max_drawdown:  max cumulative drawdown from running equity

    Args:
        pnls:             Per-trade PnL values.
        starting_capital: Starting capital for return calculation.
        n_simulations:    Number of bootstrap samples.
        seed:             RNG seed for full reproducibility.
    """
    if len(pnls) < 3:
        return _empty()

    rng = np.random.default_rng(seed)
    arr = np.array(pnls, dtype=float)
    n   = len(arr)

    # ── Vectorised bootstrap (n_simulations × n_trades matrix) ────────────────
    samples = rng.choice(arr, size=(n_simulations, n), replace=True)

    totals   = samples.sum(axis=1)
    means    = samples.mean(axis=1)
    stds     = samples.std(axis=1, ddof=1)

    returns_arr  = totals / starting_capital
    sharpes_arr  = np.where(stds > 0, means / np.maximum(stds, 1e-300), 0.0)
    win_rates_arr = (samples > 0).mean(axis=1)

    # Profit factor — can't fully vectorise the conditional sums, so loop once
    pf_arr  = np.empty(n_simulations)
    mdd_arr = np.empty(n_simulations)
    for i in range(n_simulations):
        s       = samples[i]
        gross   = float(s[s > 0].sum())
        loss    = float((-s[s < 0]).sum())
        pf_arr[i]  = gross / loss if loss > 0.0 else 999.0
        mdd_arr[i] = _max_drawdown_from_pnls(s)

    def _ci(a: np.ndarray) -> dict:
        p5, p50, p95 = np.percentile(a, [5, 50, 95])
        return {
            "pct_5" : round(float(p5),  6),
            "pct_50": round(float(p50), 6),
            "pct_95": round(float(p95), 6),
        }

    return {
        "total_return"  : _ci(returns_arr),
        "trade_sharpe"  : _ci(sharpes_arr),
        "win_rate"      : _ci(win_rates_arr),
        "profit_factor" : _ci(pf_arr),
        "expectancy"    : _ci(means),
        "max_drawdown"  : _ci(mdd_arr),
        "n_simulations" : n_simulations,
        "n_trades"      : n,
    }


def _max_drawdown_from_pnls(pnls: np.ndarray) -> float:
    """Maximum drawdown from cumulative PnL sequence (starting from 0)."""
    equity = np.concatenate([[0.0], np.cumsum(pnls)])
    peak   = np.maximum.accumulate(equity)
    dd     = equity - peak
    return float(-dd.min())


def _empty() -> dict:
    null_ci = {"pct_5": None, "pct_50": None, "pct_95": None}
    return {
        "total_return"  : null_ci,
        "trade_sharpe"  : null_ci,
        "win_rate"      : null_ci,
        "profit_factor" : null_ci,
        "expectancy"    : null_ci,
        "max_drawdown"  : null_ci,
        "n_simulations" : 0,
        "n_trades"      : 0,
    }
