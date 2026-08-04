"""Tests for PositionManager."""
from __future__ import annotations

import pytest

from bot.events import EventBus
from bot.paper_exchange import PaperFill
from bot.position_manager import PositionManager
from bot.storage import BotStorage


@pytest.fixture
def storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


@pytest.fixture
def pm(storage):
    return PositionManager(storage=storage, bus=EventBus())


def _fill(side="BUY", price=50000.0, qty=0.1, fee=5.0, ts="2024-01-01T00:00:00+00:00"):
    return PaperFill(
        order_id="test-order",
        symbol="BTCUSDT",
        side=side,
        fill_price=price,
        fill_qty=qty,
        fee=fee,
        is_maker=False,
        filled_at=ts,
    )


class TestPositionManager:
    def test_buy_fill_opens_long_position(self, pm):
        pos = pm.on_fill(_fill(side="BUY", price=50000.0))
        assert pos.status == "open"
        assert pos.direction == "long"
        assert pos.size == pytest.approx(0.1)
        assert pos.entry_price == pytest.approx(50000.0)

    def test_sell_fill_opens_short_position(self, pm):
        pos = pm.on_fill(_fill(side="SELL", price=50000.0))
        assert pos.direction == "short"
        assert pos.status == "open"

    def test_exit_fill_closes_long_position(self, pm):
        pm.on_fill(_fill(side="BUY", price=50000.0, fee=5.0))
        pos = pm.on_fill(_fill(side="SELL", price=52000.0, fee=5.2))
        assert pos.status == "closed"
        # gross = (52000 - 50000) * 0.1 = 200
        # net   = 200 - 5.0 - 5.2 = 189.8
        assert pos.realized_pnl == pytest.approx(189.8, rel=1e-5)
        assert pm.get_open("BTCUSDT") is None

    def test_has_open_position(self, pm):
        assert pm.has_open_position("BTCUSDT") is False
        pm.on_fill(_fill(side="BUY"))
        assert pm.has_open_position("BTCUSDT") is True

    def test_unrealized_pnl(self, pm):
        pm.on_fill(_fill(side="BUY", price=50000.0))
        pos = pm.get_open("BTCUSDT")
        # mark at 51000 → unrealized = (51000 - 50000) * 0.1 = 100
        assert pos.unrealized_pnl(51000.0) == pytest.approx(100.0)

    def test_position_persisted(self, pm, storage):
        pm.on_fill(_fill(side="BUY"))
        rows = storage.get_open_positions()
        assert len(rows) == 1
        assert rows[0]["direction"] == "long"

    def test_closed_position_status_in_storage(self, pm, storage):
        pm.on_fill(_fill(side="BUY", price=50000.0))
        pm.on_fill(_fill(side="SELL", price=51000.0))
        all_pos = storage.get_positions(limit=10)
        assert any(p["status"] == "closed" for p in all_pos)
