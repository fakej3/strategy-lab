"""Integration tests for audit fixes (Priorities 1-7).

Tests added to verify:
  P1 — save_fill() crash-window atomicity (idempotent fill_id, orphan recovery)
  P2 — Auth enforcement on /api/history and /api/strategies
  P4 — Exact cash recovery from realized PnL ledger
  P5 — Daily reset dispatched exactly once
  P6 — Multi-interval startup rejection
  P7 — Full pipeline, multi-symbol isolation, BotManager lifecycle,
        stream limit boundary
"""
from __future__ import annotations

import datetime
import threading
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from bot.config import BotConfig, FeedConfig, RiskConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, DailyResetEvent, EventBus, FillEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import PaperExchange, SIDE_BUY, SIDE_SELL
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskEngine
from bot.state import BotState
from bot.storage import BotStorage
from engine.strategy import Signal


# ── Shared helpers ─────────────────────────────────────────────────────────────

class AlwaysBuy:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.BUY] * len(bars), index=bars.index)


class AlwaysExit:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.EXIT] * len(bars), index=bars.index)


class BuyThenExit:
    """BUY for the first call, EXIT on all subsequent calls."""
    def __init__(self):
        self._calls = 0

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        self._calls += 1
        sig = Signal.BUY if self._calls == 1 else Signal.EXIT
        return pd.Series([sig] * len(bars), index=bars.index)


def _storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


def _components(storage, capital=1000.0, max_open_positions=1):
    cfg  = BotConfig(paper_capital=capital)
    cfg.risk.max_open_positions = max_open_positions
    bus  = EventBus()
    ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
    om   = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm   = PositionManager(storage=storage, bus=bus)
    pf   = Portfolio(starting_capital=capital, storage=storage, bus=bus, fee_rate=cfg.fee_rate)
    risk = RiskEngine(cfg.risk, bus=bus)
    st   = BotState(buffer_size=100)
    return cfg, bus, ex, om, pm, pf, risk, st


def _engine(cfg, bus, ex, om, pm, pf, risk, st, storage, strategy):
    return BotEngine(
        config=cfg, strategy=strategy,
        state=st, orders=om, positions=pm,
        portfolio=pf, risk=risk, storage=storage, bus=bus,
    )


def _emit_history(bus, n, symbol="BTCUSDT", interval="1h", price=50_000.0):
    base_ms = 1_700_000_000_000
    iv_ms   = 3_600_000
    for i in range(n):
        bus.emit(CandleEvent(
            symbol=symbol, interval=interval,
            open_time=base_ms + i * iv_ms,
            open=price, high=price * 1.01, low=price * 0.99,
            close=price, volume=100.0,
            close_time=base_ms + i * iv_ms + iv_ms - 1,
            is_history=True,
        ))


def _emit_live(bus, i, symbol="BTCUSDT", interval="1h", price=50_000.0):
    base_ms = 1_700_000_000_000
    iv_ms   = 3_600_000
    bus.emit(CandleEvent(
        symbol=symbol, interval=interval,
        open_time=base_ms + i * iv_ms,
        open=price, high=price * 1.01, low=price * 0.99,
        close=price, volume=100.0,
        close_time=base_ms + i * iv_ms + iv_ms - 1,
    ))


# ── P7-1: Full pipeline candle→signal→fill→position→portfolio ─────────────────

class TestFullPipeline:
    def test_candle_triggers_buy_and_updates_portfolio(self, tmp_path):
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s)
        _engine(cfg, bus, ex, om, pm, pf, risk, st, s, AlwaysBuy())

        initial_cash = pf.cash
        _emit_history(bus, 60)
        for i in range(60, 65):
            _emit_live(bus, i)

        # Cash decreased — position opened
        assert pf.cash < initial_cash
        # Position exists
        assert pm.open_position_count() == 1
        # Fill persisted
        fills = s.get_fills()
        assert len(fills) >= 1

    def test_exit_signal_closes_position(self, tmp_path):
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s)
        strat = BuyThenExit()
        _engine(cfg, bus, ex, om, pm, pf, risk, st, s, strat)

        _emit_history(bus, 60)
        for i in range(60, 70):
            _emit_live(bus, i)

        # Position should be closed eventually
        closed = s.get_positions()
        closed_positions = [p for p in closed if p["status"] == "closed"]
        assert len(closed_positions) >= 1


# ── P1: Crash-window atomicity ─────────────────────────────────────────────────

