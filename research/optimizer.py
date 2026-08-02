"""Grid and random search parameter optimizers."""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import pandas as pd

from engine.models import EngineConfig
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig
from research.metrics import InstitutionalMetrics, calculate_research_metrics


@dataclass
class ParameterSpace:
    """Description of hyperparameter search space.

    Each entry in ``params`` maps a parameter name to an iterable of
    candidate values.  The optimizer iterates over all combinations
    (grid) or draws random samples.

    Attributes
    ----------
    params : dict mapping parameter name → list of candidate values.

    Usage example
    -------------
    >>> space = ParameterSpace({"fast": [5, 10, 20], "slow": [30, 50, 100]})
    >>> # Grid search will evaluate 3×3 = 9 combinations.
    """

    params: dict[str, Sequence[Any]] = field(default_factory=dict)

    def all_combinations(self) -> list[dict[str, Any]]:
        """Return all Cartesian products of the parameter lists."""
        if not self.params:
            return [{}]
        keys   = list(self.params.keys())
        values = [list(self.params[k]) for k in keys]
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def random_sample(self, n: int, seed: int | None = None) -> list[dict[str, Any]]:
        """Return *n* random parameter combinations (with replacement).

        Args:
            n    : Number of samples.
            seed : Optional random seed for reproducibility.

        Returns:
            List of *n* dicts mapping parameter name → sampled value.
        """
        rng   = random.Random(seed)
        keys  = list(self.params.keys())
        lists = [list(self.params[k]) for k in keys]
        return [
            {k: rng.choice(v) for k, v in zip(keys, lists)}
            for _ in range(n)
        ]


@dataclass(frozen=True)
class OptimizationResult:
    """Output of a parameter optimization run.

    Attributes
    ----------
    best_params : Parameter combination that achieved the highest score.
    best_score  : Value of the objective metric for ``best_params``.
    all_results : DataFrame with one row per combination, columns for
                  each parameter and the ``score`` column, sorted by
                  score descending.
    objective   : Name of the :class:`~research.metrics.InstitutionalMetrics`
                  field used as the objective.
    n_evaluated : Total number of parameter combinations evaluated.
    """

    best_params : dict[str, Any]
    best_score  : float
    all_results : pd.DataFrame
    objective   : str
    n_evaluated : int


class GridSearchOptimizer:
    """Exhaustive grid search over a :class:`ParameterSpace`.

    The strategy is re-instantiated for each parameter combination via
    ``strategy_factory(**params)``.

    Args:
        space            : Parameter space defining candidates.
        strategy_factory : Callable that accepts keyword arguments from
                           *space* and returns a
                           :class:`~engine.strategy.StrategyBase`.
        objective        : Attribute name on
                           :class:`~research.metrics.InstitutionalMetrics`
                           to maximise.  Default: ``"sharpe_ratio"``.
        portfolio_config : Portfolio configuration (default: defaults).
        engine_config    : Engine execution config (default: defaults).
        bars_per_year    : Annualisation factor (default: 252).

    Usage example
    -------------
    >>> from research import GridSearchOptimizer, ParameterSpace
    >>> from strategies import EMACrossover
    >>>
    >>> space = ParameterSpace({"fast": [5, 10], "slow": [20, 50]})
    >>> opt = GridSearchOptimizer(
    ...     space=space,
    ...     strategy_factory=EMACrossover,
    ...     objective="sharpe_ratio",
    ... )
    >>> result = opt.run(bars)
    >>> print(result.best_params, result.best_score)
    """

    def __init__(
        self,
        space            : ParameterSpace,
        strategy_factory : Callable[..., object],
        objective        : str            = "sharpe_ratio",
        portfolio_config : PortfolioConfig | None = None,
        engine_config    : EngineConfig    | None = None,
        bars_per_year    : int             = 252,
    ) -> None:
        self.space            = space
        self.strategy_factory = strategy_factory
        self.objective        = objective
        self.portfolio_config = portfolio_config or PortfolioConfig()
        self.engine_config    = engine_config    or EngineConfig()
        self.bars_per_year    = bars_per_year

    def run(self, bars: pd.DataFrame) -> OptimizationResult:
        """Run grid search over all parameter combinations.

        Args:
            bars: OHLCV DataFrame to backtest each combination on.

        Returns:
            :class:`OptimizationResult` with the best parameters and a
            ranked summary table.
        """
        combos = self.space.all_combinations()
        return _run_search(
            combos           = combos,
            bars             = bars,
            strategy_factory = self.strategy_factory,
            objective        = self.objective,
            portfolio_config = self.portfolio_config,
            engine_config    = self.engine_config,
            bars_per_year    = self.bars_per_year,
        )


