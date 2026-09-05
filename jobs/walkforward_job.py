"""Walk-forward validation job wrapping research.walk_forward.WalkForwardTester."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Type

import pandas as pd

from engine.models import EngineConfig
from engine.strategy import StrategyBase
from portfolio.models import PortfolioConfig
from research.walk_forward import WalkForwardConfig, WalkForwardTester

from .base import BaseJob


@dataclass
class WalkForwardParams:
    bars: pd.DataFrame
    strategy_class: Type[StrategyBase]
    params: dict
    starting_capital: float     = 100_000.0
    fee_rate: float             = 0.001
    slippage_pct: float         = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    train_bars: int = 1008     # ~6 weeks of 1h bars
    test_bars: int  = 336      # ~2 weeks
    min_required_bars: int = 1344  # train + test


class WalkForwardJob(BaseJob):
    """Run walk-forward analysis with fixed parameters across rolling windows."""

    def __init__(self, p: WalkForwardParams) -> None:
        self.p = p

    def execute(self) -> dict[str, Any]:
        p = self.p

        if len(p.bars) < p.min_required_bars:
            return {
                "walk_forward_return": None,
                "n_folds": 0,
                "fold_returns": [],
                "skipped": True,
                "reason": f"Insufficient bars: {len(p.bars)} < {p.min_required_bars}",
            }

        def factory(train_bars: pd.DataFrame) -> StrategyBase:
            return p.strategy_class(**p.params)

        wf_cfg = WalkForwardConfig(
            train_bars = p.train_bars,
            test_bars  = p.test_bars,
        )
        port_cfg = PortfolioConfig(starting_capital=p.starting_capital)
        eng_cfg  = EngineConfig(
            fee_rate        = p.fee_rate,
            slippage_pct    = p.slippage_pct,
            stop_loss_pct   = p.stop_loss_pct,
            take_profit_pct = p.take_profit_pct,
        )

        tester = WalkForwardTester(wf_cfg, port_cfg, eng_cfg)
        wf_result = tester.run(p.bars, factory)

        fold_returns = [
            f.portfolio_result.total_return
            for f in wf_result.folds
        ]

        return {
            "walk_forward_return": _safe(wf_result.total_return),
            "n_folds"            : len(wf_result.folds),
            "fold_returns"       : [_safe(r) for r in fold_returns],
            "avg_fold_return"    : _safe(
                sum(fold_returns) / len(fold_returns) if fold_returns else 0.0
            ),
            "skipped": False,
        }


def _safe(v: float) -> float | None:
    """Preserve missing/non-finite statistics as None; never turn them into 0."""
    if not math.isfinite(v):
        return None
    return float(v)
