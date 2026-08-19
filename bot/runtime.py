"""Async WebSocket runtime for live Binance market data.

Connects to Binance public combined stream (no auth), receives closed kline
candles, and publishes them as ``CandleEvent`` on the ``EventBus``.

Features
--------
- Combined stream for multiple symbols/intervals
- Exponential backoff reconnect (5s → 60s cap)
- REST backfill on (re)connect: fetches last N candles to warm the buffer
- Missed-candle detection: compares expected vs received close_time
- Zero Binance API key required

WebSocket URL format::

    wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1h/ethusdt@kline_1h

Kline message format::

    {
      "stream": "btcusdt@kline_1h",
      "data": {
        "e": "kline",
        "k": {
          "t": 1700000000000,   open_time  (ms)
          "T": 1700003599999,   close_time (ms)
          "s": "BTCUSDT",
          "i": "1h",
          "o": "50000.00",
          "h": "51000.00",
          "l": "49500.00",
          "c": "50500.00",
          "v": "1234.56",
          "x": true            is_closed flag
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import websockets
import websockets.exceptions

from .config import BotConfig
from .events import (
    CandleEvent,
    DisconnectEvent,
    ErrorEvent,
    EventBus,
    ReconnectEvent,
)
from .state import BotState

log = logging.getLogger("strategy_lab.bot.runtime")

# Interval → milliseconds mapping for missed-candle detection.
# Covers every interval supported by Binance klines (and the bars_per_year
# table in jobs/backtest_job.py).  Adding a new interval here is all that is
# needed to enable missed-candle detection for it.
_INTERVAL_MS: dict[str, int] = {
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


class LiveFeed:
    """Async Binance WebSocket feed.

    Connects to the public combined stream, backfills candle history via REST,
    and delivers closed candles as ``CandleEvent`` on the event bus.

    Usage::

        feed = LiveFeed(config, state, bus)
        await feed.run()   # runs until cancelled
    """

    def __init__(self, config: BotConfig, state: BotState, bus: EventBus) -> None:
        self.config = config
        self.state  = state
        self.bus    = bus
        self._stop  = asyncio.Event()
        # (symbol, interval) → last seen close_time ms
        self._last_close_time: dict[tuple[str, str], int] = {}

    async def run(self) -> None:
        """Main loop — connects, backfills, streams.  Reconnects on failure.

        Raises ``RuntimeError`` after ``config.feed.max_reconnect_attempts``
        consecutive failures so the bot transitions to FAILED rather than
        retrying forever when the market-data connection is permanently broken.
        Set ``max_reconnect_attempts=0`` to restore unlimited retry behaviour.
        """
        attempt = 0
        delay = self.config.feed.reconnect_delay_s
        max_attempts = self.config.feed.max_reconnect_attempts

        while not self._stop.is_set():
            try:
                await self._backfill_all()
                await self._stream()
                attempt = 0
                delay = self.config.feed.reconnect_delay_s
            except asyncio.CancelledError:
                log.info("LiveFeed cancelled")
                self._stop.set()
                break
            except Exception as exc:
                attempt += 1
                self.state.increment_reconnects()
                log.warning("Feed error (attempt %d): %s", attempt, exc)
                self.bus.emit(ErrorEvent(
                    source="runtime",
                    message=f"Feed error: {exc}",
                    detail=str(type(exc).__name__),
                ))
                if self._stop.is_set():
                    break
                if max_attempts > 0 and attempt >= max_attempts:
                    raise RuntimeError(
                        f"Market data connection failed after {attempt} consecutive "
                        f"attempts (max_reconnect_attempts={max_attempts}); "
                        f"last error: {exc}"
                    ) from exc
                log.info("Reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.feed.max_reconnect_delay_s)

    async def stop(self) -> None:
        self._stop.set()

    # ── WebSocket streaming ───────────────────────────────────────────────────

    async def _stream(self) -> None:
        url = self._build_ws_url()
        log.info("Connecting to %s", url)

        async with websockets.connect(
            url,
            ping_interval=self.config.feed.heartbeat_interval_s,
            ping_timeout=self.config.feed.ping_timeout_s,
            open_timeout=self.config.feed.ws_open_timeout_s,
        ) as ws:
            log.info("WebSocket connected")
            async for raw_msg in ws:
                if self._stop.is_set():
                    break
                try:
                    self._handle_message(raw_msg)
                except Exception:
                    log.exception("Error handling WebSocket message")

    def _handle_message(self, raw: str) -> None:
        msg = json.loads(raw)
        data = msg.get("data", {})
        if data.get("e") != "kline":
            return
        k = data["k"]
        if not k.get("x", False):
            return   # candle not yet closed

        symbol   = k["s"]
        interval = k["i"]
        open_time  = int(k["t"])
        close_time = int(k["T"])
        t0 = time.monotonic()

        # Missed-candle detection
        key = (symbol, interval)
        last_ct = self._last_close_time.get(key)
        if last_ct is not None:
            interval_ms = _INTERVAL_MS.get(interval, 0)
            if interval_ms > 0:
                expected_open = last_ct + 1   # ms timestamp of the next expected candle open
                # Use >= so that EXACTLY ONE missed candle is detected.
                # When open_time == expected_open + interval_ms one candle was
                # skipped; the previous > check incorrectly returned False.
                if open_time >= expected_open + interval_ms:
                    missed = round((open_time - expected_open) / interval_ms)
                    log.warning(
                        "Missed %d candles for %s %s", missed, symbol, interval
                    )
                    self.state.increment_missed_candles(missed)
        self._last_close_time[key] = close_time

        event = CandleEvent(
            symbol=symbol,
            interval=interval,
            open_time=open_time,
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            close_time=close_time,
        )
        self.bus.emit(event)

        elapsed_ms = (time.monotonic() - t0) * 1000
        self.state.record_latency(elapsed_ms)

    # ── REST backfill ─────────────────────────────────────────────────────────

    async def _backfill_all(self) -> None:
        """Backfill all (symbol, interval) pairs with bounded concurrency.

        One shared aiohttp.ClientSession is created for the entire batch and
        closed in a finally block.  An asyncio.Semaphore caps the number of
        simultaneous in-flight REST requests so we never exceed
        config.feed.backfill_concurrency concurrent connections.

        All pairs run concurrently up to the semaphore limit; one failure never
        cancels other pairs.
        """
        cfg = self.config.feed
        pairs = [
            (sym, iv)
            for sym in cfg.symbols
            for iv in cfg.intervals
        ]
        if not pairs:
            return

        sem = asyncio.Semaphore(cfg.backfill_concurrency)
        # limit_per_host matches the semaphore — connector pool is never the
        # bottleneck and we never hold more open sockets than the semaphore allows.
        connector = aiohttp.TCPConnector(limit_per_host=cfg.backfill_concurrency)
        timeout    = aiohttp.ClientTimeout(total=cfg.rest_timeout_s)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            await asyncio.gather(
                *(self._backfill_one(sym, iv, session, sem) for sym, iv in pairs)
            )

    async def _backfill_one(
        self,
        symbol: str,
        interval: str,
        session: aiohttp.ClientSession,
        sem: asyncio.Semaphore,
    ) -> None:
        """Failure-isolated backfill for one (symbol, interval) pair.

        Any exception other than CancelledError is caught, logged, and emitted
        as an ErrorEvent so a single bad pair cannot abort the batch.
        CancelledError is always re-raised so the gather propagates cancellation.
        """
        try:
            backfilled = await self._backfill(symbol, interval, session, sem)
            log.info("Backfilled %d candles for %s %s", backfilled, symbol, interval)
            self.bus.emit(ReconnectEvent(
                symbol=symbol,
                interval=interval,
                backfilled=backfilled,
            ))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "Backfill failed for %s/%s — %s: %s",
                symbol, interval, type(exc).__name__, exc,
            )
            self.bus.emit(ErrorEvent(
                source="runtime",
                message=f"Backfill failed: {symbol}/{interval}",
                detail=f"{type(exc).__name__}: {exc}",
            ))

    async def _backfill(
        self,
        symbol: str,
        interval: str,
        session: aiohttp.ClientSession,
        sem: asyncio.Semaphore,
    ) -> int:
        """Fetch kline history via REST with semaphore-bounded concurrency and retry.

        The semaphore is acquired per attempt (released during sleep delays)
        so it does not block the connector pool between retries.

        Retry policy:
          - Transient errors (5xx, network, timeout): retry up to max_retries total.
          - Permanent errors (4xx, 429):              fail immediately, no retry.
          - CancelledError:                           propagate immediately.

        HTTP 429 is treated as permanent: retrying would worsen a rate-limit
        storm.  The operator should reduce backfill_concurrency if 429s appear.
        """
        cfg  = self.config.feed
        url  = (
            f"{cfg.rest_base_url}/klines"
            f"?symbol={symbol}&interval={interval}&limit={cfg.backfill_bars}"
        )
        max_retries = cfg.backfill_max_retries
        delay       = cfg.backfill_retry_delay_s

        for attempt in range(max_retries):
            try:
                async with sem:
                    async with session.get(url) as resp:
                        if resp.status == 429:
                            log.warning(
                                "Rate-limited (HTTP 429) for %s/%s on attempt %d/%d — "
                                "not retrying (would worsen rate-limit storm); "
                                "reduce backfill_concurrency if this recurs",
                                symbol, interval, attempt + 1, max_retries,
                            )
                            resp.raise_for_status()   # raises ClientResponseError(429)
                        resp.raise_for_status()
                        data: list = await resp.json()
                # Semaphore released; process response outside it so we free the
                # slot for other pairs immediately.
                return self._process_kline_rows(data, symbol, interval)

            except asyncio.CancelledError:
                raise

            except aiohttp.ClientResponseError as exc:
                # 4xx and 429 are permanent — no point retrying.
                if exc.status < 500:
                    raise
                if attempt == max_retries - 1:
                    raise
                log.warning(
                    "Backfill HTTP %d for %s/%s; retry %d/%d in %.1fs",
                    exc.status, symbol, interval, attempt + 1, max_retries, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == max_retries - 1:
                    raise
                log.warning(
                    "Backfill %s for %s/%s; retry %d/%d in %.1fs",
                    type(exc).__name__, symbol, interval, attempt + 1, max_retries, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2

        raise RuntimeError(  # unreachable: loop always returns or raises
            f"backfill retry loop exited unexpectedly for {symbol}/{interval}"
        )

    def _process_kline_rows(self, data: list, symbol: str, interval: str) -> int:
        """Convert raw Binance kline rows into CandleEvents and push to the bus.

        Rows where close_time is within 1 second of now are skipped — the candle
        may still be open.  All emitted events have is_history=True so the engine
        warms buffers without submitting orders.
        """
        now_ms = int(time.time() * 1000)
        count  = 0
        for row in data:
            # row: [open_time, open, high, low, close, volume, close_time, ...]
            close_time = int(row[6])
            if close_time > now_ms - 1000:
                continue   # candle may not be fully closed yet
            event = CandleEvent(
                symbol=symbol,
                interval=interval,
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=close_time,
                is_history=True,
            )
            self.bus.emit(event)
            self._last_close_time[(symbol, interval)] = close_time
            count += 1
        return count

    # ── URL builder ───────────────────────────────────────────────────────────

    _BINANCE_MAX_STREAMS = 1024

    def _build_ws_url(self) -> str:
        cfg = self.config.feed
        n_streams = len(cfg.symbols) * len(cfg.intervals)
        if n_streams > self._BINANCE_MAX_STREAMS:
            raise ValueError(
                f"Stream count {n_streams} ({len(cfg.symbols)} symbols × "
                f"{len(cfg.intervals)} intervals) exceeds Binance's "
                f"{self._BINANCE_MAX_STREAMS}-stream-per-connection limit. "
                "Reduce the number of symbols or intervals."
            )
        streams = "/".join(
            f"{sym.lower()}@kline_{iv}"
            for sym in cfg.symbols
            for iv in cfg.intervals
        )
        return f"{cfg.ws_base_url}?streams={streams}"
