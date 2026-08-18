"""Donchian Channel Breakout strategy."""
from __future__ import annotations

import pandas as pd

from engine.strategy import Signal, StrategyBase


class DonchianBreakout(StrategyBase):
    """Long-only Donchian channel breakout.

    Signal rules
    ------------
    - BUY  when the close breaks **above** the prior N-bar high.
    - EXIT when the close breaks **below** the prior M-bar low.
    - HOLD at all other bars.

    Prior N-bar high/low are computed from bars *before* the current bar
    (``shift(1)`` + rolling) so there is no lookahead bias.
    """

    def __init__(self, entry_period: int = 20, exit_period: int = 10) -> None:
        if entry_period < 2:
            raise ValueError(f"entry_period ({entry_period}) must be >= 2")
        if exit_period < 2:
            raise ValueError(f"exit_period ({exit_period}) must be >= 2")
        self.entry_period = entry_period
        self.exit_period = exit_period

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        high = bars["high"]
        low = bars["low"]

        # Use prior bars only (shift ensures bar i sees bars 0..i-1)
        prior_high = high.shift(1).rolling(self.entry_period).max()
        prior_low = low.shift(1).rolling(self.exit_period).min()

        prev_close = close.shift(1)

        buy = (close > prior_high) & (prev_close <= prior_high)
        exit_ = (close < prior_low) & (prev_close >= prior_low)

        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[exit_] = Signal.EXIT
        return signals
