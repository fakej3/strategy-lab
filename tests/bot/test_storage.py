"""Tests for BotStorage."""
from __future__ import annotations

import pytest

from bot.storage import BotStorage


@pytest.fixture
def db(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


def _order(**kwargs):
    defaults = {
        "order_id": "ord-001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "order_type": "MARKET",
        "status": "ACCEPTED",
        "qty": 0.1,
        "created_at": "2024-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def _position(**kwargs):
    defaults = {
        "position_id": "pos-001",
        "symbol": "BTCUSDT",
        "direction": "long",
        "status": "open",
        "size": 0.1,
        "entry_price": 50000.0,
        "avg_entry_price": 50000.0,
        "opened_at": "2024-01-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


class TestBotStorage:
    def test_save_and_get_order(self, db):
        db.save_order(_order())
        rows = db.get_orders(limit=10)
        assert len(rows) == 1
        assert rows[0]["order_id"] == "ord-001"
        assert rows[0]["symbol"] == "BTCUSDT"

    def test_get_open_orders(self, db):
        db.save_order(_order(status="ACCEPTED"))
        db.save_order(_order(order_id="ord-002", status="FILLED"))
        open_orders = db.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == "ord-001"

    def test_save_and_get_position(self, db):
        db.save_position(_position())
        rows = db.get_positions(limit=10)
        assert len(rows) == 1
        assert rows[0]["position_id"] == "pos-001"

    def test_get_open_positions(self, db):
        db.save_position(_position(status="open"))
        db.save_position(_position(position_id="pos-002", status="closed"))
        open_pos = db.get_open_positions()
        assert len(open_pos) == 1

    def test_save_and_get_fill(self, db):
        db.save_fill({
            "order_id": "ord-001", "symbol": "BTCUSDT", "side": "BUY",
            "fill_price": 50000.0, "fill_qty": 0.1, "fee": 5.0,
            "is_maker": False, "filled_at": "2024-01-01T00:00:00+00:00",
        })
        fills = db.get_fills(limit=10)
        assert len(fills) == 1
        assert fills[0]["fill_price"] == pytest.approx(50000.0)

    def test_upsert_daily_stats(self, db):
        stats = {"date_utc": "2024-01-01", "n_trades": 5, "net_pnl": 200.0}
        db.upsert_daily_stats(stats)
        row = db.get_daily_stats_for("2024-01-01")
        assert row is not None
        assert row["n_trades"] == 5

    def test_save_balance_snapshot(self, db):
        db.save_balance_snapshot(equity=100_000.0, cash=90_000.0, unrealized=10_000.0)
        hist = db.get_balance_history(limit=10)
        assert len(hist) == 1
        assert hist[0]["equity"] == pytest.approx(100_000.0)

    def test_log_error(self, db):
        db.log_error("test_source", "Something went wrong", "detail here")
        errors = db.get_errors(limit=10)
        assert len(errors) == 1
        assert errors[0]["source"] == "test_source"

    def test_save_and_get_heartbeat(self, db):
        db.save_heartbeat(uptime_s=3600.0, active_symbols=1, candles_recv=100)
        hb = db.get_last_heartbeat()
        assert hb is not None
        assert hb["uptime_s"] == pytest.approx(3600.0)

    def test_runtime_snapshot_limit(self, db):
        for i in range(5):
            db.save_runtime_snapshot({"uptime_s": float(i), "candles_total": i})
        hist = db.get_runtime_history(limit=10)
        assert len(hist) <= 5

    def test_order_upsert(self, db):
        db.save_order(_order(status="ACCEPTED"))
        db.save_order(_order(status="FILLED"))
        rows = db.get_orders(limit=10)
        assert len(rows) == 1
        assert rows[0]["status"] == "FILLED"

    def test_context_manager(self, tmp_path):
        with BotStorage(tmp_path / "ctx.db") as s:
            s.save_balance_snapshot(equity=1.0, cash=1.0)
