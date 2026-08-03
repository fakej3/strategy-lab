"""Strategy performance degradation — first/second half and thirds comparison."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def analyze_degradation(trades: list) -> dict[str, Any]:
    """Detect performance decay across a trade list.

    Splits trades into first/second halves and thirds.
    Computes per-segment: trade-level Sharpe, win rate, profit factor.
    Returns degradation_score in [0, 100] — higher = less degradation.

    Args:
        trades: Ordered list of PortfolioTrade objects.
    """
    n = len(trades)
    if n < 6:
        return _empty()

    mid = n // 2
    t1, t2 = trades[:mid], trades[mid:]

    t3 = n // 3
    s1, s2, s3 = trades[:t3], trades[t3:2 * t3], trades[2 * t3:]

    h1_sh = _trade_sharpe(t1)
    h2_sh = _trade_sharpe(t2)
    h1_wr = _win_rate(t1)
    h2_wr = _win_rate(t2)
    h1_pf = _profit_factor(t1)
    h2_pf = _profit_factor(t2)

    th1_sh = _trade_sharpe(s1)
    th2_sh = _trade_sharpe(s2)
    th3_sh = _trade_sharpe(s3)

    # ── Degradation score: 100 minus penalties ─────────────────────────────────
    penalty = 0.0

    # Sharpe decay penalty (40 pts max)
    if h1_sh is not None and h2_sh is not None and h1_sh > 0:
        decay    = (h1_sh - h2_sh) / max(h1_sh, 0.5)
        penalty += min(40.0, max(0.0, decay / 2.0 * 40.0))

    # Win-rate decay penalty (30 pts max)
    if h1_wr is not None and h2_wr is not None and h1_wr > 0:
        decay    = (h1_wr - h2_wr) / max(h1_wr, 0.2)
        penalty += min(30.0, max(0.0, decay / 0.5 * 30.0))

    # Profit-factor decay penalty (30 pts max)
    if h1_pf is not None and h2_pf is not None and h1_pf > 1.0:
        decay    = (h1_pf - h2_pf) / max(h1_pf, 1.0)
        penalty += min(30.0, max(0.0, decay / 2.0 * 30.0))

    score = max(0.0, 100.0 - penalty)

    return {
        "degradation_score"  : round(score, 2),
        "first_half_sharpe"  : _r(h1_sh),
        "second_half_sharpe" : _r(h2_sh),
        "first_half_wr"      : _r(h1_wr),
        "second_half_wr"     : _r(h2_wr),
        "first_half_pf"      : _r(h1_pf),
        "second_half_pf"     : _r(h2_pf),
        "first_third_sharpe" : _r(th1_sh),
        "second_third_sharpe": _r(th2_sh),
        "third_third_sharpe" : _r(th3_sh),
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _trade_sharpe(trades: list) -> float | None:
    """Trade-level Sharpe: mean(pnl) / std(pnl).  No annualisation."""
    if len(trades) < 2:
        return None
    pnls = np.array([t.net_pnl for t in trades], dtype=float)
    std  = float(pnls.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(pnls.mean() / std)


def _win_rate(trades: list) -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t.net_pnl > 0) / len(trades)


def _profit_factor(trades: list) -> float | None:
    if not trades:
        return None
    gross = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    loss  = sum(-t.net_pnl for t in trades if t.net_pnl < 0)
    if loss == 0.0:
        return 999.0 if gross > 0 else 0.0
    return round(gross / loss, 4)


def _r(v: float | None, d: int = 4) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _empty() -> dict:
    return {
        "degradation_score"  : None,
        "first_half_sharpe"  : None, "second_half_sharpe" : None,
        "first_half_wr"      : None, "second_half_wr"     : None,
        "first_half_pf"      : None, "second_half_pf"     : None,
        "first_third_sharpe" : None, "second_third_sharpe": None,
        "third_third_sharpe" : None,
    }
