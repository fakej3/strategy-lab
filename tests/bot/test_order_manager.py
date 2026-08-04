"""Tests for OrderManager."""
from __future__ import annotations

import pytest

from bot.events import EventBus
from bot.order_manager import OrderManager
from bot.paper_exchange import (
    PaperExchange, STATUS_ACCEPTED, STATUS_FILLED, STATUS_CANCELLED
)
from bot.storage import BotStorage


@pytest.fixture
def storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


@pytest.fixture
def om(storage):
    bus = EventBus()
    ex  = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
    return OrderManager(exchange=ex, storage=storage, bus=bus)


class TestOrderManager:
    def test_submit_market_accepted(self, om):
        o = om.submit_market("BTCUSDT", "BUY", qty=0.1)
        assert o.status == STATUS_ACCEPTED

    def test_submit_limit_accepted(self, om):
        o = om.submit_limit("BTCUSDT", "BUY", qty=0.1, price=45000.0)
        assert o.status == STATUS_ACCEPTED

    def test_on_candle_fills_market_order(self, om):
        o = om.submit_market("BTCUSDT", "BUY", qty=0.1)
        fills = om.on_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(fills) == 1
        assert o.status == STATUS_FILLED

    def test_cancel_removes_order(self, om):
        o = om.submit_limit("BTCUSDT", "BUY", qty=0.1, price=40000.0)
        assert om.cancel(o.order_id) is True
        assert o.status == STATUS_CANCELLED
        assert om.open_order_count("BTCUSDT") == 0

    def test_cancel_all(self, om):
        om.submit_limit("BTCUSDT", "BUY", qty=0.1, price=39000.0)
        om.submit_limit("BTCUSDT", "BUY", qty=0.1, price=38000.0)
        n = om.cancel_all("BTCUSDT")
        assert n == 2
        assert om.open_order_count("BTCUSDT") == 0

    def test_order_persisted_to_storage(self, om, storage):
        om.submit_market("BTCUSDT", "BUY", qty=0.1)
        rows = storage.get_orders(limit=10)
        assert len(rows) == 1

    def test_fill_persisted_to_storage(self, om, storage):
        om.submit_market("BTCUSDT", "BUY", qty=0.1)
        om.on_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        fills = storage.get_fills(limit=10)
        assert len(fills) == 1
