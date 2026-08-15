"""Regression tests for Phase 2 runtime issues.

Covers the following confirmed application bugs:
  A  REST backfill failure is handled gracefully (no crash, ErrorEvent emitted)
  B  REST backfill retry succeeds after initial failure
  C  Min-notional pre-flight rejects the order before exchange submission
  D  $25 capital + 10% equity_fraction + $10 min-notional: no order submitted
  E  Pipeline marks session "failed" when data integrity blocks all pairs
  F  background._run() emits success=False when data blocked
  G  run.n_tested == 0 after data integrity failure
  H  Research DB session status is "failed", not "complete", after data block
  I  Dashboard exclusion: get_stats() returns 0 results for a data-blocked run
  J  Repeated impossible-order prevention: BotEngine never resubmits after skip
"""
from __future__ import annotations

import asyncio
import threading
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ── Helpers shared by multiple test groups ────────────────────────────────────

def _make_bot_components(capital: float = 1000.0, equity_fraction: float = 0.10):
    """Return a minimal set of BotEngine dependencies."""
    from bot.config import BotConfig
    from bot.engine import BotEngine
    from bot.events import EventBus
    from bot.order_manager import OrderManager
    from bot.paper_exchange import PaperExchange
    from bot.portfolio import Portfolio
    from bot.position_manager import PositionManager
    from bot.risk import RiskEngine
    from bot.state import BotState
    from bot.storage import BotStorage

    import tempfile, os
    db_path = tempfile.mktemp(suffix=".db")

    cfg  = BotConfig(paper_capital=capital, equity_fraction=equity_fraction)
    bus  = EventBus()
    ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
    storage = BotStorage(db_path)
    storage.connect()
    om   = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm   = PositionManager(storage=storage, bus=bus)
    pf   = Portfolio(starting_capital=cfg.paper_capital, storage=storage, bus=bus)
    risk = RiskEngine(cfg.risk, bus=bus)
    state = BotState(buffer_size=100)
    return cfg, bus, ex, om, pm, pf, risk, state, storage


# ══════════════════════════════════════════════════════════════════════════════
# A + B  REST backfill failure / recovery
# ══════════════════════════════════════════════════════════════════════════════

class TestRestBackfillFailure:
    """Test A — REST backfill failure is handled without crashing."""

    def test_backfill_dns_failure_emits_error_event(self):
        """When aiohttp raises ClientConnectorError, ErrorEvent is emitted."""
        import aiohttp
        from bot.config import BotConfig, FeedConfig
        from bot.events import ErrorEvent, EventBus
        from bot.runtime import LiveFeed
        from bot.state import BotState

        errors_received = []

        cfg = BotConfig(feed=FeedConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            backfill_bars=10, backfill_max_retries=1,
        ))
        bus   = EventBus()
        state = BotState()
        bus.subscribe(ErrorEvent, errors_received.append)

        feed = LiveFeed(config=cfg, state=state, bus=bus)

        dns_error = aiohttp.ClientConnectorError(
            connection_key=MagicMock(),
            os_error=OSError("Name or service not known"),
        )

        async def _run():
            sem = asyncio.Semaphore(1)
            async with aiohttp.ClientSession() as session:
                # Directly test the failure-isolated wrapper
                with patch.object(feed, "_backfill", side_effect=dns_error):
                    await feed._backfill_one("BTCUSDT", "1h", session, sem)

        asyncio.run(_run())

        assert len(errors_received) == 1, "Expected exactly one ErrorEvent"
        assert "Backfill failed" in errors_received[0].message

    def test_backfill_failure_does_not_crash_run(self):
        """When all backfills fail, run() continues to the WebSocket connect phase."""
        import aiohttp
        from bot.config import BotConfig, FeedConfig
        from bot.events import ErrorEvent, EventBus
        from bot.runtime import LiveFeed
        from bot.state import BotState

        cfg = BotConfig(feed=FeedConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            backfill_bars=10, backfill_max_retries=1,
        ))
        bus   = EventBus()
        state = BotState()

        feed = LiveFeed(config=cfg, state=state, bus=bus)

        dns_error = aiohttp.ClientConnectorError(
            connection_key=MagicMock(),
            os_error=OSError("DNS failed"),
        )

        # Cancel immediately after the first backfill attempt
        stop_event = asyncio.Event()

        async def _run():
            with (
                patch.object(feed, "_backfill", side_effect=dns_error),
                patch.object(feed, "_stream", side_effect=asyncio.CancelledError),
            ):
                try:
                    await feed.run()
                except Exception:
                    pytest.fail("run() raised unexpectedly on backfill failure")

        asyncio.run(_run())


