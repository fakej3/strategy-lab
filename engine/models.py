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
    """Parameters controlling a single backtest run.

    Execution model
    ---------------
    Signal at bar T  →  fill at bar T+1 open (no lookahead bias at the
    execution layer).  SL/TP are evaluated at the beginning of every held
    bar, including the entry bar: a position that opens at bar T+1 open can
    be stopped out intrabar on bar T+1 if the bar's high/low breaches the
    level.

    Stop-loss model
    ---------------
    When ``bar_low <= stop_loss_level`` the fill is set to the stop level —
    the first price at which a market stop order would execute.  Exception:
    if the bar opens *below* the stop (gap-through), fill = bar open,
    because the stop level is no longer the first available price.  This is
    a deliberate bar-based simulation assumption; within-bar price paths are
    not modelled.

    Take-profit model
    -----------------
    When ``bar_high >= take_profit_level`` the fill is set to the TP level.
    Exception: if the bar opens *above* the target (gap-up), fill = bar
    open, because you receive the more-favourable opening price.

    End-of-data liquidation
    -----------------------
    Any position still open at the last bar is closed at that bar's close
    price.  No future bar exists to fill a market order into, so the close
    is the final observable reference price.

    Slippage model
    --------------
    Slippage is a fixed percentage applied symmetrically every fill:
    buyers pay ``raw_price × (1 + slippage_pct)``;
    sellers receive ``raw_price × (1 − slippage_pct)``.
    This model does not account for market impact, order-book depth,
    volatility regimes, or position size relative to average volume.

    Position sizing
    ---------------
    ``position_size`` is expressed in base-asset units (e.g. 1.0 = 1 BTC
    for a BTCUSDT backtest), not as a fraction of portfolio equity.  This
    engine does not track running capital or apply compounded sizing.
    Capital-relative position management belongs in a higher-level portfolio
    layer that wraps this engine.
    """

    position_size: float = 1.0
    stop_loss_pct: float | None = None    # fraction of fill price, e.g. 0.02 = 2 %
    take_profit_pct: float | None = None  # fraction of fill price, e.g. 0.04 = 4 %
    fee_rate: float = 0.001               # 0.1 % Binance maker/taker, applied each side
    slippage_pct: float = 0.0005          # 0.05 % per side

    def __post_init__(self) -> None:
        if self.position_size <= 0:
            raise ValueError(
                f"position_size must be > 0, got {self.position_size!r}"
            )
        if self.fee_rate < 0:
            raise ValueError(
                f"fee_rate must be >= 0, got {self.fee_rate!r}"
            )
        if self.slippage_pct < 0:
            raise ValueError(
                f"slippage_pct must be >= 0, got {self.slippage_pct!r}"
            )
        if self.stop_loss_pct is not None and not (0.0 < self.stop_loss_pct < 1.0):
            raise ValueError(
                f"stop_loss_pct must be in the open interval (0, 1), "
                f"got {self.stop_loss_pct!r}"
            )
        if self.take_profit_pct is not None and self.take_profit_pct <= 0.0:
            raise ValueError(
                f"take_profit_pct must be > 0, got {self.take_profit_pct!r}"
            )


@dataclass(frozen=True)
class _Position:
    """Open position.  Internal to the executor — never returned to callers."""

    direction: str           # "Long" (Short reserved for a future version)
    entry_bar: int
    entry_time: datetime
    entry_price: float       # actual fill price after slippage
    size: float
    stop_loss: float | None  # absolute price level derived from fill price
    take_profit: float | None
    entry_fee: float         # fee paid on entry, in quote currency
    entry_slippage: float    # dollar cost of entry slippage


@dataclass(frozen=True)
class BacktestTrade:
    """Completed trade record produced by BacktestExecutor.

    All price fields (``entry_price``, ``exit_price``) are actual fill
    prices after slippage has been applied.

    PnL conventions
    ---------------
    ``gross_pnl = (exit_price - entry_price) × size``.
    Since both prices already embed slippage, ``gross_pnl`` represents the
    price-movement gain net of slippage costs.  To recover the raw price
    gain before any costs, use ``gross_pnl + entry_slippage + exit_slippage``.

    ``net_pnl = gross_pnl - entry_fee - exit_fee``.
    This is the fully realised P&L after all transaction costs.

    ``profit`` is an alias for ``net_pnl``, provided for duck-type
    compatibility with ``pipeline.models.Trade``.
    """

    trade_number: int
    direction: str

    entry_time: datetime
    exit_time: datetime
    entry_bar: int
    exit_bar: int

    entry_price: float        # fill price = raw open × (1 + slippage_pct)
    exit_price: float         # fill price = raw reference × (1 − slippage_pct)
    size: float

    entry_fee: float
    exit_fee: float
    entry_slippage: float     # informational: dollar cost of entry slippage
    exit_slippage: float      # informational: dollar cost of exit slippage

    gross_pnl: float          # (exit_price − entry_price) × size; slippage embedded
    net_pnl: float            # gross_pnl − entry_fee − exit_fee
    exit_reason: ExitReason
    holding_period: int       # bars held = exit_bar − entry_bar

    # ── duck-type compatibility with pipeline.models.Trade ────────────────────

    @property
    def profit(self) -> float:
        """Alias for net_pnl — compatible with pipeline.models.Trade."""
        return self.net_pnl

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.net_pnl < 0
