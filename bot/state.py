"""In-memory mutable bot state.

Centralises the runtime counters and candle buffers that the engine and
scheduler need to share without direct coupling.  All access is
thread-safe so the async event loop and synchronous monitoring callbacks
can coexist safely.

Candle buffer optimisation (Phase 2A)
--------------------------------------
get_buffer_df() used to sort + dedup + rebuild a DataFrame on every call.
The new design tracks order per buffer and caches the built DataFrame:

  Normal live append (t > last_t):
    O(1) deque.append — is_ordered stays True — cache invalidated.

  Same-candle update (t == last_t, e.g. live kline update):
    O(1) in-place replace of deque[-1] — is_ordered stays True — cache invalidated.

  Out-of-order / backfill (t < last_t):
    O(1) deque.append — is_ordered set False — cache invalidated.

  get_buffer_df():
    Cache hit  → O(N) defensive copy (callers may freely mutate the
                 returned DataFrame; the cache is never corrupted).
    Cache miss, ordered  → O(N) list+DataFrame, no sort/dedup.
    Cache miss, unordered → O(N log N) sort + O(N) dedup + O(N) DataFrame,
                            then deque is repaired in-place so subsequent
                            in-order pushes revert to the fast path.

The lock is held for the full get_buffer_df() body.  At real candle rates
(≤1 per second per stream), lock contention is negligible.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
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
        # Kept as public-private for backward compatibility with tests that
        # inspect state._buffers directly.
        self._buffers: dict[tuple[str, str], deque[CandleRow]] = {}

        # Per-buffer optimisation metadata (parallel to _buffers)
        # _buf_ordered: True  → deque is sorted ascending and has no duplicate open_times
        # _buf_last_t:  highest open_time pushed so far (-1 if empty)
        # _buf_df:      cached DataFrame (None until first build)
        # _buf_valid:   True → _buf_df is current and safe to return
        self._buf_ordered: dict[tuple[str, str], bool]                  = {}
        self._buf_last_t:  dict[tuple[str, str], int]                   = {}
        self._buf_df:      dict[tuple[str, str], pd.DataFrame | None]   = {}
        self._buf_valid:   dict[tuple[str, str], bool]                  = {}

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
        """Push a candle into the appropriate ring buffer.

        Tracks whether the buffer remains in sorted, deduplicated order so
        get_buffer_df() can skip expensive sort/dedup on the hot path.
        """
        key = (candle.symbol, candle.interval)
        with self._lock:
            if key not in self._buffers:
                self._buffers[key]    = deque(maxlen=self._buffer_size)
                self._buf_ordered[key] = True
                self._buf_last_t[key]  = -1
                self._buf_df[key]      = None
                self._buf_valid[key]   = False

            t      = candle.open_time
            last_t = self._buf_last_t[key]
            buf    = self._buffers[key]

            if t > last_t:
                # Common case: in-order live candle — O(1) append
                buf.append(candle)
                self._buf_last_t[key] = t
                # is_ordered unchanged (True stays True; False stays False until repair)

            elif t == last_t:
                # Same open_time: update the current candle in place (live kline update)
                if buf and buf[-1].open_time == t:
                    buf[-1] = candle   # O(1) deque setitem
                else:
                    # Edge case: last_t matches but deque tail doesn't — treat as unordered
                    buf.append(candle)
                    self._buf_ordered[key] = False

            else:
                # Out-of-order arrival (backfill / reconnect overlap)
                buf.append(candle)
                self._buf_ordered[key] = False

            # Always invalidate the cached DataFrame after any push
            self._buf_valid[key] = False

            self._mark_prices[candle.symbol] = candle.close
            self._candles_total += 1

    def get_buffer_df(self, symbol: str, interval: str) -> pd.DataFrame:
        """Return the candle buffer as a pandas DataFrame.

        Sorts ascending by open_time and deduplicates (last-write-wins per
        open_time) so a post-reconnect re-backfill never delivers a corrupt
        or duplicated DataFrame to the strategy.

        The result is cached; repeated calls with no intervening push are O(1).
        Pandas 3.0+ Copy-on-Write semantics protect the cached DataFrame from
        accidental mutation by callers — no explicit .copy() is needed.
        """
        key = (symbol, interval)
        with self._lock:
            if key not in self._buffers or not self._buffers[key]:
                return pd.DataFrame()

            # ── Cache hit ──────────────────────────────────────────────────────
            if self._buf_valid[key] and self._buf_df[key] is not None:
                return self._buf_df[key].copy()

            buf        = self._buffers[key]
            is_ordered = self._buf_ordered[key]

            if is_ordered:
                # ── Fast path: deque is sorted and has no duplicates ───────────
                candles = list(buf)
            else:
                # ── Full sort + dedup (reconnect / backfill) ───────────────────
                candles = list(buf)
                candles.sort(key=lambda c: c.open_time)
                seen: dict[int, CandleRow] = {}
                for c in candles:
                    seen[c.open_time] = c
                candles = list(seen.values())

                # Repair the deque in-place so future pushes use the fast path.
                # Safe because we hold the lock throughout.
                buf.clear()
                for c in candles:
                    buf.append(c)
                if candles:
                    self._buf_last_t[key] = candles[-1].open_time
                self._buf_ordered[key] = True

            rows = [
                {
                    "open_time": c.open_time,  # ms since epoch at candle open
                    "open":      c.open,
                    "high":      c.high,
                    "low":       c.low,
                    "close":     c.close,
                    "volume":    c.volume,
                }
                for c in candles
            ]
            # Use close_time as index (ms → UTC datetime)
            idx = pd.to_datetime([c.close_time for c in candles], unit="ms", utc=True)
            df  = pd.DataFrame(rows, index=idx)

            self._buf_df[key]    = df
            self._buf_valid[key] = True
            return df.copy()

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
