"""MACD Crossover strategy."""
from __future__ import annotations

import pandas as pd

from engine.strategy import Signal, StrategyBase


class MACDCrossover(StrategyBase):
    """Long-only MACD signal-line crossover.

    Signal rules
    ------------
    - BUY  when the MACD line crosses **above** the signal line.
    - EXIT when the MACD line crosses **below** the signal line.
    - HOLD at all other bars.

    All EMAs use ``adjust=False`` (causal, recursive).
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")
        if signal < 1:
            raise ValueError(f"signal ({signal}) must be >= 1")
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()
        macd = fast_ema - slow_ema
        signal_line = macd.ewm(span=self.signal, adjust=False).mean()

        prev_macd = macd.shift(1)
        prev_signal = signal_line.shift(1)

        crossed_up = (macd > signal_line) & (prev_macd <= prev_signal)
        crossed_down = (macd < signal_line) & (prev_macd >= prev_signal)

        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        signals[crossed_up] = Signal.BUY
        signals[crossed_down] = Signal.EXIT
        return signals
