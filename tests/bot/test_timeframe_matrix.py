"""Phase 18 — Automated timeframe matrix tests.

Parameterised over every supported interval to verify:
  - interval_to_ms conversion correctness
  - gap detection threshold
  - BotEngine processes candles for each interval
  - backfill candles carry is_history=True
  - signal pipeline works end-to-end

No real API calls — purely synthetic data.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from bot.config import BotConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, EventBus, SignalEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import PaperExchange
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskEngine
from bot.runtime import LiveFeed, _INTERVAL_MS
from bot.state import BotState
from bot.storage import BotStorage
from engine.strategy import Signal

# ── Canonical supported interval list ─────────────────────────────────────────
# This is the authoritative list used across all parametrised tests.
# It mirrors the bars_per_year table in jobs/backtest_job.py and
# the _INTERVAL_MS mapping in bot/runtime.py (after the Phase 18 fix).
SUPPORTED_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w",
]

# Expected millisecond durations for each interval (ground truth).
_EXPECTED_MS: dict[str, int] = {
    "1m":  60_000,
    "3m":  3 * 60_000,
    "5m":  5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h":  60 * 60_000,
    "2h":  2 * 60 * 60_000,
    "4h":  4 * 60 * 60_000,
    "6h":  6 * 60 * 60_000,
    "8h":  8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d":  24 * 60 * 60_000,
    "3d":  3 * 24 * 60 * 60_000,
    "1w":  7 * 24 * 60 * 60_000,
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


def _make_components(storage, paper_capital: float = 1000.0):
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


def _build_candle_events(
    n: int,
    interval: str,
    symbol: str = "BTCUSDT",
    price: float = 50_000.0,
    is_history: bool = False,
) -> list[CandleEvent]:
    """Build *n* synthetic closed candle events for *interval*."""
    interval_ms = _EXPECTED_MS[interval]
    base_ms = 1_700_000_000_000
    events = []
    for i in range(n):
        open_ms  = base_ms + i * interval_ms
        close_ms = open_ms + interval_ms - 1
        events.append(CandleEvent(
            symbol=symbol,
            interval=interval,
            open_time=open_ms,
            open=price,
            high=price * 1.01,
            low=price * 0.99,
            close=price,
            volume=100.0,
            close_time=close_ms,
            is_history=is_history,
        ))
    return events


class AlwaysBuy:
    """Minimal strategy that emits BUY on every bar."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.BUY] * len(bars), index=bars.index)


class AlwaysHold:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.HOLD] * len(bars), index=bars.index)


# ── Phase 17/18 Tests ─────────────────────────────────────────────────────────

class TestIntervalToMs:
    """Verify _INTERVAL_MS carries the correct value for every supported interval."""

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_interval_in_map(self, interval):
        """Every supported interval must have an entry in _INTERVAL_MS."""
        assert interval in _INTERVAL_MS, (
            f"interval {interval!r} is missing from _INTERVAL_MS; "
            "missed-candle detection will be silently disabled for it"
        )

    @pytest.mark.parametrize("interval,expected_ms", _EXPECTED_MS.items())
    def test_interval_ms_correct_value(self, interval, expected_ms):
        """_INTERVAL_MS must map each interval to the correct ms duration."""
        assert _INTERVAL_MS[interval] == expected_ms, (
            f"_INTERVAL_MS[{interval!r}] = {_INTERVAL_MS[interval]} "
            f"but expected {expected_ms}"
        )

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_interval_ms_positive(self, interval):
        """All interval durations must be positive."""
        assert _INTERVAL_MS[interval] > 0


