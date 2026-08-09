"""In-memory mutable bot state.

Centralises the runtime counters and candle buffers that the engine and
scheduler need to share without direct coupling.  All access is
thread-safe so the async event loop and synchronous monitoring callbacks
can coexist safely.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CandleRow:
    """A single OHLCV candle as received from the feed."""

    symbol:     str
    interval:   str
    open_time:  int      # Unix ms
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     float
    close_time: int      # Unix ms


class BotState:
    """Thread-safe container for all mutable bot runtime state.

    Components that need to share state (engine, scheduler, monitor, dashboard)
    receive the single shared ``BotState`` instance.  Never access the private
    ``_*`` attributes directly — use the provided methods.
    """

    def __init__(self, buffer_size: int = 500) -> None:
        self._lock = threading.Lock()
        self._buffer_size = buffer_size

        # Candle ring buffers: (symbol, interval) → deque[CandleRow]
        self._buffers: dict[tuple[str, str], deque[CandleRow]] = {}

        # Last known mark price per symbol (updated on each candle close)
        self._mark_prices: dict[str, float] = {}

        # Runtime counters
        self._start_time:     float = time.monotonic()
        self._candles_total:  int   = 0
        self._missed_candles: int   = 0
        self._reconnects:     int   = 0

        # Latency tracking (rolling, last 60 values)
        self._latencies: deque[float] = deque(maxlen=60)

    # ── Candle buffers ────────────────────────────────────────────────────────

    def push_candle(self, candle: CandleRow) -> None:
        key = (candle.symbol, candle.interval)
        with self._lock:
            if key not in self._buffers:
                self._buffers[key] = deque(maxlen=self._buffer_size)
            self._buffers[key].append(candle)
            self._mark_prices[candle.symbol] = candle.close
            self._candles_total += 1

    def get_buffer_df(self, symbol: str, interval: str) -> pd.DataFrame:
        """Return the candle buffer as a pandas DataFrame (copy).

        Sorts ascending by open_time and deduplicates (last-write-wins per
        open_time) so a post-reconnect re-backfill never delivers a corrupt
        or duplicated DataFrame to the strategy.
        """
        key = (symbol, interval)
        with self._lock:
            buf = list(self._buffers.get(key, []))

        if not buf:
            return pd.DataFrame()

        # Sort ascending; deduplicate keeping the last occurrence of each open_time
        # so that a re-backfill after reconnect overwrites stale entries.
        buf.sort(key=lambda c: c.open_time)
        seen: dict[int, CandleRow] = {}
        for c in buf:
            seen[c.open_time] = c
        buf = list(seen.values())

        rows = [
            {
                "open":   c.open,
                "high":   c.high,
                "low":    c.low,
                "close":  c.close,
                "volume": c.volume,
            }
            for c in buf
        ]
        # Use close_time as index (ms → UTC datetime)
        idx = pd.to_datetime([c.close_time for c in buf], unit="ms", utc=True)
        return pd.DataFrame(rows, index=idx)

    def buffer_length(self, symbol: str, interval: str) -> int:
        with self._lock:
            return len(self._buffers.get((symbol, interval), []))

    # ── Mark prices ───────────────────────────────────────────────────────────

    def mark_price(self, symbol: str) -> float | None:
        with self._lock:
            return self._mark_prices.get(symbol)

    def all_mark_prices(self) -> dict[str, float]:
        with self._lock:
            return dict(self._mark_prices)

    # ── Runtime counters ──────────────────────────────────────────────────────

    def uptime_s(self) -> float:
        return time.monotonic() - self._start_time

    def increment_missed_candles(self, n: int = 1) -> None:
        with self._lock:
            self._missed_candles += n

    def increment_reconnects(self) -> None:
        with self._lock:
            self._reconnects += 1

    def record_latency(self, ms: float) -> None:
        with self._lock:
            self._latencies.append(ms)

    def avg_latency_ms(self) -> float | None:
        with self._lock:
            if not self._latencies:
                return None
            return sum(self._latencies) / len(self._latencies)

    def counters(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uptime_s":       self.uptime_s(),
                "candles_total":  self._candles_total,
                "missed_candles": self._missed_candles,
                "reconnects":     self._reconnects,
                "avg_latency_ms": (
                    sum(self._latencies) / len(self._latencies)
                    if self._latencies else None
                ),
            }

    def active_symbols(self) -> int:
        with self._lock:
            return len({sym for sym, _ in self._buffers})
