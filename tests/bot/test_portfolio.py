"""Tests for Portfolio accounting."""
from __future__ import annotations

import pytest

from bot.events import EventBus
from bot.paper_exchange import PaperFill
from bot.portfolio import Portfolio
from bot.position_manager import Position
from bot.storage import BotStorage


@pytest.fixture
def storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


@pytest.fixture
def pf(storage):
    return Portfolio(
        starting_capital=100_000.0,
        storage=storage,
        bus=EventBus(),
        fee_rate=0.001,
    )


def _buy_fill(price=50000.0, qty=1.0, fee=50.0):
    return PaperFill(
        order_id="o1", symbol="BTCUSDT", side="BUY",
        fill_price=price, fill_qty=qty, fee=fee,
        is_maker=False, filled_at="2024-01-01T00:00:00+00:00",
    )


def _sell_fill(price=52000.0, qty=1.0, fee=52.0):
    return PaperFill(
        order_id="o2", symbol="BTCUSDT", side="SELL",
        fill_price=price, fill_qty=qty, fee=fee,
        is_maker=False, filled_at="2024-01-01T01:00:00+00:00",
    )


class TestPortfolio:
    def test_initial_cash(self, pf):
        assert pf.cash == pytest.approx(100_000.0)

    def test_buy_deducts_cash(self, pf):
        pf.on_fill(_buy_fill(price=50000.0, qty=1.0, fee=50.0))
        # cash = 100000 - 50000 - 50 = 49950
        assert pf.cash == pytest.approx(49950.0)

    def test_sell_adds_cash(self, pf):
        pf.on_fill(_buy_fill(price=50000.0, qty=1.0, fee=50.0))
        pf.on_fill(_sell_fill(price=52000.0, qty=1.0, fee=52.0), closed_pnl=1898.0)
        # sell adds: 52000 - 52 = 51948
        assert pf.cash == pytest.approx(49950.0 + 51948.0)

    def test_daily_pnl_updated_on_close(self, pf):
        pf.on_fill(_buy_fill())
        pf.on_fill(_sell_fill(), closed_pnl=1000.0)
        assert pf.daily_pnl == pytest.approx(1000.0)

    def test_peak_equity_tracks_maximum(self, pf):
        assert pf.peak_equity == pytest.approx(100_000.0)

    def test_snapshot_persisted(self, pf, storage):
        snap = pf.snapshot(mark_prices={}, positions=[])
        rows = storage.get_balance_history(limit=10)
        assert len(rows) == 1
        assert rows[0]["equity"] == pytest.approx(snap.equity)

    def test_drawdown_in_snapshot(self, pf):
        # Deplete cash
        pf.on_fill(_buy_fill(price=50000.0, qty=1.0, fee=50.0), closed_pnl=-1000.0)
        # Unrealized PnL from mark price below entry
        pos = Position(
            position_id="p1", symbol="BTCUSDT", direction="long",
            status="open", size=1.0, entry_price=50000.0, avg_entry_price=50000.0,
        )
        snap = pf.snapshot(mark_prices={"BTCUSDT": 49000.0}, positions=[pos])
        assert snap.drawdown > 0.0

    def test_reset_daily_clears_counters(self, pf):
        pf.on_fill(_buy_fill(), closed_pnl=500.0)
        pf.reset_daily()
        assert pf.daily_pnl == pytest.approx(0.0)
        assert pf.n_trades_today == 0

    def test_restore(self, pf):
        pf.restore(cash=80_000.0, peak_equity=105_000.0)
        assert pf.cash == pytest.approx(80_000.0)
        assert pf.peak_equity == pytest.approx(105_000.0)
