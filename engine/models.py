"""Engine data models: configuration, internal position state, and trade output."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ExitReason(str, Enum):
    SIGNAL = "signal"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    END_OF_DATA = "end_of_data"


@dataclass
class EngineConfig:
    """Parameters for a single backtest run."""

    position_size: float = 1.0
    stop_loss_pct: float | None = None   # distance from fill price, e.g. 0.02 = 2%
    take_profit_pct: float | None = None # distance from fill price, e.g. 0.04 = 4%
    fee_rate: float = 0.001              # 0.1% Binance maker/taker, applied each side
    slippage_pct: float = 0.0005         # 0.05% per side


@dataclass
class _Position:
    """Open position.  Internal to the executor — never returned to callers."""

    direction: str          # "Long" (Short reserved)
    entry_bar: int
    entry_time: datetime
    entry_price: float      # actual fill price, after slippage
    size: float
    stop_loss: float | None
    take_profit: float | None
    entry_fee: float        # fee paid on entry
    entry_slippage: float   # dollar cost of entry slippage


@dataclass(frozen=True)
class BacktestTrade:
    """Completed trade record produced by BacktestExecutor.

    Prices are actual fill prices (after slippage has been applied).
    Slippage fields are informational dollar amounts.
    """

    trade_number: int
    direction: str

    entry_time: datetime
    exit_time: datetime
    entry_bar: int
    exit_bar: int

    entry_price: float       # fill price (raw open + slippage)
    exit_price: float        # fill price (raw reference − slippage)
    size: float

    entry_fee: float
    exit_fee: float
    entry_slippage: float    # dollar cost of entry slippage
    exit_slippage: float     # dollar cost of exit slippage

    gross_pnl: float         # (exit_price − entry_price) × size
    net_pnl: float           # gross_pnl − entry_fee − exit_fee
    exit_reason: ExitReason
    holding_period: int      # bars held = exit_bar − entry_bar

    # ── duck-type compatibility with pipeline.models.Trade ────────────────────

    @property
    def profit(self) -> float:
        return self.net_pnl

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0
