"""Tests for EventBus."""
from __future__ import annotations

import threading

import pytest

from bot.events import (
    BotEvent, CandleEvent, EventBus, FillEvent, OrderEvent
)


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(CandleEvent, received.append)
        e = CandleEvent(symbol="BTCUSDT", interval="1h", close=50000.0)
        bus.emit(e)
        assert len(received) == 1
        assert received[0].close == pytest.approx(50000.0)

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        h = received.append
        bus.subscribe(CandleEvent, h)
        bus.unsubscribe(CandleEvent, h)
        bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h"))
        assert len(received) == 0

    def test_handler_exception_does_not_crash_emitter(self):
        bus = EventBus()

        def bad_handler(e):
            raise RuntimeError("oops")

        received = []
        bus.subscribe(CandleEvent, bad_handler)
        bus.subscribe(CandleEvent, received.append)
        bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h"))
        assert len(received) == 1   # second handler still called

    def test_multiple_event_types(self):
        bus = EventBus()
        candles, orders = [], []
        bus.subscribe(CandleEvent, candles.append)
        bus.subscribe(OrderEvent,  orders.append)
        bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h"))
        bus.emit(OrderEvent(order_id="o1", symbol="BTCUSDT", side="BUY", status="FILLED"))
        assert len(candles) == 1
        assert len(orders)  == 1

    def test_emit_all(self):
        bus = EventBus()
        received = []
        bus.subscribe(CandleEvent, received.append)
        bus.emit_all([
            CandleEvent(symbol="BTCUSDT", interval="1h"),
            CandleEvent(symbol="ETHUSDT", interval="1h"),
        ])
        assert len(received) == 2

    def test_handler_count(self):
        bus = EventBus()
        assert bus.handler_count(CandleEvent) == 0
        bus.subscribe(CandleEvent, lambda e: None)
        assert bus.handler_count(CandleEvent) == 1

    def test_thread_safe_emit(self):
        bus = EventBus()
        received = []
        lock = threading.Lock()

        def handler(e):
            with lock:
                received.append(e)

        bus.subscribe(CandleEvent, handler)
        threads = [
            threading.Thread(
                target=lambda: bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h"))
            )
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(received) == 20
