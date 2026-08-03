"""Buy-and-hold benchmark and alpha/beta computation (no scipy)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BenchmarkResult:
    """Outcome of comparing a strategy against a buy-and-hold benchmark.

    Attributes
    ----------
    benchmark_return : float
        Total simple return of the buy-and-hold benchmark over the period.
    strategy_return : float
        Total simple return of the strategy equity curve over the period.
    excess_return : float
        ``strategy_return − benchmark_return``.
    alpha : float
        Jensen's alpha: annualised intercept from OLS regression of
        strategy excess returns on benchmark excess returns.
    beta : float
        OLS slope of strategy returns on benchmark returns.  A beta of
        1.0 indicates returns move in lockstep with the benchmark.
    tracking_error : float
        Annualised standard deviation of ``strategy − benchmark`` returns.
    information_ratio : float
        ``excess_return_annualised / tracking_error``.  0.0 when
        tracking error is zero.
    correlation : float
        Pearson correlation between strategy and benchmark per-bar returns.
    benchmark_equity : pd.Series
        Bar-level equity curve of the buy-and-hold position, scaled to
        the same starting capital as the strategy.
    """

    benchmark_return  : float
    strategy_return   : float
    excess_return     : float
    alpha             : float
    beta              : float
    tracking_error    : float
    information_ratio : float
    correlation       : float
    benchmark_equity  : pd.Series


class BuyAndHoldBenchmark:
    """Simulate buying at the first bar open and holding to the last bar.

    The benchmark owns ``starting_capital / open_price`` units of the
    asset and marks them to market at each bar's close.

    Args:
        starting_capital: Initial portfolio value in quote currency.

    Usage example
    -------------
    >>> from research import BuyAndHoldBenchmark
    >>> bench = BuyAndHoldBenchmark(starting_capital=100_000)
    >>> result = bench.run(bars)
    >>> print(f"B&H return: {result.benchmark_return:.2%}")
    """

    def __init__(self, starting_capital: float = 100_000.0) -> None:
        if starting_capital <= 0:
            raise ValueError(
                f"starting_capital must be > 0, got {starting_capital!r}"
            )
        self.starting_capital = starting_capital

    def run(self, bars: pd.DataFrame) -> pd.Series:
        """Build a bar-level buy-and-hold equity curve.

        Args:
            bars: OHLCV DataFrame with at least ``open`` and ``close``
                  columns and a DatetimeIndex.

        Returns:
            ``pd.Series`` indexed by ``bars.index`` with name
            ``"bh_equity"``, representing mark-to-market equity at each
            bar's close.

        Raises:
            ValueError: If ``bars`` is empty or the first open price is ≤ 0.
        """
        if bars.empty:
            raise ValueError("bars is empty — cannot build benchmark.")

        entry_price = float(bars["open"].iloc[0])
        if entry_price <= 0:
            raise ValueError(
                f"First bar open price must be > 0, got {entry_price!r}"
            )

        units  = self.starting_capital / entry_price
        equity = bars["close"] * units
        equity.name = "bh_equity"
        return equity


def compute_alpha_beta(
    strategy_equity : pd.Series,
    benchmark_equity: pd.Series,
    bars_per_year   : int   = 252,
    risk_free_rate  : float = 0.0,
) -> BenchmarkResult:
    """Compare a strategy to a benchmark and compute alpha, beta, and related stats.

    Uses ordinary least squares (manual implementation, no scipy) to
    regress strategy excess returns on benchmark excess returns.

    Args:
        strategy_equity:  Bar-level equity of the strategy.
        benchmark_equity: Bar-level equity of the benchmark (e.g. from
                          :meth:`BuyAndHoldBenchmark.run`).  Must share
                          the same index.
        bars_per_year:    Annualisation factor (252 for daily, 8760 for
                          hourly crypto).
        risk_free_rate:   Annual risk-free rate as a decimal.

    Returns:
        :class:`BenchmarkResult` with all comparative statistics.

    Raises:
        ValueError: If the two series cannot be aligned (no common dates).

    Usage example
    -------------
    >>> from research import BuyAndHoldBenchmark, compute_alpha_beta
    >>> bench   = BuyAndHoldBenchmark(100_000)
    >>> bh      = bench.run(bars)
    >>> result  = compute_alpha_beta(portfolio_result.equity_curve, bh)
    >>> print(f"Alpha: {result.alpha:.4f}  Beta: {result.beta:.4f}")
    """
    s_ret = strategy_equity.pct_change().dropna()
    b_ret = benchmark_equity.pct_change().dropna()

    s_aligned, b_aligned = s_ret.align(b_ret, join="inner")

    if len(s_aligned) < 2:
        raise ValueError(
            "Fewer than 2 common bars between strategy and benchmark — "
            "cannot compute alpha/beta."
        )

    rf_per_bar = (1 + risk_free_rate) ** (1 / bars_per_year) - 1

    s_excess = (s_aligned - rf_per_bar).to_numpy(dtype=float)
    b_excess = (b_aligned - rf_per_bar).to_numpy(dtype=float)

    # OLS: y = alpha_bar + beta * x  (per bar)
    b_mean    = b_excess.mean()
    s_mean    = s_excess.mean()
    cov_sb    = ((b_excess - b_mean) * (s_excess - s_mean)).mean()
    var_b     = ((b_excess - b_mean) ** 2).mean()

    beta      = cov_sb / var_b if var_b > 0 else 0.0
    alpha_bar = s_mean - beta * b_mean
    alpha_ann = alpha_bar * bars_per_year

    # Tracking error and information ratio
    active         = s_aligned - b_aligned
    tracking_error = float(active.std(ddof=1)) * math.sqrt(bars_per_year)

    active_mean_ann = float(active.mean()) * bars_per_year
    ir = active_mean_ann / tracking_error if tracking_error > 0 else 0.0

    # Correlation — use raw returns (not excess) for Pearson correlation.
    # cov_sb was computed from excess returns; recompute from raw returns here.
    s_raw = s_aligned.to_numpy(dtype=float)
    b_raw = b_aligned.to_numpy(dtype=float)
    s_std = float(s_raw.std(ddof=1))
    b_std = float(b_raw.std(ddof=1))
    if s_std > 0 and b_std > 0:
        cov_raw = float(((s_raw - s_raw.mean()) * (b_raw - b_raw.mean())).mean())
        corr    = cov_raw / (s_std * b_std)
    else:
        corr = 0.0

    # Total returns
    s_total = float(strategy_equity.iloc[-1] / strategy_equity.iloc[0]) - 1
    b_total = float(benchmark_equity.iloc[-1] / benchmark_equity.iloc[0]) - 1

    return BenchmarkResult(
        benchmark_return  = b_total,
        strategy_return   = s_total,
        excess_return     = s_total - b_total,
        alpha             = alpha_ann,
        beta              = beta,
        tracking_error    = tracking_error,
        information_ratio = ir,
        correlation       = corr,
        benchmark_equity  = benchmark_equity,
    )
