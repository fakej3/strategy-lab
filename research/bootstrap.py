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
    """Compute empirical percentile intervals from per-trade PnL bootstrap samples.

    This is an uncertainty diagnostic, not proof of statistical significance.
    It assumes the observed trade outcomes are an appropriate resampling unit;
    serial dependence, regime changes, and execution effects are not modeled.

    Profit factor is represented as ``inf`` when a bootstrap sample has no
    losses. No arbitrary finite sentinel is substituted.
    """
    if isinstance(n_simulations, bool) or not isinstance(n_simulations, int) or n_simulations < 1:
        raise ValueError("n_simulations must be a positive integer")
    if not np.isfinite(starting_capital) or starting_capital <= 0:
        raise ValueError("starting_capital must be finite and > 0")

    arr = np.asarray(pnls, dtype=float)
    if arr.ndim != 1:
        raise ValueError("pnls must be one-dimensional")
    if len(arr) < 3:
        return _empty()
    if not np.isfinite(arr).all():
        raise ValueError("pnls must contain only finite values")

    rng = np.random.default_rng(seed)
    n = len(arr)
    samples = rng.choice(arr, size=(n_simulations, n), replace=True)

    totals = samples.sum(axis=1)
    means = samples.mean(axis=1)
    stds = samples.std(axis=1, ddof=1)
    returns_arr = totals / starting_capital
    sharpes_arr = np.divide(means, stds, out=np.zeros_like(means), where=stds > 0)
    win_rates_arr = (samples > 0).mean(axis=1)

    pf_arr = np.empty(n_simulations, dtype=float)
    mdd_arr = np.empty(n_simulations, dtype=float)
    for i, sample in enumerate(samples):
        gross_profit = float(sample[sample > 0].sum())
        gross_loss = float((-sample[sample < 0]).sum())
        pf_arr[i] = np.inf if gross_loss == 0.0 else gross_profit / gross_loss
        mdd_arr[i] = _max_drawdown_from_pnls(sample)

    return {
        "total_return": _ci(returns_arr),
        "trade_sharpe": _ci(sharpes_arr),
        "win_rate": _ci(win_rates_arr),
        "profit_factor": _ci(pf_arr),
        "expectancy": _ci(means),
        "max_drawdown": _ci(mdd_arr),
        "n_simulations": n_simulations,
        "n_trades": n,
    }


def _ci(values: np.ndarray) -> dict[str, float]:
    """Return 5th/50th/95th percentiles, preserving legitimate infinities."""
    p5, p50, p95 = np.percentile(values, [5, 50, 95])
    return {"pct_5": float(p5), "pct_50": float(p50), "pct_95": float(p95)}


def _max_drawdown_from_pnls(pnls: np.ndarray) -> float:
    """Maximum absolute PnL drawdown from cumulative PnL starting at zero."""
    equity = np.concatenate(([0.0], np.cumsum(pnls)))
    peak = np.maximum.accumulate(equity)
    return float(np.max(peak - equity))


def _empty() -> dict[str, Any]:
    null_ci = {"pct_5": None, "pct_50": None, "pct_95": None}
    return {
        "total_return": null_ci,
        "trade_sharpe": null_ci,
        "win_rate": null_ci,
        "profit_factor": null_ci,
        "expectancy": null_ci,
        "max_drawdown": null_ci,
        "n_simulations": 0,
        "n_trades": 0,
    }
