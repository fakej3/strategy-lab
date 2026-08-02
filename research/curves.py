"""Return and metric curve builders for research analysis."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

# Re-export portfolio curve builders so callers can import from one place.
from portfolio.engine import (  # noqa: F401
    build_drawdown_curve,
    build_equity_curve,
)


def build_daily_returns(equity_curve: pd.Series) -> pd.Series:
    """Compute percentage returns between consecutive equity observations.

    The first bar has no prior bar, so its return is NaN and is dropped.

    Args:
        equity_curve: Bar-level equity values (e.g. from
                      ``portfolio.PortfolioEngine``).  Must be non-empty
                      and contain no zeros (division by prior equity).

    Returns:
        ``pd.Series`` of simple percentage returns (0.01 = 1 %) with the
        same index as *equity_curve* (minus the first element), named
        ``"returns"``.

    Usage example
    -------------
    >>> from research import build_daily_returns
    >>> returns = build_daily_returns(result.equity_curve)
    """
    pct = equity_curve.pct_change().dropna()
    pct.name = "returns"
    return pct


def build_monthly_returns(equity_curve: pd.Series) -> pd.Series:
    """Resample equity curve to month-end and compute monthly returns.

    Uses the last equity value in each calendar month.  Only months with
    at least one bar are included.

    Args:
        equity_curve: Bar-level equity values with a ``DatetimeIndex``.

    Returns:
        ``pd.Series`` of monthly simple returns, indexed by period-end
        dates, named ``"monthly_returns"``.  Empty if fewer than 2
        months are present.

    Usage example
    -------------
    >>> monthly = build_monthly_returns(result.equity_curve)
    >>> print(monthly.describe())
    """
    monthly = equity_curve.resample("ME").last()
    mr = monthly.pct_change().dropna()
    mr.name = "monthly_returns"
    return mr


def build_rolling_metric(
    equity_curve: pd.Series,
    metric_fn   : Callable[[pd.Series], float],
    window      : int,
    min_periods : int | None = None,
) -> pd.Series:
    """Apply a scalar metric function over a rolling equity window.

    Useful for visualising how Sharpe ratio, volatility, or any other
    scalar metric evolves through time without overfitting to a single
    in-sample period.

    Args:
        equity_curve: Bar-level equity values.
        metric_fn:    Callable that accepts a ``pd.Series`` of equity
                      values and returns a single ``float``.  It is
                      called once per window (after the rolling object's
                      ``apply`` step), receiving the *returns* of the
                      window rather than raw equity — unless the metric
                      needs raw equity, wrap it accordingly.
        window:       Number of bars in each rolling window.  Must be ≥ 2.
        min_periods:  Minimum observations required to produce a value.
                      Defaults to *window* (no partial windows).

    Returns:
        ``pd.Series`` indexed identically to *equity_curve*, named
        ``"rolling_metric"``.  Bars with fewer than *min_periods*
        observations are NaN.

    Raises:
        ValueError: If *window* < 2.

    Usage example
    -------------
    >>> from research import build_rolling_metric, calculate_research_metrics
    >>> def rolling_sharpe(returns):
    ...     if returns.std() == 0:
    ...         return 0.0
    ...     return (returns.mean() / returns.std()) * (252 ** 0.5)
    >>> rs = build_rolling_metric(result.equity_curve, rolling_sharpe, window=252)
    """
    if window < 2:
        raise ValueError(f"window must be ≥ 2, got {window}")

    mp = min_periods if min_periods is not None else window
    returns = equity_curve.pct_change()

    result = returns.rolling(window=window, min_periods=mp).apply(
        lambda arr: metric_fn(pd.Series(arr)), raw=False
    )
    result.name = "rolling_metric"
    return result
