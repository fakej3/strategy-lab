"""Phase 2B parallel backfill — 18 deterministic scenarios + 2B-9 benchmark.

Scenario inventory:
  1  – 3×3 = 9 pairs all backfilled concurrently
  2  – 10×3 = 30 pairs all backfilled concurrently
  3  – one pair returns 5xx; all other pairs succeed
  4  – multiple pairs return 5xx; remaining pairs succeed
  5  – one pair times out (slow endpoint); remaining succeed
  6  – HTTP 429 treated as permanent — no retry
  7  – malformed JSON from one pair isolated; remaining succeed
  8  – re-backfill is idempotent (no duplicate events)
  9  – three reconnect cycles leave buffer clean
  10 – get_buffer_df() has unique open_times after parallel backfill
  11 – get_buffer_df() is sorted ascending by open_time after backfill
  12 – all CandleEvents from backfill carry is_history=True
  13 – live WS candle processed normally after backfill
  14 – asyncio.Semaphore bounds peak server concurrency
  15 – one aiohttp.ClientSession created per _backfill_all() call
  16 – ClientSession is closed after successful batch
  17 – ClientSession is closed even when all pairs fail
  18 – asyncio.CancelledError from task.cancel() propagates cleanly

  Benchmark – sequential (concurrency=1) vs parallel (concurrency=8)
              at 9 / 30 / 90 / 150 streams, 5 ms controlled delay per request.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from contextlib import asynccontextmanager
from unittest.mock import patch

import aiohttp
import aiohttp.web
import pytest

from bot.config import BotConfig, FeedConfig
from bot.events import CandleEvent, ErrorEvent, EventBus, ReconnectEvent
from bot.runtime import LiveFeed
from bot.state import BotState, CandleRow


# ── Constants ─────────────────────────────────────────────────────────────────

BASE_T = 1_700_000_000_000   # ms — 2023, unambiguously in the past
IV_MS  = 60_000              # 1-minute candle width in ms


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _row(i: int) -> list:
    """Minimal past Binance REST kline row at slot i."""
    t0 = BASE_T + i * IV_MS
    return [t0, "50000", "51000", "49000", "50500", "100", t0 + IV_MS - 1, "0", 0, "0", "0", "0"]


def _rows(n: int) -> list[list]:
    return [_row(i) for i in range(n)]


def _kline_ws_msg(symbol: str, interval: str, idx: int, is_closed: bool = True) -> str:
    """Build a Binance combined-stream kline message (wire format)."""
    t0 = BASE_T + idx * IV_MS
    return json.dumps({
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "e": "kline",
            "k": {
                "t": t0, "T": t0 + IV_MS - 1,
                "s": symbol.upper(), "i": interval,
                "o": "50000", "h": "51000", "l": "49000", "c": "50500", "v": "100",
                "x": is_closed,
            },
        },
    })


def _make_feed(
    symbols: list[str],
    intervals: list[str],
    rest_url: str,
    *,
    backfill_bars: int = 5,
    concurrency: int = 8,
    max_retries: int = 1,     # default: no retries (fast tests)
    retry_delay: float = 0.01,
    timeout_s: int = 5,
) -> tuple[LiveFeed, BotState, EventBus]:
    cfg = BotConfig(
        paper_capital=1000.0,
        feed=FeedConfig(
            symbols=symbols,
            intervals=intervals,
            ws_base_url="ws://127.0.0.1:1/stream",  # unused — backfill tests call _backfill_all() directly
            rest_base_url=rest_url,
            backfill_bars=backfill_bars,
            reconnect_delay_s=0.05,
            max_reconnect_delay_s=0.1,
            heartbeat_interval_s=30,
            ping_timeout_s=10,
            ws_open_timeout_s=3,
            rest_timeout_s=timeout_s,
            backfill_concurrency=concurrency,
            backfill_max_retries=max_retries,
            backfill_retry_delay_s=retry_delay,
        ),
    )
    state = BotState(buffer_size=500)
    bus   = EventBus()
    feed  = LiveFeed(config=cfg, state=state, bus=bus)
    # Wire bus → state so buffer_length() reflects emitted CandleEvents.
    # Mirrors what BotEngine._on_candle() does.
    bus.subscribe(CandleEvent, lambda ev: state.push_candle(CandleRow(
        symbol=ev.symbol, interval=ev.interval, open_time=ev.open_time,
        open=ev.open, high=ev.high, low=ev.low, close=ev.close,
        volume=ev.volume, close_time=ev.close_time,
    )))
    return feed, state, bus


# ── Mock REST server ──────────────────────────────────────────────────────────

class MockRestServer:
    """Lightweight aiohttp REST mock for Binance /klines.

    Supports per-pair response configuration, uniform delay, fault injection,
    and concurrent-request tracking.  All counter mutations are synchronous
    between await points, so no additional lock is needed.
    """

    def __init__(self) -> None:
        self._klines:       dict[tuple[str, str], list]  = {}
        self._errors:       dict[tuple[str, str], int]   = {}   # → HTTP status
        self._delays:       dict[tuple[str, str], float] = {}   # → seconds
        self._bad_json:     set[tuple[str, str]]          = set()
        self._default_rows: list                          = _rows(5)
        self._default_delay: float                        = 0.0
        self._runner: aiohttp.web.AppRunner | None        = None
        self.rest_url        = ""
        self.request_count   = 0
        self.peak_concurrent = 0
        self._active         = 0

    # ── Setup helpers ──────────────────────────────────────────────────────────

    def set_klines(self, symbol: str, interval: str, rows: list) -> None:
        self._klines[(symbol.upper(), interval)] = rows

    def set_error(self, symbol: str, interval: str, status: int) -> None:
        self._errors[(symbol.upper(), interval)] = status

    def set_delay(self, symbol: str, interval: str, delay_s: float) -> None:
        self._delays[(symbol.upper(), interval)] = delay_s

    def set_bad_json(self, symbol: str, interval: str) -> None:
        self._bad_json.add((symbol.upper(), interval))

    def set_uniform_delay(self, delay_s: float) -> None:
        """Apply the same delay to every request (benchmark helper)."""
        self._default_delay = delay_s

    def set_default_rows(self, rows: list) -> None:
        self._default_rows = rows

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        port = _free_port()
        app  = aiohttp.web.Application()
        app.router.add_get("/api/v3/klines", self._handle)
        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        await aiohttp.web.TCPSite(self._runner, "127.0.0.1", port).start()
        self.rest_url = f"http://127.0.0.1:{port}/api/v3"

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # ── Request handler ───────────────────────────────────────────────────────

    async def _handle(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        symbol   = request.query.get("symbol", "").upper()
        interval = request.query.get("interval", "")
        limit    = int(request.query.get("limit", "300"))
        key      = (symbol, interval)

        # Concurrency tracking — synchronous between awaits (no lock needed).
        self.request_count += 1
        self._active += 1
        if self._active > self.peak_concurrent:
            self.peak_concurrent = self._active

        try:
            delay = self._delays.get(key, self._default_delay)
            if delay > 0:
                await asyncio.sleep(delay)

            status = self._errors.get(key)
            if status is not None:
                return aiohttp.web.Response(status=status)

            if key in self._bad_json:
                return aiohttp.web.Response(
                    text="not-json-{{}}", content_type="application/json"
                )

            rows = self._klines.get(key, self._default_rows)
            return aiohttp.web.json_response(rows[-limit:] if limit > 0 else [])
        finally:
            self._active -= 1


@asynccontextmanager
async def _server():
    """Async context manager: start server, yield, stop."""
    srv = MockRestServer()
    await srv.start()
    try:
        yield srv
    finally:
        await srv.stop()


# ── Scenario 1 & 2: Concurrent backfill ──────────────────────────────────────

class TestConcurrentBackfill:
    """Scenarios 1 & 2 — all pairs backfilled concurrently."""

    @pytest.mark.anyio
    async def test_3x3_all_buffers_populated(self):
        """Scenario 1 — 9 pairs, all buffers receive candles."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m", "15m"]
        async with _server() as srv:
            for sym in symbols:
                for iv in intervals:
                    srv.set_klines(sym, iv, _rows(5))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            await feed._backfill_all()

        assert srv.request_count == 9
        for sym in symbols:
            for iv in intervals:
                assert state.buffer_length(sym, iv) == 5, (
                    f"Expected 5 candles for {sym}/{iv}, got {state.buffer_length(sym, iv)}"
                )

    @pytest.mark.anyio
    async def test_10x3_all_buffers_populated(self):
        """Scenario 2 — 30 pairs, all buffers receive candles."""
        symbols   = [f"SYM{i:02d}USDT" for i in range(10)]
        intervals = ["1m", "5m", "15m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            await feed._backfill_all()

        assert srv.request_count == 30
        for sym in symbols:
            for iv in intervals:
                assert state.buffer_length(sym, iv) == 3, (
                    f"Expected 3 candles for {sym}/{iv}"
                )


# ── Scenarios 3–5, 7: Failure isolation ──────────────────────────────────────

class TestFailureIsolation:
    """Scenarios 3, 4, 5, 7 — one or more pair failures never abort the batch."""

    @pytest.mark.anyio
    async def test_one_5xx_failure_isolated(self):
        """Scenario 3 — one 500 error, eight other pairs succeed."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m", "15m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(4))
            srv.set_error("ETHUSDT", "5m", 500)   # one bad pair

            errors: list[ErrorEvent] = []
            reconnects: list[ReconnectEvent] = []
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            bus.subscribe(ErrorEvent, errors.append)
            bus.subscribe(ReconnectEvent, reconnects.append)

            await feed._backfill_all()

        assert len(errors) == 1
        assert "ETHUSDT/5m" in errors[0].message
        assert len(reconnects) == 8, "8 of 9 pairs should emit ReconnectEvent"
        # All other buffers are populated
        assert state.buffer_length("ETHUSDT", "5m") == 0
        assert state.buffer_length("BTCUSDT", "1m") == 4
        assert state.buffer_length("SOLUSDT", "15m") == 4

    @pytest.mark.anyio
    async def test_multiple_5xx_failures_isolated(self):
        """Scenario 4 — three bad pairs, remaining six succeed."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m", "15m"]
        bad_pairs = [("BTCUSDT", "1m"), ("ETHUSDT", "5m"), ("SOLUSDT", "15m")]
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            for sym, iv in bad_pairs:
                srv.set_error(sym, iv, 502)

            errors: list[ErrorEvent] = []
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            bus.subscribe(ErrorEvent, errors.append)
            await feed._backfill_all()

        assert len(errors) == 3
        # Six good pairs succeed
        for sym in symbols:
            for iv in intervals:
                if (sym, iv) in bad_pairs:
                    assert state.buffer_length(sym, iv) == 0
                else:
                    assert state.buffer_length(sym, iv) == 3

    @pytest.mark.anyio
    async def test_timeout_failure_isolated(self):
        """Scenario 5 — one pair hangs past timeout; all others complete normally."""
        symbols   = ["BTCUSDT", "ETHUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            srv.set_delay("ETHUSDT", "5m", 10.0)  # longer than REST timeout

            errors: list[ErrorEvent] = []
            feed, state, bus = _make_feed(
                symbols, intervals, srv.rest_url,
                timeout_s=1,  # 1-second timeout — triggers on the delayed pair
            )
            bus.subscribe(ErrorEvent, errors.append)
            await feed._backfill_all()

        assert len(errors) == 1, "Timeout pair must emit exactly one ErrorEvent"
        assert state.buffer_length("ETHUSDT", "5m") == 0
        assert state.buffer_length("BTCUSDT", "1m") == 3

    @pytest.mark.anyio
    async def test_malformed_json_isolated(self):
        """Scenario 7 — invalid JSON from one pair; remaining pairs succeed."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(4))
            srv.set_bad_json("ETHUSDT", "1m")

            errors: list[ErrorEvent] = []
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            bus.subscribe(ErrorEvent, errors.append)
            await feed._backfill_all()

        assert len(errors) == 1
        assert state.buffer_length("ETHUSDT", "1m") == 0
        assert state.buffer_length("BTCUSDT", "1m") == 4
        assert state.buffer_length("SOLUSDT", "1m") == 4


# ── Scenario 6: Retry policy ──────────────────────────────────────────────────

class TestRetryPolicy:
    """Scenario 6 — HTTP 429 is permanent; no retry issued."""

    @pytest.mark.anyio
    async def test_429_not_retried(self):
        """429 must not trigger any retry regardless of max_retries."""
        async with _server() as srv:
            srv.set_error("BTCUSDT", "1m", 429)

            errors: list[ErrorEvent] = []
            feed, state, bus = _make_feed(
                ["BTCUSDT"], ["1m"], srv.rest_url,
                max_retries=3,   # retries configured but must NOT fire for 429
            )
            bus.subscribe(ErrorEvent, errors.append)
            await feed._backfill_all()

        assert srv.request_count == 1, (
            f"429 must not be retried — expected 1 request, got {srv.request_count}"
        )
        assert len(errors) == 1


# ── Scenarios 8–11: Reconnect idempotency & buffer correctness ────────────────

class TestReconnectIdempotency:
    """Scenarios 8–11 — repeated backfills leave buffers clean."""

    @pytest.mark.anyio
    async def test_re_backfill_idempotent(self):
        """Scenario 8 — second backfill does not double-count candles."""
        symbols   = ["BTCUSDT"]
        intervals = ["1m"]
        async with _server() as srv:
            srv.set_klines("BTCUSDT", "1m", _rows(5))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            await feed._backfill_all()
            await feed._backfill_all()   # simulates reconnect

        # Buffer should contain at most buffer_size candles; no phantom doubles
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert df.index.nunique() == len(df), "Duplicate timestamps after re-backfill"

    @pytest.mark.anyio
    async def test_three_reconnect_cycles_clean_buffer(self):
        """Scenario 9 — three reconnect cycles leave buffer in clean state."""
        symbols   = ["BTCUSDT", "ETHUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(5))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            for _ in range(3):
                await feed._backfill_all()

        for sym in symbols:
            for iv in intervals:
                df = state.get_buffer_df(sym, iv)
                assert df.index.nunique() == len(df), (
                    f"Duplicate timestamps for {sym}/{iv} after 3 cycles"
                )

    @pytest.mark.anyio
    async def test_no_duplicate_open_times_after_parallel_backfill(self):
        """Scenario 10 — get_buffer_df() has strictly unique open_times."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(8))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            await feed._backfill_all()
            await feed._backfill_all()   # second pass, same data

        for sym in symbols:
            for iv in intervals:
                df = state.get_buffer_df(sym, iv)
                open_times = [c.open_time for c in state._buffers[(sym, iv)]]
                assert len(open_times) == len(set(open_times)), (
                    f"Duplicate open_times in buffer for {sym}/{iv}"
                )

    @pytest.mark.anyio
    async def test_buffer_sorted_ascending_after_parallel_backfill(self):
        """Scenario 11 — get_buffer_df() rows are ascending by open_time."""
        symbols   = ["BTCUSDT"]
        intervals = ["1m"]
        async with _server() as srv:
            srv.set_klines("BTCUSDT", "1m", _rows(6))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            await feed._backfill_all()

        df = state.get_buffer_df("BTCUSDT", "1m")
        assert list(df.index) == sorted(df.index.tolist()), (
            "Buffer DataFrame must be sorted ascending by close_time after backfill"
        )


# ── Scenarios 12 & 13: History-flag semantics ─────────────────────────────────

class TestHistorySemantics:
    """Scenarios 12 & 13 — is_history flag and live-vs-history routing."""

    @pytest.mark.anyio
    async def test_backfill_events_all_carry_is_history_true(self):
        """Scenario 12 — every CandleEvent emitted during backfill is a history event."""
        symbols   = ["BTCUSDT", "ETHUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(5))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)

            all_events: list[CandleEvent] = []
            bus.subscribe(CandleEvent, all_events.append)
            await feed._backfill_all()

        assert len(all_events) > 0, "No CandleEvents emitted during backfill"
        non_history = [ev for ev in all_events if not ev.is_history]
        assert len(non_history) == 0, (
            f"Backfill emitted {len(non_history)} events with is_history=False"
        )

    @pytest.mark.anyio
    async def test_live_ws_candle_after_backfill_is_not_history(self):
        """Scenario 13 — live WS candle injected after backfill carries is_history=False."""
        symbols   = ["BTCUSDT"]
        intervals = ["1m"]
        async with _server() as srv:
            srv.set_klines("BTCUSDT", "1m", _rows(5))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)

            live_events: list[CandleEvent] = []
            bus.subscribe(CandleEvent, lambda ev: live_events.append(ev) if not ev.is_history else None)

            await feed._backfill_all()

            # Inject a live WS candle (index 999 — clearly after the backfill rows)
            feed._handle_message(_kline_ws_msg("BTCUSDT", "1m", idx=999))

        assert len(live_events) == 1
        assert live_events[0].is_history is False
        assert live_events[0].symbol == "BTCUSDT"


# ── Scenario 14: Concurrency bound ────────────────────────────────────────────

class TestConcurrencyBound:
    """Scenario 14 — asyncio.Semaphore prevents more than `concurrency` requests in-flight."""

    @pytest.mark.anyio
    async def test_semaphore_caps_peak_concurrency(self):
        """Peak simultaneous server handlers must never exceed backfill_concurrency."""
        concurrency = 2
        symbols     = ["SYM01USDT", "SYM02USDT", "SYM03USDT", "SYM04USDT", "SYM05USDT"]
        intervals   = ["1m", "5m"]  # 10 pairs total
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            srv.set_uniform_delay(0.05)   # 50ms per request → concurrent overlap is visible

            feed, state, bus = _make_feed(
                symbols, intervals, srv.rest_url,
                concurrency=concurrency,
            )
            await feed._backfill_all()

        assert srv.peak_concurrent <= concurrency, (
            f"Peak concurrent={srv.peak_concurrent} exceeded semaphore limit {concurrency}"
        )
        assert srv.request_count == len(symbols) * len(intervals), (
            "All pairs must eventually complete"
        )


# ── Scenarios 15–17: Session lifecycle ───────────────────────────────────────

class TestSessionLifecycle:
    """Scenarios 15–17 — ClientSession sharing, closing, and cleanup on error."""

    @pytest.mark.anyio
    async def test_one_session_per_backfill_batch(self):
        """Scenario 15 — exactly one ClientSession is created for a full batch."""
        symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m", "15m"]   # 9 pairs
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)

            sessions_created: list[aiohttp.ClientSession] = []
            _orig = aiohttp.ClientSession

            def _factory(*args, **kwargs):
                s = _orig(*args, **kwargs)
                sessions_created.append(s)
                return s

            with patch("bot.runtime.aiohttp.ClientSession", side_effect=_factory):
                await feed._backfill_all()

        assert len(sessions_created) == 1, (
            f"Expected 1 shared ClientSession, got {len(sessions_created)}"
        )

    @pytest.mark.anyio
    async def test_session_closed_after_successful_batch(self):
        """Scenario 16 — ClientSession is closed when _backfill_all() exits normally."""
        symbols   = ["BTCUSDT"]
        intervals = ["1m"]
        async with _server() as srv:
            srv.set_klines("BTCUSDT", "1m", _rows(3))
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)

            captured: list[aiohttp.ClientSession] = []
            _orig = aiohttp.ClientSession

            def _factory(*args, **kwargs):
                s = _orig(*args, **kwargs)
                captured.append(s)
                return s

            with patch("bot.runtime.aiohttp.ClientSession", side_effect=_factory):
                await feed._backfill_all()

        assert captured[0].closed, "ClientSession must be closed after _backfill_all() exits"

    @pytest.mark.anyio
    async def test_session_closed_even_when_all_pairs_fail(self):
        """Scenario 17 — ClientSession is still closed if every pair raises an error."""
        symbols   = ["BTCUSDT", "ETHUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            for sym in symbols:
                for iv in intervals:
                    srv.set_error(sym, iv, 500)

            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url)
            captured: list[aiohttp.ClientSession] = []
            _orig = aiohttp.ClientSession

            def _factory(*args, **kwargs):
                s = _orig(*args, **kwargs)
                captured.append(s)
                return s

            with patch("bot.runtime.aiohttp.ClientSession", side_effect=_factory):
                await feed._backfill_all()   # must not raise even on total failure

        assert len(captured) == 1
        assert captured[0].closed, (
            "ClientSession must be closed even after all pairs fail"
        )


