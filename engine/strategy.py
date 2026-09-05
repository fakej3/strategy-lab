"""Strategy interfaces used by the backtest engine."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(str, Enum):
    """Trading signals produced by a strategy."""

    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    HOLD = "HOLD"


class StrategyBase(ABC):
    """Legacy/full-data strategy interface.

    ``generate_signals`` receives the full dataset. Implementations therefore
    remain responsible for ensuring that each signal only uses information
    available at that bar. New V2 research code should prefer
    :class:`CausalStrategyBase`, which makes the information boundary explicit.
    """

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Return one Signal per bar."""
        raise NotImplementedError


class CausalStrategyBase(StrategyBase):
    """V2 strategy interface with an engine-enforced information boundary.

    The engine calls ``generate_signal(history)`` once per bar, where
    ``history`` contains bars from the start of the dataset through the current
    bar only. A strategy never receives the future portion of the dataset.
    """

    @abstractmethod
    def generate_signal(self, history: pd.DataFrame) -> Signal:
        """Generate a signal using only the supplied historical bars."""
        raise NotImplementedError

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Generate signals through the causal one-bar-at-a-time API."""
        values = [self.generate_signal(bars.iloc[: i + 1].copy()) for i in range(len(bars))]
        return pd.Series(values, index=bars.index, dtype=object)