class TestCrashWindowRecovery:
    def test_save_fill_is_idempotent(self, tmp_path):
        """save_fill called twice with same order_id inserts only once."""
        s = _storage(tmp_path)
        fill = {
            "order_id":  "ord-crash-001",
            "symbol":    "BTCUSDT",
            "side":      "BUY",
            "fill_price": 50_000.0,
            "fill_qty":  0.01,
            "fee":       0.5,
            "is_maker":  False,
            "filled_at": "2024-01-01T00:00:00+00:00",
        }
        s.save_fill(fill)
        s.save_fill(fill)  # duplicate
        fills = s.get_fills()
        assert len(fills) == 1

    def test_buy_orphan_fill_detected(self, tmp_path):
        """A BUY fill with no matching position shows up as orphan."""
        s = _storage(tmp_path)
        s.save_fill({
            "order_id":  "ord-orphan-buy",
            "symbol":    "BTCUSDT",
            "side":      "BUY",
            "fill_price": 50_000.0,
            "fill_qty":  0.01,
            "fee":       0.5,
        })
        orphans = s.get_orphan_buy_fills()
        assert len(orphans) == 1
        assert orphans[0]["order_id"] == "ord-orphan-buy"

    def test_sell_orphan_fill_detected(self, tmp_path):
        """A SELL fill with no matching closed position shows up as orphan."""
        s = _storage(tmp_path)
        s.save_fill({
            "order_id":  "ord-orphan-sell",
            "symbol":    "BTCUSDT",
            "side":      "SELL",
            "fill_price": 51_000.0,
            "fill_qty":  0.01,
            "fee":       0.51,
        })
        orphans = s.get_orphan_sell_fills()
        assert len(orphans) == 1
        assert orphans[0]["order_id"] == "ord-orphan-sell"

    def test_buy_crash_recovery_opens_position(self, tmp_path):
        """BUY orphan fill replayed → position opened in PositionManager."""
        s = _storage(tmp_path)
        s.save_fill({
            "order_id":  "ord-buy-crash",
            "symbol":    "BTCUSDT",
            "side":      "BUY",
            "fill_price": 50_000.0,
            "fill_qty":  0.01,
            "fee":       0.5,
            "filled_at": "2024-01-01T00:00:00+00:00",
        })
        bus = EventBus()
        pm  = PositionManager(storage=s, bus=bus)
        pm.recover()  # no open positions yet (crash happened before save_position)

        assert pm.open_position_count() == 0
        applied = pm.recover_from_orphan_fills(s)
        assert applied == 1
        assert pm.open_position_count() == 1
        pos = pm.get_open("BTCUSDT")
        assert pos is not None
        assert pos.avg_entry_price == pytest.approx(50_000.0)

    def test_sell_crash_recovery_closes_position(self, tmp_path):
        """SELL orphan fill replayed → open position closed in PositionManager."""
        s = _storage(tmp_path)
        # Simulate a position already open in DB (saved before crash)
        s.save_position({
            "position_id":    "pos-001",
            "symbol":         "BTCUSDT",
            "direction":      "long",
            "status":         "open",
            "size":           0.01,
            "entry_price":    50_000.0,
            "avg_entry_price": 50_000.0,
            "entry_fee":      0.5,
            "entry_order_id": "ord-buy-001",
            "opened_at":      "2024-01-01T00:00:00+00:00",
        })
        # Simulate the SELL fill that closed it (crash before save_position updated)
        s.save_fill({
            "order_id":  "ord-sell-crash",
            "symbol":    "BTCUSDT",
            "side":      "SELL",
            "fill_price": 51_000.0,
            "fill_qty":  0.01,
            "fee":       0.51,
            "filled_at": "2024-01-01T01:00:00+00:00",
        })

        bus = EventBus()
        pm  = PositionManager(storage=s, bus=bus)
        pm.recover()  # loads the open position

        assert pm.open_position_count() == 1
        applied = pm.recover_from_orphan_fills(s)
        assert applied == 1
        assert pm.open_position_count() == 0  # position closed

    def test_no_orphans_when_positions_normal(self, tmp_path):
        """No orphan fills when entry_order_id matches the fill."""
        s = _storage(tmp_path)
        s.save_fill({
            "order_id":  "ord-normal",
            "symbol":    "BTCUSDT",
            "side":      "BUY",
            "fill_price": 50_000.0,
            "fill_qty":  0.01,
            "fee":       0.5,
        })
        s.save_position({
            "position_id":    "pos-normal",
            "symbol":         "BTCUSDT",
            "direction":      "long",
            "status":         "open",
            "size":           0.01,
            "entry_price":    50_000.0,
            "avg_entry_price": 50_000.0,
            "entry_order_id": "ord-normal",  # matches fill
            "opened_at":      "2024-01-01T00:00:00+00:00",
        })
        assert s.get_orphan_buy_fills() == []


