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

    Lookahead constraint
    --------------------
    Implementations **must** compute the signal for bar *i* using only
    information available at bar *i* — that is, bars[0..i].  Violating
    this constraint silently inflates backtest performance and produces
    results that cannot be reproduced in live trading.

    **Dangerous patterns that introduce lookahead bias:**

    * ``series.shift(-1)`` or ``series.shift(-n)`` — shifts future values
      backward, so bar *i* sees bar *i+1* (or later) data.
    * ``bars.iloc[i + 1]`` inside a loop — directly accesses the next bar.
    * Any forward-aligned rolling window, e.g.
      ``series.rolling(window=n, center=True)`` on an even window, or
      ``series.rolling(window=n).mean().shift(-k)`` — centres or
      right-aligns future values over past bars.
    * Fitting a model (e.g. linear regression, mean reversion threshold)
      on the *entire* ``bars`` DataFrame and then applying it to generate
      signals — the fit uses future data to inform past signals.
    * Using ``bars.index[-1]`` or ``len(bars)`` to special-case the last
      bar with knowledge that is only available at end-of-sample.

    **Safe patterns:**

    * Standard ``ewm(..., adjust=False).mean()`` — each value depends only
      on prior values (causal by construction).
    * ``series.rolling(window=n).mean()`` with default right-alignment —
      bar *i*'s value uses bars [i-n+1 .. i].
    * ``series.shift(n)`` with *n ≥ 1* — shifts past values forward;
      bar *i* sees bar *i-n*.
    * Any cumulative statistic (``cumsum``, ``cummax``, ``expanding``) —
      always uses bars[0..i] at bar *i*.

    The engine does **not** enforce this constraint programmatically;
    responsibility lies entirely with the strategy author.
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
