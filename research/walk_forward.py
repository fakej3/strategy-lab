"""Walk-forward testing — rolling and expanding window validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

import pandas as pd

from engine.models import EngineConfig
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult


class WalkForwardMode(str, Enum):
    """Sliding-window strategy for the training set.

    ROLLING  — fixed-length training window slides forward.  Only the most
               recent ``train_bars`` bars are used for each fold.
    EXPANDING — training window grows: starts at ``train_bars`` and
               includes all data up to the fold boundary.
    """

    ROLLING   = "rolling"
    EXPANDING = "expanding"


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward testing.

    Parameters
    ----------
    train_bars : int
        Number of bars in the initial training window.  Must be ≥ 2.
    test_bars : int
        Number of bars in each out-of-sample test window.  Must be ≥ 1.
    mode : WalkForwardMode
        ``ROLLING`` or ``EXPANDING`` (see :class:`WalkForwardMode`).
    step_bars : int | None
        How many bars to advance between folds.  Defaults to ``test_bars``
        (non-overlapping test windows).  Must be ≥ 1 when provided.

    Usage example
    -------------
    >>> cfg = WalkForwardConfig(
    ...     train_bars=504,   # ~2 years daily
    ...     test_bars=63,     # ~1 quarter
    ...     mode=WalkForwardMode.ROLLING,
    ... )
    """

    train_bars: int             = 252
    test_bars : int             = 63
    mode      : WalkForwardMode = WalkForwardMode.ROLLING
    step_bars : int | None      = None

    def __post_init__(self) -> None:
        if self.train_bars < 2:
            raise ValueError(f"train_bars must be ≥ 2, got {self.train_bars}")
        if self.test_bars < 1:
            raise ValueError(f"test_bars must be ≥ 1, got {self.test_bars}")
        step = self.step_bars if self.step_bars is not None else self.test_bars
        if step < 1:
            raise ValueError(f"step_bars must be ≥ 1, got {step}")


@dataclass(frozen=True)
class WalkForwardFold:
    """Result of a single walk-forward fold.

    Attributes
    ----------
    fold_index    : 0-based fold number.
    train_start   : First bar index (integer position) in training window.
    train_end     : Last bar index (inclusive) in training window.
    test_start    : First bar index in the test window.
    test_end      : Last bar index (inclusive) in the test window.
    portfolio_result : :class:`~portfolio.PortfolioResult` on the test window.
    """

    fold_index      : int
    train_start     : int
    train_end       : int
    test_start      : int
    test_end        : int
    portfolio_result: PortfolioResult


@dataclass
class WalkForwardResult:
    """Aggregated output of a complete walk-forward test.

    Attributes
    ----------
    folds : list of :class:`WalkForwardFold` in chronological order.
    combined_equity : Concatenated out-of-sample equity curves across all
        folds, forming a continuous out-of-sample equity curve.
        Capital continuity is maintained: each fold's equity starts where
        the previous fold's equity ended.
    total_return : Overall return across all out-of-sample folds.
    config : The :class:`WalkForwardConfig` used.
    """

    folds           : list[WalkForwardFold]
    combined_equity : pd.Series
    total_return    : float
    config          : WalkForwardConfig


class StrategyFactory(Protocol):
    """Callable that trains and returns a strategy from in-sample bars.

    Walk-forward testing calls ``factory(train_bars)`` for each fold and
    uses the returned strategy on the out-of-sample window.  The factory
    is responsible for any fitting, parameter selection, or indicator
    pre-computation that must happen in-sample.
    """

    def __call__(self, train_bars: pd.DataFrame): ...  # -> StrategyBase