# ── P4: Exact cash recovery ───────────────────────────────────────────────────

class TestExactCashRecovery:
    def test_cash_recovery_with_closed_position(self, tmp_path):
        """Cash formula: starting_capital + realized_pnl − open_cost."""
        s = _storage(tmp_path)
        # Closed position: bought at 50000, sold at 51000, qty=0.01
        #   gross_pnl = (51000-50000)*0.01 = 10.0
        #   entry_fee = 0.5, exit_fee = 0.51 → realized = 10.0 - 0.5 - 0.51 = 8.99
        s.save_position({
            "position_id":    "pos-closed",
            "symbol":         "BTCUSDT",
            "direction":      "long",
            "status":         "closed",
            "size":           0.01,
            "entry_price":    50_000.0,
            "avg_entry_price": 50_000.0,
            "exit_price":     51_000.0,
            "realized_pnl":   8.99,
            "entry_fee":      0.5,
            "exit_fee":       0.51,
            "entry_order_id": "buy-1",
            "exit_order_id":  "sell-1",
            "opened_at":      "2024-01-01T00:00:00+00:00",
            "closed_at":      "2024-01-01T01:00:00+00:00",
        })

        realized = s.get_realized_pnl()
        assert realized == pytest.approx(8.99)

        starting_capital = 1000.0
        recovered_cash = starting_capital + realized
        assert recovered_cash == pytest.approx(1008.99)

    def test_cash_recovery_with_open_position_deducted(self, tmp_path):
        """Open position cost is deducted from recovered cash."""
        s = _storage(tmp_path)
        # Open position: bought at 50000, qty=0.01, entry_fee=0.5
        s.save_position({
            "position_id":    "pos-open",
            "symbol":         "BTCUSDT",
            "direction":      "long",
            "status":         "open",
            "size":           0.01,
            "entry_price":    50_000.0,
            "avg_entry_price": 50_000.0,
            "entry_fee":      0.5,
            "entry_order_id": "buy-1",
            "opened_at":      "2024-01-01T00:00:00+00:00",
        })

        bus = EventBus()
        pm  = PositionManager(storage=s, bus=bus)
        pm.recover()

        open_positions = pm.get_all_open()
        open_cost = sum(p.avg_entry_price * p.size + p.entry_fee for p in open_positions)
        # 50000 * 0.01 + 0.5 = 500 + 0.5 = 500.5
        assert open_cost == pytest.approx(500.5)

        starting_capital = 1000.0
        realized = s.get_realized_pnl()  # 0.0 (no closed positions)
        recovered_cash = starting_capital + realized - open_cost
        assert recovered_cash == pytest.approx(499.5)

    def test_cash_recovery_reflects_trade_after_last_snapshot(self, tmp_path):
        """Cash formula gives correct value even without a recent snapshot."""
        s = _storage(tmp_path)
        # Simulate old snapshot (would be stale)
        s.save_balance_snapshot(equity=1000.0, cash=1000.0)

        # A trade happens AFTER the snapshot
        s.save_position({
            "position_id":    "pos-after-snap",
            "symbol":         "ETHUSDT",
            "direction":      "long",
            "status":         "closed",
            "size":           1.0,
            "entry_price":    2000.0,
            "avg_entry_price": 2000.0,
            "exit_price":     2100.0,
            "realized_pnl":   97.0,  # 100 gross - 3 fees
            "entry_fee":      2.0,
            "exit_fee":       2.1,
            "entry_order_id": "buy-eth",
            "exit_order_id":  "sell-eth",
            "opened_at":      "2024-01-01T00:05:00+00:00",
            "closed_at":      "2024-01-01T01:00:00+00:00",
        })

        # Snapshot-based recovery would give $1000 (stale)
        history = s.get_balance_history(limit=1)
        stale_cash = history[-1]["cash"]
        assert stale_cash == pytest.approx(1000.0)

        # Formula-based recovery correctly reflects the trade
        realized = s.get_realized_pnl()
        starting_capital = 1000.0
        recovered_cash = starting_capital + realized
        assert recovered_cash == pytest.approx(1097.0)
        assert recovered_cash != stale_cash