class TestGapDetection:
    """Verify gap detection threshold for every interval."""

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_consecutive_candles_no_gap(self, interval):
        """Consecutive candles (close_time_n + 1 == open_time_{n+1}) → no gap."""
        interval_ms = _INTERVAL_MS[interval]
        # last_ct = some ms timestamp
        last_ct = 1_700_000_000_000
        # next open is exactly consecutive (no skipped candles)
        open_time = last_ct + 1
        expected_open = last_ct + 1

        # Condition for a gap: open_time >= expected_open + interval_ms
        assert open_time < expected_open + interval_ms, (
            f"Consecutive candles must NOT trigger gap detection for {interval}"
        )

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_exactly_one_missed_detected(self, interval):
        """When exactly 1 candle is missed, the >= threshold fires."""
        interval_ms = _INTERVAL_MS[interval]
        last_ct = 1_700_000_000_000
        expected_open = last_ct + 1
        # Exactly one candle skipped: open_time is 1 interval beyond expected
        open_time = expected_open + interval_ms

        assert open_time >= expected_open + interval_ms
        missed = round((open_time - expected_open) / interval_ms)
        assert missed == 1, f"Should detect exactly 1 missed candle for {interval}"

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_two_missed_detected(self, interval):
        """Two skipped candles produce missed_count == 2."""
        interval_ms = _INTERVAL_MS[interval]
        last_ct = 1_700_000_000_000
        expected_open = last_ct + 1
        open_time = expected_open + 2 * interval_ms

        assert open_time >= expected_open + interval_ms
        missed = round((open_time - expected_open) / interval_ms)
        assert missed == 2

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_live_feed_increments_counter_on_one_gap(self, interval):
        """LiveFeed._handle_message increments missed_candles for a 1-candle gap."""
        state  = BotState(buffer_size=100)
        config = BotConfig()
        bus    = EventBus()
        feed   = LiveFeed(config, state, bus)

        interval_ms   = _INTERVAL_MS[interval]
        last_close_ms = 1_700_000_000_000

        # Prime last seen close_time for this (symbol, interval) pair.
        feed._last_close_time[("BTCUSDT", interval)] = last_close_ms

        # Construct the next open_time with exactly one skipped candle.
        open_time  = (last_close_ms + 1) + interval_ms
        close_time = open_time + interval_ms - 1

        msg = json.dumps({
            "stream": f"btcusdt@kline_{interval}",
            "data": {
                "e": "kline",
                "k": {
                    "t": open_time,
                    "T": close_time,
                    "s": "BTCUSDT",
                    "i": interval,
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
        missed_after  = state.counters()["missed_candles"]

        assert missed_after == missed_before + 1, (
            f"Exactly 1 missed candle must increment counter for interval {interval!r}"
        )


class TestEngineProcessesCandles:
    """BotEngine correctly ingests candles for every supported interval."""

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_candles_pushed_to_buffer(self, tmp_path, interval):
        """State buffer is populated for each interval."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysHold(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        events = _build_candle_events(10, interval)
        for ev in events:
            bus.emit(ev)

        assert state.buffer_length("BTCUSDT", interval) == 10

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_history_candles_do_not_trigger_orders(self, tmp_path, interval):
        """History (backfill) candles must never produce orders."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        events = _build_candle_events(70, interval, is_history=True)
        for ev in events:
            bus.emit(ev)

        assert ex.get_all_orders("BTCUSDT") == [], (
            f"History candles must not submit orders for interval {interval!r}"
        )

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_live_candle_after_warmup_triggers_order(self, tmp_path, interval):
        """After buffer warm-up, the first live candle can trigger an order."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        # Warm up buffer with history candles (above min_signal_bars=60)
        history = _build_candle_events(65, interval, is_history=True)
        for ev in history:
            bus.emit(ev)
        assert ex.get_all_orders("BTCUSDT") == [], "No orders from history"

        # One live candle should trigger BUY → order submitted
        live = _build_candle_events(1, interval, is_history=False)
        bus.emit(live[0])
        assert len(ex.get_all_orders("BTCUSDT")) == 1, (
            f"First live candle must produce an order for interval {interval!r}"
        )


class TestBackfillIsHistory:
    """Candles created with is_history=True must never trigger orders."""

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_is_history_flag_respected(self, tmp_path, interval):
        """CandleEvents with is_history=True warm the buffer only."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        events = _build_candle_events(100, interval, is_history=True)
        for ev in events:
            bus.emit(ev)

        # Buffer must be warmed
        assert state.buffer_length("BTCUSDT", interval) == 100
        # But no orders
        assert ex.get_all_orders("BTCUSDT") == []


class TestSignalPipeline:
    """Signal pipeline works end-to-end for every interval."""

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_signal_event_emitted_after_warmup(self, tmp_path, interval):
        """SignalEvent is emitted for the first live candle after warm-up."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        # Warm buffer
        for ev in _build_candle_events(65, interval, is_history=True):
            bus.emit(ev)
        assert signals == [], "No signals during warm-up"

        # Live candle
        bus.emit(_build_candle_events(1, interval, is_history=False)[0])
        assert len(signals) == 1
        assert signals[0].signal == "BUY", (
            f"Expected BUY signal for interval {interval!r}"
        )

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_hold_strategy_no_orders(self, tmp_path, interval):
        """HOLD strategy must never produce orders for any interval."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysHold(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        events = _build_candle_events(70, interval, is_history=False)
        for ev in events:
            bus.emit(ev)

        assert ex.get_all_orders("BTCUSDT") == [], (
            f"HOLD strategy must not submit orders for interval {interval!r}"
        )

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_signal_string_is_plain_value(self, tmp_path, interval):
        """SignalEvent.signal must be a plain string ('BUY'), not 'Signal.BUY'."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysBuy(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, signals.append)

        for ev in _build_candle_events(65, interval, is_history=True):
            bus.emit(ev)
        bus.emit(_build_candle_events(1, interval, is_history=False)[0])

        assert signals, f"No signal emitted for interval {interval!r}"
        sig = signals[-1].signal
        assert sig in ("BUY", "SELL", "EXIT", "HOLD"), (
            f"SignalEvent.signal must be a plain value string, got {sig!r}"
        )
        assert "Signal." not in sig, (
            f"Signal enum prefix leaked into SignalEvent.signal: {sig!r}"
        )


class TestMultiTimeframeIsolation:
    """Buffers keyed by (symbol, interval) — no cross-contamination."""

    def test_two_intervals_independent_buffers(self, tmp_path):
        """1m and 1h buffers for the same symbol are independent."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysHold(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        for ev in _build_candle_events(10, "1m"):
            bus.emit(ev)
        for ev in _build_candle_events(5, "1h"):
            bus.emit(ev)

        assert state.buffer_length("BTCUSDT", "1m") == 10
        assert state.buffer_length("BTCUSDT", "1h") == 5

    def test_different_symbols_independent_buffers(self, tmp_path):
        """BTCUSDT and ETHUSDT buffers for the same interval are independent."""
        storage = _make_storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, state = _make_components(storage)
        _make_engine(AlwaysHold(), cfg, bus, ex, om, pm, pf, risk, state, storage)

        for ev in _build_candle_events(7, "1h", symbol="BTCUSDT"):
            bus.emit(ev)
        for ev in _build_candle_events(3, "1h", symbol="ETHUSDT"):
            bus.emit(ev)

        assert state.buffer_length("BTCUSDT", "1h") == 7
        assert state.buffer_length("ETHUSDT", "1h") == 3


class TestBufferCapEnforced:
    """Ring buffer must not exceed buffer_size."""

    @pytest.mark.parametrize("interval", ["1m", "1h", "1d", "1w"])
    def test_buffer_does_not_exceed_cap(self, tmp_path, interval):
        """Pushing more candles than buffer_size must not grow the buffer beyond the cap."""
        buffer_size = 50
        storage = _make_storage(tmp_path)
        state = BotState(buffer_size=buffer_size)

        # Push 2× the cap
        for ev in _build_candle_events(buffer_size * 2, interval, is_history=True):
            from bot.state import CandleRow
            state.push_candle(CandleRow(
                symbol=ev.symbol,
                interval=ev.interval,
                open_time=ev.open_time,
                open=ev.open,
                high=ev.high,
                low=ev.low,
                close=ev.close,
                volume=ev.volume,
                close_time=ev.close_time,
            ))

        assert state.buffer_length("BTCUSDT", interval) == buffer_size, (
            f"Buffer must be capped at buffer_size={buffer_size} "
            f"for interval {interval!r}"
        )
