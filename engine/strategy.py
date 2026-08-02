"""StrategyBase — the interface every strategy must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(str, Enum):
    """Trading signals produced by a strategy.

    Strategies produce signals; the engine translates them into fills.

    BUY   — enter a long position (ignored if already long).
    EXIT  — close the current position (ignored if flat).
    SELL  — reserved for short entry; currently treated as EXIT.
    HOLD  — do nothing.
    """

    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    HOLD = "HOLD"


class StrategyBase(ABC):
    """Base class for all backtesting strategies.

    Strategies decide *what* signal to emit on each bar.
    They never execute trades, manage positions, or know about fees.

    The engine guarantees:
    - ``generate_signals`` is called once with the full bar history.
    - A BUY signal at bar T is filled at bar T+1 open.
    - An EXIT/SELL signal at bar T is filled at bar T+1 open.

    Lookahead constraint: implementations must compute signals for bar i
    using only bars[0..i].  Standard pandas rolling/ewm operations and
    positive-lag ``shift(n)`` satisfy this automatically.  Never use
    negative-lag shifts or index-ahead slices.
    """

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Return one Signal per bar.

        Args:
            bars: OHLCV DataFrame produced by ``data.get_bars()``.
                  Columns: open, high, low, close, volume.
                  Index: UTC DatetimeIndex, name="open_time".

        Returns:
            ``pd.Series`` of ``Signal`` values with the same index as bars.
        """
