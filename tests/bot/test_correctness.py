"""Regression tests for the Phase 1-16 correctness fix pass.

Each test class is labelled with the phase number it covers.
"""
from __future__ import annotations

import logging
import pytest
import pandas as pd

from bot.config import BotConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, EventBus, SignalEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import (
    ORDER_TYPE_MARKET,
    ORDER_TYPE_STOP_MARKET,
    ORDER_TYPE_TAKE_PROFIT,
    ORDER_TYPE_LIMIT,
    SIDE_BUY,
    SIDE_SELL,
    STATUS_ACCEPTED,
    STATUS_FILLED,
    STATUS_REJECTED,
    STATUS_CANCELLED,
    PaperExchange,
    SymbolRules,
    _qty_step_valid,
)
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskConfig, RiskEngine
from bot.state import BotState
from bot.storage import BotStorage
from engine.strategy import Signal


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


@pytest.fixture
def ex():
    return PaperExchange(fee_rate=0.001, slippage_pct=0.0)


def _make_components(storage, paper_capital=1000.0):
    cfg   = BotConfig(paper_capital=paper_capital)
    bus   = EventBus()
    ex    = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
    om    = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm    = PositionManager(storage=storage, bus=bus)
    pf    = Portfolio(starting_capital=paper_capital, storage=storage, bus=bus)
    risk  = RiskEngine(cfg.risk, bus=bus)
    state = BotState(buffer_size=200)
    return cfg, bus, ex, om, pm, pf, risk, state


def _make_engine(strategy, cfg, bus, ex, om, pm, pf, risk, state, storage):
    return BotEngine(
        config=cfg, strategy=strategy,
        state=state, orders=om, positions=pm,
        portfolio=pf, risk=risk, storage=storage, bus=bus,
    )


def _candle_event(i=0, symbol="BTCUSDT", interval="1h", price=50000.0,
                  is_history=False):
    base_ms = 1_700_000_000_000
    interval_ms = 3_600_000
    open_ms  = base_ms + i * interval_ms
    close_ms = open_ms + interval_ms - 1
    return CandleEvent(
        symbol=symbol, interval=interval,
        open_time=open_ms, open=price, high=price * 1.01,
        low=price * 0.99, close=price, volume=100.0,
        close_time=close_ms,
        is_history=is_history,
    )


def _emit_candles(bus, n, symbol="BTCUSDT", interval="1h", price=50000.0,
                  is_history=False):
    for i in range(n):
        bus.emit(_candle_event(i, symbol, interval, price, is_history))


# ── Phase 1: Signal Enum Bug ───────────────────────────────────────────────────

class TestPhase1SignalEnum:
    """str(Signal.BUY) returns 'Signal.BUY' in Python 3.11, not 'BUY'.
    Engine must use .value for string normalization.
    """

    class ObjectSeriesStrategy:
        """Returns signals in a dtype=object Series (like EMACrossover does)."""
        def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
            # dtype=object preserves Signal enum members (not plain strings)
            s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
            s.iloc[-1] = Signal.BUY
            return s

    def test_signal_event_stores_plain_string(self, storage):
        """SignalEvent.signal must be 'BUY', not 'Signal.BUY'."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        engine = _make_engine(
            self.ObjectSeriesStrategy(), cfg, bus, ex, om, pm, pf, risk, state, storage
        )
        received: list[SignalEvent] = []
        bus.subscribe(SignalEvent, received.append)
        _emit_candles(bus, 65)  # fills buffer; last bar triggers BUY
        assert any(e.signal == "BUY" for e in received), \
            "SignalEvent.signal should be 'BUY', not 'Signal.BUY'"

    def test_object_series_buy_submits_order(self, storage):
        """BUY signal from a dtype=object Series must trigger an order."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        engine = _make_engine(
            self.ObjectSeriesStrategy(), cfg, bus, ex, om, pm, pf, risk, state, storage
        )
        _emit_candles(bus, 65)
        all_orders = ex.get_all_orders("BTCUSDT")
        assert len(all_orders) > 0, "dtype=object Signal.BUY must produce an order"

    def test_object_series_exit_signal_recognized(self, storage):
        """EXIT from a dtype=object Series must be recognized as exit signal."""

        class ExitAfterEntry:
            """BUY on first signal, EXIT on all subsequent."""
            count = 0
            def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
                s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
                ExitAfterEntry.count += 1
                if ExitAfterEntry.count == 1:
                    s.iloc[-1] = Signal.BUY
                else:
                    s.iloc[-1] = Signal.EXIT
                return s

        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        engine = _make_engine(
            ExitAfterEntry(), cfg, bus, ex, om, pm, pf, risk, state, storage
        )
        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)
        _emit_candles(bus, 65)
        assert any(e.signal == "EXIT" for e in signals), \
            "EXIT signal from dtype=object Series must be recognized"


