"""Portfolio layer data models — configuration, trades, and results."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from engine.models import ExitReason


class SizingMode(str, Enum):
    """Position sizing strategy applied by the portfolio engine.

    FIXED_UNITS   — constant number of base-asset units per trade (e.g. 1 BTC).
    PCT_OF_EQUITY — fraction of current equity converted to units at entry price
                    (e.g. 0.10 = 10% of equity).  Compounds: later trades are
                    larger when the account has grown.
    FIXED_DOLLAR  — fixed quote-currency amount converted to units at entry price
                    (e.g. $10,000 worth of BTC per trade).
    FRACTIONAL    — user-supplied fraction of equity; designed for Kelly or other
                    mathematically derived sizing rules.

    Usage example
    -------------
    >>> cfg = PortfolioConfig(
    ...     starting_capital=100_000,
    ...     sizing_mode=SizingMode.PCT_OF_EQUITY,
    ...     equity_fraction=0.05,   # risk 5% of equity per trade
    ... )
    """

    FIXED_UNITS   = "fixed_units"
    PCT_OF_EQUITY = "pct_of_equity"
    FIXED_DOLLAR  = "fixed_dollar"
    FRACTIONAL    = "fractional"


@dataclass
class PortfolioConfig:
    """Configuration for the portfolio engine.

    Parameters
    ----------
    starting_capital : float
        Initial account balance in quote currency (e.g. USD).
    sizing_mode : SizingMode
        Determines how position size is computed at each entry.
    position_size : float
        Units per trade — used only when sizing_mode is FIXED_UNITS.
        Must be > 0.
    equity_fraction : float
        Fraction of current equity per trade — used with PCT_OF_EQUITY.
        Must be in (0, 1].
    trade_capital : float
        Fixed quote-currency amount per trade — used with FIXED_DOLLAR.
        Size = trade_capital / entry_fill_price.  Must be > 0.
    fraction : float
        Custom fraction of equity — used with FRACTIONAL.
        Must be in (0, 1].

    Usage example
    -------------
    >>> cfg = PortfolioConfig(starting_capital=50_000)
    >>> cfg2 = PortfolioConfig(
    ...     starting_capital=100_000,
    ...     sizing_mode=SizingMode.PCT_OF_EQUITY,
    ...     equity_fraction=0.02,
    ... )
    """

    starting_capital : float      = 100_000.0
    sizing_mode      : SizingMode = SizingMode.FIXED_UNITS
    position_size    : float      = 1.0
    equity_fraction  : float      = 0.10
    trade_capital    : float      = 10_000.0
    fraction         : float      = 0.25

    def __post_init__(self) -> None:
        if self.starting_capital <= 0:
            raise ValueError(
                f"starting_capital must be > 0, got {self.starting_capital!r}"
            )
        if self.position_size <= 0:
            raise ValueError(
                f"position_size must be > 0, got {self.position_size!r}"
            )
        if not (0.0 < self.equity_fraction <= 1.0):
            raise ValueError(
                f"equity_fraction must be in (0, 1], got {self.equity_fraction!r}"
            )
        if self.trade_capital <= 0:
            raise ValueError(
                f"trade_capital must be > 0, got {self.trade_capital!r}"
            )
        if not (0.0 < self.fraction <= 1.0):
            raise ValueError(
                f"fraction must be in (0, 1], got {self.fraction!r}"
            )


@dataclass(frozen=True)
class PortfolioTrade:
    """A completed trade scaled to actual portfolio sizing.

    All price fields (entry_price, exit_price) are after slippage, identical
    to the underlying BacktestTrade.  Monetary fields (fees, PnL, slippage
    costs) reflect the actual position size that was used.

    Additional field vs BacktestTrade
    ----------------------------------
    portfolio_equity_at_entry : float
        Portfolio equity at the moment this position was opened.  Useful for
        computing per-trade R-multiples and risk metrics.

    PnL conventions
    ---------------
    gross_pnl = (exit_price − entry_price) × size
    net_pnl   = gross_pnl − entry_fee − exit_fee
    profit    = net_pnl  (alias for duck-type compatibility)
    """

    trade_number              : int
    direction                 : str

    entry_time                : object   # datetime
    exit_time                 : object   # datetime
    entry_bar                 : int
    exit_bar                  : int

    entry_price               : float
    exit_price                : float
    size                      : float

    entry_fee                 : float
    exit_fee                  : float
    entry_slippage            : float
    exit_slippage             : float

    gross_pnl                 : float
    net_pnl                   : float
    exit_reason               : object   # ExitReason

    holding_period            : int
    portfolio_equity_at_entry : float

    @property
    def profit(self) -> float:
        """Alias for net_pnl — duck-type compatible with pipeline.models.Trade."""
        return self.net_pnl

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0


@dataclass
class PortfolioResult:
    """Complete result of a portfolio-level backtest.

    All capital and PnL fields are in quote currency (e.g. USD).
    Return and exposure fields are dimensionless fractions (e.g. 0.15 = 15 %).

    Curve fields (equity_curve, balance_curve, drawdown_curve) are
    ``pd.Series`` indexed by bar timestamps from the input bars DataFrame.

    Curve semantics
    ---------------
    equity_curve  : total portfolio value at each bar, including unrealized PnL
                    for bars while a position is open.
    balance_curve : realized equity only — steps only when trades close, flat
                    while a position is open.
    drawdown_curve: rolling drawdown from the equity peak, expressed as a
                    fraction in [−1, 0].  −0.15 means 15 % below peak.
    """

    starting_capital : float

    ending_equity    : float
    peak_equity      : float
    net_profit       : float
    total_return     : float

    max_drawdown_pct : float
    max_drawdown_abs : float

    exposure_pct     : float

    equity_curve     : pd.Series
    balance_curve    : pd.Series
    drawdown_curve   : pd.Series

    trades           : list[PortfolioTrade]
