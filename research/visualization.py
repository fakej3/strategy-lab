"""Visualization data structures — matplotlib/plotly-ready, no GUI dependency."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from portfolio.models import PortfolioResult, PortfolioTrade
from research.metrics import InstitutionalMetrics


@dataclass
class VisualizationData:
    """Pre-computed, plot-ready data derived from a portfolio backtest.

    Every attribute is either a plain Python list, a dict, or a simple
    numeric value — no matplotlib or plotly objects are created here.
    Pass these arrays directly to your preferred plotting library.

    Attributes
    ----------
    timestamps : list of bar timestamps (from equity_curve index).
    equity     : list of float — portfolio equity at each bar.
    balance    : list of float — realized balance at each bar.
    drawdown   : list of float — drawdown fraction (≤ 0) at each bar.
    trade_entries : list of (timestamp, price) tuples — entry points.
    trade_exits   : list of (timestamp, price, pnl) tuples — exit points.
    monthly_pnl   : dict mapping "YYYY-MM" → total PnL for that month.
    pnl_histogram_bins   : bin edges for a PnL distribution histogram.
    pnl_histogram_counts : count per bin.
    rolling_equity_peak  : list of float — running all-time high of equity.
    """

    timestamps           : list
    equity               : list[float]
    balance              : list[float]
    drawdown             : list[float]
    trade_entries        : list[tuple]
    trade_exits          : list[tuple]
    monthly_pnl          : dict[str, float]
    pnl_histogram_bins   : list[float]
    pnl_histogram_counts : list[int]
    rolling_equity_peak  : list[float]


def build_visualization_data(
    portfolio_result: PortfolioResult,
    n_pnl_bins      : int = 20,
) -> VisualizationData:
    """Build plot-ready data arrays from a :class:`~portfolio.PortfolioResult`.

    No matplotlib or plotly is imported or used here.  The returned
    :class:`VisualizationData` can be serialised or passed directly to
    any plotting library.

    Args:
        portfolio_result: Output of :class:`~portfolio.PortfolioEngine`.
        n_pnl_bins:       Number of bins for the PnL histogram.

    Returns:
        :class:`VisualizationData` populated with all curve data and
        trade marker coordinates.

    Usage example
    -------------
    >>> from research import build_visualization_data
    >>> import matplotlib.pyplot as plt
    >>>
    >>> vdata = build_visualization_data(result)
    >>> plt.plot(vdata.timestamps, vdata.equity, label="Equity")
    >>> plt.fill_between(vdata.timestamps, vdata.drawdown, 0, alpha=0.3, label="DD")
    >>> plt.show()
    """
    ec = portfolio_result.equity_curve
    bc = portfolio_result.balance_curve
    dc = portfolio_result.drawdown_curve

    timestamps = list(ec.index)
    equity     = ec.tolist()
    balance    = bc.tolist()
    drawdown   = dc.tolist()

    rolling_peak = ec.cummax().tolist()

    trades = portfolio_result.trades

    entries: list[tuple] = []
    exits  : list[tuple] = []

    for t in trades:
        entries.append((t.entry_time, t.entry_price))
        exits.append((t.exit_time, t.exit_price, t.net_pnl))

    # Monthly PnL
    monthly_pnl: dict[str, float] = {}
    for t in trades:
        try:
            key = str(t.exit_time)[:7]  # "YYYY-MM"
        except Exception:
            key = "unknown"
        monthly_pnl[key] = monthly_pnl.get(key, 0.0) + t.net_pnl

    # PnL histogram
    pnls = [t.net_pnl for t in trades]
    if pnls:
        arr    = np.array(pnls, dtype=float)
        counts, bin_edges = np.histogram(arr, bins=n_pnl_bins)
        hist_bins   = bin_edges.tolist()
        hist_counts = counts.tolist()
    else:
        hist_bins   = []
        hist_counts = []

    return VisualizationData(
        timestamps           = timestamps,
        equity               = equity,
        balance              = balance,
        drawdown             = drawdown,
        trade_entries        = entries,
        trade_exits          = exits,
        monthly_pnl          = monthly_pnl,
        pnl_histogram_bins   = hist_bins,
        pnl_histogram_counts = hist_counts,
        rolling_equity_peak  = rolling_peak,
    )
