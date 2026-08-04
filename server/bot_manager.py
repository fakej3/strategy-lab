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
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._error: str  = ""

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(
        self,
        capital: float,
        symbols: list[str],
        interval: str,
        strategy: str,
        db_path: str = "bot.db",
        log_path: str = "logs/bot.log",
        recover: bool = True,
    ) -> tuple[bool, str]:
        """Build a BotConfig and start the bot. Returns (success, error_message)."""
        from bot.config import BotConfig, FeedConfig, RiskConfig

        try:
            cfg = BotConfig(
                paper_capital    = capital,
                strategy_name    = strategy,
                strategy_params  = {"fast": 20, "slow": 50},
                feed             = FeedConfig(
                    symbols   = symbols,
                    intervals = [interval],
                ),
                risk = RiskConfig(
                    max_position_size_usd = min(capital * 0.8, 20.0),
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

        result: dict[str, Any] = {
            "running":         running,
            "started_at":      started_at.isoformat()  if started_at  else None,
            "stopped_at":      stopped_at.isoformat()  if stopped_at  else None,
            "error":           error,
            "symbols":         cfg.feed.symbols          if cfg else [],
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

    async def _run_bot(self) -> None:
        """Core bot coroutine — mirrors bot_trade._main() without argparse."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from bot.engine import BotEngine
        from bot.events import DailyResetEvent, EventBus
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

        # Wire up a file handler for the bot logger so the UI can tail it
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
            strategy = _load_strategy(cfg)
            engine   = BotEngine(
                config    = cfg,
                strategy  = strategy,
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
