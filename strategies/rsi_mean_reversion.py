"""RSI Mean Reversion strategy."""
from __future__ import annotations

import pandas as pd

from engine.strategy import Signal, StrategyBase


class RSIMeanReversion(StrategyBase):
    """Long-only RSI mean reversion.

    Signal rules
    ------------
    - BUY  when RSI crosses **above** the oversold threshold (from below).
    - EXIT when RSI crosses **above** the overbought threshold (from below).
    - HOLD at all other bars.

    RSI is computed with Wilder's smoothing (``ewm(alpha=1/period, adjust=False)``),
    which is causal — bar i depends only on bars 0..i.
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ) -> None:
        if period < 2:
            raise ValueError(f"period ({period}) must be >= 2")
        if oversold >= overbought:
            raise ValueError(
                f"oversold ({oversold}) must be less than overbought ({overbought})"
            )
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        alpha = 1.0 / self.period
        avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
        avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.fillna(50.0)

        prev_rsi = rsi.shift(1).fillna(50.0)

        buy = (rsi >= self.oversold) & (prev_rsi < self.oversold)
        exit_ = (rsi >= self.overbought) & (prev_rsi < self.overbought)

        signals = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        signals[buy] = Signal.BUY
        signals[exit_] = Signal.EXIT
        return signals
