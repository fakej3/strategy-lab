"""Engine data models: configuration, internal position state, and trade output."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math


class ExitReason(str, Enum):
    SIGNAL = "signal"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    END_OF_DATA = "end_of_data"


@dataclass
class EngineConfig:
    """Parameters controlling a single backtest run.

    Signals are evaluated causally: a signal at bar T fills at bar T+1 open.
    SL/TP are evaluated intrabar using OHLC data, with explicit gap-through
    handling. End-of-data positions are liquidated at the final close.

    ``position_size`` is base-asset units. Capital-relative sizing belongs to
    the portfolio layer. Slippage is a fixed percentage per fill and does not
    model market impact, liquidity, or order-book depth.
    """

    position_size: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    fee_rate: float = 0.001
    slippage_pct: float = 0.0005

    def __post_init__(self) -> None:
        if not math.isfinite(self.position_size) or self.position_size <= 0:
            raise ValueError(f"position_size must be finite and > 0, got {self.position_size!r}")
        if not math.isfinite(self.fee_rate) or self.fee_rate < 0:
            raise ValueError(f"fee_rate must be finite and >= 0, got {self.fee_rate!r}")
        if not math.isfinite(self.slippage_pct) or self.slippage_pct < 0:
            raise ValueError(f"slippage_pct must be finite and >= 0, got {self.slippage_pct!r}")
        if self.stop_loss_pct is not None and (
            not math.isfinite(self.stop_loss_pct) or not (0.0 < self.stop_loss_pct < 1.0)
        ):
            raise ValueError(f"stop_loss_pct must be finite and in (0, 1), got {self.stop_loss_pct!r}")
        if self.take_profit_pct is not None and (
            not math.isfinite(self.take_profit_pct) or self.take_profit_pct <= 0.0
        ):
            raise ValueError(f"take_profit_pct must be finite and > 0, got {self.take_profit_pct!r}")


@dataclass(frozen=True)
class _Position:
    """Open position. Internal to the executor."""

    direction: str
    entry_bar: int
    entry_time: datetime
    entry_price: float
    size: float
    stop_loss: float | None
    take_profit: float | None
    entry_fee: float
    entry_slippage: float


@dataclass(frozen=True)
class BacktestTrade:
    """Completed trade record produced by BacktestExecutor."""

    trade_number: int
    direction: str
    entry_time: datetime
    exit_time: datetime
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    size: float
    entry_fee: float
    exit_fee: float
    entry_slippage: float
    exit_slippage: float
    gross_pnl: float
    net_pnl: float
    exit_reason: ExitReason
    holding_period: int

    @property
    def profit(self) -> float:
        return self.net_pnl

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0