class TestRestBackfillRecovery:
    """Test B — REST backfill retry loop succeeds after transient ClientError."""

    def test_backfill_retry_succeeds_on_second_attempt(self):
        """_backfill retries transient ClientError and returns successfully.

        _backfill_one provides failure isolation (not retry); the retry loop
        lives inside _backfill itself.  This test calls _backfill directly with
        a mock session that fails on the first GET and succeeds on the second.
        """
        import aiohttp
        from bot.config import BotConfig, FeedConfig
        from bot.events import EventBus
        from bot.runtime import LiveFeed
        from bot.state import BotState

        cfg = BotConfig(feed=FeedConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            backfill_bars=2,
            backfill_max_retries=3,
            backfill_retry_delay_s=0.0,
        ))
        bus   = EventBus()
        state = BotState()
        feed  = LiveFeed(config=cfg, state=state, bus=bus)

        call_count = {"n": 0}

        # Build two closed candles in the distant past (always below "now - 1s" guard).
        past_ms = 1_600_000_000_000
        interval_ms = 3_600_000
        valid_data = [
            [past_ms + i * interval_ms, "50000", "51000", "49000", "50500",
             "100", past_ms + (i + 1) * interval_ms - 1, "", 0, "", "", ""]
            for i in range(2)
        ]

        class _SuccessCtx:
            status = 200
            def raise_for_status(self): pass  # sync; _backfill doesn't await it
            async def json(self): return valid_data
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass

        class _MockSession:
            def get(self, url):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # Raise synchronously inside the try block — _backfill catches
                    # ClientError and retries.
                    raise aiohttp.ClientError("transient 503")
                return _SuccessCtx()

        async def _run():
            sem = asyncio.Semaphore(1)
            return await feed._backfill("BTCUSDT", "1h", _MockSession(), sem)

        result = asyncio.run(_run())

        assert call_count["n"] == 2, (
            f"Expected 2 session.get() calls (1 failure + 1 success), got {call_count['n']}"
        )
        assert result == 2, f"Expected 2 candles processed, got {result}"


# ══════════════════════════════════════════════════════════════════════════════
# C + D  Minimum-notional pre-flight rejection
# ══════════════════════════════════════════════════════════════════════════════

