"""Batch backtest engine — runs a strategy across multiple symbols and intervals.

Phase 4: per-symbol/interval results using the existing PortfolioEngine.
Phase 5: portfolio-level simulation — chronological trade replay with shared
         capital so positions across symbols share a single equity pool.

Usage::

    from jobs.batch_backtest import BatchBacktest, BatchBacktestParams

    result = BatchBacktest(
        symbols=["BTCUSDT", "ETHUSDT"],
        intervals=["1h"],
        strategy_class=EMACrossover,
        params={"fast": 20, "slow": 50},
        bars={("BTCUSDT","1h"): btc_df, ("ETHUSDT","1h"): eth_df},
        starting_capital=100_000.0,
        equity_fraction=0.10,
    ).run()

    for sr in result.symbol_results:
        print(sr.symbol, sr.interval, sr.portfolio_result.total_return)

    print("Portfolio return:", result.portfolio_total_return)
    print("Portfolio Sharpe:", result.portfolio_sharpe)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Type

import numpy as np
import pandas as pd

from engine.models import EngineConfig
from engine.strategy import StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult, PortfolioTrade, SizingMode

from .backtest_job import BARS_PER_YEAR

log = logging.getLogger("strategy_lab.jobs.batch_backtest")


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class SymbolResult:
    """Per-(symbol, interval) backtest result."""

    symbol:           str
    interval:         str
    portfolio_result: PortfolioResult | None = None
    error:            str | None = None

    @property
    def ok(self) -> bool:
        return self.portfolio_result is not None and self.error is None

    @property
    def n_trades(self) -> int:
        if not self.ok:
            return 0
        return len(self.portfolio_result.trades)  # type: ignore[union-attr]

    @property
    def total_return(self) -> float:
        if not self.ok:
            return 0.0
        return self.portfolio_result.total_return  # type: ignore[union-attr]


@dataclass
class BatchBacktestResult:
    """Results of a multi-symbol/interval batch backtest.

    ``symbol_results``  — one entry per (symbol, interval) pair.
    ``portfolio_*``     — portfolio-level metrics from the chronological
                          shared-capital simulation (Phase 5).
    """

    symbol_results:         list[SymbolResult]
    starting_capital:       float

    # Portfolio-level equity curve (chronological shared-capital simulation)
    portfolio_equity_curve: pd.Series = field(
        default_factory=lambda: pd.Series(dtype=float)
    )

    # Aggregate portfolio metrics
    portfolio_total_return:  float = 0.0
    portfolio_net_profit:    float = 0.0
    portfolio_max_drawdown:  float = 0.0
    portfolio_sharpe:        float = 0.0
    portfolio_sortino:       float = 0.0
    portfolio_calmar:        float = 0.0
    portfolio_n_trades:      int   = 0
    portfolio_win_rate:      float = 0.0

    @property
    def successful_pairs(self) -> list[SymbolResult]:
        return [r for r in self.symbol_results if r.ok]

    @property
    def failed_pairs(self) -> list[SymbolResult]:
        return [r for r in self.symbol_results if not r.ok]


# ── Batch backtest engine ──────────────────────────────────────────────────────

class BatchBacktest:
    """Runs a strategy across a grid of (symbol × interval) pairs.

    Per-pair runs use the existing ``PortfolioEngine`` without modification.
    Portfolio-level simulation merges all trade events chronologically and
    replays them through a single shared capital pool (Phase 5).

    Args:
        symbols:          List of trading symbols, e.g. ["BTCUSDT", "ETHUSDT"].
        intervals:        List of timeframe strings, e.g. ["1h", "4h"].
        strategy_class:   ``StrategyBase`` subclass (not instantiated; one
                          instance is created per pair to ensure state isolation).
        params:           Strategy constructor kwargs.
        bars:             Pre-loaded OHLCV DataFrames keyed by (symbol, interval).
                          All bars in the dict must have the same columns as
                          BacktestExecutor expects (open, high, low, close, volume).
        starting_capital: Total portfolio capital.
        equity_fraction:  Fraction of current equity allocated per new position
                          in the portfolio simulation.  Does NOT affect per-pair
                          runs (which each receive the full starting_capital).
        engine_config:    Execution parameters (fees, slippage, SL/TP).
        max_workers:      If > 1, per-pair runs are parallelised with a thread
                          pool.  Use 1 to run sequentially (simpler, easier to
                          debug).
    """

    def __init__(
        self,
        symbols:          list[str],
        intervals:        list[str],
        strategy_class:   Type[StrategyBase],
        params:           dict[str, Any],
        bars:             dict[tuple[str, str], pd.DataFrame],
        starting_capital: float = 100_000.0,
        equity_fraction:  float = 0.10,
        engine_config:    EngineConfig | None = None,
        max_workers:      int = 1,
    ) -> None:
        if not symbols:
            raise ValueError("symbols must be a non-empty list")
        if not intervals:
            raise ValueError("intervals must be a non-empty list")
        if starting_capital <= 0:
            raise ValueError(f"starting_capital must be > 0, got {starting_capital!r}")
        if not (0.0 < equity_fraction <= 1.0):
            raise ValueError(f"equity_fraction must be in (0, 1], got {equity_fraction!r}")

        self.symbols          = list(symbols)
        self.intervals        = list(intervals)
        self.strategy_class   = strategy_class
        self.params           = dict(params)
        self.bars             = bars
        self.starting_capital = starting_capital
        self.equity_fraction  = equity_fraction
        self.engine_config    = engine_config or EngineConfig()
        self.max_workers      = max(1, max_workers)

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> BatchBacktestResult:
        """Execute the batch backtest and return aggregated results."""
        pairs = [
            (sym, iv)
            for sym in self.symbols
            for iv in self.intervals
        ]

        symbol_results = self._run_pairs(pairs)

        # Portfolio-level simulation
        portfolio_equity, portfolio_metrics = self._simulate_portfolio(symbol_results)

        return BatchBacktestResult(
            symbol_results=symbol_results,
            starting_capital=self.starting_capital,
            portfolio_equity_curve=portfolio_equity,
            **portfolio_metrics,
        )

    # ── Per-pair execution ─────────────────────────────────────────────────────

    def _run_pairs(self, pairs: list[tuple[str, str]]) -> list[SymbolResult]:
        if self.max_workers == 1 or len(pairs) == 1:
            return [self._run_one(sym, iv) for sym, iv in pairs]

        from concurrent.futures import ProcessPoolExecutor, as_completed
        results: list[SymbolResult | None] = [None] * len(pairs)
        with ProcessPoolExecutor(max_workers=self.max_workers) as pool:
            futs = {
                pool.submit(
                    _run_one_worker,
                    sym, iv,
                    self.strategy_class,
                    self.params,
                    self.bars.get((sym, iv)),
                    self.starting_capital,
                    self.engine_config,
                ): i
                for i, (sym, iv) in enumerate(pairs)
            }
            for fut in as_completed(futs):
                results[futs[fut]] = fut.result()
        return [r for r in results if r is not None]

    def _run_one(self, symbol: str, interval: str) -> SymbolResult:
        """Run a single (symbol, interval) pair with the full starting_capital."""
        key = (symbol, interval)
        if key not in self.bars:
            return SymbolResult(
                symbol=symbol,
                interval=interval,
                error=f"No bars data for {symbol} {interval}",
            )

        bars = self.bars[key]
        if bars.empty:
            return SymbolResult(
                symbol=symbol,
                interval=interval,
                error=f"Empty bars for {symbol} {interval}",
            )

        try:
            strategy  = self.strategy_class(**self.params)
            port_cfg  = PortfolioConfig(starting_capital=self.starting_capital)
            result    = PortfolioEngine(port_cfg).run(bars, strategy, self.engine_config)
            log.info(
                "Backtest %s %s: %d trades, return=%.2f%%",
                symbol, interval, len(result.trades), result.total_return * 100,
            )
            return SymbolResult(symbol=symbol, interval=interval, portfolio_result=result)
        except Exception as exc:
            log.warning("Backtest failed %s %s: %s", symbol, interval, exc)
            return SymbolResult(symbol=symbol, interval=interval, error=str(exc))

    # ── Portfolio-level simulation (Phase 5) ───────────────────────────────────

    def _simulate_portfolio(
        self,
        symbol_results: list[SymbolResult],
    ) -> tuple[pd.Series, dict]:
        """Chronological trade replay through a shared capital pool.

        Collects all trades from all per-pair runs, sorts them by entry_time,
        and replays each through a single equity pool.  The actual position
        size for each trade is determined by the current equity × equity_fraction
        at the moment the trade is entered.

        Returns:
            (equity_curve, metrics_dict) — equity_curve is a pd.Series indexed
            by trade exit times; metrics_dict contains portfolio_total_return,
            portfolio_net_profit, portfolio_max_drawdown, portfolio_sharpe,
            portfolio_sortino, portfolio_calmar, portfolio_n_trades,
            portfolio_win_rate.
        """
        # Collect all trades across all successful pairs
        tagged_trades: list[tuple[str, str, PortfolioTrade]] = []
        for sr in symbol_results:
            if not sr.ok or not sr.portfolio_result:
                continue
            for t in sr.portfolio_result.trades:
                tagged_trades.append((sr.symbol, sr.interval, t))

        if not tagged_trades:
            empty = pd.Series(
                [self.starting_capital],
                index=[pd.Timestamp.now(tz=timezone.utc)],
                dtype=float,
            )
            return empty, _zero_portfolio_metrics()

        # Sort by entry_time (chronological replay)
        tagged_trades.sort(key=lambda x: x[2].entry_time)

        # Replay events through shared capital pool
        equity = self.starting_capital
        peak   = equity
        equity_points: list[tuple[datetime, float]] = [
            (_ts(tagged_trades[0][2].entry_time), equity)
        ]

        trade_pnls: list[float] = []
        n_winners  = 0

        for sym, iv, trade in tagged_trades:
            # Size position based on current equity at entry time
            entry_price = trade.entry_price
            if entry_price <= 0:
                continue

            actual_size = (equity * self.equity_fraction) / entry_price
            if actual_size <= 0:
                continue

            # Scale pnl and fees linearly from unit-size run
            # unit_run used size=1.0 (PortfolioConfig default position_size=1.0
            # is overridden by PCT_OF_EQUITY runs; for FIXED_UNITS size=1.0 run,
            # trade.size is the actual size used by that run)
            unit_size = trade.size if trade.size > 0 else 1.0

            scale = actual_size / unit_size
            actual_gross = trade.gross_pnl * scale
            actual_fees  = (trade.entry_fee + trade.exit_fee) * scale
            actual_net   = actual_gross - actual_fees

            equity += actual_net
            trade_pnls.append(actual_net)
            if actual_net > 0:
                n_winners += 1

            if equity > peak:
                peak = equity

            equity_points.append((_ts(trade.exit_time), equity))

        # Build equity curve Series
        times   = [pt[0] for pt in equity_points]
        values  = [pt[1] for pt in equity_points]
        eq_series = pd.Series(values, index=pd.DatetimeIndex(times), dtype=float)
        eq_series = eq_series[~eq_series.index.duplicated(keep="last")]
        eq_series.sort_index(inplace=True)

        # Compute portfolio metrics
        n_trades   = len(trade_pnls)
        net_profit = equity - self.starting_capital
        total_ret  = net_profit / self.starting_capital if self.starting_capital > 0 else 0.0
        max_dd     = _max_drawdown(eq_series)
        win_rate   = n_winners / n_trades if n_trades > 0 else 0.0

        # Sharpe / Sortino from per-trade returns
        sharpe   = _sharpe_from_pnls(trade_pnls, self.starting_capital)
        sortino  = _sortino_from_pnls(trade_pnls, self.starting_capital)
        calmar   = total_ret / abs(max_dd) if max_dd < 0 else 0.0

        metrics = {
            "portfolio_total_return":  total_ret,
            "portfolio_net_profit":    net_profit,
            "portfolio_max_drawdown":  max_dd,
            "portfolio_sharpe":        sharpe,
            "portfolio_sortino":       sortino,
            "portfolio_calmar":        calmar,
            "portfolio_n_trades":      n_trades,
            "portfolio_win_rate":      win_rate,
        }
        return eq_series, metrics


# ── Module-level worker (must be top-level for ProcessPoolExecutor pickling) ────

def _run_one_worker(
    symbol:          str,
    interval:        str,
    strategy_class:  Type[StrategyBase],
    params:          dict[str, Any],
    bars:            "pd.DataFrame | None",
    starting_capital: float,
    engine_config:   EngineConfig,
) -> SymbolResult:
    """Picklable worker for ProcessPoolExecutor — runs one (symbol, interval) pair."""
    if bars is None or (hasattr(bars, "empty") and bars.empty):
        return SymbolResult(
            symbol=symbol, interval=interval,
            error=f"No bars data for {symbol} {interval}",
        )
    try:
        strategy = strategy_class(**params)
        port_cfg = PortfolioConfig(starting_capital=starting_capital)
        result   = PortfolioEngine(port_cfg).run(bars, strategy, engine_config)
        log.info(
            "Backtest %s %s: %d trades, return=%.2f%%",
            symbol, interval, len(result.trades), result.total_return * 100,
        )
        return SymbolResult(symbol=symbol, interval=interval, portfolio_result=result)
    except Exception as exc:
        log.warning("Backtest failed %s %s: %s", symbol, interval, exc)
        return SymbolResult(symbol=symbol, interval=interval, error=str(exc))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts(t: object) -> datetime:
    """Normalise any timestamp-like object to a UTC datetime."""
    if isinstance(t, datetime):
        if t.tzinfo is None:
            return t.replace(tzinfo=timezone.utc)
        return t
    if isinstance(t, pd.Timestamp):
        ts = t.to_pydatetime()
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    return datetime.now(timezone.utc)


def _max_drawdown(equity: pd.Series) -> float:
    """Return max drawdown as a negative fraction, e.g. -0.15 = 15% drawdown."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max.replace(0, np.nan)
    dd = dd.fillna(0.0)
    return float(dd.min())


