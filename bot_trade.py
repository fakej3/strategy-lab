#!/usr/bin/env python3
"""Entry point for the paper trading bot.

Usage
-----
  python bot_trade.py                         # default config (25 USDT)
  python bot_trade.py --capital 25            # custom capital
  python bot_trade.py --symbols BTCUSDT,ETHUSDT --interval 1h
  python bot_trade.py --dashboard             # also start bot dashboard on :8001
  BOT_CAPITAL=25 BOT_SYMBOLS=BTCUSDT python bot_trade.py  # env vars

The bot connects to public Binance WebSocket streams (no API key), executes
all trades in simulation only, and persists data to bot.db.

Press Ctrl-C to stop gracefully.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading
from pathlib import Path

# ── Ensure repo root on path ───────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from bot.config import BotConfig, FeedConfig, RiskConfig
from bot.dashboard import bot_dashboard_app
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
from shared.logging import setup_logging


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper trading bot")
    p.add_argument("--capital",       type=float, default=None,  help="Starting capital (USDT)")
    p.add_argument("--symbols",       type=str,   default=None,  help="Comma-separated symbols e.g. BTCUSDT,ETHUSDT")
    p.add_argument("--interval",      type=str,   default=None,  help="Candle interval e.g. 1h")
    p.add_argument("--strategy",      type=str,   default=None,  help="Strategy name (default: EMACrossover)")
    p.add_argument("--db",            type=str,   default=None,  help="Database path (default: bot.db)")
    p.add_argument("--max-positions", type=int,   default=0,
                   help="Max simultaneous open positions (default: one per configured symbol)")
    p.add_argument("--log-level",     type=str,   default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"])
    p.add_argument("--dashboard",     action="store_true", help="Also start bot dashboard on port 8001")
    p.add_argument("--dashboard-port", type=int,  default=8001)
    p.add_argument("--no-recover",    action="store_true", help="Don't recover open orders/positions on start")
    return p.parse_args()


def _build_config(args: argparse.Namespace) -> BotConfig:
    cfg = BotConfig.from_env()
    if args.capital is not None:
        cfg.paper_capital = args.capital
    if args.symbols:
        cfg.feed.symbols = [s.strip() for s in args.symbols.split(",")]
    if args.interval:
        cfg.feed.intervals = [args.interval.strip()]
    if args.strategy:
        cfg.strategy_name = args.strategy
    if args.db:
        cfg.db_path = args.db
    if args.no_recover:
        cfg.recover_on_restart = False

    # Derive max_open_positions from configured symbols if not explicitly
    # overridden — mirrors BotManager.start() so CLI and web-UI are consistent.
    explicit = args.max_positions if args.max_positions else 0
    cfg.risk.max_open_positions = explicit if explicit > 0 else len(cfg.feed.symbols)

    return cfg


def _load_strategy(cfg: BotConfig):
    """Load the configured strategy from the StrategyRegistry.

    The registry is the single source of truth for available strategies.
    Register a new strategy in ``strategies/__init__.py`` to make it
    available here, in BotManager, and in BatchBacktest automatically.
    """
    from strategies import registry
    try:
        return registry.create(cfg.strategy_name, cfg.strategy_params)
    except KeyError:
        available = ", ".join(registry.list_strategies()) or "none registered"
        raise ValueError(
            f"Unknown strategy {cfg.strategy_name!r}. Available: {available}"
        )


def _start_dashboard(port: int) -> None:
    """Start bot dashboard in a background thread."""
    try:
        import uvicorn
        config = uvicorn.Config(
            bot_dashboard_app,
            host="0.0.0.0",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True, name="bot-dashboard")
        thread.start()
        logging.getLogger("strategy_lab.bot").info(
            "Bot dashboard running at http://localhost:%d/bot", port
        )
    except ImportError:
        logging.getLogger("strategy_lab.bot").warning(
            "uvicorn not installed — dashboard not started"
        )


async def _main(args: argparse.Namespace) -> None:
    # ── Config ──────────────────────────────────────────────────────────────
    cfg = _build_config(args)
    setup_logging(level=args.log_level, log_file=cfg.log_path)
    log = logging.getLogger("strategy_lab.bot")

    log.info("=" * 60)
    log.info("Paper Trading Bot starting")
    log.info("  Capital:   %s USDT", cfg.paper_capital)
    log.info("  Symbols:   %s", cfg.feed.symbols)
    log.info("  Intervals: %s", cfg.feed.intervals)
    log.info("  Strategy:  %s %s", cfg.strategy_name, cfg.strategy_params)
    log.info("  DB:        %s", cfg.db_path)
    log.info("=" * 60)

    # ── Core components ──────────────────────────────────────────────────────
    bus      = EventBus()
    storage  = BotStorage(cfg.db_path)
    storage.connect()

    state    = BotState(buffer_size=cfg.buffer_size)
    exchange = PaperExchange(
        fee_rate=cfg.fee_rate,
        maker_fee_rate=cfg.maker_fee_rate,
        slippage_pct=cfg.slippage_pct,
        bus=bus,
    )
    orders   = OrderManager(exchange=exchange, storage=storage, bus=bus)
    positions = PositionManager(storage=storage, bus=bus)
    portfolio = Portfolio(
        starting_capital=cfg.paper_capital,
        storage=storage,
        bus=bus,
        fee_rate=cfg.fee_rate,
    )
    risk     = RiskEngine(config=cfg.risk, bus=bus)

    # Create an independent strategy instance per (symbol, interval) pair so
    # that stateful strategies never cross-contaminate between different pairs.
    strategy_map = {
        (sym, iv): _load_strategy(cfg)
        for sym in cfg.feed.symbols
        for iv in cfg.feed.intervals
    }

    engine = BotEngine(
        config=cfg,
        strategy=strategy_map,
        state=state,
        orders=orders,
        positions=positions,
        portfolio=portfolio,
        risk=risk,
        storage=storage,
        bus=bus,
    )

    monitor = Monitor(state=state, storage=storage, bus=bus)

    # ── Recovery ─────────────────────────────────────────────────────────────
    if cfg.recover_on_restart:
        n_orders    = orders.recover_open_orders()
        n_positions = positions.recover()
        # Restore portfolio cash from last balance snapshot
        history = storage.get_balance_history(limit=1)
        if history:
            last = history[-1]
            portfolio.restore(
                cash=last.get("cash", cfg.paper_capital),
                peak_equity=last.get("equity", cfg.paper_capital),
            )

    # ── Dashboard ─────────────────────────────────────────────────────────────
    if args.dashboard:
        _start_dashboard(args.dashboard_port)

    # ── Scheduler ────────────────────────────────────────────────────────────
    scheduler = Scheduler()
    scheduler.every(cfg.monitor_interval_s, monitor.tick, name="monitor_tick")

    def _snapshot():
        marks = state.all_mark_prices()
        open_pos = positions.get_all_open()
        portfolio.snapshot(marks, open_pos)

    scheduler.every(cfg.snapshot_interval_s, _snapshot, name="equity_snapshot")

    def _daily_reset():
        from datetime import datetime, timedelta, timezone
        # Scheduler fires at midnight UTC; subtract 1 day to get the day that ended.
        yesterday = (
            (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        try:
            generate_daily_report(storage, cfg.reports_dir)
        except Exception:
            log.exception("Failed to generate daily report")
        ev = DailyResetEvent(date_utc=yesterday)
        bus.emit(ev)
        engine.on_daily_reset(ev)

    scheduler.daily_at_utc(cfg.daily_report_hour_utc, _daily_reset, name="daily_reset")
    scheduler.start()

    # ── Feed ─────────────────────────────────────────────────────────────────
    feed = LiveFeed(config=cfg, state=state, bus=bus)

    log.info("Starting live feed...")
    try:
        await feed.run()
    except asyncio.CancelledError:
        log.info("Feed cancelled — shutting down")

    # ── Teardown ─────────────────────────────────────────────────────────────
    scheduler.stop()
    try:
        final_marks = state.all_mark_prices()
        open_pos = positions.get_all_open()
        portfolio.snapshot(final_marks, open_pos)
    except Exception:
        log.exception("Failed final snapshot")
    storage.close()
    log.info("Bot stopped cleanly")


def main() -> None:
    args = _parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task: asyncio.Task | None = None

    def _shutdown(*_):
        if main_task and not main_task.done():
            main_task.cancel()

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        main_task = loop.create_task(_main(args))
        loop.run_until_complete(main_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
