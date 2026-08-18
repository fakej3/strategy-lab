"""Bollinger Band Mean Reversion strategy."""
from __future__ import annotations

import pandas as pd

from engine.strategy import Signal, StrategyBase


class BollingerBand(StrategyBase):
    """Long-only Bollinger Band mean reversion.

    Signal rules
    ------------
    - BUY  when price crosses **above** the lower band (from below).
    - EXIT when price crosses **above** the middle band (SMA) from below.
    - HOLD at all other bars.

    Uses a simple rolling window (causal — only past bars enter each window).
    """

    def __init__(self, period: int = 20, num_std: float = 2.0) -> None:
        if period < 2:
            raise ValueError(f"period ({period}) must be >= 2")
        if num_std <= 0:
            raise ValueError(f"num_std ({num_std}) must be > 0")
        self.period = period
        self.num_std = num_std

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        sma = close.rolling(self.period).mean()
        std = close.rolling(self.period).std(ddof=1)
        lower = sma - self.num_std * std

        prev_close = close.shift(1)
        prev_lower = lower.shift(1)
        prev_sma = sma.shift(1)

        buy = (close >= lower) & (prev_close < prev_lower)
        exit_ = (close >= sma) & (prev_close < prev_sma)

        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[exit_] = Signal.EXIT
        return signals