class TestMinNotionalPreflight:
    """Tests C and D — BotEngine pre-flight notional check."""

    def test_c_submit_market_not_called_when_below_min_notional(self):
        """Test C — engine.orders.submit_market() is never called when notional < MIN."""
        from bot.config import BotConfig
        from bot.engine import BotEngine
        from bot.events import EventBus
        from bot.order_manager import OrderManager
        from bot.paper_exchange import PaperExchange, MIN_NOTIONAL
        from bot.portfolio import Portfolio
        from bot.position_manager import PositionManager
        from bot.risk import RiskEngine
        from bot.state import BotState
        from bot.storage import BotStorage
        import tempfile

        db = BotStorage(tempfile.mktemp(suffix=".db"))
        db.connect()

        # With $25 capital and 10% fraction: notional = $2.50 < $10 minimum
        capital = 25.0
        cfg  = BotConfig(paper_capital=capital, equity_fraction=0.10)
        bus  = EventBus()
        ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
        om   = OrderManager(exchange=ex, storage=db, bus=bus)
        pm   = PositionManager(storage=db, bus=bus)
        pf   = Portfolio(starting_capital=capital, storage=db, bus=bus)
        risk = RiskEngine(cfg.risk, bus=bus)
        state = BotState(buffer_size=100)

        class _FixedBuy:
            def generate_signals(self, bars):
                import pandas as _pd
                from engine.strategy import Signal
                return _pd.Series([Signal.BUY] * len(bars), index=bars.index)

        engine = BotEngine(
            config=cfg, strategy=_FixedBuy(),
            state=state, orders=om, positions=pm,
            portfolio=pf, risk=risk, storage=db, bus=bus,
        )

        submitted = []
        _orig = om.submit_market
        def _spy(*a, **kw):
            submitted.append((a, kw))
            return _orig(*a, **kw)
        om.submit_market = _spy

        # Emit enough candles to fill the buffer and trigger a BUY signal
        from bot.events import CandleEvent
        base = 1_700_000_000_000
        iv_ms = 3_600_000
        price = 50_000.0
        for i in range(65):
            bus.emit(CandleEvent(
                symbol="BTCUSDT", interval="1h",
                open_time=base + i * iv_ms,
                open=price, high=price * 1.01, low=price * 0.99, close=price,
                volume=100.0, close_time=base + (i + 1) * iv_ms - 1,
            ))

        # Pre-flight check must have blocked submission: no market orders submitted
        assert submitted == [], (
            f"submit_market was called {len(submitted)} time(s) despite notional "
            f"{capital * 0.10:.2f} USDT being below MIN_NOTIONAL={MIN_NOTIONAL}"
        )
        # Also confirm no orders reached the exchange
        assert ex.get_all_orders("BTCUSDT") == []

    def test_d_exact_scenario_25_capital_10pct_10min(self):
        """Test D — $25, 10%, $10 minimum: order never submitted."""
        from bot.paper_exchange import MIN_NOTIONAL
        capital = 25.0
        equity_fraction = 0.10
        price = 50_000.0
        notional = capital * equity_fraction  # $2.50

        assert notional < MIN_NOTIONAL, (
            f"Scenario sanity check: expected {notional} < {MIN_NOTIONAL}"
        )

        cfg, bus, ex, om, pm, pf, risk, state, storage = _make_bot_components(
            capital=capital, equity_fraction=equity_fraction,
        )

        class _AlwaysBuy:
            def generate_signals(self, bars):
                import pandas as _pd
                from engine.strategy import Signal
                return _pd.Series([Signal.BUY] * len(bars), index=bars.index)

        from bot.engine import BotEngine
        engine = BotEngine(
            config=cfg, strategy=_AlwaysBuy(),
            state=state, orders=om, positions=pm,
            portfolio=pf, risk=risk, storage=storage, bus=bus,
        )

        from bot.events import CandleEvent
        base  = 1_700_000_000_000
        iv_ms = 3_600_000
        for i in range(70):
            bus.emit(CandleEvent(
                symbol="BTCUSDT", interval="1h",
                open_time=base + i * iv_ms,
                open=50_000.0, high=50_500.0, low=49_500.0, close=50_000.0,
                volume=100.0, close_time=base + (i + 1) * iv_ms - 1,
            ))

        assert ex.get_all_orders("BTCUSDT") == [], (
            "No orders should reach the exchange when capital × equity_fraction "
            f"({notional:.2f} USDT) < min_notional ({MIN_NOTIONAL} USDT)"
        )
        assert pm.open_position_count() == 0


# ══════════════════════════════════════════════════════════════════════════════
# E + F + G + H  Pipeline false-success fix
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineDataIntegrityFailure:
    """Tests E, G, H — pipeline marks 'failed' when integrity blocks all pairs."""

    @pytest.fixture
    def tmp_db(self, tmp_path):
        return str(tmp_path / "research.db")

    def test_e_session_status_is_failed_when_integrity_blocks(self, tmp_db):
        """Test E — pipeline.execute() persists status='failed' to the DB."""
        from automation.pipeline import PipelineConfig, ResearchPipeline
        from research_db.storage import ResearchStorage

        cfg = PipelineConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 31),
            db_path=tmp_db,
            verbose=False,
            fast_mode=True,
        )

        # Patch _step1_fetch to return None (simulates integrity failure)
        pipeline = ResearchPipeline(cfg)
        with patch.object(pipeline, "_step1_fetch", return_value=None):
            run = pipeline.execute()

        assert run.n_tested == 0
        assert run.n_data_failures == 1

        storage = ResearchStorage(tmp_db)
        session = storage.get_session(run.session_id)
        storage.close()

        assert session is not None
        assert session.status == "failed", (
            f"Expected status='failed', got '{session.status}'. "
            "Data integrity failure must not be silently treated as success."
        )

    def test_g_n_tested_is_zero_after_data_failure(self, tmp_db):
        """Test G — run.n_tested == 0 when data integrity blocks all pairs."""
        from automation.pipeline import PipelineConfig, ResearchPipeline

        cfg = PipelineConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            db_path=tmp_db, verbose=False, fast_mode=True,
        )
        pipeline = ResearchPipeline(cfg)
        with patch.object(pipeline, "_step1_fetch", return_value=None):
            run = pipeline.execute()

        assert run.n_tested == 0
        assert run.n_data_failures >= 1

    def test_h_persisted_status_is_failed_not_complete(self, tmp_db):
        """Test H — the ResearchStorage session row has status='failed'."""
        from automation.pipeline import PipelineConfig, ResearchPipeline
        from research_db.storage import ResearchStorage

        cfg = PipelineConfig(
            symbols=["BTCUSDT", "ETHUSDT"], intervals=["1h"],
            db_path=tmp_db, verbose=False, fast_mode=True,
        )
        pipeline = ResearchPipeline(cfg)
        # Both pairs fail integrity
        with patch.object(pipeline, "_step1_fetch", return_value=None):
            run = pipeline.execute()

        assert run.n_data_failures == 2

        storage = ResearchStorage(tmp_db)
        session = storage.get_session(run.session_id)
        storage.close()

        assert session.status == "failed"
        assert session.n_strategies_run == 0


