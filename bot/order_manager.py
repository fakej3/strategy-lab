"""Order lifecycle manager for the paper trading bot.

Wraps PaperExchange to provide a higher-level order API:
- New-order submission with automatic ID generation
- Cancel by order ID or cancel-all
- State machine: NEW → ACCEPTED → FILLED | CANCELLED | REJECTED
- Persists every order and fill to BotStorage
- Emits events via EventBus on every transition

This module owns the authoritative in-memory order book.  BotStorage is the
durable record; the in-memory state is rebuilt from storage on restart.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from .events import EventBus, FillEvent, OrderEvent
from .interfaces import ExchangeAdapter
from .paper_exchange import (
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_STOP_LIMIT,
    ORDER_TYPE_STOP_MARKET,
    ORDER_TYPE_TAKE_PROFIT,
    SIDE_BUY,
    SIDE_SELL,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_REJECTED,
    TIF_GTC,
    PaperFill,
    PaperOrder,
)
from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.order_manager")


class OrderManager:
    """High-level order lifecycle management.

    Keeps an in-memory map of all open orders and delegates fill simulation to
    ``PaperExchange``.  All state changes are persisted to ``BotStorage`` and
    broadcast on the ``EventBus``.
    """

    def __init__(
        self,
        exchange: ExchangeAdapter,
        storage: BotStorage,
        bus: EventBus,
    ) -> None:
        self.exchange = exchange
        self.storage  = storage
        self.bus      = bus

        # order_id → PaperOrder (open orders only)
        self._open: dict[str, PaperOrder] = {}
        # order_id → PaperOrder (all: open + terminal).
        # Grows unboundedly over bot uptime. At realistic trade frequencies
        # (≤10/day) this is negligible for months; defer pruning until needed.
        self._all:  dict[str, PaperOrder] = {}

    # ── Submit ────────────────────────────────────────────────────────────────

    def submit_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        current_position_size: float = 0.0,
        instance_id: str = "",
    ) -> PaperOrder:
        return self._submit(
            symbol=symbol, side=side, order_type=ORDER_TYPE_MARKET, qty=qty,
            reduce_only=reduce_only, current_position_size=current_position_size,
            instance_id=instance_id,
        )

    def submit_limit(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool = False,
        time_in_force: str = TIF_GTC,
        current_position_size: float = 0.0,
    ) -> PaperOrder:
        return self._submit(
            symbol=symbol, side=side, order_type=ORDER_TYPE_LIMIT, qty=qty,
            price=price, time_in_force=time_in_force,
            reduce_only=reduce_only, current_position_size=current_position_size,
        )

    def submit_stop_market(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        reduce_only: bool = False,
        current_position_size: float = 0.0,
        instance_id: str = "",
    ) -> PaperOrder:
        return self._submit(
            symbol=symbol, side=side, order_type=ORDER_TYPE_STOP_MARKET, qty=qty,
            stop_price=stop_price, reduce_only=reduce_only,
            current_position_size=current_position_size,
            instance_id=instance_id,
        )

    def submit_stop_limit(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        price: float,
        reduce_only: bool = False,
        current_position_size: float = 0.0,
    ) -> PaperOrder:
        return self._submit(
            symbol=symbol, side=side, order_type=ORDER_TYPE_STOP_LIMIT, qty=qty,
            price=price, stop_price=stop_price, reduce_only=reduce_only,
            current_position_size=current_position_size,
        )

    def submit_take_profit(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_price: float,
        reduce_only: bool = True,
        current_position_size: float = 0.0,
        instance_id: str = "",
    ) -> PaperOrder:
        return self._submit(
            symbol=symbol, side=side, order_type=ORDER_TYPE_TAKE_PROFIT, qty=qty,
            stop_price=stop_price, reduce_only=reduce_only,
            current_position_size=current_position_size,
            instance_id=instance_id,
        )

    # ── Cancel ────────────────────────────────────────────────────────────────

    def cancel(self, order_id: str) -> bool:
        """Cancel a specific open order.  Returns True if cancelled."""
        cancelled = self.exchange.cancel_order(order_id)
        if cancelled:
            order = self._all.get(order_id)
            if order:
                self._open.pop(order_id, None)
                self.storage.save_order(order.to_dict())
        return cancelled

    def cancel_all(self, symbol: str | None = None) -> int:
        """Cancel all open orders for *symbol* (or all if None)."""
        count = self.exchange.cancel_all(symbol)
        # Sync state from exchange for any cancelled orders
        for oid, order in list(self._open.items()):
            if symbol and order.symbol != symbol:
                continue
            if order.status == STATUS_CANCELLED:
                self._open.pop(oid, None)
                self.storage.save_order(order.to_dict())
        return count

    # ── Candle processing ─────────────────────────────────────────────────────

    def on_candle(
        self,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        candle_ts: str | None = None,
    ) -> list[PaperFill]:
        """Process a closed candle — triggers order matching.

        Returns fills generated by this candle.  Filled orders are moved to
        terminal state, persisted, and their fills are persisted.
        """
        fills = self.exchange.process_candle(symbol, open_, high, low, close, candle_ts)

        for fill in fills:
            order = self._all.get(fill.order_id)
            if order:
                self._open.pop(fill.order_id, None)
                self.storage.save_order(order.to_dict())
                self.storage.save_fill(fill.to_dict())

        # Sync fill-time rejections: market orders can be rejected inside
        # process_candle (e.g. MIN_NOTIONAL check).  They don't produce a fill
        # so the loop above skips them, but their status is now REJECTED.
        # Remove them from _open so they are not counted as open orders.
        for oid in list(self._open):
            order = self._open[oid]
            if order.symbol == symbol and order.status == STATUS_REJECTED:
                self._open.pop(oid, None)
                self.storage.save_order(order.to_dict())

        return fills

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_open_orders(self, symbol: str | None = None) -> list[PaperOrder]:
        if symbol:
            return [o for o in self._open.values() if o.symbol == symbol]
        return list(self._open.values())

    def get_order(self, order_id: str) -> PaperOrder | None:
        return self._all.get(order_id)

    def open_order_count(self, symbol: str | None = None) -> int:
        if symbol:
            return sum(1 for o in self._open.values() if o.symbol == symbol)
        return len(self._open)

    # ── Recovery ─────────────────────────────────────────────────────────────

    def recover_open_orders(self) -> int:
        """Reload open orders from storage into the in-memory book.

        Called on bot restart when ``BotConfig.recover_on_restart=True``.
        Returns number of orders recovered.
        """
        rows = self.storage.get_open_orders()
        recovered = 0
        for row in rows:
            order = _row_to_order(row)
            self._all[order.order_id] = order
            self._open[order.order_id] = order
            # Re-register with the exchange so it participates in matching
            self.exchange.restore_order(order)
            recovered += 1
        if recovered:
            log.info("Recovered %d open orders from storage", recovered)
        return recovered

    # ── Private ───────────────────────────────────────────────────────────────

    def _submit(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = TIF_GTC,
        reduce_only: bool = False,
        current_position_size: float = 0.0,
        instance_id: str = "",
    ) -> PaperOrder:
        oid = str(uuid.uuid4())
        order = self.exchange.submit_order(
            symbol=symbol, side=side, order_type=order_type, qty=qty,
            price=price, stop_price=stop_price,
            time_in_force=time_in_force, reduce_only=reduce_only,
            order_id=oid, current_position_size=current_position_size,
            instance_id=instance_id,
        )
        self._all[oid] = order
        if order.status == STATUS_ACCEPTED:
            self._open[oid] = order
        self.storage.save_order(order.to_dict())
        log.info(
            "Order %s %s %s %s qty=%.5f price=%s stop=%s → %s",
            oid[:8], symbol, side, order_type, qty,
            price, stop_price, order.status,
        )
        return order


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_order(row: dict) -> PaperOrder:
    """Reconstruct a PaperOrder from a storage row."""
    return PaperOrder(
        order_id=row["order_id"],
        symbol=row["symbol"],
        side=row["side"],
        order_type=row["order_type"],
        qty=row["qty"],
        price=row.get("price"),
        stop_price=row.get("stop_price"),
        time_in_force=row.get("time_in_force", TIF_GTC),
        reduce_only=bool(row.get("reduce_only", False)),
        status=row["status"],
        filled_qty=row.get("filled_qty", 0.0),
        avg_fill_price=row.get("avg_fill_price") or 0.0,
        total_fee=row.get("total_fee", 0.0),
        reject_reason=row.get("reject_reason") or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
