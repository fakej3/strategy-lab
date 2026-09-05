"""Monte Carlo robustness analysis for completed trade outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class MonteCarloResult:
    """Distributional summary of simulated trade-order paths."""
    simulations: int
    trades_per_simulation: int
    starting_capital: float
    terminal_equity: np.ndarray
    max_drawdown: np.ndarray
    probability_of_loss: float
    terminal_equity_percentiles: dict[float, float]
    max_drawdown_percentiles: dict[float, float]


def simulate_trade_paths(
    trade_pnls: Sequence[float],
    starting_capital: float = 100_000.0,
    simulations: int = 10_000,
    seed: int | None = 42,
    mode: str = "shuffle",
) -> MonteCarloResult:
    """Simulate alternative trade paths without changing trade outcomes.

    ``shuffle`` samples each observed trade exactly once per simulation,
    changing only the order. ``bootstrap`` samples observed trades with
    replacement and therefore also models outcome-sampling uncertainty.

    The simulation is intentionally trade-level: it does not manufacture
    synthetic returns or infer a distribution that was not observed.
    """
    if not isinstance(simulations, int) or isinstance(simulations, bool) or simulations < 1:
        raise ValueError("simulations must be a positive integer")
    if not np.isfinite(starting_capital) or starting_capital <= 0:
        raise ValueError("starting_capital must be finite and > 0")
    if mode not in {"shuffle", "bootstrap"}:
        raise ValueError("mode must be 'shuffle' or 'bootstrap'")

    pnls = np.asarray(list(trade_pnls), dtype=float)
    if pnls.ndim != 1 or len(pnls) == 0:
        raise ValueError("trade_pnls must contain at least one trade")
    if not np.isfinite(pnls).all():
        raise ValueError("trade_pnls must contain only finite values")

    rng = np.random.default_rng(seed)
    n = len(pnls)
    terminal = np.empty(simulations, dtype=float)
    drawdowns = np.empty(simulations, dtype=float)

    for i in range(simulations):
        if mode == "shuffle":
            path = rng.permutation(pnls)
        else:
            path = rng.choice(pnls, size=n, replace=True)
        equity = starting_capital + np.cumsum(path)
        peaks = np.maximum.accumulate(np.concatenate(([starting_capital], equity)))
        all_equity = np.concatenate(([starting_capital], equity))
        dd = 1.0 - all_equity / peaks
        terminal[i] = equity[-1]
        drawdowns[i] = float(np.max(dd))

    qs = (1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0)
    terminal_pct = {q: float(np.percentile(terminal, q)) for q in qs}
    dd_pct = {q: float(np.percentile(drawdowns, q)) for q in qs}
    return MonteCarloResult(
        simulations=simulations,
        trades_per_simulation=n,
        starting_capital=float(starting_capital),
        terminal_equity=terminal,
        max_drawdown=drawdowns,
        probability_of_loss=float(np.mean(terminal < starting_capital)),
        terminal_equity_percentiles=terminal_pct,
        max_drawdown_percentiles=dd_pct,
    )
