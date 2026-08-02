"""Multi-strategy comparison and ranking."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.models import EngineConfig
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult
from engine.strategy import StrategyBase
from research.metrics import InstitutionalMetrics, calculate_research_metrics


@dataclass
class ComparisonResult:
    """Ranked comparison of multiple strategies on the same dataset.

    Attributes
    ----------
    ranking : DataFrame with one row per strategy, sorted by
              ``sharpe_ratio`` descending.  Columns include all
              :class:`~research.metrics.InstitutionalMetrics` fields plus
              ``strategy_name``.
    metrics : Dict mapping strategy name → :class:`InstitutionalMetrics`.
    results : Dict mapping strategy name → :class:`~portfolio.PortfolioResult`.
    """

    ranking : pd.DataFrame
    metrics : dict[str, InstitutionalMetrics]
    results : dict[str, PortfolioResult]


def compare_strategies(
    bars             : pd.DataFrame,
    strategies       : dict[str, StrategyBase],
    portfolio_config : PortfolioConfig | None = None,
    engine_config    : EngineConfig    | None = None,
    bars_per_year    : int             = 252,
    sort_by          : str             = "sharpe_ratio",
) -> ComparisonResult:
    """Run multiple strategies on the same bars and produce a ranked table.

    Each strategy is run independently with the same portfolio and engine
    configuration.  The resulting metrics are assembled into a DataFrame
    sorted by *sort_by* descending.

    Args:
        bars:             OHLCV DataFrame.  All strategies see the same data.
        strategies:       Mapping of ``strategy_name → strategy_instance``.
        portfolio_config: Portfolio configuration (default: defaults).
        engine_config:    Engine execution config (default: defaults).
        bars_per_year:    Annualisation factor (default: 252).
        sort_by:          :class:`~research.metrics.InstitutionalMetrics`
                          field to sort by.  Default: ``"sharpe_ratio"``.

    Returns:
        :class:`ComparisonResult` with the ranking DataFrame and per-strategy
        metrics and portfolio results.

    Raises:
        ValueError: If *strategies* is empty.

    Usage example
    -------------
    >>> from research import compare_strategies
    >>> from strategies import EMACrossover, BollingerBreakout
    >>>
    >>> result = compare_strategies(
    ...     bars,
    ...     {
    ...         "EMA(10,30)": EMACrossover(fast=10, slow=30),
    ...         "BB(20,2)":   BollingerBreakout(period=20, std_dev=2.0),
    ...     },
    ...     bars_per_year=8760,
    ...     sort_by="calmar_ratio",
    ... )
    >>> print(result.ranking[["strategy_name", "sharpe_ratio", "cagr", "max_drawdown_pct"]])
    """
    if not strategies:
        raise ValueError("strategies dict must contain at least one entry.")

    pc  = portfolio_config or PortfolioConfig()
    ec  = engine_config    or EngineConfig()
    eng = PortfolioEngine(pc)

    all_metrics : dict[str, InstitutionalMetrics] = {}
    all_results : dict[str, PortfolioResult]      = {}
    rows        : list[dict]                       = []

    for name, strategy in strategies.items():
        result  = eng.run(bars, strategy, ec)
        metrics = calculate_research_metrics(
            result.equity_curve, result.trades, bars_per_year
        )
        all_metrics[name] = metrics
        all_results[name] = result

        row = {"strategy_name": name}
        row.update({
            "cagr"               : metrics.cagr,
            "sharpe_ratio"       : metrics.sharpe_ratio,
            "sortino_ratio"      : metrics.sortino_ratio,
            "calmar_ratio"       : metrics.calmar_ratio,
            "max_drawdown_pct"   : metrics.max_drawdown_pct,
            "total_return"       : result.total_return,
            "win_rate"           : metrics.win_rate,
            "profit_factor"      : metrics.profit_factor,
            "payoff_ratio"       : metrics.payoff_ratio,
            "kelly_fraction"     : metrics.kelly_fraction,
            "recovery_factor"    : metrics.recovery_factor,
            "avg_trade_pnl"      : metrics.avg_trade_pnl,
            "avg_holding_period" : metrics.avg_holding_period,
            "total_trades"       : metrics.total_trades,
            "information_ratio"  : metrics.information_ratio,
            "skewness"           : metrics.skewness,
            "kurtosis"           : metrics.kurtosis,
            "downside_volatility": metrics.downside_volatility,
            "avg_drawdown"       : metrics.avg_drawdown,
        })
        rows.append(row)

    ranking = pd.DataFrame(rows)
    if sort_by in ranking.columns:
        ranking = ranking.sort_values(sort_by, ascending=False).reset_index(drop=True)

    return ComparisonResult(
        ranking = ranking,
        metrics = all_metrics,
        results = all_results,
    )
