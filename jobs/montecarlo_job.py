"""Monte Carlo simulation via bootstrap resampling of trade returns."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .base import BaseJob


@dataclass(frozen=True)
class MonteCarloResult:
    n_simulations: int
    n_trades: int
    median_return: float
    pct5_return: float
    pct95_return: float
    median_max_dd: float
    worst_max_dd: float
    best_max_dd: float
    prob_positive: float
    all_returns: list[float] = field(default_factory=list)
    all_max_dds: list[float] = field(default_factory=list)


@dataclass
class MonteCarloParams:
    pnl_sequence: list[float]
    starting_capital: float = 100_000.0
    n_simulations: int = 1000
    seed: int = 42


class MonteCarloJob(BaseJob):
    """Bootstrap-resample trade PnLs to estimate an outcome distribution."""

    def __init__(self, p: MonteCarloParams) -> None:
        self.p = p

    def execute(self) -> dict[str, Any]:
        p = self.p
        if p.starting_capital <= 0 or not math.isfinite(p.starting_capital):
            raise ValueError("starting_capital must be positive and finite")
        if p.n_simulations <= 0:
            raise ValueError("n_simulations must be positive")
        if not all(math.isfinite(float(x)) for x in p.pnl_sequence):
            raise ValueError("pnl_sequence must contain only finite values")

        pnls = [float(x) for x in p.pnl_sequence]
        n = len(pnls)

        if n < 2:
            return _empty_result(p.n_simulations, n)

        rng = random.Random(p.seed)
        returns: list[float] = []
        max_dds: list[float] = []

        for _ in range(p.n_simulations):
            sample = [rng.choice(pnls) for _ in range(n)]
            eq = [p.starting_capital]
            for pnl in sample:
                eq.append(eq[-1] + pnl)

            total_ret = (eq[-1] - eq[0]) / eq[0]
            returns.append(total_ret)

            peak = eq[0]
            maxdd = 0.0
            for value in eq:
                if value > peak:
                    peak = value
                # Once equity is <= 0, conventional percentage drawdown is
                # undefined.  We conservatively cap the path at 100% loss.
                dd = (peak - value) / peak if peak > 0 else 1.0
                maxdd = max(maxdd, dd)
            max_dds.append(maxdd)

        returns.sort()
        max_dds.sort()
        m = len(returns)

        med_ret = returns[(m - 1) // 2]
        pct5 = returns[min(m - 1, int(m * 0.05))]
        pct95 = returns[min(m - 1, int(m * 0.95))]
        med_dd = max_dds[(m - 1) // 2]
        worst_dd = max_dds[-1]
        best_dd = max_dds[0]
        prob_pos = sum(1 for r in returns if r > 0) / m

        return {
            "n_simulations": p.n_simulations,
            "n_trades": n,
            "median_return": med_ret,
            "pct5_return": pct5,
            "pct95_return": pct95,
            "median_max_dd": med_dd,
            "worst_max_dd": worst_dd,
            "best_max_dd": best_dd,
            "prob_positive": prob_pos,
            "all_returns": returns,
            "all_max_dds": max_dds,
        }


def run_monte_carlo(
    trades,
    starting_capital: float = 100_000.0,
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Convenience wrapper — accepts trades with ``.net_pnl`` attributes."""
    pnls = [t.net_pnl for t in trades]
    job = MonteCarloJob(MonteCarloParams(
        pnl_sequence=pnls,
        starting_capital=starting_capital,
        n_simulations=n_simulations,
        seed=seed,
    ))
    result = job.run()
    return result.data or {}


def _empty_result(n_sims: int, n_trades: int) -> dict[str, Any]:
    return {
        "n_simulations": n_sims,
        "n_trades": n_trades,
        "median_return": 0.0,
        "pct5_return": 0.0,
        "pct95_return": 0.0,
        "median_max_dd": 0.0,
        "worst_max_dd": 0.0,
        "best_max_dd": 0.0,
        "prob_positive": 0.0,
        "all_returns": [],
        "all_max_dds": [],
    }
