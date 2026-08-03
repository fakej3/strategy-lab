"""ResearchLab facade — wraps the jobs/research layers for external consumers."""
from __future__ import annotations

from datetime import date
from typing import Any, Type

import pandas as pd

from shared.errors import ResearchError


class ResearchLab:
    """High-level interface for running backtests and research analysis.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``jobs`` or ``research`` directly.

    Example
    -------
    >>> from engine import StrategyBase, Signal
    >>> lab = ResearchLab()
    >>> result = lab.evaluate(
    ...     bars=bars, strategy_class=MyStrategy, params={},
    ...     symbol="BTCUSDT", interval="1h",
    ...     start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
    ... )
    """

    def evaluate(
        self,
        bars: pd.DataFrame,
        strategy_class: Type,
        params: dict[str, Any],
        symbol: str,
        interval: str,
        start_date: date,
        end_date: date,
        starting_capital: float = 100_000.0,
        fee_rate: float = 0.001,
        slippage_pct: float = 0.0005,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> dict[str, Any]:
        """Run a full backtest and return the result dict.

        Args:
            bars:             Pre-loaded OHLCV DataFrame.
            strategy_class:   A StrategyBase subclass.
            params:           Strategy hyper-parameters to pass to the strategy.
            symbol:           Ticker / trading pair, e.g. "BTCUSDT".
            interval:         Bar interval, e.g. "1h".
            start_date:       Backtest start date.
            end_date:         Backtest end date.
            starting_capital: Initial equity in dollars.
            fee_rate:         Round-trip fee as a fraction (0.001 = 0.1%).
            slippage_pct:     Slippage per fill as a fraction.
            stop_loss_pct:    Optional trailing stop-loss fraction.
            take_profit_pct:  Optional take-profit fraction.

        Returns:
            Dict with keys: metrics, gate_result, portfolio_result, …

        Raises:
            ResearchError: if the backtest execution fails.
        """
        try:
            from jobs.backtest_job import BacktestJob, BacktestParams
            job = BacktestJob(BacktestParams(
                bars            = bars,
                strategy_class  = strategy_class,
                params          = params,
                symbol          = symbol,
                interval        = interval,
                start_date      = start_date,
                end_date        = end_date,
                starting_capital = starting_capital,
                fee_rate        = fee_rate,
                slippage_pct    = slippage_pct,
                stop_loss_pct   = stop_loss_pct,
                take_profit_pct = take_profit_pct,
            ))
            return job.execute()
        except Exception as exc:
            raise ResearchError(f"Backtest failed: {exc}") from exc

    def calculate_metrics(
        self,
        equity_curve: pd.Series,
        trades: list,
        bars_per_year: int = 252,
        benchmark_returns: pd.Series | None = None,
    ):
        """Compute institutional-quality research metrics for an equity curve.

        Returns:
            InstitutionalMetrics instance.

        Raises:
            ResearchError: if the calculation fails.
        """
        try:
            from research.metrics import calculate_research_metrics
            return calculate_research_metrics(
                equity_curve,
                trades,
                bars_per_year=bars_per_year,
                benchmark_returns=benchmark_returns,
            )
        except Exception as exc:
            raise ResearchError(f"Metrics calculation failed: {exc}") from exc
