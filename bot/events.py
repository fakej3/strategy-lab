"""Event system for the paper trading bot.

All significant state transitions emit an Event.  Subscribers register a
callable and receive events synchronously (in the emitter's thread/task).

Design notes
------------
- Events are plain dataclasses — cheap to create, easy to serialize.
- The EventBus is thread-safe: subscribe/emit can be called from any thread.
- Subscribers that raise exceptions are logged and skipped; they never crash
  the emitter.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("strategy_lab.bot.events")


# ── Event types ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BotEvent:
    """Base class for all bot events."""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class CandleEvent(BotEvent):
    """A closed OHLCV candle has arrived from the feed.

    ``is_history`` is ``True`` for REST-backfilled candles used only to warm
    strategy buffers.  The engine must NOT submit orders from history candles —
    they are stale data injected before live streaming begins.
    """
    symbol:     str   = ""
    interval:   str   = ""
    open_time:  int   = 0    # Unix ms
    open:       float = 0.0
    high:       float = 0.0
    low:        float = 0.0
    close:      float = 0.0
    volume:     float = 0.0
    close_time: int   = 0    # Unix ms
    is_history: bool  = False  # True for backfill candles; never triggers orders


@dataclass(frozen=True)
class SignalEvent(BotEvent):
    """Strategy has produced a signal on a closed candle."""
    symbol:   str = ""
    interval: str = ""
    signal:   str = "HOLD"   # Signal enum value


@dataclass(frozen=True)
class OrderEvent(BotEvent):
    """Order state has changed."""
    order_id: str = ""
    symbol:   str = ""
    side:     str = ""   # "BUY" | "SELL"
    status:   str = ""   # NEW | ACCEPTED | FILLED | CANCELLED | REJECTED | EXPIRED
    detail:   str = ""   # human-readable explanation


@dataclass(frozen=True)
class FillEvent(BotEvent):
    """An order (or part of it) has been filled."""
    order_id:    str   = ""
    symbol:      str   = ""
    side:        str   = ""
    fill_price:  float = 0.0
    fill_qty:    float = 0.0
    fee:         float = 0.0
    fee_asset:   str   = "USDT"
    is_maker:    bool  = False


@dataclass(frozen=True)
class PositionEvent(BotEvent):
    """A position has been opened or closed."""
    symbol:       str   = ""
    action:       str   = ""     # "opened" | "closed" | "updated"
    direction:    str   = ""     # "long" | "short"
    size:         float = 0.0
    entry_price:  float = 0.0
    exit_price:   float = 0.0   # 0.0 if still open
    realized_pnl: float = 0.0


@dataclass(frozen=True)
class RiskRejectionEvent(BotEvent):
    """An order was rejected by the risk engine."""
    symbol: str = ""
    side:   str = ""
    reason: str = ""


@dataclass(frozen=True)
class HeartbeatEvent(BotEvent):
    """Periodic heartbeat from the runtime."""
    uptime_s:         float = 0.0
    candles_received: int   = 0
    active_symbols:   int   = 0


@dataclass(frozen=True)
class DisconnectEvent(BotEvent):
    """WebSocket feed disconnected."""
    symbol:   str = ""
    interval: str = ""
    reason:   str = ""


@dataclass(frozen=True)
class ReconnectEvent(BotEvent):
    """WebSocket feed reconnected after a disconnect."""
    symbol:     str = ""
    interval:   str = ""
    attempt:    int = 0
    backfilled: int = 0   # number of candles backfilled


@dataclass(frozen=True)
class ErrorEvent(BotEvent):
    """An unexpected error occurred."""
    source:  str = ""
    message: str = ""
    detail:  str = ""


@dataclass(frozen=True)
class DailyResetEvent(BotEvent):
    """Daily statistics have been reset (midnight UTC)."""
    date_utc: str = ""   # YYYY-MM-DD of the day that just ended


# ── Event bus ──────────────────────────────────────────────────────────────────

EventHandler = Callable[[BotEvent], None]


class EventBus:
    """Thread-safe synchronous publish/subscribe event bus.

    Usage
    -----
    >>> bus = EventBus()
    >>> bus.subscribe(CandleEvent, lambda e: print(e.close))
    >>> bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h", close=50000.0))
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Register *handler* to be called for events of *event_type*."""
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: type, handler: EventHandler) -> None:
        """Remove *handler* from *event_type* subscriptions."""
        with self._lock:
            lst = self._handlers.get(event_type, [])
            if handler in lst:
                lst.remove(handler)

    def emit(self, event: BotEvent) -> None:
        """Deliver *event* to all registered handlers.

        Handler exceptions are caught and logged — they never propagate to
        the emitter.
        """
        with self._lock:
            handlers = list(self._handlers.get(type(event), []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                log.exception("EventBus handler raised for %s", type(event).__name__)

    def emit_all(self, events: list[BotEvent]) -> None:
        """Emit multiple events in order."""
        for ev in events:
            self.emit(ev)

    def handler_count(self, event_type: type) -> int:
        with self._lock:
            return len(self._handlers.get(event_type, []))
