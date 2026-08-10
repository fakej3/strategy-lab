"""Paper trading bot lifecycle manager — runs inside the FastAPI server process.

Only one bot instance may run at a time.  The bot's asyncio event loop runs
in a dedicated daemon thread so it never blocks FastAPI's own event loop.

Usage
-----
    from server.bot_manager import bot_manager

    ok, err = bot_manager.start(capital=25.0, symbols=["BTCUSDT"], ...)
    status  = bot_manager.get_status()
    ok, err = bot_manager.stop()
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("strategy_lab.server.bot_manager")


class BotManager:
    """Thread-safe singleton that owns the paper trading bot lifecycle."""

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._running     = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._config      = None   # BotConfig while running
        self._portfolio   = None   # Portfolio — in-memory cash reads
        self._positions   = None   # PositionManager — in-memory position reads
        self._state       = None   # BotState — candle buffers and counters
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._error: str  = ""

        # Priority-split event queues.
        # HIGH: fills/signals/errors/positions/reconnects — never dropped.
        # LOW : candles/ticks — oldest dropped when full.
        self._q_high: queue.Queue = queue.Queue()          # unbounded
        self._q_low:  queue.Queue = queue.Queue(maxsize=500)

        # Active (symbol, interval) viewed in the chart.  When set, only that
        # pair receives full OHLCV candle events; all others get lightweight ticks.
        self._active_symbol:   str | None = None
        self._active_interval: str | None = None
        # Last-seen close price per (symbol, interval) for tick change calculation.
        self._last_close: dict[tuple[str, str], float] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(
        self,
        capital: float,
        symbols: list[str],
        interval: str | None = None,
        intervals: list[str] | None = None,
        strategy: str = "EMACrossover",
        db_path: str = "bot.db",
        log_path: str = "logs/bot.log",
        recover: bool = True,
        max_open_positions: int | None = None,
    ) -> tuple[bool, str]:
        """Build a BotConfig and start the bot. Returns (success, error_message).

        Accepts either ``intervals`` (list) or the legacy ``interval`` (single
        string).  ``intervals`` takes precedence when both are supplied.

        ``max_open_positions`` defaults to ``len(symbols)`` so every configured
        symbol can hold one position simultaneously.  Pass an explicit value to
        override (e.g. 1 for single-market mode, N for a tighter portfolio limit).
        """
        from bot.config import BotConfig, FeedConfig, RiskConfig

        resolved_intervals: list[str] = (
            intervals if intervals
            else ([interval] if interval else ["1h"])
        )
        n_symbols = len(symbols)
        resolved_max_positions: int = (
            max_open_positions if max_open_positions is not None else n_symbols
        )

        # Per-position notional cap: divide total available capital by number of
        # symbols so each position uses at most its fair share.  Floor at 1 USD
        # to avoid degenerate zero limits.
        per_position_usd = max(1.0, (capital * 0.8) / max(n_symbols, 1))
        per_position_cap = min(per_position_usd, 20.0 * max(n_symbols, 1))

        # Portfolio-level total exposure cap: 80% of capital (prevents over-
        # allocation when many positions are open simultaneously).
        total_exposure_cap = capital * 0.8

        try:
            cfg = BotConfig(
                paper_capital    = capital,
                strategy_name    = strategy,
                strategy_params  = {"fast": 20, "slow": 50},
                feed             = FeedConfig(
                    symbols   = symbols,
                    intervals = resolved_intervals,
                ),
                risk = RiskConfig(
                    max_open_positions    = resolved_max_positions,
                    max_position_size_usd = per_position_cap,
                    max_total_exposure_usd = total_exposure_cap,
                    max_daily_loss_usd    = capital * 0.05,
                ),
                db_path            = db_path,
                log_path           = log_path,
                recover_on_restart = recover,
            )
        except ValueError as exc:
            return False, str(exc)

        with self._lock:
            if self._running:
                return False, "Bot is already running"
            if self._thread and self._thread.is_alive():
                return False, "Previous bot thread still shutting down — please wait"
            self._config     = cfg
            self._error      = ""
            self._running    = True
            self._started_at = datetime.now(timezone.utc)
            self._stopped_at = None

        # Drain stale events from previous run
        for q in (self._q_high, self._q_low):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

        self._thread = threading.Thread(
            target=self._run_in_thread,
            daemon=True,
            name="paper-bot",
        )
        self._thread.start()
        return True, ""

    def stop(self) -> tuple[bool, str]:
        """Request bot shutdown. Blocks up to 15 s waiting for the thread."""
        with self._lock:
            if not self._running:
                return False, "Bot is not running"
            loop = self._loop
            task = self._task

        if loop and task:
            loop.call_soon_threadsafe(task.cancel)

        if self._thread:
            self._thread.join(timeout=15)

        with self._lock:
            self._running    = False
            self._stopped_at = datetime.now(timezone.utc)
        return True, ""

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # LOW-priority event types — candles and ticks.  Everything else (fills,
    # signals, errors, positions, reconnects…) is HIGH and never dropped.
    _LOW_EV_TYPES: frozenset[str] = frozenset({"candle", "tick"})

    def _enqueue(self, ev_dict: dict) -> None:
        """Enqueue an event for the WebSocket.

        HIGH-priority events (fills, errors, …) go to an unbounded queue and
        are never dropped.  LOW-priority events (candles, ticks) go to a
        bounded queue; when it is full the oldest LOW event is discarded.
        """
        ev_type = ev_dict.get("type", "")
        if ev_type in self._LOW_EV_TYPES:
            try:
                self._q_low.put_nowait(ev_dict)
            except queue.Full:
                try:
                    self._q_low.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._q_low.put_nowait(ev_dict)
                except queue.Full:
                    pass
        else:
            self._q_high.put_nowait(ev_dict)

    def drain_events(self, max_n: int = 50) -> list[dict]:
        """Return up to *max_n* queued bot events without blocking.

        HIGH-priority events (fills, signals, errors…) are always drained
        first so they reach the browser before any pending candle updates.
        """
        events: list[dict] = []
        # HIGH priority first
        while len(events) < max_n:
            try:
                events.append(self._q_high.get_nowait())
            except queue.Empty:
                break
        # LOW priority for remaining slots
        remaining = max_n - len(events)
        for _ in range(remaining):
            try:
                events.append(self._q_low.get_nowait())
            except queue.Empty:
                break
        return events

    def set_active_pair(self, symbol: str, interval: str) -> None:
        """Record which (symbol, interval) the browser is currently viewing.

        Once set, only that pair receives full OHLCV candle events; every
        other pair sends lightweight tick events for the Market Watch table.
        Thread-safe — can be called from any request handler.
        """
        with self._lock:
            self._active_symbol   = symbol
            self._active_interval = interval

    def get_candles(self, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        """Return the most recent OHLCV candles from the live buffer.

        Uses the Phase 2A cache (BotState.get_buffer_df) so sort/dedup only
        runs when the buffer has been modified since the last call.

        ``time`` is ``open_time // 1000`` (Unix seconds at candle open), which
        is the canonical x-axis key used by both the REST endpoint and the live
        WebSocket feed so the frontend can deduplicate updates without drift.
        """
        with self._lock:
            state = self._state
        if state is None:
            return []
        df = state.get_buffer_df(symbol, interval)
        if df.empty:
            return []
        df = df.tail(limit)
        return [
            {
                "time":   int(row.open_time) // 1000,  # Unix seconds at candle open
                "open":   row.open,
                "high":   row.high,
                "low":    row.low,
                "close":  row.close,
                "volume": row.volume,
            }
            for row in df.itertuples()
        ]

    def get_counters(self) -> dict:
        """Return runtime counters from BotState."""
        with self._lock:
            state = self._state
        if state is None:
            return {}
        return state.counters()

    def get_status(self) -> dict[str, Any]:
        """Return a status dict suitable for JSON serialisation."""
        with self._lock:
            running     = self._running
            cfg         = self._config
            started_at  = self._started_at
            stopped_at  = self._stopped_at
            error       = self._error
            portfolio   = self._portfolio
            positions_m = self._positions
            state       = self._state

        result: dict[str, Any] = {
            "running":         running,
            "started_at":      started_at.isoformat()  if started_at  else None,
            "stopped_at":      stopped_at.isoformat()  if stopped_at  else None,
            "error":           error,
            "symbols":         cfg.feed.symbols          if cfg else [],
            "intervals":       cfg.feed.intervals        if cfg else [],
            "interval":        (cfg.feed.intervals[0]
                                if cfg and cfg.feed.intervals else "—"),
            "strategy":        cfg.strategy_name          if cfg else "",
            "capital":         cfg.paper_capital           if cfg else 0.0,
            # live numbers (filled below)
            "cash":            cfg.paper_capital           if cfg else 0.0,
            "equity":          cfg.paper_capital           if cfg else 0.0,
            "unrealized_pnl":  0.0,
            "realized_pnl":    0.0,
            "drawdown":        0.0,
            "open_positions":  [],
            "recent_trades":   [],
            "log_tail":        [],
            "mark_prices":     {},
        }

        # In-memory cash (always current, no DB round-trip)
        if portfolio:
            try:
                result["cash"] = portfolio.cash
            except Exception:
                pass

        # In-memory open positions
        if positions_m:
            try:
                result["open_positions"] = [
                    {
                        "symbol":      p.symbol,
                        "direction":   p.direction,
                        "size":        p.size,
                        "entry_price": p.avg_entry_price,
                        "notional":    round(p.notional(), 4),
                        "opened_at":   p.opened_at,
                    }
                    for p in positions_m.get_all_open()
                ]
            except Exception:
                pass

        # Live mark prices from BotState
        if state:
            try:
                result["mark_prices"] = state.all_mark_prices()
            except Exception:
                pass

        # Storage reads (thread-safe — BotStorage uses RLock internally)
        if cfg:
            try:
                from bot.storage import BotStorage
                reader = BotStorage(cfg.db_path)
                reader.connect()
                try:
                    hist = reader.get_balance_history(limit=1)
                    if hist:
                        snap = hist[0]
                        result["equity"]        = snap.get("equity",    result["cash"])
                        result["unrealized_pnl"] = snap.get("unrealized", 0.0)
                        result["drawdown"]      = snap.get("drawdown",  0.0)

                    fills = reader.get_fills(limit=20)
                    result["recent_trades"] = fills

                    closed = reader.get_positions(limit=500)
                    result["realized_pnl"] = sum(
                        p.get("realized_pnl", 0.0)
                        for p in closed
                        if p.get("status") == "closed"
                    )
                finally:
                    reader.close()
            except Exception:
                log.debug("Status storage read failed", exc_info=True)

        # Log tail (last 50 lines of bot log file)
        if cfg:
            try:
                lp = Path(cfg.log_path)
                if lp.exists():
                    lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
                    result["log_tail"] = lines[-50:]
            except Exception:
                pass

        return result

    # ── Background thread ──────────────────────────────────────────────────────

    def _run_in_thread(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            loop.run_until_complete(self._run_bot())
        except Exception:
            log.exception("Bot thread raised an unhandled exception")
            with self._lock:
                import traceback
                self._error = traceback.format_exc(limit=10)
        finally:
            loop.close()
            with self._lock:
                self._running   = False
                self._loop      = None
                self._task      = None
                self._portfolio = None
                self._positions = None
                self._state     = None

    async def _run_bot(self) -> None:
        """Core bot coroutine — mirrors bot_trade._main() without argparse."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from bot.engine import BotEngine
        from bot.events import (
            CandleEvent, DailyResetEvent, DisconnectEvent, ErrorEvent,
            EventBus, FillEvent, OrderEvent, PositionEvent, ReconnectEvent,
            RiskRejectionEvent, SignalEvent,
        )
        from bot.monitor import Monitor
        from bot.order_manager import OrderManager
        from bot.paper_exchange import PaperExchange
        from bot.portfolio import Portfolio
        from bot.position_manager import PositionManager
        from bot.report import generate_daily_report
        from bot.risk import RiskEngine
        from bot.runtime import LiveFeed
        from bot.scheduler import Scheduler
        from bot.state import BotState
        from bot.storage import BotStorage
        from bot_trade import _load_strategy

        cfg = self._config

        from bot.paper_exchange import MIN_NOTIONAL
        min_equity_needed = MIN_NOTIONAL / cfg.equity_fraction
        log.info(
            "Bot starting: capital=%.2f equity_fraction=%.2f "
            "max_position_usd=%.2f min_notional=%.2f "
            "min_capital_for_fill=%.2f symbols=%s intervals=%s strategy=%s",
            cfg.paper_capital, cfg.equity_fraction,
            cfg.risk.max_position_size_usd, MIN_NOTIONAL,
            min_equity_needed, cfg.feed.symbols,
            cfg.feed.intervals, cfg.strategy_name,
        )
        if cfg.paper_capital < min_equity_needed:
            log.warning(
                "CAPITAL TOO SMALL: paper_capital=%.2f < minimum %.2f USDT "
                "(min_notional=%.2f / equity_fraction=%.2f). "
                "All market orders will be rejected at fill time with no fills.",
                cfg.paper_capital, min_equity_needed,
                MIN_NOTIONAL, cfg.equity_fraction,
            )

        # Wire up a file handler so the UI can tail the bot log
        bot_log_root = logging.getLogger("strategy_lab.bot")
        file_handler: logging.FileHandler | None = None
        try:
            Path(cfg.log_path).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(cfg.log_path)
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            bot_log_root.addHandler(file_handler)
        except Exception:
            file_handler = None

        try:
            bus      = EventBus()
            storage  = BotStorage(cfg.db_path)
            storage.connect()
            state    = BotState(buffer_size=cfg.buffer_size)
            exchange = PaperExchange(
                fee_rate       = cfg.fee_rate,
                maker_fee_rate = cfg.maker_fee_rate,
                slippage_pct   = cfg.slippage_pct,
                bus            = bus,
            )
            orders    = OrderManager(exchange=exchange, storage=storage, bus=bus)
            positions = PositionManager(storage=storage, bus=bus)
            portfolio = Portfolio(
                starting_capital = cfg.paper_capital,
                storage          = storage,
                bus              = bus,
                fee_rate         = cfg.fee_rate,
            )
            risk     = RiskEngine(config=cfg.risk, bus=bus)
            # Create an independent strategy instance for every (symbol, interval)
            # pair so that stateful strategies never cross-contaminate buffers.
            strategy_map = {
                (sym, iv): _load_strategy(cfg)
                for sym in cfg.feed.symbols
                for iv in cfg.feed.intervals
            }
            engine   = BotEngine(
                config    = cfg,
                strategy  = strategy_map,
                state     = state,
                orders    = orders,
                positions = positions,
                portfolio = portfolio,
                risk      = risk,
                storage   = storage,
                bus       = bus,
            )
            monitor = Monitor(state=state, storage=storage, bus=bus)

            # Expose in-memory objects for status reads
            with self._lock:
                self._portfolio = portfolio
                self._positions = positions
                self._state     = state

            # Bridge bot EventBus → WebSocket event queue
            def _enq(ev_type: str):
                def _h(ev):
                    d: dict = {'type': ev_type, 'ts': ev.ts.isoformat()}
                    for fname in type(ev).__dataclass_fields__:
                        if fname != 'ts':
                            d[fname] = getattr(ev, fname)
                    self._enqueue(d)
                return _h

            def _on_candle(ev: CandleEvent) -> None:
                # Skip backfill candles — browser fetches history via REST
                if ev.is_history:
                    return

                pair_key = (ev.symbol, ev.interval)
                with self._lock:
                    last_close  = self._last_close.get(pair_key)
                    active_sym  = self._active_symbol
                    active_iv   = self._active_interval

                # Lightweight tick for Market Watch (all symbols, LOW priority)
                tick: dict = {
                    'type':     'tick',
                    'ts':       ev.ts.isoformat(),
                    'symbol':   ev.symbol,
                    'interval': ev.interval,
                    'close':    ev.close,
                }
                if last_close is not None and last_close != 0.0:
                    tick['change'] = round(
                        (ev.close - last_close) / last_close * 100.0, 4
                    )
                self._enqueue(tick)

                # Update last-seen close (under lock to avoid race conditions)
                with self._lock:
                    self._last_close[pair_key] = ev.close

                # Full OHLCV candle for active pair only (or all if no pair set)
                is_active = (
                    active_sym is None
                    or (ev.symbol == active_sym and ev.interval == active_iv)
                )
                if is_active:
                    self._enqueue({
                        'type':      'candle',
                        'ts':        ev.ts.isoformat(),
                        'symbol':    ev.symbol,
                        'interval':  ev.interval,
                        'open_time': ev.open_time,
                        'open':      ev.open,
                        'high':      ev.high,
                        'low':       ev.low,
                        'close':     ev.close,
                        'volume':    ev.volume,
                        'is_history': False,
                    })

            bus.subscribe(CandleEvent,        _on_candle)
            bus.subscribe(SignalEvent,        _enq('signal'))
            bus.subscribe(FillEvent,          _enq('fill'))
            bus.subscribe(ErrorEvent,         _enq('error'))
            bus.subscribe(DisconnectEvent,    _enq('disconnect'))
            bus.subscribe(ReconnectEvent,     _enq('reconnect'))
            bus.subscribe(RiskRejectionEvent, _enq('risk_rejected'))
            bus.subscribe(PositionEvent,      _enq('position'))

            def _on_order_event(ev: OrderEvent) -> None:
                if ev.status == 'REJECTED':
                    self._enqueue({
                        'type':   'rejected',
                        'ts':     ev.ts.isoformat(),
                        'symbol': ev.symbol,
                        'side':   ev.side,
                        'detail': ev.detail,
                    })
            bus.subscribe(OrderEvent, _on_order_event)

            # Recovery
            if cfg.recover_on_restart:
                orders.recover_open_orders()
                positions.recover()
                history = storage.get_balance_history(limit=1)
                if history:
                    last = history[0]
                    portfolio.restore(
                        cash        = last.get("cash",   cfg.paper_capital),
                        peak_equity = last.get("equity", cfg.paper_capital),
                    )

            # Scheduler
            scheduler = Scheduler()
            scheduler.every(cfg.monitor_interval_s, monitor.tick, name="monitor_tick")

            def _snapshot() -> None:
                marks    = state.all_mark_prices()
                open_pos = positions.get_all_open()
                portfolio.snapshot(marks, open_pos)

            scheduler.every(cfg.snapshot_interval_s, _snapshot, name="equity_snapshot")

            def _daily_reset() -> None:
                from datetime import datetime as _dt
                yesterday = _dt.now(timezone.utc).strftime("%Y-%m-%d")
                try:
                    generate_daily_report(storage, cfg.reports_dir)
                except Exception:
                    pass
                ev = DailyResetEvent(date_utc=yesterday)
                bus.emit(ev)
                engine.on_daily_reset(ev)

            scheduler.daily_at_utc(cfg.daily_report_hour_utc, _daily_reset,
                                   name="daily_reset")
            scheduler.start()

            # Feed
            feed = LiveFeed(config=cfg, state=state, bus=bus)
            task = asyncio.create_task(feed.run())
            with self._lock:
                self._task = task

            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                scheduler.stop()
                try:
                    final_marks = state.all_mark_prices()
                    open_pos    = positions.get_all_open()
                    portfolio.snapshot(final_marks, open_pos)
                except Exception:
                    pass
                storage.close()
                log.info("Paper bot stopped cleanly")

        finally:
            if file_handler:
                bot_log_root.removeHandler(file_handler)
                file_handler.close()


# ── Singleton ──────────────────────────────────────────────────────────────────

bot_manager = BotManager()
