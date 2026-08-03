"""Market regime classification and per-regime strategy performance analysis."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


BULL     = "Bull"
BEAR     = "Bear"
SIDEWAYS = "Sideways"
HIGH_VOL = "HighVol"
LOW_VOL  = "LowVol"

_ALL_REGIMES = (BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL)


def classify_regimes(
    bars: pd.DataFrame,
    window: int = 20,
    trend_threshold: float = 0.01,
    high_vol_mult: float = 1.5,
    low_vol_mult: float = 0.75,
) -> pd.Series:
    """Return a Series of regime labels aligned to *bars*.

    Labels: Bull, Bear, Sideways, HighVol, LowVol.
    Volatility overrides trend when extreme.
    First *window* bars are labelled Sideways (insufficient history).

    Args:
        bars:             OHLCV DataFrame indexed by timestamp.
        window:           Look-back window for rolling stats.
        trend_threshold:  ±threshold for Bull/Bear classification.
        high_vol_mult:    Multiplier above median vol → HighVol.
        low_vol_mult:     Multiplier below median vol → LowVol.
    """
    close      = bars["close"]
    pct_change = close.pct_change()
    rolling_ret = (close / close.shift(window) - 1).fillna(0.0)
    rolling_vol = pct_change.rolling(window).std().fillna(0.0)

    valid_vol  = rolling_vol.iloc[window:]
    median_vol = float(valid_vol.median()) if len(valid_vol) > 0 else 0.0

    labels = pd.Series(SIDEWAYS, index=bars.index, dtype=object)

    if median_vol == 0.0:
        return labels

    ret_arr = rolling_ret.to_numpy(dtype=float)
    vol_arr = rolling_vol.to_numpy(dtype=float)

    result = np.full(len(bars), SIDEWAYS, dtype=object)
    for i in range(len(bars)):
        if i < window:
            result[i] = SIDEWAYS
            continue
        v = vol_arr[i]
        r = ret_arr[i]
        if v > high_vol_mult * median_vol:
            result[i] = HIGH_VOL
        elif v < low_vol_mult * median_vol:
            result[i] = LOW_VOL
        elif r > trend_threshold:
            result[i] = BULL
        elif r < -trend_threshold:
            result[i] = BEAR
        else:
            result[i] = SIDEWAYS

    return pd.Series(result, index=bars.index, dtype=object)


def analyze_per_regime(
    bars: pd.DataFrame,
    trades: list,
    equity_curve: pd.Series,
    window: int = 20,
) -> dict[str, Any]:
    """Compute per-regime stats for a strategy's trade list.

    Assigns each trade to the regime at its entry bar.

    Returns:
        Dict with:
          - "labels": list of [timestamp_str, regime_label] pairs
          - "regime_stats": dict mapping regime → stats dict
    """
    regime_labels = classify_regimes(bars, window=window)

    # Build regime_stats, assigning each trade to the regime at entry_time
    trade_regimes: dict[str, list] = {r: [] for r in _ALL_REGIMES}

    for trade in trades:
        entry_ts = getattr(trade, "entry_time", None)
        if entry_ts is None:
            continue
        label = _lookup_regime(regime_labels, entry_ts)
        trade_regimes[label].append(trade)

    regime_stats: dict[str, dict] = {}
    for regime in _ALL_REGIMES:
        ts = trade_regimes[regime]
        n  = len(ts)
        if n == 0:
            regime_stats[regime] = {
                "n_trades": 0, "win_rate": None, "profit_factor": None,
                "avg_pnl": None, "total_pnl": None,
            }
            continue

        pnls    = [t.net_pnl for t in ts]
        winners = [p for p in pnls if p > 0]
        losers  = [abs(p) for p in pnls if p < 0]
        win_rate = len(winners) / n
        gross_p  = sum(winners)
        gross_l  = sum(losers)
        pf       = gross_p / gross_l if gross_l > 0 else (999.0 if gross_p > 0 else 0.0)
        avg_pnl  = float(np.mean(pnls))

        regime_stats[regime] = {
            "n_trades"     : n,
            "win_rate"     : round(win_rate, 4),
            "profit_factor": round(min(pf, 999.0), 4),
            "avg_pnl"      : round(avg_pnl, 4),
            "total_pnl"    : round(float(sum(pnls)), 4),
        }

    # Compact label list: [ts_str, label], downsampled to ≤500 points for storage
    import math as _math
    all_labels = [[str(ts), lbl] for ts, lbl in zip(regime_labels.index, regime_labels)]
    if len(all_labels) > 500:
        step       = _math.ceil(len(all_labels) / 500)  # guarantees result ≤ 500
        all_labels = all_labels[::step]

    return {
        "labels"      : all_labels,
        "regime_stats": regime_stats,
    }


def _lookup_regime(regime_labels: pd.Series, entry_time) -> str:
    """Find the regime label at or just before entry_time."""
    idx = regime_labels.index
    pos = idx.searchsorted(entry_time, side="right")
    if pos == 0:
        return SIDEWAYS
    return str(regime_labels.iloc[pos - 1])