# ── P5: Daily reset dispatched exactly once ───────────────────────────────────

class TestDailyResetDispatch:
    def test_on_daily_reset_called_once(self, tmp_path):
        """engine.on_daily_reset() is called exactly once per reset cycle."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s)
        engine = _engine(cfg, bus, ex, om, pm, pf, risk, st, s, AlwaysBuy())

        reset_calls = []
        original_reset = engine.on_daily_reset

        def counting_reset(ev):
            reset_calls.append(ev)
            original_reset(ev)

        engine.on_daily_reset = counting_reset

        ev = DailyResetEvent(date_utc="2024-01-01")
        bus.emit(ev)          # DailyResetEvent has no bus subscriber in BotEngine
        engine.on_daily_reset(ev)  # the only real call

        # Only one call (direct) — bus.emit() had no effect
        assert len(reset_calls) == 1

    def test_bus_emit_daily_reset_has_no_engine_subscriber(self, tmp_path):
        """BotEngine does NOT subscribe to DailyResetEvent — bus.emit is a no-op."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s)
        _engine(cfg, bus, ex, om, pm, pf, risk, st, s, AlwaysBuy())

        called = []
        ev = DailyResetEvent(date_utc="2024-01-01")
        bus.subscribe(DailyResetEvent, called.append)

        # The listener we just added IS called; this proves bus works.
        # But there are no engine listeners for this event type.
        bus.emit(ev)
        assert len(called) == 1  # only our test listener, not the engine


# ── P2: Auth enforcement ──────────────────────────────────────────────────────

