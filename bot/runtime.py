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

# Interval → milliseconds mapping for missed-candle detection
_INTERVAL_MS: dict[str, int] = {
    "1m":  60_000,
    "3m":  3 * 60_000,
    "5m":  5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h":  60 * 60_000,
    "2h":  2 * 60 * 60_000,
    "4h":  4 * 60 * 60_000,
    "1d":  24 * 60 * 60_000,
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
        """Main loop — connects, backfills, streams.  Reconnects on failure."""
        attempt = 0
        delay = self.config.feed.reconnect_delay_s

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
                expected_open = last_ct + 1
                if open_time > expected_open + interval_ms:
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
        cfg = self.config.feed
        for symbol in cfg.symbols:
            for interval in cfg.intervals:
                try:
                    backfilled = await self._backfill(symbol, interval)
                    log.info(
                        "Backfilled %d candles for %s %s",
                        backfilled, symbol, interval,
                    )
                    self.bus.emit(ReconnectEvent(
                        symbol=symbol,
                        interval=interval,
                        backfilled=backfilled,
                    ))
                except Exception:
                    log.exception("Backfill failed for %s %s", symbol, interval)

    async def _backfill(self, symbol: str, interval: str) -> int:
        limit = self.config.feed.backfill_bars
        url = (
            f"{self.config.feed.rest_base_url}/klines"
            f"?symbol={symbol}&interval={interval}&limit={limit}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.config.feed.rest_timeout_s)) as resp:
                resp.raise_for_status()
                data = await resp.json()

        count = 0
        for row in data:
            # row: [open_time, open, high, low, close, volume, close_time, ...]
            close_time = int(row[6])
            # Skip the last (open) candle — it may not be closed yet
            if close_time > int(time.time() * 1000) - 1000:
                continue
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
            )
            self.bus.emit(event)
            self._last_close_time[(symbol, interval)] = close_time
            count += 1

        return count

    # ── URL builder ───────────────────────────────────────────────────────────

    def _build_ws_url(self) -> str:
        cfg = self.config.feed
        streams = "/".join(
            f"{sym.lower()}@kline_{iv}"
            for sym in cfg.symbols
            for iv in cfg.intervals
        )
        return f"{cfg.ws_base_url}?streams={streams}"
