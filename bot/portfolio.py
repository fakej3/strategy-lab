"""Portfolio accounting for the paper trading bot.

Tracks cash, equity, peak, and drawdown.  Updated on every fill and every
monitoring tick.  Thread-safe via a lock so the dashboard can read without
racing the main event loop.

Equity = cash + (mark_price * size) for each open position.
Each BUY fill deducts the entry notional from cash, so adding the current
market value of each position gives the correct total portfolio value.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .events import EventBus
from .paper_exchange import PaperFill, SIDE_BUY, SIDE_SELL
from .position_manager import Position
from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.portfolio")


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""

    ts:         str
    cash:       float
    equity:     float
    unrealized: float
    drawdown:   float   # fraction (0.0 → 1.0)
    peak:       float


class Portfolio:
    """Mutable portfolio state.

    On each fill:
      - BUY:  deduct notional + fee from cash
      - SELL: add notional − fee to cash

    Equity is recomputed on demand from cash + unrealized PnL.

    Usage::

        pf = Portfolio(starting_capital=100_000.0, storage=storage, bus=bus)
        pf.on_fill(fill)
        snap = pf.snapshot(mark_prices={"BTCUSDT": 50000.0}, positions=open_positions)
    """

    def __init__(
        self,
        starting_capital: float,
        storage: BotStorage,
        bus: EventBus,
        fee_rate: float = 0.001,
    ) -> None:
        self.starting_capital = starting_capital
        self.storage = storage
        self.bus     = bus
        self.fee_rate = fee_rate

        self._lock        = threading.Lock()
        self._cash        = starting_capital
        self._peak_equity = starting_capital
        self._daily_pnl   = 0.0
        self._n_trades    = 0        # today
        self._n_winners   = 0        # today
        self._n_losers    = 0        # today
        self._gross_profit = 0.0    # today
        self._gross_loss   = 0.0    # today
        self._total_fees   = 0.0    # today
        self._last_trade_ts: float  = 0.0   # monotonic

    # ── Fill handling ─────────────────────────────────────────────────────────

    def on_fill(self, fill: PaperFill, closed_pnl: float | None = None) -> None:
        """Update cash after a fill.

        ``closed_pnl`` is the net realized PnL when this fill closes a position
        (provided by the position manager after it computes realized PnL).
        """
        with self._lock:
            notional = fill.fill_price * fill.fill_qty

            if fill.side == SIDE_BUY:
                self._cash -= notional + fill.fee
            else:
                self._cash += notional - fill.fee

            self._total_fees += fill.fee

            if closed_pnl is not None:
                self._daily_pnl += closed_pnl
                self._n_trades  += 1
                import time
                self._last_trade_ts = time.monotonic()

                if closed_pnl > 0:
                    self._n_winners   += 1
                    self._gross_profit += closed_pnl
                else:
                    self._n_losers   += 1
                    self._gross_loss  += closed_pnl   # negative value

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def snapshot(
        self,
        mark_prices: dict[str, float],
        positions: list[Position],
    ) -> PortfolioSnapshot:
        """Compute and persist a portfolio snapshot."""
        with self._lock:
            # Equity = cash + full market value of open positions.
            # cash is already reduced by entry notionals on each BUY fill, so
            # cash + mark*size gives the correct total portfolio value.
            position_value = sum(
                mark_prices.get(p.symbol, p.avg_entry_price) * p.size
                for p in positions
            )
            equity = self._cash + position_value

            # Unrealized PnL = gain/loss from entry prices; kept as a readable
            # dashboard metric separate from equity.
            unrealized = sum(
                p.unrealized_pnl(mark_prices.get(p.symbol, p.avg_entry_price))
                for p in positions
            )

            if equity > self._peak_equity:
                self._peak_equity = equity

            drawdown = 0.0
            if self._peak_equity > 0:
                drawdown = (self._peak_equity - equity) / self._peak_equity

            snap = PortfolioSnapshot(
                ts=_now(),
                cash=self._cash,
                equity=equity,
                unrealized=unrealized,
                drawdown=drawdown,
                peak=self._peak_equity,
            )

        self.storage.save_balance_snapshot(
            equity=snap.equity,
            cash=snap.cash,
            unrealized=snap.unrealized,
            drawdown=snap.drawdown,
        )
        return snap

    # ── Readers (thread-safe) ─────────────────────────────────────────────────

    @property
    def cash(self) -> float:
        with self._lock:
            return self._cash

    @property
    def peak_equity(self) -> float:
        with self._lock:
            return self._peak_equity

    @property
    def daily_pnl(self) -> float:
        with self._lock:
            return self._daily_pnl

    @property
    def n_trades_today(self) -> int:
        with self._lock:
            return self._n_trades

    @property
    def last_trade_ts(self) -> float:
        with self._lock:
            return self._last_trade_ts

    def daily_stats(
        self,
        equity: float,
        starting_equity: float,
        date_utc: str | None = None,
    ) -> dict[str, Any]:
        """Return a dict suitable for BotStorage.upsert_daily_stats().

        *date_utc* overrides the date key.  Pass it from DailyResetEvent at
        midnight so the completed day's stats are stored under yesterday's date,
        not today's.  Leave it as None for intraday updates (uses today).
        """
        with self._lock:
            win_rate = (
                self._n_winners / self._n_trades
                if self._n_trades > 0 else None
            )
            loss_abs = abs(self._gross_loss) if self._gross_loss < 0 else 0.0
            profit_factor = (
                self._gross_profit / loss_abs
                if loss_abs > 0 else None
            )
            dd = 0.0
            if self._peak_equity > 0:
                dd = (self._peak_equity - equity) / self._peak_equity

            return {
                "date_utc":        date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "n_trades":        self._n_trades,
                "n_winners":       self._n_winners,
                "n_losers":        self._n_losers,
                "gross_profit":    self._gross_profit,
                "gross_loss":      self._gross_loss,
                "net_pnl":         self._daily_pnl,
                "total_fees":      self._total_fees,
                "starting_equity": starting_equity,
                "ending_equity":   equity,
                "max_drawdown":    dd,
                "win_rate":        win_rate,
                "profit_factor":   profit_factor,
            }

    # ── Daily reset ───────────────────────────────────────────────────────────

    def reset_daily(self) -> None:
        """Reset per-day counters at midnight UTC."""
        with self._lock:
            self._daily_pnl    = 0.0
            self._n_trades     = 0
            self._n_winners    = 0
            self._n_losers     = 0
            self._gross_profit = 0.0
            self._gross_loss   = 0.0
            self._total_fees   = 0.0

    # ── Recovery ─────────────────────────────────────────────────────────────

    def restore(self, cash: float, peak_equity: float) -> None:
        """Restore cash and peak from a persisted snapshot (on restart)."""
        with self._lock:
            self._cash        = cash
            self._peak_equity = peak_equity
        log.info("Portfolio restored: cash=%.2f peak=%.2f", cash, peak_equity)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