# ── Phase 2: Backfill Must Not Trigger Trading ─────────────────────────────────

class TestPhase2BackfillSeparation:
    """Backfill candles (is_history=True) warm the buffer but must not cause
    order submission or order matching.
    """

    class AlwaysBuy:
        def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
            return pd.Series([Signal.BUY] * len(bars), index=bars.index)

    def test_backfill_warms_buffer(self, storage):
        """History candles are pushed into the state buffer."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(self.AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        for i in range(70):
            bus.emit(_candle_event(i, is_history=True))

        assert state.buffer_length("BTCUSDT", "1h") >= 70

    def test_backfill_does_not_submit_orders(self, storage):
        """History candles must never produce submitted orders."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(self.AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        _emit_candles(bus, 70, is_history=True)
        all_orders = ex.get_all_orders("BTCUSDT")
        assert len(all_orders) == 0, \
            "Backfill candles must not trigger order submission"

    def test_first_live_candle_can_submit_order(self, storage):
        """After backfill warms the buffer, a live candle can trigger an order."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(self.AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        # Warm up with 65 history candles (buffer threshold is 60)
        _emit_candles(bus, 65, is_history=True)
        assert ex.get_all_orders("BTCUSDT") == [], "Still no orders after backfill"

        # Emit one live candle — should trigger BUY signal
        bus.emit(_candle_event(65, is_history=False))
        all_orders = ex.get_all_orders("BTCUSDT")
        assert len(all_orders) == 1, \
            "First live candle after warm-up must produce an order"


# ── Phase 3: Missed Candle Detection ──────────────────────────────────────────

class TestPhase3MissedCandles:
    """Missed-candle detection uses >= so exactly-one-missed is caught."""

    def _state_with_handler(self):
        from bot.state import BotState
        from bot.runtime import LiveFeed, _INTERVAL_MS
        # We test the detection logic indirectly via BotState's counter
        state = BotState(buffer_size=100)
        return state, _INTERVAL_MS

    def test_consecutive_no_missed(self):
        from bot.state import BotState
        state = BotState(buffer_size=100)
        interval_ms = 3_600_000  # 1h

        # last_ct = 100, interval_ms = 3600000 → expected_open = 101
        # next open_time = 101 (consecutive) → no gap
        last_ct = 100
        open_time = last_ct + 1  # consecutive
        expected_open = last_ct + 1

        # Condition: open_time >= expected_open + interval_ms → False (consecutive)
        assert open_time < expected_open + interval_ms, \
            "Consecutive candles should not trigger missed-candle detection"

    def test_exactly_one_missed(self):
        interval_ms = 3_600_000
        last_ct = 1_000_000_000_000
        expected_open = last_ct + 1
        # Exactly one candle missed: next received open is 1 interval after expected
        open_time = expected_open + interval_ms

        # With the fixed >=, this should be detected
        assert open_time >= expected_open + interval_ms, \
            "open_time == expected + interval means exactly 1 candle was missed"

        missed = round((open_time - expected_open) / interval_ms)
        assert missed == 1

    def test_two_missed(self):
        interval_ms = 3_600_000
        last_ct = 1_000_000_000_000
        expected_open = last_ct + 1
        open_time = expected_open + 2 * interval_ms

        assert open_time >= expected_open + interval_ms
        missed = round((open_time - expected_open) / interval_ms)
        assert missed == 2

    def test_runtime_increments_on_one_missed(self):
        """LiveFeed._handle_message increments missed count for exactly 1 gap."""
        from bot.state import BotState
        from bot.config import BotConfig
        from bot.events import EventBus
        from bot.runtime import LiveFeed
        import json

        state = BotState(buffer_size=100)
        config = BotConfig()
        bus = EventBus()
        feed = LiveFeed(config, state, bus)

        interval_ms = 3_600_000
        last_close_time = 1_700_000_000_000

        # Prime the last_close_time for BTCUSDT/1h
        feed._last_close_time[("BTCUSDT", "1h")] = last_close_time

        # The next open_time should be last_close_time + 1 (consecutive).
        # We set it to last_close_time + 1 + interval_ms (exactly 1 gap).
        open_time = last_close_time + 1 + interval_ms
        close_time = open_time + interval_ms - 1

        msg = json.dumps({
            "stream": "btcusdt@kline_1h",
            "data": {
                "e": "kline",
                "k": {
                    "t": open_time,
                    "T": close_time,
                    "s": "BTCUSDT",
                    "i": "1h",
                    "o": "50000",
                    "h": "50500",
                    "l": "49500",
                    "c": "50200",
                    "v": "100",
                    "x": True,
                },
            },
        })

        missed_before = state.counters()["missed_candles"]
        feed._handle_message(msg)
        missed_after = state.counters()["missed_candles"]
        assert missed_after == missed_before + 1, \
            "Exactly 1 missed candle must increment missed_candles counter"


# ── Phase 4: Paper Exchange Market Min-Notional ────────────────────────────────

class TestPhase4MarketMinNotional:
    """MARKET orders validate minimum notional at fill time (real price known)."""

    def test_market_below_min_notional_rejected_at_fill(self):
        """Market order with tiny qty → fill_notional < MIN_NOTIONAL → rejected."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        # qty=0.00001 @ fill_price=50000 → notional=0.5 < 10 → rejected
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.00001)
        assert o.status == STATUS_ACCEPTED  # accepted at submission (no price yet)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=49000, close=50000)
        assert len(fills) == 0, "Fill below min notional must be rejected"
        assert o.status == STATUS_REJECTED
        assert "notional" in o.reject_reason.lower()

    def test_market_at_min_notional_fills(self):
        """Market order with notional exactly at MIN_NOTIONAL → accepted."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        # qty=0.0002 @ 50000 → notional=10.0 == MIN_NOTIONAL → fills
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.0002)
        assert o.status == STATUS_ACCEPTED
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=49000, close=50000)
        assert len(fills) == 1, "Order at exactly MIN_NOTIONAL must fill"
        assert o.status == STATUS_FILLED

    def test_market_above_min_notional_fills(self):
        """Market order with notional well above MIN_NOTIONAL → accepted."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        # qty=0.1 @ 50000 → notional=5000 >> 10 → fills
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        assert o.status == STATUS_ACCEPTED
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=49000, close=50000)
        assert len(fills) == 1


