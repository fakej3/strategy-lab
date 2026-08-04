"""Regression tests for thread safety in PositionManager and BotStorage."""
from __future__ import annotations

import threading
import time

import pytest

from bot.events import EventBus
from bot.paper_exchange import PaperFill, SIDE_BUY, SIDE_SELL
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


def _fill(
    order_id: str = "o1",
    symbol: str = "BTCUSDT",
    side: str = SIDE_BUY,
    price: float = 50000.0,
    qty: float = 0.001,
) -> PaperFill:
    return PaperFill(
        order_id=order_id,
        symbol=symbol,
        side=side,
        fill_price=price,
        fill_qty=qty,
        fee=price * qty * 0.001,
    )


class TestPositionManagerThreadSafety:
    def test_concurrent_reads_while_open(self, pm):
        """get_all_open / has_open_position / open_position_count are safe under concurrency."""
        pm.on_fill(_fill(side=SIDE_BUY, order_id="o1"))

        errors: list[Exception] = []

        def reader():
            for _ in range(200):
                try:
                    pm.get_all_open()
                    pm.has_open_position("BTCUSDT")
                    pm.open_position_count()
                    pm.total_unrealized_pnl({"BTCUSDT": 50000.0})
                    pm.total_exposure()
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Reader threads raised: {errors[:3]}"

    def test_concurrent_open_and_close(self, pm, storage):
        """on_fill from multiple virtual trades must not corrupt internal state."""
        errors: list[Exception] = []

        def trade_cycle(n: int):
            try:
                entry = _fill(order_id=f"e{n}", symbol="BTCUSDT", side=SIDE_BUY)
                pm.on_fill(entry, equity=25.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=trade_cycle, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At most one open position per symbol — we may have multiple because
        # the last writer wins; what must NOT happen is an unhandled exception.
        assert errors == [], f"Threads raised: {errors[:3]}"

    def test_total_unrealized_pnl_no_dict_size_error(self, pm):
        """total_unrealized_pnl must not raise RuntimeError during position changes."""
        pm.on_fill(_fill(side=SIDE_BUY, order_id="o1"))

        errors: list[Exception] = []
        stop = threading.Event()

        def compute_pnl():
            while not stop.is_set():
                try:
                    pm.total_unrealized_pnl({"BTCUSDT": 50100.0})
                except Exception as exc:
                    errors.append(exc)

        def close_position():
            try:
                pm.on_fill(_fill(side=SIDE_SELL, order_id="o2"), equity=25.0)
            except Exception as exc:
                errors.append(exc)

        readers = [threading.Thread(target=compute_pnl) for _ in range(4)]
        writer = threading.Thread(target=close_position)

        for r in readers:
            r.start()
        time.sleep(0.01)
        writer.start()
        writer.join()
        stop.set()
        for r in readers:
            r.join()

        assert errors == [], f"Threads raised: {errors[:3]}"


class TestBotStorageThreadSafety:
    def test_concurrent_writes_to_different_tables(self, storage):
        """Writes to heartbeat and balance tables from different threads must not raise."""
        errors: list[Exception] = []

        def heartbeat_writer(n: int):
            for i in range(30):
                try:
                    storage.save_heartbeat(uptime_s=float(n * 100 + i), active_symbols=1, candles_recv=i)
                except Exception as exc:
                    errors.append(exc)

        def balance_writer(n: int):
            for i in range(30):
                try:
                    storage.save_balance_snapshot(equity=float(n + i), cash=float(n + i))
                except Exception as exc:
                    errors.append(exc)

        threads = (
            [threading.Thread(target=heartbeat_writer, args=(i,)) for i in range(4)] +
            [threading.Thread(target=balance_writer, args=(i,)) for i in range(4)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Writer threads raised: {errors[:3]}"

    def test_reads_concurrent_with_writes(self, storage):
        """Reads must not corrupt or deadlock when writes are in-flight."""
        errors: list[Exception] = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                try:
                    storage.save_heartbeat(uptime_s=float(i), active_symbols=1, candles_recv=i)
                    i += 1
                except Exception as exc:
                    errors.append(exc)

        def reader():
            while not stop.is_set():
                try:
                    storage.get_last_heartbeat()
                    storage.get_balance_history(limit=5)
                except Exception as exc:
                    errors.append(exc)

        writers = [threading.Thread(target=writer) for _ in range(2)]
        readers = [threading.Thread(target=reader) for _ in range(3)]

        for t in writers + readers:
            t.start()
        time.sleep(0.2)
        stop.set()
        for t in writers + readers:
            t.join()

        assert errors == [], f"Threads raised: {errors[:3]}"

    def test_error_log_concurrent(self, storage):
        errors: list[Exception] = []

        def log_errors(n: int):
            for i in range(20):
                try:
                    storage.log_error("test", f"msg {n}-{i}", "detail")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=log_errors, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised: {errors[:3]}"
        # All 100 errors should be persisted
        logged = storage.get_errors(limit=200)
        assert len(logged) == 100
