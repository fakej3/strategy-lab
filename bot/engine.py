"""Bot engine — the core signal→order pipeline.

Receives closed OHLCV candles from the runtime feed, runs the strategy,
applies risk checks, submits paper orders, and updates portfolio state.

Pipeline per candle
-------------------
  CandleEvent
    → push to state buffer
    → generate_signals(buffer_df) — last signal is the action
    → risk check
    → if BUY signal + no open position → submit MARKET BUY
    → if EXIT/SELL signal + open position → submit MARKET SELL
    → fill next candle open (PaperExchange defers to next process_candle call)
    → on fill: update portfolio + position manager + daily stats
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from .config import BotConfig
from .events import (
    BotEvent,
    CandleEvent,
    DailyResetEvent,
    ErrorEvent,
    EventBus,
    FillEvent,
    SignalEvent,
)
from .order_manager import OrderManager
from .paper_exchange import PaperFill, SIDE_BUY, SIDE_SELL
from .portfolio import Portfolio
from .position_manager import PositionManager
from .risk import RiskContext, RiskEngine
from .state import BotState, CandleRow
from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.engine")


class BotEngine:
    """Stateful pipeline: candle → signal → risk → order → portfolio.

    Components are injected (no direct instantiation) so they can be unit-
    tested independently.  The engine subscribes to CandleEvents from the
    EventBus and also handles FillEvents to update portfolio accounting.
    """

    def __init__(
        self,
        config: BotConfig,
        strategy: Any,             # StrategyBase subclass instance
        state: BotState,
        orders: OrderManager,
        positions: PositionManager,
        portfolio: Portfolio,
        risk: RiskEngine,
        storage: BotStorage,
        bus: EventBus,
    ) -> None:
        self.config    = config
        self.strategy  = strategy   # original value; may be a dict or single instance
        self.state     = state

        # Support both a single strategy instance (applied to all symbol/interval pairs)
        # and a dict of {(symbol, interval): strategy_instance} for per-pair isolation.
        if isinstance(strategy, dict):
            self._strategy_map: dict[tuple[str, str], Any] = strategy
            self._strategy_default: Any = None
        else:
            self._strategy_map = {}
            self._strategy_default = strategy
        self.orders    = orders
        self.positions = positions
        self.portfolio = portfolio
        self.risk      = risk
        self.storage   = storage
        self.bus       = bus

        self._starting_equity = config.paper_capital

        # max_risk_pct is a RISK LIMIT checked by RiskEngine, NOT a sizing
        # input.  Order size is always computed from equity_fraction.  A proper
        # risk-per-trade sizer needs stop-loss distance at submission time,
        # which is not yet available in this pipeline.
        log.info(
            "Sizing: equity_fraction=%.2f%% — max_risk_pct=%.2f%% is a post-sizing "
            "risk limit enforced by RiskEngine, not used for qty calculation.",
            config.equity_fraction * 100,
            config.risk.max_risk_pct * 100,
        )

        # Subscribe to events
        bus.subscribe(CandleEvent, self._on_candle)
        bus.subscribe(FillEvent,  self._on_fill)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_candle(self, event: CandleEvent) -> None:
        """Handle a closed candle from the feed."""
        t0 = time.monotonic()
        try:
            candle = CandleRow(
                symbol=event.symbol,
                interval=event.interval,
                open_time=event.open_time,
                open=event.open,
                high=event.high,
                low=event.low,
                close=event.close,
                volume=event.volume,
                close_time=event.close_time,
            )
            # Always push to buffer — history candles warm the strategy.
            self.state.push_candle(candle)

            # History (backfill) candles must NEVER trigger order submission or
            # order matching.  They exist only to warm the indicator buffer
            # before live trading begins.
            if event.is_history:
                return

            # 1. Match any pending orders against this candle
            ts = event.ts.isoformat() if event.ts else None
            fills = self.orders.on_candle(
                symbol=event.symbol,
                open_=event.open,
                high=event.high,
                low=event.low,
                close=event.close,
                candle_ts=ts,
            )

            # 2. Generate signal from strategy
            self._maybe_signal(event)

        except Exception:
            log.exception("Engine error on candle %s %s", event.symbol, event.interval)
            self.bus.emit(ErrorEvent(
                source="engine",
                message="Candle processing error",
                detail=f"{event.symbol} {event.interval}",
            ))
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self.state.record_latency(elapsed_ms)

    def _on_fill(self, event: FillEvent) -> None:
        """Handle a fill event — update portfolio and positions."""
        try:
            # Rebuild a PaperFill-like object from the event
            fill = _fill_from_event(event)

            # Determine if this fill closes or opens a position
            pos_before = self.positions.has_open_position(event.symbol)

            updated_pos = self.positions.on_fill(
                fill, equity=self._current_equity()
            )

            # Determine realized PnL (None for entry fills)
            closed_pnl: float | None = None
            if pos_before and updated_pos.status == "closed":
                closed_pnl = updated_pos.realized_pnl
                log.info(
                    "Position closed: %s pnl=%.4f",
                    event.symbol, closed_pnl,
                )
                self._update_daily_stats(closed_pnl)

            self.portfolio.on_fill(fill, closed_pnl=closed_pnl)

        except Exception:
            log.exception("Engine error processing fill %s", event.order_id)

    # ── Signal generation ─────────────────────────────────────────────────────

    def _get_strategy(self, symbol: str, interval: str) -> Any | None:
        """Return the strategy for (symbol, interval), or the global default."""
        if self._strategy_map:
            return self._strategy_map.get((symbol, interval))
        return self._strategy_default

    def _maybe_signal(self, event: CandleEvent) -> None:
        """Run strategy and submit order if signal warrants it."""
        buf_len = self.state.buffer_length(event.symbol, event.interval)
        if buf_len < self.config.min_signal_bars:
            return

        df = self.state.get_buffer_df(event.symbol, event.interval)
        if df.empty:
            return

        strategy = self._get_strategy(event.symbol, event.interval)
        if strategy is None:
            log.warning("No strategy configured for %s %s", event.symbol, event.interval)
            return

        try:
            signals = strategy.generate_signals(df)
        except Exception:
            log.exception("Strategy error for %s %s", event.symbol, event.interval)
            return

        if signals.empty:
            return

        last_signal = signals.iloc[-1]

        # Normalize to a plain string regardless of whether the strategy
        # returned a Signal enum (dtype=object Series) or a raw string (inferred
        # string dtype Series).  In Python 3.11+ str(Signal.BUY) produces
        # "Signal.BUY", not "BUY", so we must use .value on enum members.
        signal_str: str = (
            last_signal.value                          # Signal enum member
            if hasattr(last_signal, "value")
            else str(last_signal)                      # plain string fallback
        )

        # Emit signal event regardless of action
        self.bus.emit(SignalEvent(
            symbol=event.symbol,
            interval=event.interval,
            signal=signal_str,
        ))

        has_position = self.positions.has_open_position(event.symbol)

        if signal_str == "BUY" and not has_position:
            self._submit_entry(event.symbol, event.close)
        elif signal_str in ("EXIT", "SELL") and has_position:
            self._submit_exit(event.symbol, event.close)

    def _submit_entry(self, symbol: str, close_price: float) -> None:
        """Size and submit a market entry order."""
        equity = self._current_equity()
        qty = self._size_order(equity, close_price)
        if qty <= 0:
            log.warning("Entry sizing produced qty=0 for %s", symbol)
            return

        # Pre-flight notional check: reject orders whose notional is below
        # the exchange minimum BEFORE submission.  MARKET orders have no price
        # at submission, so PaperExchange defers the check to fill time —
        # which causes the order to be accepted, sit in the open book, and then
        # be silently rejected on the next candle.  Checking here avoids
        # accumulating rejected orphan orders and gives an actionable log line.
        notional = qty * close_price
        min_notional = self.orders.exchange.get_min_notional(symbol)
        if min_notional > 0 and notional < min_notional:
            log.warning(
                "Skipping entry for %s: notional %.4f USDT is below the exchange "
                "minimum of %.2f USDT (equity=%.2f equity_fraction=%.3f qty=%.5f "
                "price=%.2f). Increase capital or equity_fraction to place trades.",
                symbol, notional, min_notional,
                equity, self.config.equity_fraction, qty, close_price,
            )
            return

        risk_ctx = RiskContext(
            symbol=symbol,
            side=SIDE_BUY,
            qty=qty,
            ref_price=close_price,
            equity=equity,
            peak_equity=self.portfolio.peak_equity,
            daily_pnl=self.portfolio.daily_pnl,
            n_trades_today=self.portfolio.n_trades_today,
            open_positions=self.positions.open_position_count(),
            total_exposure=self.positions.total_exposure(),
            last_trade_ts=self.portfolio.last_trade_ts,
        )
        reason = self.risk.check(risk_ctx)
        if reason:
            return

        self.orders.submit_market(
            symbol=symbol,
            side=SIDE_BUY,
            qty=qty,
        )
        log.info("Entry order submitted: %s BUY qty=%.5f @ ~%.2f", symbol, qty, close_price)

    def _submit_exit(self, symbol: str, close_price: float) -> None:
        """Submit a market exit order for the current position."""
        pos = self.positions.get_open(symbol)
        if pos is None:
            return

        # Cancel any resting SL/TP orders before exiting
        self.orders.cancel_all(symbol)

        self.orders.submit_market(
            symbol=symbol,
            side=SIDE_SELL,
            qty=pos.size,
            reduce_only=True,
            current_position_size=pos.size,
        )
        log.info("Exit order submitted: %s SELL qty=%.5f @ ~%.2f", symbol, pos.size, close_price)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _current_equity(self) -> float:
        """Cash + market value of open positions at current mark prices.

        Using mark_price * size (not unrealized_pnl) so that equity includes
        the full notional of open positions, not just the gain/loss from entry.
        cash is already reduced by the entry notional on each BUY fill, so
        cash + position_market_value = true portfolio value.
        """
        marks = self.state.all_mark_prices()
        open_positions = self.positions.get_all_open()
        position_value = sum(
            marks.get(p.symbol, p.avg_entry_price) * p.size
            for p in open_positions
        )
        return self.portfolio.cash + position_value

    def _size_order(self, equity: float, price: float) -> float:
        """Compute order quantity from equity fraction and price."""
        if price <= 0:
            return 0.0
        notional = equity * self.config.equity_fraction
        notional = min(notional, self.config.risk.max_position_size_usd)
        qty = notional / price
        return round(qty, self.config.qty_precision)

    def _update_daily_stats(self, pnl: float) -> None:
        """Persist daily stats after each trade closes."""
        try:
            equity = self._current_equity()
            stats = self.portfolio.daily_stats(equity, self._starting_equity)
            self.storage.upsert_daily_stats(stats)
        except Exception:
            log.exception("Failed to update daily stats")

    def on_daily_reset(self, event: DailyResetEvent) -> None:
        """Called at midnight UTC — persist final daily stats and reset counters."""
        try:
            equity = self._current_equity()
            stats = self.portfolio.daily_stats(
                equity, self._starting_equity, date_utc=event.date_utc
            )
            self.storage.upsert_daily_stats(stats)
        except Exception:
            log.exception("Failed to finalize daily stats")
        self.portfolio.reset_daily()
        log.info("Daily reset complete for %s", event.date_utc)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fill_from_event(event: FillEvent):
    """Create a minimal PaperFill-compatible object from a FillEvent."""
    from .paper_exchange import PaperFill
    from datetime import timezone
    return PaperFill(
        order_id=event.order_id,
        symbol=event.symbol,
        side=event.side,
        fill_price=event.fill_price,
        fill_qty=event.fill_qty,
        fee=event.fee,
        is_maker=event.is_maker,
        filled_at=event.ts.isoformat() if event.ts else "",
    )
