"""Grid-search optimisation job — wraps research.optimizer.GridSearchOptimizer."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Type

import pandas as pd

from engine.models import EngineConfig
from engine.strategy import StrategyBase
from portfolio.models import PortfolioConfig
from research.optimizer import GridSearchOptimizer, ParameterSpace

from .base import BaseJob


@dataclass
class OptimizationParams:
    bars: pd.DataFrame
    strategy_class: Type[StrategyBase]
    param_space: dict[str, list]     # name → candidate values
    objective: str                   = "sharpe_ratio"
    starting_capital: float          = 100_000.0
    fee_rate: float                  = 0.001
    slippage_pct: float              = 0.0005
    stop_loss_pct: float | None      = None
    take_profit_pct: float | None    = None
    bars_per_year: int               = 252


class OptimizationJob(BaseJob):
    """Grid search over all parameter combinations for a strategy class."""

    def __init__(self, p: OptimizationParams) -> None:
        self.p = p

    def execute(self) -> dict[str, Any]:
        p = self.p

        space    = ParameterSpace(p.param_space)
        port_cfg = PortfolioConfig(starting_capital=p.starting_capital)
        eng_cfg  = EngineConfig(
            fee_rate        = p.fee_rate,
            slippage_pct    = p.slippage_pct,
            stop_loss_pct   = p.stop_loss_pct,
            take_profit_pct = p.take_profit_pct,
        )

        opt = GridSearchOptimizer(
            space            = space,
            strategy_factory = p.strategy_class,
            objective        = p.objective,
            portfolio_config = port_cfg,
            engine_config    = eng_cfg,
            bars_per_year    = p.bars_per_year,
        )

        result = opt.run(p.bars)

        top_rows = (
            result.all_results.head(10).to_dict(orient="records")
            if not result.all_results.empty else []
        )

        return {
            "best_params"  : result.best_params,
            "best_score"   : _safe(result.best_score),
            "objective"    : result.objective,
            "n_evaluated"  : result.n_evaluated,
            "top_10"       : top_rows,
        }


def _safe(v: float) -> float:
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return v
