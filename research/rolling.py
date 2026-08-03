"""Rolling performance metrics — Sharpe, Sortino, CAGR, drawdown, win rate, PF."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def compute_rolling_metrics(
    equity_curve: pd.Series,
    trades: list,
    bars_per_year: int = 8760,
    window: int | None = None,
) -> dict[str, Any]:
    """Compute rolling performance metrics over a sliding window.

    Equity-based metrics (Sharpe, Sortino, CAGR, drawdown) are computed
    at every bar from the equity curve.
    Trade metrics (win_rate, profit_factor, expectancy) use trades whose
    ``exit_bar`` falls inside the rolling window.

    Args:
        equity_curve:  Bar-level portfolio equity Series.
        trades:        List of PortfolioTrade objects.
        bars_per_year: Annualisation factor.
        window:        Rolling window in bars (default: max(20, bars_per_year//52)).

    Returns:
        Dict with: window, timestamps, sharpe, sortino, cagr,
        drawdown, win_rate, profit_factor, expectancy.
        Each series is a list of floats (None where no trades in window).
    """
    if window is None:
        window = max(20, bars_per_year // 52)

    n = len(equity_curve)
    if n < window + 1:
        return _empty(window)

    eq     = equity_curve.to_numpy(dtype=float)
    ts_arr = equity_curve.index
    # Bar returns (length = n-1)
    prev   = np.maximum(eq[:-1], 1e-10)
    ret    = (eq[1:] - eq[:-1]) / prev

    # Sort trades by exit_bar for efficient binary search
    valid_trades = [t for t in trades if hasattr(t, "exit_bar")]
    sorted_trades = sorted(valid_trades, key=lambda t: t.exit_bar)

    timestamps: list[str]         = []
    sharpe_out: list[float]       = []
    sortino_out: list[float]      = []
    cagr_out: list[float]         = []
    dd_out: list[float]           = []
    wr_out: list[float | None]    = []
    pf_out: list[float | None]    = []
    exp_out: list[float | None]   = []

    for end in range(window, n):
        start   = end - window
        w_ret   = ret[start:end]       # window-1 returns leading into bar 'end'
        w_eq    = eq[start:end + 1]    # window+1 equity values

        timestamps.append(str(ts_arr[end]))

        # ── Sharpe ────────────────────────────────────────────────────────────
        r_mean = float(w_ret.mean())
        r_std  = float(w_ret.std(ddof=1))
        sharpe_out.append(round(r_mean / r_std * math.sqrt(bars_per_year), 4)
                          if r_std > 0 else 0.0)

        # ── Sortino ───────────────────────────────────────────────────────────
        neg_sq   = np.minimum(w_ret, 0.0) ** 2
        down_std = math.sqrt(float(neg_sq.mean())) * math.sqrt(bars_per_year)
        sortino_out.append(round(r_mean * bars_per_year / down_std, 4)
                           if down_std > 0 else 0.0)

        # ── Rolling CAGR ──────────────────────────────────────────────────────
        s_eq, e_eq = float(w_eq[0]), float(w_eq[-1])
        if s_eq > 0 and e_eq > 0:
            n_years  = window / bars_per_year
            cagr_val = (e_eq / s_eq) ** (1.0 / n_years) - 1 if n_years > 0 else 0.0
        else:
            cagr_val = 0.0
        cagr_out.append(round(cagr_val, 4))

        # ── Max drawdown in window ─────────────────────────────────────────────
        peak   = np.maximum.accumulate(w_eq)
        dd_arr = (w_eq - peak) / np.maximum(peak, 1e-10)
        dd_out.append(round(float(-dd_arr.min()), 4))

        # ── Trade metrics in window ────────────────────────────────────────────
        lo = _bisect_left(sorted_trades, start, key=lambda t: t.exit_bar)
        hi = _bisect_right(sorted_trades, end,   key=lambda t: t.exit_bar)
        wt = sorted_trades[lo:hi]

        if wt:
            pnls  = [t.net_pnl for t in wt]
            wr    = sum(1 for p in pnls if p > 0) / len(pnls)
            gross = sum(p for p in pnls if p > 0)
            loss  = sum(-p for p in pnls if p < 0)
            pf    = gross / loss if loss > 0 else (999.0 if gross > 0 else 0.0)
            exp   = float(np.mean(pnls))
            wr_out.append(round(wr, 4))
            pf_out.append(round(min(pf, 999.0), 4))
            exp_out.append(round(exp, 4))
        else:
            wr_out.append(None)
            pf_out.append(None)
            exp_out.append(None)

    return {
        "window"       : window,
        "timestamps"   : timestamps,
        "sharpe"       : sharpe_out,
        "sortino"      : sortino_out,
        "cagr"         : cagr_out,
        "drawdown"     : dd_out,
        "win_rate"     : wr_out,
        "profit_factor": pf_out,
        "expectancy"   : exp_out,
    }


# ── Binary search helpers (no stdlib bisect import needed) ─────────────────────

def _bisect_left(lst: list, val, key) -> int:
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(lst[mid]) < val:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(lst: list, val, key) -> int:
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi) // 2
        if key(lst[mid]) <= val:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _empty(window: int) -> dict:
    return {
        "window": window, "timestamps": [], "sharpe": [], "sortino": [],
        "cagr": [], "drawdown": [], "win_rate": [], "profit_factor": [],
        "expectancy": [],
    }