# ── Scenario 18: Cancellation ─────────────────────────────────────────────────

class TestCancellation:
    """Scenario 18 — asyncio.CancelledError propagates cleanly from _backfill_all()."""

    @pytest.mark.anyio
    async def test_cancellation_propagates(self):
        """Cancelling the parent task cancels _backfill_all() cleanly."""
        symbols   = ["BTCUSDT", "ETHUSDT"]
        intervals = ["1m", "5m"]
        async with _server() as srv:
            srv.set_default_rows(_rows(3))
            srv.set_uniform_delay(5.0)   # all pairs hang — ensures cancel fires mid-flight
            feed, state, bus = _make_feed(symbols, intervals, srv.rest_url, timeout_s=30)

            task = asyncio.create_task(feed._backfill_all())
            await asyncio.sleep(0.05)    # let the task start and reach the delay
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task


# ── 2B-9 Performance benchmark ────────────────────────────────────────────────

class TestPerformanceBenchmark:
    """Phase 2B-9 — sequential (concurrency=1) vs parallel (concurrency=8).

    Each stream uses a 5 ms controlled delay so timing differences are
    dominated by concurrency, not asyncio overhead.
    """

    DELAY_S  = 0.005   # 5 ms per request
    PARALLEL = 8
    STREAM_CONFIGS = [
        (3,  ["1m", "5m", "15m"],             9),    # 3 symbols × 3 intervals
        (10, ["1m", "5m", "15m"],            30),    # 10 × 3
        (30, ["1m", "5m", "15m"],            90),    # 30 × 3
        (50, ["1m", "5m", "15m"],           150),    # 50 × 3
    ]

    def _sym_list(self, n: int) -> list[str]:
        return [f"SYM{i:03d}UST" for i in range(n)]

    async def _run_backfill(
        self,
        symbols: list[str],
        intervals: list[str],
        srv: MockRestServer,
        concurrency: int,
    ) -> float:
        """Return elapsed seconds for one _backfill_all() call."""
        feed, _, _ = _make_feed(
            symbols, intervals, srv.rest_url,
            concurrency=concurrency,
            timeout_s=60,
        )
        t0 = time.monotonic()
        await feed._backfill_all()
        return time.monotonic() - t0

    @pytest.mark.anyio
    async def test_parallel_faster_than_sequential(self):
        """Parallel backfill must be measurably faster than sequential at every scale."""
        print()  # blank line before benchmark output
        print(f"{'streams':>8}  {'sequential':>12}  {'parallel':>10}  {'speedup':>8}  {'peak_conc':>10}  {'status':>6}")
        print("-" * 65)

        all_passed = True
        async with _server() as srv:
            srv.set_default_rows(_rows(5))
            srv.set_uniform_delay(self.DELAY_S)

            for n_sym, intervals, n_streams in self.STREAM_CONFIGS:
                symbols = self._sym_list(n_sym)
                srv.request_count   = 0
                srv.peak_concurrent = 0

                seq_s  = await self._run_backfill(symbols, intervals, srv, concurrency=1)

                srv.request_count   = 0
                srv.peak_concurrent = 0

                par_s  = await self._run_backfill(symbols, intervals, srv, concurrency=self.PARALLEL)
                peak   = srv.peak_concurrent
                speedup = seq_s / par_s if par_s > 0 else float("inf")

                ok = speedup >= 2.0 and peak <= self.PARALLEL
                status = "PASS" if ok else "FAIL"
                if not ok:
                    all_passed = False

                print(
                    f"{n_streams:>8}  {seq_s:>11.3f}s  {par_s:>9.3f}s  "
                    f"{speedup:>7.1f}x  {peak:>10}  {status:>6}"
                )

        assert all_passed, (
            "At least one stream-count failed: speedup < 2× or peak_concurrent > PARALLEL. "
            "See printed table above for details."
        )
