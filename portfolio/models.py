"""Portfolio layer data models — configuration, trades, and results."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
import math

import pandas as pd

if TYPE_CHECKING:
    from engine.models import ExitReason


class SizingMode(str, Enum):
    """Position sizing strategy applied by the portfolio engine.

    FIXED_UNITS   — constant number of base-asset units per trade.
    PCT_OF_EQUITY — fraction of current equity allocated at entry price.
    FIXED_DOLLAR  — fixed quote-currency notional converted to units at entry.
    FRACTIONAL    — custom fraction of current equity allocated at entry.

    These modes control *position notional*, not loss risk. A risk-per-trade
    model requires an explicit stop distance and belongs in a separate sizing
    layer; ``equity_fraction=0.05`` therefore means 5% allocation, not 5% risk.
    """

    FIXED_UNITS   = "fixed_units"
    PCT_OF_EQUITY = "pct_of_equity"
    FIXED_DOLLAR  = "fixed_dollar"
    FRACTIONAL    = "fractional"


@dataclass
class PortfolioConfig:
    """Configuration for the portfolio engine."""

    starting_capital : float      = 100_000.0
    sizing_mode      : SizingMode = SizingMode.FIXED_UNITS
    position_size    : float      = 1.0
    equity_fraction  : float      = 0.10
    trade_capital    : float      = 10_000.0
    fraction         : float      = 0.25
    summary_only     : bool       = False

    def __post_init__(self) -> None:
        # Dataclasses do not enforce annotations at runtime. Reject arbitrary
        # strings/objects rather than letting the engine silently fall back to
        # FIXED_UNITS, which would make an invalid configuration look valid.
        if not isinstance(self.sizing_mode, SizingMode):
            try:
                self.sizing_mode = SizingMode(self.sizing_mode)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"sizing_mode must be a valid SizingMode, got {self.sizing_mode!r}"
                ) from exc
        if not math.isfinite(self.starting_capital) or self.starting_capital <= 0:
            raise ValueError(f"starting_capital must be finite and > 0, got {self.starting_capital!r}")
        if not math.isfinite(self.position_size) or self.position_size <= 0:
            raise ValueError(f"position_size must be finite and > 0, got {self.position_size!r}")
        if not math.isfinite(self.equity_fraction) or not (0.0 < self.equity_fraction <= 1.0):
            raise ValueError(f"equity_fraction must be finite and in (0, 1], got {self.equity_fraction!r}")
        if not math.isfinite(self.trade_capital) or self.trade_capital <= 0:
            raise ValueError(f"trade_capital must be finite and > 0, got {self.trade_capital!r}")
        if not math.isfinite(self.fraction) or not (0.0 < self.fraction <= 1.0):
            raise ValueError(f"fraction must be finite and in (0, 1], got {self.fraction!r}")


@dataclass(frozen=True)
class PortfolioTrade:
    """A completed trade scaled to actual portfolio sizing.

    All monetary fields reflect the actual position size used. PnL is
    ``gross_pnl - entry_fee - exit_fee``; slippage is already embedded in the
    fill prices and is therefore not deducted a second time.
    """

    trade_number              : int
    direction                 : str
    entry_time                : object
    exit_time                 : object
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
    exit_reason               : object
    holding_period            : int
    portfolio_equity_at_entry : float

    @property
    def profit(self) -> float:
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

    ``equity_curve`` is mark-to-market equity including unrealized PnL;
    ``balance_curve`` is realized-only equity; ``drawdown_curve`` is the
    fractional decline from the running equity peak.
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