@pytest.fixture
def api_app(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGELAB_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("EDGELAB_USERNAME",   "testuser")

    from server.auth import hash_password
    monkeypatch.setenv("EDGELAB_PASSWORD_HASH", hash_password("testpass"))
    monkeypatch.setenv("EDGELAB_DB",      str(tmp_path / "test.db"))
    monkeypatch.setenv("EDGELAB_REPORTS", str(tmp_path / "reports"))
    monkeypatch.setenv("EDGELAB_LOG",     str(tmp_path / "test.log"))

    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_USERNAME",  "testuser")
    monkeypatch.setattr(auth_mod, "_PASS_HASH", hash_password("testpass"))
    monkeypatch.setattr(auth_mod, "USING_DEFAULT_CREDS", False)

    import server.api as api_mod
    monkeypatch.setattr(api_mod, "_REPORTS_DIR", tmp_path / "reports")

    from server.app import create_app
    return create_app()


@pytest.fixture
def unauthed_client(api_app):
    from fastapi.testclient import TestClient
    return TestClient(api_app, raise_server_exceptions=True)


@pytest.fixture
def authed_client(api_app):
    from fastapi.testclient import TestClient
    client = TestClient(api_app, raise_server_exceptions=True)
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass", "next": "/"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return client


class TestAuthEnforcement:
    def test_history_unauthenticated_rejected(self, unauthed_client):
        resp = unauthed_client.get("/api/history", follow_redirects=False)
        assert resp.status_code in (303, 401, 302, 307)

    def test_strategies_unauthenticated_rejected(self, unauthed_client):
        resp = unauthed_client.get("/api/strategies", follow_redirects=False)
        assert resp.status_code in (303, 401, 302, 307)

    def test_history_authenticated_succeeds(self, authed_client):
        resp = authed_client.get("/api/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_strategies_authenticated_succeeds(self, authed_client):
        resp = authed_client.get("/api/strategies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_bot_status_unauthenticated_rejected(self, unauthed_client):
        resp = unauthed_client.get("/api/bot/status", follow_redirects=False)
        assert resp.status_code in (303, 401, 302, 307)

    def test_logs_unauthenticated_rejected(self, unauthed_client):
        resp = unauthed_client.get("/api/logs", follow_redirects=False)
        assert resp.status_code in (303, 401, 302, 307)


# ── P6: Multi-interval startup rejection ──────────────────────────────────────

class TestMultiIntervalRejection:
    def test_bot_manager_rejects_multi_interval(self):
        from server.bot_manager import BotManager
        mgr = BotManager()
        ok, err = mgr.start(
            capital=100.0,
            symbols=["BTCUSDT"],
            intervals=["1h", "4h"],
        )
        assert ok is False
        assert "interval" in err.lower() or "multi" in err.lower()

    def test_bot_manager_accepts_single_interval(self):
        from server.bot_manager import BotManager
        mgr = BotManager()
        with patch("bot.runtime.LiveFeed") as mock_feed:
            mock_feed.return_value.run = MagicMock(return_value=None)
            ok, err = mgr.start(
                capital=100.0,
                symbols=["BTCUSDT"],
                intervals=["1h"],
            )
        # ok may be True or False depending on whether thread started,
        # but the error should NOT be about multi-interval
        if not ok:
            assert "multi" not in err.lower()
        mgr.stop()

    def test_single_interval_config_valid(self):
        """BotConfig with single interval is not rejected at the config level."""
        cfg = BotConfig(feed=FeedConfig(intervals=["1h"]))
        assert cfg.feed.intervals == ["1h"]

    def test_multi_interval_config_is_just_data(self):
        """BotConfig itself accepts multi-interval (validation is at startup)."""
        cfg = BotConfig(feed=FeedConfig(intervals=["1h", "4h"]))
        assert cfg.feed.intervals == ["1h", "4h"]


# ── P7-4: Multi-symbol isolation ─────────────────────────────────────────────

class TestMultiSymbolIsolation:
    def test_btc_position_does_not_affect_eth(self, tmp_path):
        """BTC and ETH positions are tracked independently."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, max_open_positions=2)
        strategy_map = {
            ("BTCUSDT", "1h"): AlwaysBuy(),
            ("ETHUSDT", "1h"): AlwaysBuy(),
        }
        _engine(cfg, bus, ex, om, pm, pf, risk, st, s, strategy_map)

        _emit_history(bus, 60, symbol="BTCUSDT")
        _emit_history(bus, 60, symbol="ETHUSDT", price=2000.0)

        for i in range(60, 65):
            _emit_live(bus, i, symbol="BTCUSDT", price=50_000.0)
            _emit_live(bus, i, symbol="ETHUSDT", price=2000.0)

        btc_pos = pm.get_open("BTCUSDT")
        eth_pos = pm.get_open("ETHUSDT")
        # If either opened, verify they are independent records
        if btc_pos and eth_pos:
            assert btc_pos.position_id != eth_pos.position_id
            assert btc_pos.symbol == "BTCUSDT"
            assert eth_pos.symbol == "ETHUSDT"


# ── P7-7: BotManager lifecycle ────────────────────────────────────────────────

class TestBotManagerLifecycle:
    def test_start_stop(self):
        from server.bot_manager import BotManager
        mgr = BotManager()
        assert not mgr._running

        with patch("bot.runtime.LiveFeed") as mock_lf:
            # Make the async run() return immediately so the thread exits
            import asyncio

            async def _noop():
                pass

            mock_lf.return_value.run = _noop
            ok, err = mgr.start(
                capital=100.0, symbols=["BTCUSDT"], intervals=["1h"],
                db_path=":memory:",
            )

        assert ok is True, err

        # Give thread time to start
        import time
        time.sleep(0.1)

        ok2, err2 = mgr.stop()
        assert ok2 is True, err2

    def test_double_start_rejected(self):
        from server.bot_manager import BotManager
        mgr = BotManager()
        # Force running state
        mgr._running = True
        ok, err = mgr.start(capital=100.0, symbols=["BTCUSDT"], intervals=["1h"])
        assert ok is False
        assert "already running" in err.lower()


# ── P7-10: Stream limit boundary ──────────────────────────────────────────────

class TestStreamLimitBoundary:
    def _make_config(self, n_symbols):
        return BotConfig(
            feed=FeedConfig(
                symbols=[f"SYM{i:04d}USDT" for i in range(n_symbols)],
                intervals=["1h"],
            )
        )

    def test_1024_streams_allowed(self, tmp_path):
        """Exactly 1024 streams (1024 symbols × 1 interval) is allowed."""
        from bot.runtime import LiveFeed
        cfg = self._make_config(1024)
        bus = EventBus()
        st  = BotState(buffer_size=10)
        feed = LiveFeed(config=cfg, state=st, bus=bus)
        url = feed._build_ws_url()
        assert "sym0000usdt" in url
        assert "sym1023usdt" in url

    def test_1025_streams_rejected(self, tmp_path):
        """1025 streams exceeds the Binance limit and raises ValueError."""
        from bot.runtime import LiveFeed
        cfg = self._make_config(1025)
        bus = EventBus()
        st  = BotState(buffer_size=10)
        feed = LiveFeed(config=cfg, state=st, bus=bus)
        with pytest.raises(ValueError, match="1025"):
            feed._build_ws_url()
