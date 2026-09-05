"""Strict V2 walk-forward protocol.

The protocol separates model fitting from OOS evaluation and records exact
integer boundaries. It does not claim that fold-level portfolio resets are
identical to one continuous portfolio; callers must choose a capital policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

import pandas as pd


class WFOCapitalPolicy(str, Enum):
    RESET = "reset"
    CARRY = "carry"


@dataclass(frozen=True)
class V2WalkForwardConfig:
    train_bars: int = 252
    test_bars: int = 63
    step_bars: int | None = None
    mode: str = "rolling"
    capital_policy: WFOCapitalPolicy = WFOCapitalPolicy.CARRY

    def __post_init__(self):
        if self.train_bars < 2 or self.test_bars < 1:
            raise ValueError("train_bars >= 2 and test_bars >= 1 are required")
        if self.step_bars is not None and self.step_bars < 1:
            raise ValueError("step_bars must be >= 1")
        if self.mode not in {"rolling", "expanding"}:
            raise ValueError("mode must be rolling or expanding")


@dataclass(frozen=True)
class V2Fold:
    index: int
    train_start: int
    train_end_exclusive: int
    test_start: int
    test_end_exclusive: int


@dataclass(frozen=True)
class V2WalkForwardPlan:
    folds: tuple[V2Fold, ...]
    config: V2WalkForwardConfig


def build_plan(n_bars: int, config: V2WalkForwardConfig | None = None) -> V2WalkForwardPlan:
    cfg = config or V2WalkForwardConfig()
    if n_bars < cfg.train_bars + cfg.test_bars:
        raise ValueError("dataset is too short for one complete OOS fold")
    step = cfg.step_bars or cfg.test_bars
    folds = []
    test_start = cfg.train_bars
    i = 0
    while test_start + cfg.test_bars <= n_bars:
        train_start = test_start - cfg.train_bars if cfg.mode == "rolling" else 0
        folds.append(V2Fold(i, train_start, test_start, test_start, test_start + cfg.test_bars))
        test_start += step
        i += 1
    return V2WalkForwardPlan(tuple(folds), cfg)


def execute_oos_plan(
    bars: pd.DataFrame,
    plan: V2WalkForwardPlan,
    fit: Callable[[pd.DataFrame], object],
    evaluate: Callable[[pd.DataFrame, object, float], tuple[pd.Series, float]],
    starting_capital: float,
):
    """Execute a precomputed plan.

    ``evaluate`` receives only the OOS slice and returns (equity_curve,
    ending_equity). This explicit seam makes leakage and capital policy testable.
    """
    if starting_capital <= 0:
        raise ValueError("starting_capital must be positive")
    running = float(starting_capital)
    results = []
    for fold in plan.folds:
        train = bars.iloc[fold.train_start:fold.train_end_exclusive].copy()
        test = bars.iloc[fold.test_start:fold.test_end_exclusive].copy()
        model = fit(train)
        capital = running if plan.config.capital_policy == WFOCapitalPolicy.CARRY else starting_capital
        curve, ending = evaluate(test, model, capital)
        if not isinstance(curve, pd.Series) or len(curve) == 0:
            raise ValueError("evaluate must return a non-empty equity Series")
        if ending <= 0:
            raise ValueError("ending equity must remain positive")
        results.append((fold, curve, float(ending)))
        running = float(ending)
    return results
