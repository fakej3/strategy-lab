"""Adversarial state-machine tests for the paper trading layer."""
from __future__ import annotations

import pytest

from bot.events import EventBus
from bot.paper_exchange import (
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    SIDE_BUY,
    SIDE_SELL,
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_REJECTED,
    PaperExchange,
)


def test_cancel_is_terminal_and_idempotent() -> None:
    ex = PaperExchange()
    order = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, 0.01, price=90.0)
    assert order.status == STATUS_ACCEPTED

    assert ex.cancel_order(order.order_id) is True
    assert order.status == STATUS_CANCELLED
    assert ex.cancel_order(order.order_id) is False


def test_duplicate_explicit_order_id_must_not_create_two_live_orders() -> None:
    ex = PaperExchange()
    oid = "deterministic-test-order"

    first = ex.submit_order(
        "BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, 0.01, order_id=oid
    )
    second = ex.submit_order(
        "BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, 0.01, order_id=oid
    )

    # An order ID is the exchange identity. Reusing it must never result in
    # two independently matchable orders, regardless of the exact rejection
    # policy chosen by the implementation.
    open_orders = ex.get_open_orders("BTCUSDT")
    assert len([o for o in open_orders if o.order_id == oid]) <= 1
    assert second.order_id == oid
    assert second.status in (STATUS_REJECTED, STATUS_ACCEPTED)


def test_reduce_only_sell_without_long_position_is_rejected() -> None:
    ex = PaperExchange()
    order = ex.submit_order(
        "BTCUSDT",
        SIDE_SELL,
        ORDER_TYPE_MARKET,
        0.01,
        reduce_only=True,
        current_position_size=0.0,
    )
    assert order.status == STATUS_REJECTED


def test_event_bus_does_not_change_order_identity() -> None:
    bus = EventBus()
    ex = PaperExchange(bus=bus)
    order = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, 0.01)
    assert order.order_id
    assert order.status == STATUS_ACCEPTED
