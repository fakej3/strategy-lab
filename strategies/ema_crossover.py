"""EMA Crossover strategy."""
from __future__ import annotations

import pandas as pd

from engine.strategy import Signal, StrategyBase


class EMACrossover(StrategyBase):
    """Long-only EMA crossover.

    Signal rules
    ------------
    - BUY  when the fast EMA crosses **above** the slow EMA.
    - EXIT when the fast EMA crosses **below** the slow EMA.
    - HOLD at all other bars.

    Both EMAs use ``adjust=False`` (recursive/standard EWM), which is
    causal by construction — bar i's EMA value depends only on bars 0..i.
    """

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")
        self.fast = fast
        self.slow = slow

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()

        crossed_up = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1))
        crossed_down = (fast_ema < slow_ema) & (fast_ema.shift(1) >= slow_ema.shift(1))

        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        signals[crossed_up] = Signal.BUY
        signals[crossed_down] = Signal.EXIT
        return signals