class WalkForwardTester:
    """Walk-forward tester that re-trains a strategy on a rolling/expanding window.

    For each fold:
    1. Extract training bars (rolling or expanding window).
    2. Call ``strategy_factory(train_bars)`` to obtain a fitted strategy.
    3. Run the strategy on the out-of-sample test bars using
       :class:`~portfolio.PortfolioEngine`.
    4. Record results and advance the window.

    Args:
        wf_config        : Walk-forward configuration.
        portfolio_config : Portfolio sizing configuration.  Starting
                           capital is re-used as the capital at the start
                           of each fold (independent folds semantics).
                           Pass ``None`` for defaults.
        engine_config    : Execution parameters (fees, slippage, SL/TP).
                           Pass ``None`` for defaults.

    Usage example
    -------------
    >>> from research import WalkForwardTester, WalkForwardConfig
    >>> from strategies import EMACrossover
    >>>
    >>> def factory(train_bars):
    ...     # Fit any parameters here using train_bars
    ...     return EMACrossover(fast=10, slow=30)
    >>>
    >>> tester = WalkForwardTester(WalkForwardConfig(train_bars=252, test_bars=63))
    >>> wf_result = tester.run(all_bars, factory)
    >>> print(f"OOS return: {wf_result.total_return:.2%}")
    >>> print(f"Folds: {len(wf_result.folds)}")
    """

    def __init__(
        self,
        wf_config        : WalkForwardConfig  | None = None,
        portfolio_config : PortfolioConfig     | None = None,
        engine_config    : EngineConfig        | None = None,
    ) -> None:
        self.wf_config        = wf_config        or WalkForwardConfig()
        self.portfolio_config = portfolio_config  or PortfolioConfig()
        self.engine_config    = engine_config     or EngineConfig()

    def run(
        self,
        bars            : pd.DataFrame,
        strategy_factory: Callable[[pd.DataFrame], object],
    ) -> WalkForwardResult:
        """Execute all walk-forward folds and return aggregated results.

        Args:
            bars:             Full OHLCV dataset to partition into
                              training and test windows.
            strategy_factory: Callable matching the
                              :class:`StrategyFactory` protocol.  Receives
                              training bars, returns a fitted
                              :class:`~engine.strategy.StrategyBase`.

        Returns:
            :class:`WalkForwardResult` with fold-level and combined results.

        Raises:
            ValueError: If bars is too short to fit even one fold.
        """
        cfg      = self.wf_config
        n        = len(bars)
        min_bars = cfg.train_bars + cfg.test_bars
        step     = cfg.step_bars if cfg.step_bars is not None else cfg.test_bars

        if n < min_bars:
            raise ValueError(
                f"bars has {n} rows but need at least "
                f"{min_bars} (train={cfg.train_bars} + test={cfg.test_bars})."
            )

        folds           : list[WalkForwardFold] = []
        equity_segments : list[pd.Series]       = []
        running_capital = self.portfolio_config.starting_capital
        fold_idx        = 0
        test_start      = cfg.train_bars

        while test_start + cfg.test_bars <= n:
            test_end = test_start + cfg.test_bars  # exclusive slice end

            if cfg.mode == WalkForwardMode.ROLLING:
                train_start = test_start - cfg.train_bars
            else:
                train_start = 0  # expanding: all data from start

            train_bars_df = bars.iloc[train_start:test_start]
            test_bars_df  = bars.iloc[test_start:test_end]

            strategy = strategy_factory(train_bars_df)

            fold_pc = _portfolio_config_with_capital(
                self.portfolio_config, running_capital
            )
            engine  = PortfolioEngine(fold_pc)
            result  = engine.run(test_bars_df, strategy, self.engine_config)

            fold = WalkForwardFold(
                fold_index       = fold_idx,
                train_start      = train_start,
                train_end        = test_start - 1,
                test_start       = test_start,
                test_end         = test_end - 1,
                portfolio_result = result,
            )
            folds.append(fold)
            equity_segments.append(result.equity_curve)
            running_capital = result.ending_equity

            fold_idx   += 1
            test_start += step

        if not folds:
            raise ValueError("No complete walk-forward folds could be constructed.")

        combined_equity = pd.concat(equity_segments)
        combined_equity.name = "wf_equity"

        starting = float(equity_segments[0].iloc[0])
        ending   = float(equity_segments[-1].iloc[-1])
        total_return = (ending - starting) / starting if starting > 0 else 0.0

        return WalkForwardResult(
            folds           = folds,
            combined_equity = combined_equity,
            total_return    = total_return,
            config          = cfg,
        )


def _portfolio_config_with_capital(
    base   : PortfolioConfig,
    capital: float,
) -> PortfolioConfig:
    """Return a copy of *base* with ``starting_capital`` replaced by *capital*."""
    return PortfolioConfig(
        starting_capital = capital,
        sizing_mode      = base.sizing_mode,
        position_size    = base.position_size,
        equity_fraction  = base.equity_fraction,
        trade_capital    = base.trade_capital,
        fraction         = base.fraction,
    )
