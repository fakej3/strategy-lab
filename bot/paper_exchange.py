"""Paper exchange simulator for the trading bot.

Simulates realistic order execution against closed OHLCV candles.  No live
trading, no Binance trading endpoints, no API keys.

Fill model (mirrors engine/executor.py):
  MARKET          → next candle open + slippage (taker fee)
  LIMIT (BUY)     → fills when bar_low <= limit_price (maker fee)
  LIMIT (SELL)    → fills when bar_high >= limit_price (maker fee)
  STOP_MARKET     → triggers when bar_low <= stop_price (long SL) or
                    bar_high >= stop_price (short SL); fills at stop or open
                    if gap-through (taker fee)
  STOP_LIMIT      → triggers like STOP_MARKET, then becomes a limit order
  TAKE_PROFIT     → triggers when bar_high >= stop_price (long TP) or
                    bar_low <= stop_price (short TP); fills at stop or open
                    if gap-through (maker fee, resting) or taker if gapped
  REDUCE_ONLY     — flag respected: order rejected if it would increase size

OCO orders are represented as two separate orders managed externally.
IOC / FOK time-in-force: IOC fills fully or cancels; FOK placeholder cancels.
GTC: standard, rests until filled or cancelled.

Slippage is applied symmetrically:
  buyers  pay  open * (1 + slippage_pct)
  sellers receive open * (1 - slippage_pct)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .events import (
    EventBus, FillEvent, OrderEvent,
)
from .interfaces import ExchangeAdapter

log = logging.getLogger("strategy_lab.bot.paper_exchange")

# ── Order constants ────────────────────────────────────────────────────────────

ORDER_TYPE_MARKET      = "MARKET"
ORDER_TYPE_LIMIT       = "LIMIT"
ORDER_TYPE_STOP_MARKET = "STOP_MARKET"
ORDER_TYPE_STOP_LIMIT  = "STOP_LIMIT"
ORDER_TYPE_TAKE_PROFIT = "TAKE_PROFIT"

SIDE_BUY  = "BUY"
SIDE_SELL = "SELL"

STATUS_NEW              = "NEW"
STATUS_ACCEPTED         = "ACCEPTED"
STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
STATUS_FILLED           = "FILLED"
STATUS_CANCELLED        = "CANCELLED"
STATUS_REJECTED         = "REJECTED"
STATUS_EXPIRED          = "EXPIRED"

TIF_GTC = "GTC"
TIF_IOC = "IOC"
TIF_FOK = "FOK"

@dataclass
class SymbolRules:
    """Per-symbol exchange filter rules (LOT_SIZE, MIN_NOTIONAL, PRICE_FILTER).

    Each tradeable symbol must have an explicit entry in BUILTIN_SYMBOL_RULES
    or must be registered at startup via PaperExchange.register_symbol_rules().
    Unknown symbols log a WARNING and fall back to the BTCUSDT defaults — this
    is intentionally loud so missing symbol configuration is caught early.
    """
    min_notional: float = 10.0    # USDT minimum order notional
    min_qty:      float = 0.00001  # base currency minimum quantity
    qty_step:     float = 0.00001  # base currency step size (LOT_SIZE filter)
    tick_size:    float = 0.01     # quote currency price precision


# Default rules (BTCUSDT-equivalent).  Used as last-resort fallback only.
# Prefer explicit registration via BUILTIN_SYMBOL_RULES or register_symbol_rules().
_DEFAULT_RULES = SymbolRules()

# Module-level aliases kept for backward compatibility with tests/imports.
MIN_NOTIONAL = _DEFAULT_RULES.min_notional
MIN_QTY      = _DEFAULT_RULES.min_qty
QTY_STEP     = _DEFAULT_RULES.qty_step
TICK_SIZE    = _DEFAULT_RULES.tick_size

# Built-in per-symbol rules for common symbols.  Approximates Binance spot
# LOT_SIZE and PRICE_FILTER values.  Add a new entry here whenever a new symbol
# is used in production so no silent BTCUSDT-fallback warnings fire at runtime.
#
# Design note on qty_step for engine compatibility:
#   The live BotEngine sizes orders via round(notional/price, qty_precision=5),
#   which produces up to 5 decimal places (multiples of 0.00001).  Any symbol
#   that may be processed by the live engine must therefore have
#   qty_step = 0.00001 to guarantee step-valid quantities.  Symbols used only in
#   isolated exchange tests (e.g. SNDKUSDT) may carry larger step sizes to
#   demonstrate per-symbol rule isolation.
BUILTIN_SYMBOL_RULES: dict[str, SymbolRules] = {
    # Engine-compatible symbols: qty_step=0.00001; differ by min_qty / tick_size
    "BTCUSDT":  SymbolRules(min_notional=10.0, min_qty=0.00001, qty_step=0.00001, tick_size=0.01),
    "ETHUSDT":  SymbolRules(min_notional=10.0, min_qty=0.0001,  qty_step=0.00001, tick_size=0.01),
    "XAUUSDT":  SymbolRules(min_notional=10.0, min_qty=0.001,   qty_step=0.00001, tick_size=0.01),
    "XAGUSDT":  SymbolRules(min_notional=10.0, min_qty=0.01,    qty_step=0.00001, tick_size=0.001),
    "BNBUSDT":  SymbolRules(min_notional=10.0, min_qty=0.001,   qty_step=0.00001, tick_size=0.01),
    "SOLUSDT":  SymbolRules(min_notional=10.0, min_qty=0.001,   qty_step=0.00001, tick_size=0.01),
    "XRPUSDT":  SymbolRules(min_notional=10.0, min_qty=0.01,    qty_step=0.00001, tick_size=0.0001),
    # Isolated-test symbols: larger step sizes; not used in live engine scenarios
    "ADAUSDT":  SymbolRules(min_notional=10.0, min_qty=1.0,     qty_step=1.0,     tick_size=0.0001),
    "DOGEUSDT": SymbolRules(min_notional=10.0, min_qty=1.0,     qty_step=1.0,     tick_size=0.00001),
    "SNDKUSDT": SymbolRules(min_notional=10.0, min_qty=1.0,     qty_step=1.0,     tick_size=0.0001),
}


def validate_symbol_registration(
    symbols: list[str],
    exchange: "PaperExchange | None" = None,
) -> list[str]:
    """Return symbols that have no explicit rules configured.

    A symbol is considered "configured" if it appears in BUILTIN_SYMBOL_RULES
    or has been registered on *exchange* via register_symbol_rules().  Symbols
    that are neither will trigger a WARNING fallback at order-submission time.

    Use this at startup::

        unknown = validate_symbol_registration(cfg.symbols, paper_exchange)
        if unknown:
            raise ValueError(f"No symbol rules for: {unknown}")

    Args:
        symbols:  List of symbols to check.
        exchange: If provided, also checks symbols registered on this exchange instance.

    Returns:
        List of symbol strings that have no rules configured.  Empty list
        means all symbols have explicit rules and no fallback warnings will fire.
    """
    unknown = []
    for sym in symbols:
        if exchange is not None and sym in exchange._symbol_rules:
            continue
        if sym in BUILTIN_SYMBOL_RULES:
            continue
        unknown.append(sym)
    return unknown


# ── Order record ───────────────────────────────────────────────────────────────

@dataclass
class PaperOrder:
    """Full lifecycle record for a simulated order."""

    order_id:      str
    symbol:        str
    side:          str          # BUY | SELL
    order_type:    str          # MARKET | LIMIT | STOP_MARKET | STOP_LIMIT | TAKE_PROFIT
    qty:           float
    price:         float | None  # limit price (None for market)
    stop_price:    float | None  # stop trigger price
    time_in_force: str = TIF_GTC
    reduce_only:   bool = False
    instance_id:   str  = ""    # owning strategy instance

    status:         str   = STATUS_NEW
    filled_qty:     float = 0.0
    avg_fill_price: float = 0.0
    total_fee:      float = 0.0
    reject_reason:  str   = ""
    created_at:     str   = field(default_factory=lambda: _now())
    updated_at:     str   = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id":       self.order_id,
            "symbol":         self.symbol,
            "side":           self.side,
            "order_type":     self.order_type,
            "status":         self.status,
            "price":          self.price,
            "stop_price":     self.stop_price,
            "qty":            self.qty,
            "filled_qty":     self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "total_fee":      self.total_fee,
            "time_in_force":  self.time_in_force,
            "reduce_only":    self.reduce_only,
            "reject_reason":  self.reject_reason,
            "created_at":     self.created_at,
            "updated_at":     self.updated_at,
        }


# ── Fill record ────────────────────────────────────────────────────────────────

@dataclass
class PaperFill:
    """A single fill event."""

    order_id:    str
    symbol:      str
    side:        str
    fill_price:  float
    fill_qty:    float
    fee:         float
    is_maker:    bool = False
    filled_at:   str  = field(default_factory=lambda: _now())
    instance_id: str  = ""     # owning strategy instance (positionally last for compat)

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id":    self.order_id,
            "symbol":      self.symbol,
            "instance_id": self.instance_id,
            "side":        self.side,
            "fill_price":  self.fill_price,
            "fill_qty":    self.fill_qty,
            "fee":         self.fee,
            "is_maker":    self.is_maker,
            "filled_at":   self.filled_at,
        }


# ── Paper exchange ─────────────────────────────────────────────────────────────

class PaperExchange(ExchangeAdapter):
    """Simulates exchange order matching against closed OHLCV candles.

    Usage::

        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0005, bus=event_bus)

        # Submit an order (returns PaperOrder with status=ACCEPTED)
        order = ex.submit_order(symbol="BTCUSDT", side="BUY",
                                order_type="MARKET", qty=0.1)

        # On each closed candle, run matching — returns list of fills
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=49500, close=50500)
    """

    def __init__(
        self,
        fee_rate: float = 0.001,
        maker_fee_rate: float = 0.0009,
        slippage_pct: float = 0.0005,
        bus: EventBus | None = None,
    ) -> None:
        self.fee_rate       = fee_rate
        self.maker_fee_rate = maker_fee_rate
        self.slippage_pct   = slippage_pct
        self.bus            = bus

        # symbol → list of open orders (not yet FILLED / CANCELLED / REJECTED)
        self._open_orders: dict[str, list[PaperOrder]] = {}
        # all orders ever seen, by order_id
        self._all_orders:  dict[str, PaperOrder] = {}

        # Per-symbol exchange rules.  Default BTCUSDT rules are used unless
        # overridden via register_symbol_rules().
        self._symbol_rules: dict[str, SymbolRules] = {}

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        """Return exchange filter rules for *symbol*.

        Lookup order:
        1. Explicitly registered via register_symbol_rules() — highest priority.
        2. Built-in rules from BUILTIN_SYMBOL_RULES.
        3. Default (BTCUSDT-equivalent) rules — a WARNING is logged so that
           missing symbol configuration is caught early rather than silently
           applying BTC rules to a symbol that may have very different filters.
        """
        if symbol in self._symbol_rules:
            return self._symbol_rules[symbol]
        if symbol in BUILTIN_SYMBOL_RULES:
            return BUILTIN_SYMBOL_RULES[symbol]
        log.warning(
            "No rules configured for symbol %s; using BTCUSDT defaults. "
            "Add the symbol to BUILTIN_SYMBOL_RULES or call register_symbol_rules().",
            symbol,
        )
        return _DEFAULT_RULES

    def register_symbol_rules(self, symbol: str, rules: SymbolRules) -> None:
        """Override per-symbol exchange rules (e.g. loaded from exchangeInfo)."""
        self._symbol_rules[symbol] = rules

    def get_min_notional(self, symbol: str) -> float:
        """Return the minimum order notional for *symbol* (from SymbolRules)."""
        return self.get_symbol_rules(symbol).min_notional

    # ── Public API ────────────────────────────────────────────────────────────

    def submit_order(
        self,
        symbol:        str,
        side:          str,
        order_type:    str,
        qty:           float,
        price:         float | None = None,
        stop_price:    float | None = None,
        time_in_force: str  = TIF_GTC,
        reduce_only:   bool = False,
        order_id:      str | None = None,
        current_position_size: float = 0.0,
        instance_id:   str = "",
    ) -> PaperOrder:
        """Validate and accept (or reject) a new order.

        Returns a ``PaperOrder`` whose ``status`` is either ``ACCEPTED`` or
        ``REJECTED``.  Rejected orders are still stored so callers can inspect
        ``reject_reason``.

        Args:
            current_position_size: Absolute size of current position in base
                currency.  Used for reduce_only validation.
            instance_id: Strategy instance that owns this order — propagated to
                fills and fill events so positions can be routed correctly.
        """
        oid = order_id or str(uuid.uuid4())
        order = PaperOrder(
            order_id=oid,
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            instance_id=instance_id,
        )

        reject = self._validate(order, current_position_size)
        if reject:
            order.status = STATUS_REJECTED
            order.reject_reason = reject
            order.updated_at = _now()
            self._all_orders[oid] = order
            self._emit_order_event(order, reject)
            log.warning("Order %s rejected: %s", oid[:8], reject)
            return order

        order.status = STATUS_ACCEPTED
        order.updated_at = _now()
        self._all_orders[oid] = order
        self._open_orders.setdefault(symbol, []).append(order)
        self._emit_order_event(order, "order accepted")

        # MARKET orders are queued — they will fill on the *next* candle open.
        # IOC/FOK are also queued; they get special treatment in process_candle.
        log.debug("Order %s accepted: %s %s %s qty=%.5f", oid[:8], symbol, side, order_type, qty)
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.  Returns True if cancelled, False if not found."""
        order = self._all_orders.get(order_id)
        if order is None or order.status not in (STATUS_NEW, STATUS_ACCEPTED, STATUS_PARTIALLY_FILLED):
            return False
        order.status = STATUS_CANCELLED
        order.updated_at = _now()
        symbol = order.symbol
        if symbol in self._open_orders:
            self._open_orders[symbol] = [o for o in self._open_orders[symbol] if o.order_id != order_id]
        self._emit_order_event(order, "cancelled by user")
        return True

    def cancel_all(self, symbol: str | None = None) -> int:
        """Cancel all open orders for *symbol* (or all symbols if None).

        Returns number of orders cancelled.
        """
        count = 0
        symbols = [symbol] if symbol else list(self._open_orders.keys())
        for sym in symbols:
            for order in list(self._open_orders.get(sym, [])):
                if self.cancel_order(order.order_id):
                    count += 1
        return count

    def process_candle(
        self,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        candle_ts: str | None = None,
    ) -> list[PaperFill]:
        """Match all open orders for *symbol* against the provided candle.

        Called once per closed candle.  Returns a list of fills generated.
        Orders that fill are moved to FILLED status and removed from the open
        list.  Resting orders that did not fill remain open (GTC).

        The fill model:
          1. MARKET      → fills at open + slippage (always fills).
          2. LIMIT BUY   → fills when low <= price.
          3. LIMIT SELL  → fills when high >= price.
          4. STOP_MARKET → triggers when bar crosses stop_price; fills at stop
                           or open if gap-through.
          5. STOP_LIMIT  → triggers like STOP_MARKET, then limit check.
          6. TAKE_PROFIT → long: triggers when high >= stop_price;
                           short: triggers when low <= stop_price.

        OCO / same-candle SL-TP policy
        --------------------------------
        When BOTH a stop-loss (STOP_MARKET/STOP_LIMIT) and a take-profit
        (TAKE_PROFIT) order would trigger on the same candle, stop-loss is
        filled first (conservative/worst-case assumption).  After any
        reduce_only order fills, all remaining reduce_only orders for the
        same symbol are cancelled (OCO behaviour).
        """
        fills: list[PaperFill] = []
        ts = candle_ts or _now()

        # Sort orders so protective stop orders are evaluated before take-profit
        # orders.  This implements the conservative "stop-first" same-candle
        # policy: if both SL and TP would trigger, SL wins.
        _SL_TYPES = (ORDER_TYPE_STOP_MARKET, ORDER_TYPE_STOP_LIMIT)
        open_orders = sorted(
            self._open_orders.get(symbol, []),
            key=lambda o: (0 if o.order_type in _SL_TYPES else 1),
        )

        for order in open_orders:
            # Skip orders that were already cancelled (e.g. by OCO logic below)
            if order.status not in (STATUS_NEW, STATUS_ACCEPTED, STATUS_PARTIALLY_FILLED):
                continue

            fill = self._try_fill(order, open_, high, low, close, ts)
            if fill:
                fills.append(fill)
                # Remove from open list
                self._open_orders[symbol] = [
                    o for o in self._open_orders[symbol]
                    if o.order_id != order.order_id
                ]

                # OCO: when a reduce_only order fills, cancel all remaining
                # reduce_only orders for the same symbol so the opposing
                # protective order does not also execute.
                if order.reduce_only:
                    self._cancel_reduce_only_orders(symbol)

        # Remove orders that reached a terminal state during matching but were
        # not removed inline (e.g. market orders rejected at fill time due to
        # MIN_NOTIONAL — _try_fill returns None so the inline removal is skipped).
        self._open_orders[symbol] = [
            o for o in self._open_orders.get(symbol, [])
            if o.status in (STATUS_NEW, STATUS_ACCEPTED, STATUS_PARTIALLY_FILLED)
        ]

        return fills

    def _cancel_reduce_only_orders(self, symbol: str) -> None:
        """Cancel all remaining reduce_only open orders for *symbol* (OCO)."""
        for order in list(self._open_orders.get(symbol, [])):
            if order.reduce_only and order.status in (
                STATUS_NEW, STATUS_ACCEPTED, STATUS_PARTIALLY_FILLED
            ):
                order.status = STATUS_CANCELLED
                order.updated_at = _now()
                self._emit_order_event(order, "cancelled by OCO after sibling fill")
        # Remove cancelled orders from the open list
        self._open_orders[symbol] = [
            o for o in self._open_orders.get(symbol, [])
            if o.status not in (STATUS_CANCELLED, STATUS_REJECTED, STATUS_FILLED)
        ]

    def get_open_orders(self, symbol: str | None = None) -> list[PaperOrder]:
        if symbol:
            return list(self._open_orders.get(symbol, []))
        return [o for orders in self._open_orders.values() for o in orders]

    def get_order(self, order_id: str) -> PaperOrder | None:
        return self._all_orders.get(order_id)

    def get_all_orders(self, symbol: str | None = None, limit: int = 200) -> list[PaperOrder]:
        orders = list(self._all_orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders[:limit]

    def restore_order(self, order: PaperOrder) -> None:
        """Re-register a previously-accepted open order (used on restart recovery)."""
        self._all_orders[order.order_id] = order
        self._open_orders.setdefault(order.symbol, []).append(order)

    # ── Fill logic ─────────────────────────────────────────────────────────────

    def _try_fill(
        self,
        order: PaperOrder,
        open_: float,
        high: float,
        low: float,
        close: float,
        ts: str,
    ) -> PaperFill | None:
        """Return a fill if this candle triggers *order*, else None."""

        ot = order.order_type

        if ot == ORDER_TYPE_MARKET:
            return self._fill_market(order, open_, ts)

        if ot == ORDER_TYPE_LIMIT:
            return self._fill_limit(order, open_, high, low, ts)

        if ot == ORDER_TYPE_STOP_MARKET:
            return self._fill_stop_market(order, open_, high, low, ts)

        if ot == ORDER_TYPE_STOP_LIMIT:
            return self._fill_stop_limit(order, open_, high, low, ts)

        if ot == ORDER_TYPE_TAKE_PROFIT:
            return self._fill_take_profit(order, open_, high, low, ts)

        log.warning("Unknown order type %s for %s", ot, order.order_id[:8])
        return None

    def _fill_market(
        self, order: PaperOrder, open_: float, ts: str
    ) -> PaperFill | None:
        """Market order — fills at open with taker slippage.

        Returns None if the fill notional is below the minimum (e.g. price
        moved significantly between order submission and next candle open).
        """
        if order.side == SIDE_BUY:
            fill_price = open_ * (1.0 + self.slippage_pct)
        else:
            fill_price = open_ * (1.0 - self.slippage_pct)

        # Validate minimum notional at fill time using the actual fill price.
        # MARKET orders cannot be checked at submission (no price known yet).
        rules = self.get_symbol_rules(order.symbol)
        fill_price = _round_tick(fill_price, rules.tick_size)
        notional = fill_price * order.qty
        if notional < rules.min_notional:
            reject = (
                f"market fill notional {notional:.4f} below minimum "
                f"{rules.min_notional} (fill_price={fill_price:.2f})"
            )
            order.status = STATUS_REJECTED
            order.reject_reason = reject
            order.updated_at = ts
            self._emit_order_event(order, reject)
            log.warning(
                "Market order %s rejected at fill time: %s (symbol=%s qty=%.5f)",
                order.order_id[:8], reject, order.symbol, order.qty,
            )
            return None

        return self._record_fill(order, fill_price, order.qty, is_maker=False, ts=ts)

    def _fill_limit(
        self, order: PaperOrder, open_: float, high: float, low: float, ts: str
    ) -> PaperFill | None:
        """Limit order — fills when bar crosses the limit price."""
        price = order.price
        if price is None:
            return None

        rules = self.get_symbol_rules(order.symbol)

        if order.side == SIDE_BUY:
            # Fills when bar_low dips to or below limit price.
            # If bar opens below limit (gap-down), fill at open (better price).
            if low > price:
                return None
            fill_price = min(price, open_)
        else:
            # Fills when bar_high rises to or above limit price.
            if high < price:
                return None
            fill_price = max(price, open_)

        fill_price = _round_tick(fill_price, rules.tick_size)

        if order.time_in_force == TIF_IOC:
            # IOC: fill or cancel immediately; no partial fills in paper mode
            pass  # fills fully below
        if order.time_in_force == TIF_FOK:
            # FOK: full fill or cancel — always full fill in paper mode
            pass

        return self._record_fill(order, fill_price, order.qty, is_maker=True, ts=ts)

    def _fill_stop_market(
        self, order: PaperOrder, open_: float, high: float, low: float, ts: str
    ) -> PaperFill | None:
        """Stop market — triggers on breach, fills at stop or gap open."""
        stop = order.stop_price
        if stop is None:
            return None

        if order.side == SIDE_BUY:
            # BUY stop: triggers when price rises to stop (e.g. short SL or breakout)
            if high < stop:
                return None
            # Gap-up through stop: if bar_open >= stop, fill at open
            raw = max(stop, open_)
        else:
            # SELL stop: triggers when price falls to stop (e.g. long SL)
            if low > stop:
                return None
            # Gap-down through stop: fill at open if open < stop
            raw = min(stop, open_)

        if order.side == SIDE_BUY:
            fill_price = raw * (1.0 + self.slippage_pct)
        else:
            fill_price = raw * (1.0 - self.slippage_pct)

        rules = self.get_symbol_rules(order.symbol)
        fill_price = _round_tick(fill_price, rules.tick_size)
        return self._record_fill(order, fill_price, order.qty, is_maker=False, ts=ts)

    def _fill_stop_limit(
        self, order: PaperOrder, open_: float, high: float, low: float, ts: str
    ) -> PaperFill | None:
        """Stop limit — triggers like stop market, then applies limit check."""
        stop = order.stop_price
        price = order.price
        if stop is None or price is None:
            return None

        if order.side == SIDE_BUY:
            if high < stop:
                return None
            raw_trigger = max(stop, open_)
            # After trigger, treat as limit buy: fill if low <= price
            if low > price:
                return None
            fill_price = min(price, raw_trigger)
        else:
            if low > stop:
                return None
            raw_trigger = min(stop, open_)
            if high < price:
                return None
            fill_price = max(price, raw_trigger)

        rules = self.get_symbol_rules(order.symbol)
        fill_price = _round_tick(fill_price, rules.tick_size)
        return self._record_fill(order, fill_price, order.qty, is_maker=True, ts=ts)

    def _fill_take_profit(
        self, order: PaperOrder, open_: float, high: float, low: float, ts: str
    ) -> PaperFill | None:
        """Take profit — triggers when price reaches the take-profit level.

        For long positions (SELL side): triggers when high >= stop_price.
        For short positions (BUY side): triggers when low <= stop_price.
        """
        stop = order.stop_price
        if stop is None:
            return None

        rules = self.get_symbol_rules(order.symbol)

        if order.side == SIDE_SELL:
            # Long TP: sell when price rises to target
            if high < stop:
                return None
            # Gap-up: if open >= stop, fill at open (better price)
            raw = max(stop, open_)
            fill_price = raw * (1.0 - self.slippage_pct)
            is_maker = open_ < stop  # resting if not gapped through
        else:
            # Short TP: buy when price falls to target
            if low > stop:
                return None
            raw = min(stop, open_)
            fill_price = raw * (1.0 + self.slippage_pct)
            is_maker = open_ > stop

        fill_price = _round_tick(fill_price, rules.tick_size)
        return self._record_fill(order, fill_price, order.qty, is_maker=is_maker, ts=ts)

    # ── Internal helpers ───────────────────────────────────────────────────────

    # ── State transition guard ─────────────────────────────────────────────────

    # Valid order status transitions.  Terminal states (FILLED, REJECTED,
    # CANCELLED, EXPIRED) have no outgoing edges.
    _VALID_TRANSITIONS: dict[str, set[str]] = {
        STATUS_NEW:              {STATUS_ACCEPTED, STATUS_REJECTED},
        STATUS_ACCEPTED:         {STATUS_FILLED, STATUS_CANCELLED, STATUS_PARTIALLY_FILLED},
        STATUS_PARTIALLY_FILLED: {STATUS_FILLED, STATUS_CANCELLED},
        STATUS_FILLED:           set(),   # terminal
        STATUS_REJECTED:         set(),   # terminal
        STATUS_CANCELLED:        set(),   # terminal
        STATUS_EXPIRED:          set(),   # terminal
    }

    def _validate_transition(self, order: PaperOrder, new_status: str) -> bool:
        """Log and return False if *new_status* is not reachable from current status.

        Returns True if the transition is valid.
        """
        allowed = self._VALID_TRANSITIONS.get(order.status, set())
        if new_status not in allowed:
            log.warning(
                "Invalid order state transition %s → %s for order %s (symbol=%s)",
                order.status, new_status, order.order_id[:8], order.symbol,
            )
            return False
        return True

    def _record_fill(
        self,
        order: PaperOrder,
        fill_price: float,
        fill_qty: float,
        is_maker: bool,
        ts: str,
    ) -> PaperFill:
        """Update order state and create a PaperFill record."""
        self._validate_transition(order, STATUS_FILLED)

        fee_rate = self.maker_fee_rate if is_maker else self.fee_rate
        fee = fill_price * fill_qty * fee_rate

        order.filled_qty = order.qty  # paper: always full fill
        order.avg_fill_price = fill_price
        order.total_fee += fee
        order.status = STATUS_FILLED
        order.updated_at = ts

        self._emit_order_event(order, f"filled at {fill_price:.2f}")

        fill = PaperFill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fee=fee,
            is_maker=is_maker,
            filled_at=ts,
            instance_id=order.instance_id,
        )

        if self.bus:
            self.bus.emit(FillEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                instance_id=order.instance_id,
                side=order.side,
                fill_price=fill_price,
                fill_qty=fill_qty,
                fee=fee,
                is_maker=is_maker,
            ))

        log.debug(
            "Fill %s: %s %s qty=%.5f @ %.2f fee=%.4f maker=%s",
            order.order_id[:8], order.symbol, order.side,
            fill_qty, fill_price, fee, is_maker,
        )
        return fill

    def _validate(self, order: PaperOrder, current_position_size: float) -> str:
        """Return a rejection reason string, or empty string if valid."""
        rules = self.get_symbol_rules(order.symbol)

        if order.qty < rules.min_qty:
            return f"qty {order.qty} below minimum {rules.min_qty}"

        # Reject quantities that are not exact multiples of the step size.
        # Use Decimal arithmetic to avoid floating-point rounding errors.
        if not _qty_step_valid(order.qty, rules.qty_step):
            return (
                f"qty {order.qty} is not a valid multiple of step {rules.qty_step}"
            )

        # Estimate notional for non-market orders (price is known at submission).
        # MARKET orders are checked at fill time when the real fill price is known.
        ref_price = order.price or order.stop_price
        if ref_price is not None and order.qty * ref_price < rules.min_notional:
            return (
                f"notional {order.qty * ref_price:.2f} below minimum "
                f"{rules.min_notional}"
            )

        if order.order_type in (ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_LIMIT):
            if order.price is None:
                return f"{order.order_type} requires price"

        if order.order_type in (ORDER_TYPE_STOP_MARKET, ORDER_TYPE_STOP_LIMIT, ORDER_TYPE_TAKE_PROFIT):
            if order.stop_price is None:
                return f"{order.order_type} requires stop_price"

        if order.reduce_only and order.qty > current_position_size:
            return (
                f"reduce_only order qty {order.qty} exceeds "
                f"position size {current_position_size}"
            )

        if order.side not in (SIDE_BUY, SIDE_SELL):
            return f"unknown side: {order.side}"

        if order.order_type not in (
            ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP_MARKET,
            ORDER_TYPE_STOP_LIMIT, ORDER_TYPE_TAKE_PROFIT,
        ):
            return f"unsupported order_type: {order.order_type}"

        return ""

    def _emit_order_event(self, order: PaperOrder, detail: str) -> None:
        if self.bus:
            self.bus.emit(OrderEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                status=order.status,
                detail=detail,
            ))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_tick(price: float, tick: float = TICK_SIZE) -> float:
    """Round *price* to nearest tick size."""
    return round(round(price / tick) * tick, 10)


def _qty_step_valid(qty: float, step: float) -> bool:
    """Return True iff *qty* is an exact non-zero multiple of *step*.

    Uses ``Decimal`` arithmetic to avoid floating-point rounding artifacts.
    For example: qty=0.00003, step=0.00001 → True (3 × step).
                 qty=0.0000137, step=0.00001 → False (not a whole multiple).
    """
    if qty <= 0 or step <= 0:
        return False
    try:
        qty_d  = Decimal(str(qty))
        step_d = Decimal(str(step))
        remainder = qty_d % step_d
        return remainder == Decimal("0")
    except Exception:
        # Malformed input — fail safe (reject)
        return False
