"""Walk-forward testing — rolling and expanding window validation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

import pandas as pd

from engine.models import EngineConfig
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult


class WalkForwardMode(str, Enum):
    ROLLING = "rolling"
    EXPANDING = "expanding"


@dataclass
class WalkForwardConfig:
    train_bars: int = 252
    test_bars: int = 63
    mode: WalkForwardMode = WalkForwardMode.ROLLING
    step_bars: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.train_bars, bool) or not isinstance(self.train_bars, int) or self.train_bars < 2:
            raise ValueError(f"train_bars must be an integer >= 2, got {self.train_bars}")
        if isinstance(self.test_bars, bool) or not isinstance(self.test_bars, int) or self.test_bars < 1:
            raise ValueError(f"test_bars must be an integer >= 1, got {self.test_bars}")
        step = self.test_bars if self.step_bars is None else self.step_bars
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError(f"step_bars must be an integer >= 1, got {step}")
        self.mode = WalkForwardMode(self.mode)


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    portfolio_result: PortfolioResult


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    combined_equity: pd.Series
    total_return: float
    config: WalkForwardConfig


class StrategyFactory(Protocol):
    def __call__(self, train_bars: pd.DataFrame): ...


class WalkForwardTester:
    """Run sequential OOS folds with continuous portfolio capital.

    Because ``combined_equity`` represents one continuous portfolio path,
    overlapping test windows are rejected instead of being silently
    double-counted.
    """

    def __init__(self, wf_config=None, portfolio_config=None, engine_config=None) -> None:
        self.wf_config = wf_config or WalkForwardConfig()
        self.portfolio_config = portfolio_config or PortfolioConfig()
        self.engine_config = engine_config or EngineConfig()

    def run(self, bars: pd.DataFrame, strategy_factory: Callable[[pd.DataFrame], object]) -> WalkForwardResult:
        cfg = self.wf_config
        n = len(bars)
        step = cfg.test_bars if cfg.step_bars is None else cfg.step_bars
        if step < cfg.test_bars:
            raise ValueError(
                "step_bars must be >= test_bars for a continuous OOS equity curve; "
                f"got step_bars={step}, test_bars={cfg.test_bars}"
            )
        if n < cfg.train_bars + cfg.test_bars:
            raise ValueError(
                f"bars has {n} rows but need at least {cfg.train_bars + cfg.test_bars} "
                f"(train={cfg.train_bars} + test={cfg.test_bars})."
            )

        folds: list[WalkForwardFold] = []
        equity_segments: list[pd.Series] = []
        running_capital = self.portfolio_config.starting_capital
        test_start = cfg.train_bars
        fold_idx = 0

        while test_start + cfg.test_bars <= n:
            test_end = test_start + cfg.test_bars
            train_start = test_start - cfg.train_bars if cfg.mode == WalkForwardMode.ROLLING else 0
            train_bars_df = bars.iloc[train_start:test_start]
            test_bars_df = bars.iloc[test_start:test_end]

            strategy = strategy_factory(train_bars_df)
            fold_config = _portfolio_config_with_capital(self.portfolio_config, running_capital)
            result = PortfolioEngine(fold_config).run(test_bars_df, strategy, self.engine_config)

            folds.append(WalkForwardFold(
                fold_index=fold_idx,
                train_start=train_start,
                train_end=test_start - 1,
                test_start=test_start,
                test_end=test_end - 1,
                portfolio_result=result,
            ))
            equity_segments.append(result.equity_curve)
            running_capital = result.ending_equity
            fold_idx += 1
            test_start += step

        if not folds:
            raise ValueError("No complete walk-forward folds could be constructed.")

        combined_equity = pd.concat(equity_segments)
        combined_equity = combined_equity[~combined_equity.index.duplicated(keep="last")]
        combined_equity.name = "wf_equity"
        starting = float(combined_equity.iloc[0])
        ending = float(combined_equity.iloc[-1])
        return WalkForwardResult(folds, combined_equity, (ending / starting) - 1.0, cfg)


def _portfolio_config_with_capital(base: PortfolioConfig, capital: float) -> PortfolioConfig:
    """Clone all portfolio settings, replacing only starting capital."""
    return PortfolioConfig(
        starting_capital=capital,
        sizing_mode=base.sizing_mode,
        position_size=base.position_size,
        equity_fraction=base.equity_fraction,
        trade_capital=base.trade_capital,
        fraction=base.fraction,
        summary_only=base.summary_only,
    )
