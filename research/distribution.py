"""Return distribution analysis — percentiles, VaR/CVaR, streaks, drawdown durations."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def analyze_distribution(
    pnls: list[float],
    equity_curve: pd.Series,
    n_bins: int = 20,
) -> dict[str, Any]:
    """Analyse the trade PnL distribution.

    Args:
        pnls:         Per-trade PnL values.
        equity_curve: Bar-level equity curve for drawdown duration analysis.
        n_bins:       Number of histogram bins.

    Returns:
        Dict with: pct_5/25/50/75/95, var_5pct, cvar_5pct,
        max_consec_wins, max_consec_losses, histogram, dd_durations.
    """
    if not pnls:
        return _empty()

    arr = np.array(pnls, dtype=float)

    # ── Percentiles ───────────────────────────────────────────────────────────
    p5, p25, p50, p75, p95 = np.percentile(arr, [5, 25, 50, 75, 95])

    # ── VaR / CVaR at 5% ─────────────────────────────────────────────────────
    var_5  = float(p5)
    below  = arr[arr <= var_5]
    cvar_5 = float(below.mean()) if len(below) > 0 else var_5

    # ── Consecutive streaks ───────────────────────────────────────────────────
    max_wins = max_losses = cur_wins = cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins  += 1
            cur_losses = 0
        elif p < 0:
            cur_losses += 1
            cur_wins   = 0
        else:
            cur_wins = cur_losses = 0
        if cur_wins   > max_wins:   max_wins   = cur_wins
        if cur_losses > max_losses: max_losses = cur_losses

    # ── Histogram ─────────────────────────────────────────────────────────────
    counts, bin_edges = np.histogram(arr, bins=n_bins)
    histogram = {
        "bins"  : [round(float(e), 4) for e in bin_edges],
        "counts": [int(c) for c in counts],
    }

    # ── Drawdown durations from equity curve ──────────────────────────────────
    dd_durations = _compute_dd_durations(equity_curve)

    return {
        "pct_5"            : round(float(p5),  4),
        "pct_25"           : round(float(p25), 4),
        "pct_50"           : round(float(p50), 4),
        "pct_75"           : round(float(p75), 4),
        "pct_95"           : round(float(p95), 4),
        "var_5pct"         : round(var_5, 4),
        "cvar_5pct"        : round(cvar_5, 4),
        "max_consec_wins"  : max_wins,
        "max_consec_losses": max_losses,
        "histogram"        : histogram,
        "dd_durations"     : dd_durations,
    }


def _compute_dd_durations(equity_curve: pd.Series) -> dict[str, Any]:
    """Measure length (bars) of each drawdown period in the equity curve."""
    if len(equity_curve) < 2:
        return {"max_bars": 0, "avg_bars": None, "median_bars": None, "n_periods": 0}

    eq        = equity_curve.to_numpy(dtype=float)
    peak      = eq[0]
    in_dd     = False
    start     = 0
    durations: list[int] = []

    for i, val in enumerate(eq):
        if val > peak:
            if in_dd:
                durations.append(i - start)
                in_dd = False
            peak = val
        elif val < peak and not in_dd:
            in_dd = True
            start = i

    if in_dd:
        durations.append(len(eq) - start)

    if not durations:
        return {"max_bars": 0, "avg_bars": None, "median_bars": None, "n_periods": 0}

    arr = np.array(durations, dtype=float)
    return {
        "max_bars"   : int(arr.max()),
        "avg_bars"   : round(float(arr.mean()), 2),
        "median_bars": round(float(np.median(arr)), 2),
        "n_periods"  : len(durations),
    }


def _empty() -> dict:
    return {
        "pct_5": None, "pct_25": None, "pct_50": None,
        "pct_75": None, "pct_95": None,
        "var_5pct": None, "cvar_5pct": None,
        "max_consec_wins": 0, "max_consec_losses": 0,
        "histogram": {"bins": [], "counts": []},
        "dd_durations": {
            "max_bars": 0, "avg_bars": None, "median_bars": None, "n_periods": 0,
        },
    }
