"""Phase 11 live-feed harness — deterministic local mock server + pipeline audit.

Covers (from the 17-phase mandate):
  Phase 2  – 9-stream (3×3) candle routing, per-(symbol,interval) buffer isolation
  Phase 3  – Binance WS URL format and stream-name generation
  Phase 4  – Candle semantics: x=False gate, non-kline events, all 14 intervals,
              missed-candle detection (exact boundary)
  Phase 5  – Reconnect dedup: get_buffer_df() never delivers duplicate rows to
              the strategy after a re-backfill
  Phase 6  – Per-(symbol,interval) strategy-instance isolation (Bug 2 regression)
  Phase 11 – MockBinanceServer: local HTTP+WS harness, full LiveFeed pipeline
  Phase 12 – Real Binance connectivity probe (NETWORK BLOCKED expected here)
  Phase 13 – Throughput: 3×3 and 10×5 candle injection benchmarks
  Phase 14 – Failure injection: malformed JSON, non-kline, strategy exception,
              unknown interval
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import aiohttp.web
import pytest
import websockets
import websockets.asyncio.server as ws_server

from bot.config import BotConfig, FeedConfig, RiskConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, EventBus, SignalEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import PaperExchange
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskEngine
from bot.runtime import LiveFeed, _INTERVAL_MS
from bot.state import BotState, CandleRow
from bot.storage import BotStorage


# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w",
]

THREE_SYMBOLS   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
THREE_INTERVALS = ["1m", "5m", "15m"]
BASE_OPEN_TIME  = 1_700_000_000_000   # ms — year 2023, clearly in the past


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _binance_kline_msg(
    symbol: str,
    interval: str,
    open_time: int,
    close_time: int,
    open_: float = 50_000.0,
    high: float = 51_000.0,
    low: float = 49_000.0,
    close: float = 50_500.0,
    volume: float = 100.0,
    is_closed: bool = True,
) -> dict:
    """Build a Binance combined-stream kline message (exact wire format)."""
    return {
        "stream": f"{symbol.lower()}@kline_{interval}",
        "data": {
            "e": "kline",
            "k": {
                "t": open_time,
                "T": close_time,
                "s": symbol.upper(),
                "i": interval,
                "o": str(open_),
                "h": str(high),
                "l": str(low),
                "c": str(close),
                "v": str(volume),
                "x": is_closed,
            },
        },
    }


def _kline_rest_row(
    open_time: int,
    close_time: int,
    open_: float = 50_000.0,
    high: float = 51_000.0,
    low: float = 49_000.0,
    close: float = 50_500.0,
    volume: float = 100.0,
) -> list:
    """Build a Binance REST klines API row (12-element list)."""
    return [
        open_time,
        str(open_), str(high), str(low), str(close), str(volume),
        close_time,
        "0", 0, "0", "0", "0",
    ]


def _make_feed(
    symbols: list[str] | None = None,
    intervals: list[str] | None = None,
    ws_url: str = "ws://127.0.0.1:9999/stream",
    rest_url: str = "http://127.0.0.1:8888/api/v3",
    backfill_bars: int = 2,
    min_signal_bars: int = 2,
    push_to_state: bool = True,
) -> tuple[LiveFeed, BotState, EventBus]:
    cfg = BotConfig(
        paper_capital=1000.0,
        feed=FeedConfig(
            symbols=symbols or ["BTCUSDT"],
            intervals=intervals or ["1m"],
            ws_base_url=ws_url,
            rest_base_url=rest_url,
            backfill_bars=backfill_bars,
            reconnect_delay_s=0.05,
            max_reconnect_delay_s=0.5,
            heartbeat_interval_s=30,
            ping_timeout_s=10,
            ws_open_timeout_s=3,
            rest_timeout_s=5,
        ),
        min_signal_bars=min_signal_bars,
    )
    state = BotState(buffer_size=200)
    bus   = EventBus()
    feed  = LiveFeed(config=cfg, state=state, bus=bus)
    if push_to_state:
        _subscribe_state_pusher(bus, state)
    return feed, state, bus


def _make_storage(tmp_path):
    s = BotStorage(str(tmp_path / "test.db"))
    s.connect()
    return s


def _subscribe_state_pusher(bus: EventBus, state: BotState) -> None:
    """Wire bus → BotState.push_candle so unit tests can check buffer_length
    without a full BotEngine.  Mirrors what BotEngine._on_candle() does."""
    def _push(ev: CandleEvent) -> None:
        state.push_candle(CandleRow(
            symbol=ev.symbol, interval=ev.interval,
            open_time=ev.open_time,
            open=ev.open, high=ev.high, low=ev.low, close=ev.close,
            volume=ev.volume, close_time=ev.close_time,
        ))
    bus.subscribe(CandleEvent, _push)


def _make_engine(
    cfg: BotConfig,
    strategy: Any,
    state: BotState,
    bus: EventBus,
    storage: BotStorage,
) -> BotEngine:
    ex   = PaperExchange(fee_rate=0.001, slippage_pct=0.0, bus=bus)
    om   = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm   = PositionManager(storage=storage, bus=bus)
    pf   = Portfolio(starting_capital=cfg.paper_capital, storage=storage, bus=bus)
    risk = RiskEngine(cfg.risk, bus=bus)
    return BotEngine(
        config=cfg, strategy=strategy, state=state,
        orders=om, positions=pm, portfolio=pf,
        risk=risk, storage=storage, bus=bus,
    )


# ── MockBinanceServer ─────────────────────────────────────────────────────────

class MockBinanceServer:
    """Deterministic local HTTP+WebSocket server that mimics Binance public endpoints.

    REST: GET /api/v3/klines?symbol=X&interval=Y&limit=N → JSON row array
    WS:   ws://host:PORT/stream?streams=...             → broadcast kline messages
    """

    def __init__(self) -> None:
        self._klines: dict[tuple[str, str], list] = {}
        self._rest_runner: aiohttp.web.AppRunner | None = None
        self._connections: set = set()
        self._ws_task: asyncio.Task | None = None
        self._ws_ready: asyncio.Event | None = None
        self._ws_stop:  asyncio.Event | None = None
        self.rest_url = ""
        self.ws_url   = ""

    def set_klines(self, symbol: str, interval: str, rows: list) -> None:
        """Pre-load REST klines response for a (symbol, interval) pair."""
        self._klines[(symbol.upper(), interval)] = rows

    async def broadcast(self, msg: dict) -> None:
        """Send a kline message to all connected WebSocket clients."""
        if not self._connections:
            return
        raw = json.dumps(msg)
        await asyncio.gather(
            *(conn.send(raw) for conn in list(self._connections)),
            return_exceptions=True,
        )

    async def start(self) -> None:
        rest_port = _free_port()

        # ── REST ──────────────────────────────────────────────────────────────
        app = aiohttp.web.Application()
        app.router.add_get("/api/v3/klines", self._handle_klines)
        self._rest_runner = aiohttp.web.AppRunner(app)
        await self._rest_runner.setup()
        site = aiohttp.web.TCPSite(self._rest_runner, "127.0.0.1", rest_port)
        await site.start()
        self.rest_url = f"http://127.0.0.1:{rest_port}/api/v3"

        # ── WebSocket ─────────────────────────────────────────────────────────
        self._ws_ready = asyncio.Event()
        self._ws_stop  = asyncio.Event()
        self._ws_task  = asyncio.create_task(self._run_ws_server())
        await asyncio.wait_for(self._ws_ready.wait(), timeout=5.0)

    async def stop(self) -> None:
        if self._ws_stop:
            self._ws_stop.set()
        if self._ws_task:
            try:
                await asyncio.wait_for(self._ws_task, timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                pass
        if self._rest_runner:
            await self._rest_runner.cleanup()

    async def _run_ws_server(self) -> None:
        async with ws_server.serve(self._handle_ws, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            self.ws_url = f"ws://127.0.0.1:{port}/stream"
            self._ws_ready.set()
            await self._ws_stop.wait()

    async def _handle_ws(self, connection) -> None:
        self._connections.add(connection)
        try:
            async for _ in connection:
                pass
        except Exception:
            pass
        finally:
            self._connections.discard(connection)

    async def _handle_klines(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        symbol   = request.query.get("symbol", "").upper()
        interval = request.query.get("interval", "")
        limit    = int(request.query.get("limit", "300"))
        rows     = self._klines.get((symbol, interval), [])
        return aiohttp.web.json_response(rows[-limit:] if limit > 0 else [])


# ── Phase 3: URL format ───────────────────────────────────────────────────────

class TestPhase3WsUrlFormat:
    """Phase 3 — Verify the exact Binance combined-stream URL format."""

    def test_single_symbol_single_interval(self):
        feed, _, _ = _make_feed(symbols=["BTCUSDT"], intervals=["1h"])
        url = feed._build_ws_url()
        assert "?streams=" in url
        assert "btcusdt@kline_1h" in url

    def test_three_symbols_three_intervals(self):
        """3×3 = 9 stream segments, all lower-cased symbol names."""
        feed, _, _ = _make_feed(symbols=THREE_SYMBOLS, intervals=THREE_INTERVALS)
        url = feed._build_ws_url()
        assert url.count("@kline_") == 9
        for sym in THREE_SYMBOLS:
            for iv in THREE_INTERVALS:
                assert f"{sym.lower()}@kline_{iv}" in url

    def test_url_base_preserved(self):
        feed, _, _ = _make_feed(ws_url="ws://localhost:9999/stream")
        url = feed._build_ws_url()
        assert url.startswith("ws://localhost:9999/stream?streams=")

    def test_streams_separated_by_slash(self):
        feed, _, _ = _make_feed(symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m"])
        url = feed._build_ws_url()
        assert "btcusdt@kline_1m/ethusdt@kline_1m" in url


# ── Phase 2 + 4: _handle_message() injection ─────────────────────────────────

class TestPhase2And4HandleMessage:
    """Phase 2 + 4 — Direct injection into LiveFeed._handle_message().

    No network required.  Each test calls _handle_message(raw_json) and
    checks the resulting CandleEvent or BotState buffer.
    """

    def _feed_with_events(self, symbols=None, intervals=None):
        # push_to_state=True (default) already wires bus → state.push_candle
        feed, state, bus = _make_feed(symbols=symbols, intervals=intervals)
        received: list[CandleEvent] = []
        bus.subscribe(CandleEvent, received.append)
        return feed, state, received

    # ── Routing ───────────────────────────────────────────────────────────────

    def test_candle_routed_to_correct_symbol_interval(self):
        feed, state, received = self._feed_with_events(
            symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m", "5m"]
        )
        iv_ms = _INTERVAL_MS["1m"]
        raw = json.dumps(_binance_kline_msg(
            "ETHUSDT", "5m",
            open_time=BASE_OPEN_TIME,
            close_time=BASE_OPEN_TIME + _INTERVAL_MS["5m"] - 1,
        ))
        feed._handle_message(raw)

        assert len(received) == 1
        ev = received[0]
        assert ev.symbol   == "ETHUSDT"
        assert ev.interval == "5m"
        assert state.buffer_length("ETHUSDT", "5m") == 1
        assert state.buffer_length("BTCUSDT", "1m") == 0

    def test_nine_streams_3x3_all_routed_independently(self):
        """Phase 2 core: 3 symbols × 3 intervals = 9 independent buffers."""
        feed, state, received = self._feed_with_events(
            symbols=THREE_SYMBOLS, intervals=THREE_INTERVALS
        )
        open_t = BASE_OPEN_TIME
        for sym in THREE_SYMBOLS:
            for iv in THREE_INTERVALS:
                iv_ms = _INTERVAL_MS[iv]
                raw = json.dumps(_binance_kline_msg(
                    sym, iv,
                    open_time=open_t,
                    close_time=open_t + iv_ms - 1,
                ))
                feed._handle_message(raw)
                open_t += 1

        assert len(received) == 9
        for sym in THREE_SYMBOLS:
            for iv in THREE_INTERVALS:
                assert state.buffer_length(sym, iv) == 1, (
                    f"{sym}/{iv} buffer should have exactly 1 candle"
                )

    def test_symbol_buffers_are_isolated(self):
        """Candles for BTCUSDT must not appear in the ETHUSDT buffer."""
        feed, state, _ = self._feed_with_events(
            symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m"]
        )
        iv_ms = _INTERVAL_MS["1m"]
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", "1m", BASE_OPEN_TIME, BASE_OPEN_TIME + iv_ms - 1
        )))
        assert state.buffer_length("BTCUSDT", "1m") == 1
        assert state.buffer_length("ETHUSDT", "1m") == 0

    def test_interval_buffers_are_isolated(self):
        """1m candles must not appear in the 5m buffer for the same symbol."""
        feed, state, _ = self._feed_with_events(
            symbols=["BTCUSDT"], intervals=["1m", "5m"]
        )
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", "1m", BASE_OPEN_TIME, BASE_OPEN_TIME + _INTERVAL_MS["1m"] - 1
        )))
        assert state.buffer_length("BTCUSDT", "1m") == 1
        assert state.buffer_length("BTCUSDT", "5m") == 0

    # ── x=False gate ──────────────────────────────────────────────────────────

    def test_unclosed_candle_dropped(self):
        """Phase 4: x=False candles must be silently discarded."""
        feed, state, received = self._feed_with_events()
        raw = json.dumps(_binance_kline_msg(
            "BTCUSDT", "1m",
            open_time=BASE_OPEN_TIME,
            close_time=BASE_OPEN_TIME + _INTERVAL_MS["1m"] - 1,
            is_closed=False,
        ))
        feed._handle_message(raw)
        assert len(received) == 0
        assert state.buffer_length("BTCUSDT", "1m") == 0

    def test_closed_candle_accepted(self):
        """x=True candles must be forwarded."""
        feed, state, received = self._feed_with_events()
        raw = json.dumps(_binance_kline_msg(
            "BTCUSDT", "1m",
            open_time=BASE_OPEN_TIME,
            close_time=BASE_OPEN_TIME + _INTERVAL_MS["1m"] - 1,
            is_closed=True,
        ))
        feed._handle_message(raw)
        assert len(received) == 1

    # ── Non-kline messages ────────────────────────────────────────────────────

    def test_non_kline_event_type_ignored(self):
        """Phase 4: messages where e != 'kline' must be silently ignored."""
        feed, state, received = self._feed_with_events()
        msg = {
            "stream": "btcusdt@trade",
            "data": {"e": "trade", "p": "50000"},
        }
        feed._handle_message(json.dumps(msg))
        assert len(received) == 0

    def test_message_missing_data_field_ignored(self):
        """Messages without 'data' key must be silently ignored."""
        feed, state, received = self._feed_with_events()
        feed._handle_message(json.dumps({"stream": "btcusdt@kline_1m"}))
        assert len(received) == 0

    # ── All 14 intervals: missed-candle detection ─────────────────────────────

    @pytest.mark.parametrize("interval", SUPPORTED_INTERVALS)
    def test_missed_candle_detection_all_intervals(self, interval):
        """Phase 4: missed-candle counter increments for every supported interval."""
        feed, state, _ = self._feed_with_events(intervals=[interval])
        iv_ms = _INTERVAL_MS[interval]

        # First candle — establishes the baseline
        t0 = BASE_OPEN_TIME
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval,
            open_time=t0,
            close_time=t0 + iv_ms - 1,
        )))
        before = state.counters()["missed_candles"]

        # Second candle — skips exactly one interval (two intervals after t0)
        t1 = t0 + 2 * iv_ms
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval,
            open_time=t1,
            close_time=t1 + iv_ms - 1,
        )))
        after = state.counters()["missed_candles"]
        assert after > before, (
            f"interval={interval}: missed_candles did not increment "
            f"(before={before}, after={after})"
        )

    def test_no_missed_candle_for_consecutive_candles(self):
        """Consecutive candles with no gap must not increment missed_candles."""
        interval = "1h"
        feed, state, _ = self._feed_with_events(intervals=[interval])
        iv_ms = _INTERVAL_MS[interval]

        # Two consecutive candles
        t0 = BASE_OPEN_TIME
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval, t0, t0 + iv_ms - 1
        )))
        t1 = t0 + iv_ms
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval, t1, t1 + iv_ms - 1
        )))
        assert state.counters()["missed_candles"] == 0

    def test_missed_candle_exact_boundary(self):
        """open_time == last_close_time+1+interval_ms → exactly 1 missed candle."""
        interval = "1h"
        iv_ms    = _INTERVAL_MS[interval]
        feed, state, _ = self._feed_with_events(intervals=[interval])

        t0 = BASE_OPEN_TIME
        t0_close = t0 + iv_ms - 1
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval, t0, t0_close
        )))

        # exactly one interval gap: open_time == last_close + 1 + interval_ms
        t1 = t0_close + 1 + iv_ms
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", interval, t1, t1 + iv_ms - 1
        )))
        assert state.counters()["missed_candles"] == 1

    def test_all_14_intervals_present_in_interval_ms_table(self):
        """Phase 4: _INTERVAL_MS must map all 14 Binance intervals."""
        for iv in SUPPORTED_INTERVALS:
            assert iv in _INTERVAL_MS, f"_INTERVAL_MS missing interval: {iv}"
            assert _INTERVAL_MS[iv] > 0


# ── Phase 5: Reconnect dedup ─────────────────────────────────────────────────

class TestPhase5ReconnectDedup:
    """Phase 5 — get_buffer_df() deduplication (Bug 1 regression tests).

    After reconnect _backfill_all() re-pushes all historical candles.
    The buffer then contains duplicates; get_buffer_df() must remove them
    before handing a DataFrame to the strategy.
    """

    def _candle(self, open_time: int, close: float = 50_000.0) -> CandleRow:
        iv_ms = _INTERVAL_MS["1m"]
        return CandleRow(
            symbol="BTCUSDT", interval="1m",
            open_time=open_time,
            open=49_000.0, high=51_000.0, low=48_000.0, close=close,
            volume=100.0,
            close_time=open_time + iv_ms - 1,
        )

    def test_duplicate_open_times_produce_single_df_row(self):
        """Pushing the same open_time twice must yield len(df)==1."""
        state = BotState(buffer_size=200)
        c1 = self._candle(BASE_OPEN_TIME, close=50_000.0)
        c2 = self._candle(BASE_OPEN_TIME, close=50_100.0)  # same open_time
        state.push_candle(c1)
        state.push_candle(c2)
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert len(df) == 1, "duplicate open_time must be deduplicated"

    def test_last_write_wins_on_duplicate(self):
        """After dedup, the latest-pushed candle's close price must survive."""
        state = BotState(buffer_size=200)
        state.push_candle(self._candle(BASE_OPEN_TIME, close=50_000.0))
        state.push_candle(self._candle(BASE_OPEN_TIME, close=99_999.0))
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert df.iloc[0]["close"] == 99_999.0, "last-write-wins expected"

    def test_df_sorted_ascending_by_open_time(self):
        """Candles pushed out of order must emerge in ascending open_time order."""
        state = BotState(buffer_size=200)
        iv_ms = _INTERVAL_MS["1m"]
        # Push in reverse order
        for i in reversed(range(5)):
            state.push_candle(self._candle(BASE_OPEN_TIME + i * iv_ms))
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert list(df.index) == sorted(df.index.tolist())

    def test_three_candles_no_duplicates_unaffected(self):
        """Three distinct open_times must produce len(df)==3."""
        state = BotState(buffer_size=200)
        iv_ms = _INTERVAL_MS["1m"]
        for i in range(3):
            state.push_candle(self._candle(BASE_OPEN_TIME + i * iv_ms))
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert len(df) == 3

    def test_mixed_duplicates_and_uniques_correct_count(self):
        """5 pushes with 2 duplicates → 4 unique rows."""
        state = BotState(buffer_size=200)
        iv_ms = _INTERVAL_MS["1m"]
        times = [0, 1, 1, 2, 3]   # open_time offset multiples
        for mult in times:
            state.push_candle(self._candle(BASE_OPEN_TIME + mult * iv_ms))
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert len(df) == 4, f"expected 4 unique rows, got {len(df)}"

    def test_empty_buffer_returns_empty_df(self):
        state = BotState()
        df = state.get_buffer_df("BTCUSDT", "1m")
        assert df.empty