def _sharpe_from_pnls(pnls: list[float], starting_capital: float) -> float:
    """Approximate Sharpe from trade-level PnL (not annualised)."""
    if len(pnls) < 2:
        return 0.0
    rets = [p / starting_capital for p in pnls]
    mu   = float(np.mean(rets))
    std  = float(np.std(rets, ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return _safe(mu / std)


def _sortino_from_pnls(pnls: list[float], starting_capital: float) -> float:
    """Approximate Sortino from trade-level PnL (not annualised)."""
    if len(pnls) < 2:
        return 0.0
    rets = [p / starting_capital for p in pnls]
    mu   = float(np.mean(rets))
    neg  = [r for r in rets if r < 0]
    if not neg:
        return 0.0
    downstd = float(np.std(neg, ddof=1)) if len(neg) > 1 else abs(neg[0])
    if downstd == 0 or math.isnan(downstd):
        return 0.0
    return _safe(mu / downstd)


def _safe(v: float) -> float:
    return 0.0 if (math.isnan(v) or math.isinf(v)) else v


def _zero_portfolio_metrics() -> dict:
    return {
        "portfolio_total_return": 0.0,
        "portfolio_net_profit":   0.0,
        "portfolio_max_drawdown": 0.0,
        "portfolio_sharpe":       0.0,
        "portfolio_sortino":      0.0,
        "portfolio_calmar":       0.0,
        "portfolio_n_trades":     0,
        "portfolio_win_rate":     0.0,
    }
