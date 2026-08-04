"""Position tracker for the paper trading bot.

Manages open and closed positions.  One position per symbol at a time (the
risk engine enforces this).  Positions are rebuilt from fills, so the fill
record is always the source of truth.

Position lifecycle
------------------
  ENTRY FILL (BUY)  → position opened (long)
  ENTRY FILL (SELL) → position opened (short)  [not used with max_open=1 / long-only]
  EXIT FILL         → position closed, realized PnL computed

Unrealized PnL is computed on demand from the last known mark price.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .events import EventBus, FillEvent, PositionEvent
from .paper_exchange import PaperFill, SIDE_BUY, SIDE_SELL
from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.position_manager")


@dataclass
class Position:
    """Mutable position record."""

    position_id:     str
    symbol:          str
    direction:       str    # "long" | "short"
    status:          str    # "open" | "closed"
    size:            float  # base currency units (e.g. BTC)
    entry_price:     float  # average entry price (fill price at open)
    avg_entry_price: float
    exit_price:      float = 0.0
    realized_pnl:    float = 0.0
    entry_fee:       float = 0.0
    exit_fee:        float = 0.0
    equity_at_entry: float = 0.0
    entry_order_id:  str   = ""
    exit_order_id:   str   = ""
    opened_at:       str   = field(default_factory=lambda: _now())
    closed_at:       str   = ""

    def unrealized_pnl(self, mark_price: float) -> float:
        if self.direction == "long":
            return (mark_price - self.avg_entry_price) * self.size
        else:
            return (self.avg_entry_price - mark_price) * self.size

    def notional(self) -> float:
        return self.avg_entry_price * self.size

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id":     self.position_id,
            "symbol":          self.symbol,
            "direction":       self.direction,
            "status":          self.status,
            "size":            self.size,
            "entry_price":     self.entry_price,
            "avg_entry_price": self.avg_entry_price,
            "exit_price":      self.exit_price,
            "realized_pnl":    self.realized_pnl,
            "entry_fee":       self.entry_fee,
            "exit_fee":        self.exit_fee,
            "equity_at_entry": self.equity_at_entry,
            "entry_order_id":  self.entry_order_id,
            "exit_order_id":   self.exit_order_id,
            "opened_at":       self.opened_at,
            "closed_at":       self.closed_at or None,
        }


class PositionManager:
    """Tracks open and closed positions.

    Usage::

        pm = PositionManager(storage, bus)
        pm.on_fill(fill, equity=100_000)   # call after every order fill
        open_pos = pm.get_open("BTCUSDT")  # None if flat
    """

    def __init__(self, storage: BotStorage, bus: EventBus) -> None:
        self.storage = storage
        self.bus     = bus
        # RLock so event handlers invoked while the lock is held can re-enter
        self._lock   = threading.RLock()

        # symbol → open Position (one per symbol at a time)
        self._open: dict[str, Position] = {}
        # All positions (open + closed) keyed by position_id
        self._all:  dict[str, Position] = {}

    # ── Fill ingestion ────────────────────────────────────────────────────────

    def on_fill(self, fill: PaperFill, equity: float = 0.0) -> Position:
        """Process a fill and update position state.

        Returns the affected position (newly opened or closed).
        """
        with self._lock:
            existing = self._open.get(fill.symbol)
            if existing is None:
                pos = self._open_position(fill, equity)
            else:
                pos = self._close_position(existing, fill)
        return pos

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_open(self, symbol: str) -> Position | None:
        with self._lock:
            return self._open.get(symbol)

    def get_all_open(self) -> list[Position]:
        with self._lock:
            return list(self._open.values())

    def get_position(self, position_id: str) -> Position | None:
        with self._lock:
            return self._all.get(position_id)

    def has_open_position(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self._open

    def open_position_count(self) -> int:
        with self._lock:
            return len(self._open)

    def total_unrealized_pnl(self, mark_prices: dict[str, float]) -> float:
        with self._lock:
            total = 0.0
            for sym, pos in self._open.items():
                mp = mark_prices.get(sym)
                if mp is not None:
                    total += pos.unrealized_pnl(mp)
            return total

    def total_exposure(self) -> float:
        """Total notional (entry_price * size) across all open positions."""
        with self._lock:
            return sum(p.notional() for p in self._open.values())

    # ── Recovery ─────────────────────────────────────────────────────────────

    def recover(self) -> int:
        """Reload open positions from storage on restart."""
        with self._lock:
            rows = self.storage.get_open_positions()
            recovered = 0
            for row in rows:
                pos = _row_to_position(row)
                self._open[pos.symbol] = pos
                self._all[pos.position_id] = pos
                recovered += 1
            if recovered:
                log.info("Recovered %d open positions from storage", recovered)
            return recovered

    # ── Private ───────────────────────────────────────────────────────────────

    def _open_position(self, fill: PaperFill, equity: float) -> Position:
        direction = "long" if fill.side == SIDE_BUY else "short"
        pos = Position(
            position_id=str(uuid.uuid4()),
            symbol=fill.symbol,
            direction=direction,
            status="open",
            size=fill.fill_qty,
            entry_price=fill.fill_price,
            avg_entry_price=fill.fill_price,
            entry_fee=fill.fee,
            equity_at_entry=equity,
            entry_order_id=fill.order_id,
            opened_at=fill.filled_at,
        )
        self._open[fill.symbol] = pos
        self._all[pos.position_id] = pos
        self.storage.save_position(pos.to_dict())
        log.info(
            "Position opened: %s %s size=%.5f @ %.2f",
            fill.symbol, direction, fill.fill_qty, fill.fill_price,
        )
        if self.bus:
            self.bus.emit(PositionEvent(
                symbol=fill.symbol,
                action="opened",
                direction=direction,
                size=fill.fill_qty,
                entry_price=fill.fill_price,
            ))
        return pos

    def _close_position(self, pos: Position, fill: PaperFill) -> Position:
        if pos.direction == "long":
            raw_pnl = (fill.fill_price - pos.avg_entry_price) * pos.size
        else:
            raw_pnl = (pos.avg_entry_price - fill.fill_price) * pos.size

        realized = raw_pnl - pos.entry_fee - fill.fee

        pos.exit_price    = fill.fill_price
        pos.exit_fee      = fill.fee
        pos.realized_pnl  = realized
        pos.status        = "closed"
        pos.exit_order_id = fill.order_id
        pos.closed_at     = fill.filled_at

        del self._open[pos.symbol]
        self.storage.save_position(pos.to_dict())
        log.info(
            "Position closed: %s %s size=%.5f exit=%.2f pnl=%.4f",
            pos.symbol, pos.direction, pos.size, fill.fill_price, realized,
        )
        if self.bus:
            self.bus.emit(PositionEvent(
                symbol=pos.symbol,
                action="closed",
                direction=pos.direction,
                size=pos.size,
                entry_price=pos.avg_entry_price,
                exit_price=fill.fill_price,
                realized_pnl=realized,
            ))
        return pos


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_position(row: dict) -> Position:
    return Position(
        position_id=row["position_id"],
        symbol=row["symbol"],
        direction=row["direction"],
        status=row["status"],
        size=row["size"],
        entry_price=row["entry_price"],
        avg_entry_price=row.get("avg_entry_price", row["entry_price"]),
        exit_price=row.get("exit_price") or 0.0,
        realized_pnl=row.get("realized_pnl", 0.0),
        entry_fee=row.get("entry_fee", 0.0),
        exit_fee=row.get("exit_fee", 0.0),
        equity_at_entry=row.get("equity_at_entry") or 0.0,
        entry_order_id=row.get("entry_order_id") or "",
        exit_order_id=row.get("exit_order_id") or "",
        opened_at=row["opened_at"],
        closed_at=row.get("closed_at") or "",
    )