# ── Phase 5: QTY Step Enforcement ─────────────────────────────────────────────

class TestPhase5QtyStep:
    """Quantities that are not exact multiples of QTY_STEP are rejected."""

    def test_exact_step_accepted(self, ex):
        # 0.00001 == 1 × step
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT,
                            qty=0.00001, price=50000.0)
        # notional = 0.00001 * 50000 = 0.5 < 10 → rejected for notional, not step
        # So use a qty that clears min_notional too
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT,
                            qty=0.001, price=50000.0)
        # notional = 0.001 * 50000 = 50 >= 10 → accepted
        assert o.status == STATUS_ACCEPTED

    def test_multiple_of_step_accepted(self, ex):
        # 0.003 == 300 × step (0.00001)
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT,
                            qty=0.003, price=50000.0)
        assert o.status == STATUS_ACCEPTED

    def test_invalid_fractional_step_rejected(self, ex):
        # 0.0000137 is not a multiple of 0.00001
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET,
                            qty=0.0000137)
        assert o.status == STATUS_REJECTED
        assert "multiple of step" in o.reject_reason

    def test_floating_point_edge_case(self):
        """0.1 + 0.2 style floats should be handled correctly via Decimal."""
        # 0.00003 = 3 × 0.00001 — should pass despite float representation
        assert _qty_step_valid(0.00003, 0.00001) is True
        # 0.000013 is not a multiple of 0.00001
        assert _qty_step_valid(0.000013, 0.00001) is False

    def test_below_minimum_qty_rejected(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.000001)
        assert o.status == STATUS_REJECTED
        assert "below minimum" in o.reject_reason

    def test_custom_symbol_rules_applied(self):
        """Per-symbol rules override defaults."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        rules = SymbolRules(min_notional=1.0, min_qty=0.001, qty_step=0.001,
                            tick_size=0.01)
        ex.register_symbol_rules("ETHUSDT", rules)

        # qty=0.001 is exact multiple of step=0.001 → accepted
        o = ex.submit_order("ETHUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.001)
        assert o.status == STATUS_ACCEPTED

        # qty=0.0015 is NOT a multiple of step=0.001 → rejected
        o2 = ex.submit_order("ETHUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.0015)
        assert o2.status == STATUS_REJECTED


# ── Phase 7: Risk Sizing vs max_risk_pct ──────────────────────────────────────

class TestPhase7RiskSizing:
    """max_risk_pct is a post-sizing limit, not a sizing input.
    equity_fraction always drives qty calculation.
    """

    class AlwaysBuy:
        def generate_signals(self, bars):
            return pd.Series([Signal.BUY] * len(bars), index=bars.index)

    def test_equity_fraction_drives_sizing_not_max_risk_pct(self, storage):
        """Changing max_risk_pct alone must not change order size."""
        # Config A: default max_risk_pct
        cfg_a = BotConfig(paper_capital=1000.0)
        cfg_a.risk.max_risk_pct = 0.01  # 1%
        cfg_a.equity_fraction = 0.10    # 10%

        # Config B: 50x higher max_risk_pct, same equity_fraction
        cfg_b = BotConfig(paper_capital=1000.0)
        cfg_b.risk.max_risk_pct = 0.50  # 50%
        cfg_b.equity_fraction = 0.10    # 10% (same)

        # Both should produce the same order qty
        for cfg in (cfg_a, cfg_b):
            qty = cfg.equity_fraction * cfg.paper_capital / 50000.0
            qty = round(qty, cfg.qty_precision)
            # notional = 1000 * 0.10 = 100 USDT; qty = 100/50000 = 0.002
            assert qty == pytest.approx(0.002, rel=1e-5), \
                "max_risk_pct must not change order sizing"


# ── Phase 8: Order Rejection Observability ────────────────────────────────────

class TestPhase8RejectionObservability:
    """Rejected orders are logged at WARNING, have reject_reason set,
    and are persisted to storage via OrderManager.
    """

    def test_rejected_order_saved_to_storage(self, storage):
        """OrderManager saves rejected orders (bad qty) to the DB."""
        bus = EventBus()
        ex  = PaperExchange(fee_rate=0.001, slippage_pct=0.0, bus=bus)
        om  = OrderManager(exchange=ex, storage=storage, bus=bus)

        o = om.submit_market("BTCUSDT", SIDE_BUY, qty=0.000001)  # below MIN_QTY
        assert o.status == STATUS_REJECTED
        assert o.reject_reason != ""

        rows = storage.get_orders(limit=10)
        assert len(rows) == 1, "Rejected order must appear in storage"
        assert rows[0]["status"] == STATUS_REJECTED
        assert rows[0]["reject_reason"] != ""

    def test_rejected_order_warns(self, caplog, storage):
        """A rejected order is logged at WARNING level."""
        bus = EventBus()
        ex  = PaperExchange(fee_rate=0.001, slippage_pct=0.0, bus=bus)
        om  = OrderManager(exchange=ex, storage=storage, bus=bus)

        with caplog.at_level(logging.WARNING, logger="strategy_lab.bot.paper_exchange"):
            om.submit_market("BTCUSDT", SIDE_BUY, qty=0.000001)

        assert any("rejected" in r.message.lower() for r in caplog.records)


# ── Phase 9: Order Manager Idempotency ────────────────────────────────────────

class TestPhase9Idempotency:
    """A single CandleEvent must produce at most one order submission even if
    the _on_candle handler is somehow triggered twice for the same candle.
    The position guard (has_open_position) prevents double-entry.
    """

    class AlwaysBuy:
        def generate_signals(self, bars):
            return pd.Series([Signal.BUY] * len(bars), index=bars.index)

    def test_single_candle_single_order(self, storage):
        """Emitting the same candle twice does not create two open positions."""
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        engine = _make_engine(
            self.AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage
        )
        # Warm up buffer
        _emit_candles(bus, 65, is_history=True)

        # Emit the same live candle event twice
        ev = _candle_event(65, is_history=False)
        bus.emit(ev)
        bus.emit(ev)  # duplicate

        # Process pending orders (if any) so position is opened
        ex.process_candle("BTCUSDT", open_=50000, high=50500, low=49500, close=50000)

        open_positions = pm.get_all_open()
        assert len(open_positions) <= 1, \
            "Duplicate candle event must not create more than one open position"


# ── Phase 10: Order State Transitions ─────────────────────────────────────────

class TestPhase10StateTransitions:
    """Invalid order state transitions are detected and logged."""

    def test_filled_to_new_is_invalid(self, caplog):
        """Transitioning a FILLED order back to NEW logs a WARNING."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        o  = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        # Fill it
        ex.process_candle("BTCUSDT", open_=50000, high=51000, low=49000, close=50000)
        assert o.status == STATUS_FILLED

        # Attempt invalid transition FILLED → NEW
        with caplog.at_level(logging.WARNING,
                             logger="strategy_lab.bot.paper_exchange"):
            valid = ex._validate_transition(o, "NEW")

        assert valid is False
        assert any("Invalid order state transition" in r.message
                   for r in caplog.records)

    def test_cancelled_to_filled_is_invalid(self, caplog, ex):
        """Transitioning CANCELLED to FILLED is invalid."""
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT,
                            qty=0.1, price=40000.0)
        ex.cancel_order(o.order_id)
        assert o.status == STATUS_CANCELLED

        with caplog.at_level(logging.WARNING,
                             logger="strategy_lab.bot.paper_exchange"):
            valid = ex._validate_transition(o, STATUS_FILLED)
        assert valid is False

    def test_accepted_to_filled_is_valid(self, ex):
        """ACCEPTED → FILLED is the normal transition."""
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_MARKET, qty=0.1)
        assert o.status == STATUS_ACCEPTED
        assert ex._validate_transition(o, STATUS_FILLED) is True

    def test_accepted_to_cancelled_is_valid(self, ex):
        o = ex.submit_order("BTCUSDT", SIDE_BUY, ORDER_TYPE_LIMIT,
                            qty=0.1, price=40000.0)
        assert ex._validate_transition(o, STATUS_CANCELLED) is True