class TestBackgroundDataBlockedFailure:
    """Test F — JobManager._run() emits success=False on data-blocked pipeline."""

    def test_f_job_status_failed_when_data_blocked(self, tmp_path):
        """Test F — job is marked 'failed' (not 'done') when integrity blocks."""
        from server.background import JobManager

        db_path = str(tmp_path / "research.db")
        jm = JobManager(db_path=db_path)

        config = {
            "symbols": "BTCUSDT",
            "intervals": "1h",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "db_path": db_path,
            "verbose": "false",
            "fast_mode": "true",
        }

        # Patch the pipeline so _step1_fetch always returns None (integrity failure)
        from automation.pipeline import ResearchPipeline
        original_init = ResearchPipeline.__init__

        def _patched_init(self, cfg=None):
            original_init(self, cfg)
            self._step1_fetch = lambda sym, iv: None

        with patch.object(ResearchPipeline, "__init__", _patched_init):
            job_id = jm.submit(config)

            # Wait for the thread to finish (up to 30s)
            deadline = 30
            import time
            t0 = time.time()
            while time.time() - t0 < deadline:
                info = jm.get_job(job_id)
                if info and info.status in ("done", "failed", "cancelled"):
                    break
                time.sleep(0.1)

        info = jm.get_job(job_id)
        assert info is not None
        assert info.status == "failed", (
            f"Expected job status='failed', got '{info.status}'. "
            "Data-integrity-blocked run must not report success."
        )
        assert info.error  # error message must be set

    def test_f_success_false_in_queue_when_data_blocked(self, tmp_path):
        """The done event in the queue has success=False for data-blocked runs."""
        import queue as _queue
        import time
        from server.background import JobManager

        db_path = str(tmp_path / "rb2.db")
        jm = JobManager(db_path=db_path)

        config = {
            "symbols": "BTCUSDT", "intervals": "1h",
            "start_date": "2025-01-01", "end_date": "2025-01-31",
            "db_path": db_path, "verbose": "false", "fast_mode": "true",
        }

        from automation.pipeline import ResearchPipeline
        original_init = ResearchPipeline.__init__

        def _patched_init(self, cfg=None):
            original_init(self, cfg)
            self._step1_fetch = lambda sym, iv: None

        with patch.object(ResearchPipeline, "__init__", _patched_init):
            job_id = jm.submit(config)
            q = jm.get_queue(job_id)
            assert q is not None

            # Drain queue until done event or timeout
            done_event = None
            t0 = time.time()
            while time.time() - t0 < 30:
                try:
                    msg = q.get(timeout=0.2)
                    if msg.get("type") == "done":
                        done_event = msg
                        break
                except _queue.Empty:
                    pass

        assert done_event is not None, "No 'done' event received from queue"
        assert done_event.get("success") is False, (
            f"Expected success=False in done event, got: {done_event}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# I  Dashboard exclusion of failed jobs
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboardExcludesFailedJobs:
    """Test I — get_stats() is not polluted by data-integrity-failed sessions."""

    def test_i_failed_session_produces_no_strategy_results(self, tmp_path):
        """A data-blocked run writes no rows to strategy_results, so stats are clean."""
        from automation.pipeline import PipelineConfig, ResearchPipeline
        from research_db.storage import ResearchStorage

        db_path = str(tmp_path / "stats.db")
        cfg = PipelineConfig(
            symbols=["BTCUSDT"], intervals=["1h"],
            db_path=db_path, verbose=False, fast_mode=True,
        )
        pipeline = ResearchPipeline(cfg)
        with patch.object(pipeline, "_step1_fetch", return_value=None):
            pipeline.execute()

        storage = ResearchStorage(db_path)
        stats = storage.get_stats()
        storage.close()

        total = stats.get("total", 0) or 0
        assert total == 0, (
            f"Expected 0 strategy results after a data-blocked run, got {total}. "
            "Failed sessions must not pollute the dashboard stats."
        )


# ══════════════════════════════════════════════════════════════════════════════
# J  Repeated impossible-order prevention
# ══════════════════════════════════════════════════════════════════════════════

class TestRepeatedImpossibleOrderPrevention:
    """Test J — BotEngine never resubmits an impossible order on repeated signals."""

    def test_j_no_repeated_submissions_on_impossible_notional(self):
        """With sub-minimum capital, 70 BUY signals produce zero exchange orders."""
        from bot.paper_exchange import MIN_NOTIONAL

        capital = 15.0
        equity_fraction = 0.10
        price = 50_000.0
        # Sanity: this scenario IS below the minimum
        assert capital * equity_fraction < MIN_NOTIONAL

        cfg, bus, ex, om, pm, pf, risk, state, storage = _make_bot_components(
            capital=capital, equity_fraction=equity_fraction,
        )

        class _AlwaysBuy:
            def generate_signals(self, bars):
                import pandas as _pd
                from engine.strategy import Signal
                return _pd.Series([Signal.BUY] * len(bars), index=bars.index)

        from bot.engine import BotEngine
        engine = BotEngine(
            config=cfg, strategy=_AlwaysBuy(),
            state=state, orders=om, positions=pm,
            portfolio=pf, risk=risk, storage=storage, bus=bus,
        )

        from bot.events import CandleEvent
        base  = 1_700_000_000_000
        iv_ms = 3_600_000
        for i in range(70):
            bus.emit(CandleEvent(
                symbol="BTCUSDT", interval="1h",
                open_time=base + i * iv_ms,
                open=price, high=price * 1.01, low=price * 0.99, close=price,
                volume=100.0, close_time=base + (i + 1) * iv_ms - 1,
            ))

        all_orders = ex.get_all_orders("BTCUSDT")
        assert len(all_orders) == 0, (
            f"Expected 0 exchange orders, found {len(all_orders)}. "
            "Pre-flight notional check must prevent repeated impossible submissions."
        )

    def test_j_exchange_open_orders_remains_clean_after_impossible_signals(self):
        """_open_orders must not accumulate rejected-orphan records."""
        from bot.paper_exchange import MIN_NOTIONAL, PaperExchange

        capital = 10.0
        cfg, bus, ex, om, pm, pf, risk, state, storage = _make_bot_components(
            capital=capital, equity_fraction=0.05,  # 0.5 USDT << 10 USDT min
        )

        class _AlwaysBuy:
            def generate_signals(self, bars):
                import pandas as _pd
                from engine.strategy import Signal
                return _pd.Series([Signal.BUY] * len(bars), index=bars.index)

        from bot.engine import BotEngine
        engine = BotEngine(
            config=cfg, strategy=_AlwaysBuy(),
            state=state, orders=om, positions=pm,
            portfolio=pf, risk=risk, storage=storage, bus=bus,
        )

        from bot.events import CandleEvent
        base  = 1_700_000_000_000
        iv_ms = 3_600_000
        for i in range(65):
            bus.emit(CandleEvent(
                symbol="BTCUSDT", interval="1h",
                open_time=base + i * iv_ms,
                open=50_000.0, high=50_500.0, low=49_500.0, close=50_000.0,
                volume=100.0, close_time=base + (i + 1) * iv_ms - 1,
            ))

        # The exchange open-orders list must be empty
        open_on_exchange = ex.get_open_orders("BTCUSDT")
        assert open_on_exchange == [], (
            f"Exchange has {len(open_on_exchange)} orphaned open orders. "
            "Rejected orders must not accumulate in _open_orders."
        )

        # OrderManager open count must also be zero
        open_on_om = om.get_open_orders("BTCUSDT")
        assert open_on_om == [], (
            f"OrderManager has {len(open_on_om)} stale 'open' orders. "
            "Rejected orders must be removed from OrderManager._open."
        )
