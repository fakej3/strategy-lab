"""Tests for PaperExchange order matching logic."""
from __future__ import annotations

import pytest

from bot.paper_exchange import (
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_STOP_LIMIT,
    ORDER_TYPE_STOP_MARKET,
    ORDER_TYPE_TAKE_PROFIT,
    SIDE_BUY,
    SIDE_SELL,
    STATUS_ACCEPTED,
    STATUS_FILLED,
    STATUS_REJECTED,
    PaperExchange,
)


@pytest.fixture
def ex():
    return PaperExchange(fee_rate=0.001, maker_fee_rate=0.0009, slippage_pct=0.0)


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_missing_price_for_limit_rejected(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1)
        assert o.status == STATUS_REJECTED
        assert "requires price" in o.reject_reason

    def test_missing_stop_price_for_stop_market_rejected(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_STOP_MARKET, qty=0.1)
        assert o.status == STATUS_REJECTED
        assert "requires stop_price" in o.reject_reason

    def test_qty_below_minimum_rejected(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.000001)
        assert o.status == STATUS_REJECTED

    def test_reduce_only_too_large_rejected(self, ex):
        o = ex.submit_order(
            "BTCUSDT", SIDE_SELL, ORDER_TYPE_MARKET, qty=1.0,
            reduce_only=True, current_position_size=0.5,
        )
        assert o.status == STATUS_REJECTED
        assert "reduce_only" in o.reject_reason

    def test_valid_market_order_accepted(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        assert o.status == STATUS_ACCEPTED


# ── Market orders ─────────────────────────────────────────────────────────────

class TestMarketOrders:
    def test_market_buy_fills_at_open(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(50000.0, rel=1e-5)
        assert fills[0].fill_qty  == pytest.approx(0.1)
        assert fills[0].side      == SIDE_BUY

    def test_market_sell_fills_at_open(self, ex):
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_MARKET, qty=0.1)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(50000.0, rel=1e-5)
        assert fills[0].side      == SIDE_SELL

    def test_market_order_taker_fee(self):
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=1.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert fills[0].fee == pytest.approx(50000.0 * 1.0 * 0.001, rel=1e-5)
        assert fills[0].is_maker is False

    def test_market_order_slippage(self):
        ex = PaperExchange(fee_rate=0.0, slippage_pct=0.001)
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert fills[0].fill_price == pytest.approx(50000.0 * 1.001, rel=1e-5)

    def test_market_order_removed_after_fill(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(ex.get_open_orders("BTCUSDT")) == 0


# ── Limit orders ──────────────────────────────────────────────────────────────

class TestLimitOrders:
    def test_limit_buy_fills_when_low_reaches_price(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=49000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=48500, close=49500)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(49000.0, rel=1e-5)
        assert fills[0].is_maker is True

    def test_limit_buy_does_not_fill_when_price_not_reached(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=48000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50000)
        assert len(fills) == 0

    def test_limit_sell_fills_when_high_reaches_price(self, ex):
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_LIMIT, qty=0.1, price=51000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51500, low=49500, close=50500)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(51000.0, rel=1e-5)

    def test_limit_buy_gap_down_fills_at_open(self, ex):
        """If bar opens below limit price, fill at open (better execution)."""
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=50000.0)
        fills = ex.process_candle("BTCUSDT", open_=49000, high=49500, low=48500, close=49200)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(49000.0, rel=1e-5)

    def test_limit_maker_fee(self):
        ex = PaperExchange(fee_rate=0.001, maker_fee_rate=0.0009, slippage_pct=0.0)
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=1.0, price=49000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=48500, close=50000)
        assert fills[0].fee == pytest.approx(49000.0 * 0.0009, rel=1e-5)
        assert fills[0].is_maker is True


# ── Stop Market orders ────────────────────────────────────────────────────────

class TestStopMarketOrders:
    def test_sell_stop_triggers_on_low(self, ex):
        # Long SL: sell when price drops to stop
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET, qty=0.1, stop_price=49000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=50500, low=48500, close=49000)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(49000.0, rel=1e-5)

    def test_gap_through_stop_fills_at_open(self, ex):
        """Gap-down through stop: fill at open (best executable price)."""
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET, qty=0.1, stop_price=49000.0)
        # Bar opens at 48000, below stop — gap through
        fills = ex.process_candle("BTCUSDT", open_=48000, high=48500, low=47500, close=48000)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(48000.0, rel=1e-5)

    def test_buy_stop_triggers_on_high(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_STOP_MARKET, qty=0.1, stop_price=51000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51500, low=49500, close=51000)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(51000.0, rel=1e-5)

    def test_stop_not_triggered(self, ex):
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET, qty=0.1, stop_price=48000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50000)
        assert len(fills) == 0


# ── Take Profit orders ────────────────────────────────────────────────────────

class TestTakeProfitOrders:
    def test_long_tp_triggers_on_high(self, ex):
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT, qty=0.1, stop_price=52000.0)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=52500, low=49500, close=52000)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(52000.0, rel=1e-5)

    def test_long_tp_gap_up_fills_at_open(self, ex):
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT, qty=0.1, stop_price=50000.0)
        # Opens above TP
        fills = ex.process_candle("BTCUSDT", open_=51000, high=51500, low=50500, close=51000)
        assert len(fills) == 1
        assert fills[0].fill_price == pytest.approx(51000.0, rel=1e-5)


# ── Cancel ────────────────────────────────────────────────────────────────────

class TestCancel:
    def test_cancel_removes_order(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=45000.0)
        assert ex.cancel_order(o.order_id) is True
        assert len(ex.get_open_orders("BTCUSDT")) == 0

    def test_cancel_all(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=44000.0)
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=43000.0)
        n = ex.cancel_all("BTCUSDT")
        assert n == 2
        assert len(ex.get_open_orders("BTCUSDT")) == 0

    def test_cancel_already_filled_returns_false(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert ex.cancel_order(o.order_id) is False


# ── Multiple orders ───────────────────────────────────────────────────────────

class TestMultipleOrders:
    def test_multiple_orders_same_candle(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_MARKET, qty=0.05)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(fills) == 2

    def test_unfilled_limit_persists_across_candles(self, ex):
        ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT, qty=0.1, price=40000.0)
        fills1 = ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50500)
        assert len(fills1) == 0
        assert len(ex.get_open_orders("BTCUSDT")) == 1
        # Still open next candle
        fills2 = ex.process_candle("BTCUSDT", open_=49000, high=50000, low=45000, close=47000)
        assert len(fills2) == 0  # still above 40k