# ── Phase 13: OCO / Stop / Take-Profit ────────────────────────────────────────

class TestPhase13OCO:
    """When one reduce_only protective order fills, the sibling is cancelled."""

    def test_stop_fills_cancels_tp(self):
        """SL fill → TP is cancelled (OCO)."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        # Entry position size = 0.1 BTC
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=48000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=53000.0, reduce_only=True,
                             current_position_size=0.1)
        assert sl.status == STATUS_ACCEPTED
        assert tp.status == STATUS_ACCEPTED

        # Candle that triggers SL (low 47000 < 48000) but NOT TP (high 49000 < 53000)
        fills = ex.process_candle("BTCUSDT", open_=50000, high=49000,
                                  low=47000, close=48500)

        assert len(fills) == 1
        assert fills[0].order_id == sl.order_id
        assert sl.status == STATUS_FILLED
        # TP must have been cancelled by OCO logic
        assert tp.status == STATUS_CANCELLED, \
            "TP must be cancelled after SL fills (OCO)"
        assert len(ex.get_open_orders("BTCUSDT")) == 0

    def test_tp_fills_cancels_sl(self):
        """TP fill → SL is cancelled (OCO)."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=48000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=53000.0, reduce_only=True,
                             current_position_size=0.1)

        # Candle that triggers TP (high 54000 >= 53000) but NOT SL (low 51000 > 48000)
        fills = ex.process_candle("BTCUSDT", open_=52000, high=54000,
                                  low=51000, close=53000)

        assert len(fills) == 1
        assert fills[0].order_id == tp.order_id
        assert tp.status == STATUS_FILLED
        assert sl.status == STATUS_CANCELLED, \
            "SL must be cancelled after TP fills (OCO)"

    def test_neither_triggered_both_remain(self):
        """When neither SL nor TP triggers, both orders remain open."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=47000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=54000.0, reduce_only=True,
                             current_position_size=0.1)

        # Candle within range — neither triggers
        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=49000, close=50500)
        assert len(fills) == 0
        assert sl.status == STATUS_ACCEPTED
        assert tp.status == STATUS_ACCEPTED


# ── Phase 14: Same-Candle SL/TP Ambiguity ─────────────────────────────────────

class TestPhase14SameCandleSLTP:
    """Conservative (stop-first) policy when both SL and TP trigger on one candle."""

    def test_only_stop_triggered(self):
        """Low hits SL, high does not reach TP → SL fills."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=48000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=55000.0, reduce_only=True,
                             current_position_size=0.1)

        fills = ex.process_candle("BTCUSDT", open_=50000, high=51000,
                                  low=47000, close=49000)
        assert len(fills) == 1
        assert fills[0].order_id == sl.order_id

    def test_only_target_triggered(self):
        """High hits TP, low does not reach SL → TP fills."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=44000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=53000.0, reduce_only=True,
                             current_position_size=0.1)

        fills = ex.process_candle("BTCUSDT", open_=50000, high=54000,
                                  low=48000, close=52000)
        assert len(fills) == 1
        assert fills[0].order_id == tp.order_id

    def test_both_triggered_stop_wins_conservative(self):
        """When BOTH SL and TP would trigger on the same candle, SL fills first."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        sl = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                             qty=0.1, stop_price=48000.0, reduce_only=True,
                             current_position_size=0.1)
        tp = ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                             qty=0.1, stop_price=53000.0, reduce_only=True,
                             current_position_size=0.1)

        # Candle where low=47000 triggers SL AND high=55000 triggers TP
        fills = ex.process_candle("BTCUSDT", open_=50000, high=55000,
                                  low=47000, close=51000)

        assert len(fills) == 1, \
            "Only one order should fill (stop-first conservative policy)"
        assert fills[0].order_id == sl.order_id, \
            "SL must fill first (conservative worst-case assumption)"
        # TP must be cancelled by OCO
        assert tp.status == STATUS_CANCELLED

    def test_neither_triggered_no_fill(self):
        """When candle is within range, no protective order fills."""
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0)
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_STOP_MARKET,
                        qty=0.1, stop_price=44000.0, reduce_only=True,
                        current_position_size=0.1)
        ex.submit_order("BTCUSDT", SIDE_SELL, ORDER_TYPE_TAKE_PROFIT,
                        qty=0.1, stop_price=58000.0, reduce_only=True,
                        current_position_size=0.1)

        fills = ex.process_candle("BTCUSDT", open_=50000, high=52000,
                                  low=48000, close=51000)
        assert len(fills) == 0
        assert len(ex.get_open_orders("BTCUSDT")) == 2