class RandomSearchOptimizer:
    """Random search over a :class:`ParameterSpace`.

    Evaluates *n_iter* randomly sampled parameter combinations rather
    than the full Cartesian product.  Useful when the search space is
    large and grid search is prohibitively slow.

    Args:
        space            : Parameter space defining candidates.
        strategy_factory : Same as :class:`GridSearchOptimizer`.
        n_iter           : Number of random combinations to evaluate.
        objective        : Metric to maximise (default: ``"sharpe_ratio"``).
        seed             : Random seed for reproducibility.
        portfolio_config : Portfolio configuration.
        engine_config    : Engine execution config.
        bars_per_year    : Annualisation factor.

    Usage example
    -------------
    >>> from research import RandomSearchOptimizer, ParameterSpace
    >>> space = ParameterSpace({"fast": list(range(5, 51)), "slow": list(range(20, 201))})
    >>> opt   = RandomSearchOptimizer(space, EMACrossover, n_iter=50, seed=42)
    >>> result = opt.run(bars)
    """

    def __init__(
        self,
        space            : ParameterSpace,
        strategy_factory : Callable[..., object],
        n_iter           : int             = 20,
        objective        : str             = "sharpe_ratio",
        seed             : int | None      = None,
        portfolio_config : PortfolioConfig | None = None,
        engine_config    : EngineConfig    | None = None,
        bars_per_year    : int             = 252,
    ) -> None:
        if n_iter < 1:
            raise ValueError(f"n_iter must be ≥ 1, got {n_iter}")
        self.space            = space
        self.strategy_factory = strategy_factory
        self.n_iter           = n_iter
        self.objective        = objective
        self.seed             = seed
        self.portfolio_config = portfolio_config or PortfolioConfig()
        self.engine_config    = engine_config    or EngineConfig()
        self.bars_per_year    = bars_per_year

    def run(self, bars: pd.DataFrame) -> OptimizationResult:
        """Run random search for ``n_iter`` parameter combinations.

        Args:
            bars: OHLCV DataFrame to backtest each combination on.

        Returns:
            :class:`OptimizationResult` with the best parameters found.
        """
        combos = self.space.random_sample(self.n_iter, seed=self.seed)
        return _run_search(
            combos           = combos,
            bars             = bars,
            strategy_factory = self.strategy_factory,
            objective        = self.objective,
            portfolio_config = self.portfolio_config,
            engine_config    = self.engine_config,
            bars_per_year    = self.bars_per_year,
        )


# ── Shared search runner ───────────────────────────────────────────────────────

def _run_search(
    combos           : list[dict[str, Any]],
    bars             : pd.DataFrame,
    strategy_factory : Callable[..., object],
    objective        : str,
    portfolio_config : PortfolioConfig,
    engine_config    : EngineConfig,
    bars_per_year    : int,
) -> OptimizationResult:
    engine = PortfolioEngine(portfolio_config)
    rows: list[dict[str, Any]] = []

    best_score  = float("-inf")
    best_params : dict[str, Any] = {}

    for params in combos:
        try:
            strategy = strategy_factory(**params)
            result   = engine.run(bars, strategy, engine_config)
            metrics  = calculate_research_metrics(
                result.equity_curve, result.trades, bars_per_year
            )
            score = float(getattr(metrics, objective, float("nan")))
        except Exception:
            score = float("nan")

        row = dict(params)
        row["score"] = score
        rows.append(row)

        if score > best_score and not _is_nan(score):
            best_score  = score
            best_params = dict(params)

    df = pd.DataFrame(rows)
    if not df.empty and "score" in df.columns:
        df = df.sort_values("score", ascending=False).reset_index(drop=True)

    return OptimizationResult(
        best_params = best_params,
        best_score  = best_score if best_score > float("-inf") else float("nan"),
        all_results = df,
        objective   = objective,
        n_evaluated = len(combos),
    )


def _is_nan(x: float) -> bool:
    return x != x  # NaN is the only float not equal to itself