# ── Phase 6: Per-key strategy isolation ──────────────────────────────────────

class TestPhase6PerKeyStrategyIsolation:
    """Phase 6 — BotEngine per-(symbol,interval) strategy dict (Bug 2 regression)."""

    def _mock_strategy(self, signal_value="HOLD"):
        """Return a mock strategy that records calls and emits a fixed signal."""
        from pandas import Series

        class _MockStrategy:
            def __init__(self):
                self.calls: list[int] = []   # bar counts passed in

            def generate_signals(self, bars):
                self.calls.append(len(bars))
                return Series([signal_value] * len(bars))

        return _MockStrategy()

    def _emit_candle(self, bus: EventBus, symbol: str, interval: str, seq: int = 0) -> None:
        iv_ms = _INTERVAL_MS.get(interval, 60_000)
        t0 = BASE_OPEN_TIME + seq * iv_ms
        ev = CandleEvent(
            symbol=symbol, interval=interval,
            open_time=t0,
            open=50_000.0, high=51_000.0, low=49_000.0,
            close=50_500.0, volume=100.0,
            close_time=t0 + iv_ms - 1,
            is_history=False,
        )
        bus.emit(ev)

    def test_per_key_strategy_dict_routes_correctly(self, tmp_path):
        """Each (symbol,interval) pair must call only its own strategy instance."""
        s_btc_1m  = self._mock_strategy()
        s_eth_1m  = self._mock_strategy()
        s_btc_5m  = self._mock_strategy()

        cfg = BotConfig(
            paper_capital=1000.0,
            feed=FeedConfig(symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m", "5m"]),
            min_signal_bars=1,
        )
        state   = BotState(buffer_size=200)
        bus     = EventBus()
        storage = _make_storage(tmp_path)
        strategy_map = {
            ("BTCUSDT", "1m"): s_btc_1m,
            ("ETHUSDT", "1m"): s_eth_1m,
            ("BTCUSDT", "5m"): s_btc_5m,
        }
        engine = _make_engine(cfg, strategy_map, state, bus, storage)

        # Only emit BTCUSDT 1m candles (3 of them)
        for i in range(3):
            self._emit_candle(bus, "BTCUSDT", "1m", seq=i)

        assert len(s_btc_1m.calls) == 3,  "BTCUSDT/1m strategy must be called 3×"
        assert len(s_eth_1m.calls) == 0,  "ETHUSDT/1m strategy must NOT be called"
        assert len(s_btc_5m.calls) == 0,  "BTCUSDT/5m strategy must NOT be called"

    def test_single_strategy_still_applied_to_all_pairs(self, tmp_path):
        """When a single strategy instance is passed it is used for every pair."""
        s = self._mock_strategy()
        cfg = BotConfig(
            paper_capital=1000.0,
            feed=FeedConfig(symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m"]),
            min_signal_bars=1,
        )
        state   = BotState(buffer_size=200)
        bus     = EventBus()
        storage = _make_storage(tmp_path)
        engine  = _make_engine(cfg, s, state, bus, storage)

        self._emit_candle(bus, "BTCUSDT", "1m", seq=0)
        self._emit_candle(bus, "ETHUSDT", "1m", seq=0)

        assert len(s.calls) == 2, "single strategy must be called for each symbol"

    def test_missing_key_in_dict_does_not_crash(self, tmp_path):
        """If a (symbol,interval) has no entry in the dict, the engine skips gracefully."""
        cfg = BotConfig(
            paper_capital=1000.0,
            feed=FeedConfig(symbols=["BTCUSDT"], intervals=["1m"]),
            min_signal_bars=1,
        )
        state   = BotState(buffer_size=200)
        bus     = EventBus()
        storage = _make_storage(tmp_path)
        # Empty strategy map — no key for BTCUSDT/1m
        engine  = _make_engine(cfg, {}, state, bus, storage)

        # Should not raise
        self._emit_candle(bus, "BTCUSDT", "1m", seq=0)
        # Buffer is still populated even when strategy is absent
        assert state.buffer_length("BTCUSDT", "1m") == 1

    def test_engine_get_strategy_returns_correct_instance(self, tmp_path):
        """BotEngine._get_strategy() must return the exact per-key instance."""
        s_btc = self._mock_strategy()
        s_eth = self._mock_strategy()
        cfg = BotConfig(paper_capital=1000.0)
        state, bus, storage = BotState(), EventBus(), _make_storage(tmp_path)
        strategy_map = {("BTCUSDT", "1m"): s_btc, ("ETHUSDT", "1m"): s_eth}
        engine = _make_engine(cfg, strategy_map, state, bus, storage)

        assert engine._get_strategy("BTCUSDT", "1m") is s_btc
        assert engine._get_strategy("ETHUSDT", "1m") is s_eth
        assert engine._get_strategy("SOLUSDT", "1m") is None


# ── Phase 11: MockBinanceServer full pipeline ─────────────────────────────────

class TestPhase11MockServer:
    """Phase 11 — Full LiveFeed pipeline using the local MockBinanceServer."""

    @pytest.mark.anyio
    async def test_rest_klines_endpoint_returns_correct_data(self):
        """MockBinanceServer REST endpoint returns the rows we set_klines with."""
        server = MockBinanceServer()
        rows = [_kline_rest_row(BASE_OPEN_TIME, BASE_OPEN_TIME + 59_999)]
        server.set_klines("BTCUSDT", "1m", rows)
        await server.start()
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{server.rest_url}/klines",
                    params={"symbol": "BTCUSDT", "interval": "1m", "limit": "5"},
                ) as resp:
                    data = await resp.json()
            assert data == rows
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_backfill_populates_state_via_rest(self):
        """LiveFeed._backfill() populates BotState via the mock REST server."""
        server = MockBinanceServer()
        iv_ms = _INTERVAL_MS["1m"]
        rows = [
            _kline_rest_row(
                BASE_OPEN_TIME + i * iv_ms,
                BASE_OPEN_TIME + i * iv_ms + iv_ms - 1,
            )
            for i in range(5)
        ]
        server.set_klines("BTCUSDT", "1m", rows)
        await server.start()

        try:
            feed, state, bus = _make_feed(
                symbols=["BTCUSDT"], intervals=["1m"],
                ws_url=server.ws_url, rest_url=server.rest_url,
                backfill_bars=5,
            )

            task = asyncio.create_task(feed.run())
            # Poll until backfill fills the buffer (up to 5 s)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if state.buffer_length("BTCUSDT", "1m") >= 5:
                    break
                await asyncio.sleep(0.05)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            assert state.buffer_length("BTCUSDT", "1m") == 5
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_ws_closed_candle_delivered_to_state(self):
        """A closed kline broadcast via WS lands in BotState after backfill."""
        server = MockBinanceServer()
        server.set_klines("BTCUSDT", "1m", [])  # no backfill
        await server.start()

        try:
            feed, state, bus = _make_feed(
                symbols=["BTCUSDT"], intervals=["1m"],
                ws_url=server.ws_url, rest_url=server.rest_url,
                backfill_bars=1,
            )
            candle_received = asyncio.Event()
            bus.subscribe(
                CandleEvent,
                lambda ev: candle_received.set() if not ev.is_history else None,
            )

            task = asyncio.create_task(feed.run())
            # Give LiveFeed time to connect (backfill + WS connect)
            await asyncio.sleep(0.4)

            msg = _binance_kline_msg(
                "BTCUSDT", "1m",
                open_time=BASE_OPEN_TIME,
                close_time=BASE_OPEN_TIME + _INTERVAL_MS["1m"] - 1,
            )
            await server.broadcast(msg)

            await asyncio.wait_for(candle_received.wait(), timeout=5.0)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            assert state.buffer_length("BTCUSDT", "1m") >= 1
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_ws_9_streams_all_routed(self):
        """3 symbols × 3 intervals — all 9 streams must reach the correct buffer."""
        server = MockBinanceServer()
        for sym in THREE_SYMBOLS:
            for iv in THREE_INTERVALS:
                server.set_klines(sym, iv, [])
        await server.start()

        try:
            feed, state, bus = _make_feed(
                symbols=THREE_SYMBOLS, intervals=THREE_INTERVALS,
                ws_url=server.ws_url, rest_url=server.rest_url,
                backfill_bars=0,
            )
            ev_count = 0
            ev_lock  = asyncio.Lock()
            received_combos: set[tuple[str, str]] = set()

            async def _on_candle(ev: CandleEvent):
                nonlocal ev_count
                if not ev.is_history:
                    async with ev_lock:
                        ev_count += 1
                        received_combos.add((ev.symbol, ev.interval))

            bus.subscribe(CandleEvent, lambda ev: asyncio.create_task(_on_candle(ev)))

            task = asyncio.create_task(feed.run())
            await asyncio.sleep(0.4)  # wait for WS connect

            open_t = BASE_OPEN_TIME
            for sym in THREE_SYMBOLS:
                for iv in THREE_INTERVALS:
                    iv_ms = _INTERVAL_MS[iv]
                    await server.broadcast(_binance_kline_msg(
                        sym, iv, open_t, open_t + iv_ms - 1
                    ))
                    open_t += 1

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                async with ev_lock:
                    if ev_count >= 9:
                        break
                await asyncio.sleep(0.05)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            for sym in THREE_SYMBOLS:
                for iv in THREE_INTERVALS:
                    assert state.buffer_length(sym, iv) == 1, (
                        f"{sym}/{iv} buffer expected 1 candle"
                    )
        finally:
            await server.stop()


# ── Phase 12: Binance connectivity ───────────────────────────────────────────

class TestPhase12Connectivity:
    """Phase 12 — Probe real Binance connectivity; report NETWORK BLOCKED if
    unreachable.  This test never fails — it only records the status."""

    @pytest.mark.anyio
    async def test_binance_rest_connectivity(self):
        """Attempt a real Binance REST call; record the outcome."""
        url = "https://api.binance.com/api/v3/time"
        status = "UNKNOWN"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    if resp.status == 200:
                        status = "REACHABLE"
                    else:
                        status = f"HTTP_{resp.status}"
        except Exception as exc:
            status = f"NETWORK BLOCKED ({type(exc).__name__})"

        # Always passes — just records the network state.
        print(f"\n[Phase 12] Binance REST connectivity: {status}")

    @pytest.mark.anyio
    async def test_binance_ws_connectivity(self):
        """Attempt a real Binance WebSocket connect; record the outcome."""
        url = "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1m"
        status = "UNKNOWN"
        try:
            async with websockets.connect(url, open_timeout=5.0) as ws:
                status = "REACHABLE"
        except Exception as exc:
            status = f"NETWORK BLOCKED ({type(exc).__name__})"
        print(f"\n[Phase 12] Binance WS  connectivity: {status}")


# ── Phase 13: Throughput benchmarks ──────────────────────────────────────────

class TestPhase13Throughput:
    """Phase 13 — Candle processing throughput for 3×3 and 10×5 configurations."""

    def _inject_candles(
        self,
        feed: LiveFeed,
        symbols: list[str],
        intervals: list[str],
        n_candles: int,
    ) -> tuple[int, float]:
        total = 0
        start = time.monotonic()
        open_t = BASE_OPEN_TIME
        for i in range(n_candles):
            for sym in symbols:
                for iv in intervals:
                    iv_ms = _INTERVAL_MS[iv]
                    t = open_t + i * iv_ms
                    raw = json.dumps(_binance_kline_msg(
                        sym, iv, t, t + iv_ms - 1
                    ))
                    feed._handle_message(raw)
                    total += 1
        elapsed = time.monotonic() - start
        return total, elapsed

    def test_3x3_throughput_exceeds_1000_candles_per_second(self):
        """3 symbols × 3 intervals, 200 candles each → > 1000 candles/s."""
        feed, state, _ = _make_feed(
            symbols=THREE_SYMBOLS, intervals=THREE_INTERVALS
        )
        total, elapsed = self._inject_candles(feed, THREE_SYMBOLS, THREE_INTERVALS, 200)
        throughput = total / elapsed
        print(
            f"\n[Phase 13] 3×3 throughput: {total} candles in {elapsed:.3f}s "
            f"= {throughput:,.0f} candles/s"
        )
        assert throughput > 1_000, (
            f"3×3 throughput {throughput:.0f} candles/s is below 1000 candles/s minimum"
        )

    def test_10x5_throughput_exceeds_1000_candles_per_second(self):
        """10 symbols × 5 intervals, 50 candles each → > 1000 candles/s."""
        symbols   = [f"SYM{i:02d}USDT" for i in range(10)]
        intervals = ["1m", "5m", "15m", "1h", "4h"]
        feed, state, _ = _make_feed(symbols=symbols, intervals=intervals)
        total, elapsed = self._inject_candles(feed, symbols, intervals, 50)
        throughput = total / elapsed
        print(
            f"\n[Phase 13] 10×5 throughput: {total} candles in {elapsed:.3f}s "
            f"= {throughput:,.0f} candles/s"
        )
        assert throughput > 1_000, (
            f"10×5 throughput {throughput:.0f} candles/s is below 1000 candles/s minimum"
        )

    def test_3x3_correct_buffer_counts_after_injection(self):
        """Sanity: after 100-candle injection each buffer must hold 100 rows."""
        feed, state, _ = _make_feed(
            symbols=THREE_SYMBOLS, intervals=THREE_INTERVALS
        )
        self._inject_candles(feed, THREE_SYMBOLS, THREE_INTERVALS, 100)
        for sym in THREE_SYMBOLS:
            for iv in THREE_INTERVALS:
                assert state.buffer_length(sym, iv) == 100, (
                    f"{sym}/{iv}: expected 100 buffered candles"
                )


# ── Phase 14: Failure injection ───────────────────────────────────────────────

class TestPhase14FailureInjection:
    """Phase 14 — The pipeline must survive malformed messages and strategy errors."""

    # ── Malformed messages ────────────────────────────────────────────────────
    # NOTE: _handle_message() propagates JSONDecodeError and KeyError.
    # The LiveFeed._stream() wrapper catches all exceptions:
    #   try: self._handle_message(raw_msg)
    #   except Exception: log.exception(...)
    # These tests document the real per-method behaviour.

    def test_malformed_json_raises_json_error(self):
        """_handle_message() raises JSONDecodeError on malformed input.
        The _stream() coroutine catches it — the runtime survives."""
        import json as _json
        feed, state, bus = _make_feed()
        with pytest.raises(_json.JSONDecodeError):
            feed._handle_message("{invalid json")

    def test_truncated_message_raises_json_error(self):
        """Truncated JSON triggers JSONDecodeError (caught by _stream())."""
        import json as _json
        feed, state, bus = _make_feed()
        with pytest.raises(_json.JSONDecodeError):
            feed._handle_message('{"stream": "btcusdt@kline_1m"')

    def test_completely_empty_message_raises_json_error(self):
        """Empty string triggers JSONDecodeError (caught by _stream())."""
        import json as _json
        feed, state, bus = _make_feed()
        with pytest.raises(_json.JSONDecodeError):
            feed._handle_message("")

    def test_kline_with_missing_k_field_raises(self):
        """Message with e=kline but no 'k' dict raises a KeyError or similar.
        The _stream() wrapper catches it — the runtime survives."""
        feed, state, bus = _make_feed()
        received: list = []
        bus.subscribe(CandleEvent, received.append)
        msg = {"stream": "btcusdt@kline_1m", "data": {"e": "kline"}}
        with pytest.raises(Exception):
            feed._handle_message(json.dumps(msg))
        assert received == []  # no event emitted before the error

    def test_subsequent_valid_candle_processed_after_exception(self):
        """After a JSON exception, the feed has no corrupted state.
        The NEXT valid call to _handle_message() must succeed normally."""
        feed, state, bus = _make_feed()
        received: list[CandleEvent] = []
        bus.subscribe(CandleEvent, received.append)

        # Malformed — exception caught by caller (simulating _stream()'s try/except)
        try:
            feed._handle_message("{not json")
        except Exception:
            pass

        # Valid second candle must be processed normally
        iv_ms = _INTERVAL_MS["1m"]
        feed._handle_message(json.dumps(_binance_kline_msg(
            "BTCUSDT", "1m", BASE_OPEN_TIME, BASE_OPEN_TIME + iv_ms - 1
        )))
        assert len(received) == 1, "valid candle after exception must be processed"

    # ── Strategy exceptions ───────────────────────────────────────────────────

    def test_strategy_exception_isolated_per_candle(self, tmp_path):
        """A strategy that raises must not crash the BotEngine; next candles proceed."""
        from pandas import Series

        call_count = [0]

        class _BoomStrategy:
            def generate_signals(self, bars):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("strategy exploded on first call")
                return Series(["HOLD"] * len(bars))

        cfg = BotConfig(paper_capital=1000.0, min_signal_bars=1)
        state   = BotState(buffer_size=200)
        bus     = EventBus()
        storage = _make_storage(tmp_path)
        engine  = _make_engine(cfg, _BoomStrategy(), state, bus, storage)

        iv_ms = _INTERVAL_MS["1m"]

        # First candle → strategy raises → engine must survive
        t0 = BASE_OPEN_TIME
        bus.emit(CandleEvent(
            symbol="BTCUSDT", interval="1m",
            open_time=t0, open=50_000.0, high=51_000.0, low=49_000.0,
            close=50_000.0, volume=100.0, close_time=t0 + iv_ms - 1,
        ))

        # Second candle → strategy returns HOLD normally
        t1 = t0 + iv_ms
        bus.emit(CandleEvent(
            symbol="BTCUSDT", interval="1m",
            open_time=t1, open=50_100.0, high=51_100.0, low=49_100.0,
            close=50_100.0, volume=100.0, close_time=t1 + iv_ms - 1,
        ))

        assert call_count[0] == 2, "strategy must be called for both candles"
        assert state.buffer_length("BTCUSDT", "1m") == 2

    def test_unknown_interval_does_not_break_missed_candle_detection(self):
        """An interval absent from _INTERVAL_MS must produce zero missed-candle count."""
        feed, state, bus = _make_feed(intervals=["1h"])
        received: list[CandleEvent] = []
        bus.subscribe(CandleEvent, received.append)

        # Build a raw message with an interval not in _INTERVAL_MS
        msg = {
            "stream": "btcusdt@kline_99x",
            "data": {
                "e": "kline",
                "k": {
                    "t": BASE_OPEN_TIME,
                    "T": BASE_OPEN_TIME + 999_000,
                    "s": "BTCUSDT",
                    "i": "99x",   # unknown interval
                    "o": "50000", "h": "51000", "l": "49000",
                    "c": "50500", "v": "100",
                    "x": True,
                },
            },
        }
        # Must not crash; missed_candles must remain 0
        feed._handle_message(json.dumps(msg))
        assert state.counters()["missed_candles"] == 0
