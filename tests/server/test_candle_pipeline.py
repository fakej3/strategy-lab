"""Tests for the OHLCV candle data pipeline: BotState → get_candles() → API.

Covers:
- Output shape and field presence
- `time` field uses open_time (not close_time)
- Ascending open_time ordering
- Duplicate open_time deduplication (last write wins)
- limit parameter respected
- Empty buffer returns []
- Multi-symbol isolation (BTCUSDT buffer doesn't pollute ETHUSDT)
- Chart update deduplication invariant (same open_time → in-place update)
"""
from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from bot.state import BotState, CandleRow
from server.bot_manager import BotManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_candle(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_time_ms: int = 1_700_000_000_000,
    open: float = 65_000.0,
    high: float = 65_050.0,
    low: float = 64_990.0,
    close: float = 65_030.0,
    volume: float = 1.5,
) -> CandleRow:
    """Return a CandleRow with close_time = open_time + 59_999 ms (1m candle)."""
    return CandleRow(
        symbol=symbol,
        interval=interval,
        open_time=open_time_ms,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        close_time=open_time_ms + 59_999,
    )


def _make_manager_with_candles(candles: list[CandleRow]) -> BotManager:
    """Return a BotManager whose _state contains the given candles."""
    mgr = BotManager()
    state = BotState()
    for c in candles:
        state.push_candle(c)
    mgr._state = state
    return mgr


# ── Output format ─────────────────────────────────────────────────────────────

class TestGetCandlesFormat:
    def test_returns_list_of_dicts(self):
        c = _make_candle()
        mgr = _make_manager_with_candles([c])
        result = mgr.get_candles("BTCUSDT", "1m")
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_required_fields_present(self):
        c = _make_candle()
        mgr = _make_manager_with_candles([c])
        row = mgr.get_candles("BTCUSDT", "1m")[0]
        for field in ("time", "open", "high", "low", "close", "volume"):
            assert field in row, f"Field '{field}' missing from get_candles() output"

    def test_time_uses_open_time_not_close_time(self):
        open_ms = 1_700_000_000_000
        c = _make_candle(open_time_ms=open_ms)
        mgr = _make_manager_with_candles([c])
        row = mgr.get_candles("BTCUSDT", "1m")[0]
        expected_time = open_ms // 1000   # Unix seconds at candle OPEN
        assert row["time"] == expected_time, (
            f"time={row['time']} but expected open_time_sec={expected_time}. "
            "The chart uses open_time as the canonical x-axis key."
        )

    def test_time_is_not_close_time(self):
        open_ms = 1_700_000_000_000
        c = _make_candle(open_time_ms=open_ms)
        mgr = _make_manager_with_candles([c])
        row = mgr.get_candles("BTCUSDT", "1m")[0]
        close_time_sec = (open_ms + 59_999) // 1000
        assert row["time"] != close_time_sec, (
            "time should be open_time (candle start), not close_time (candle end)"
        )

    def test_ohlcv_values_match_candle(self):
        c = _make_candle(open=65_000.0, high=65_050.0, low=64_990.0,
                         close=65_030.0, volume=1.5)
        mgr = _make_manager_with_candles([c])
        row = mgr.get_candles("BTCUSDT", "1m")[0]
        assert row["open"]   == 65_000.0
        assert row["high"]   == 65_050.0
        assert row["low"]    == 64_990.0
        assert row["close"]  == 65_030.0
        assert row["volume"] == 1.5

    def test_empty_buffer_returns_empty_list(self):
        mgr = _make_manager_with_candles([])
        result = mgr.get_candles("BTCUSDT", "1m")
        assert result == []

    def test_no_state_returns_empty_list(self):
        mgr = BotManager()
        # _state is None by default (bot not running)
        assert mgr._state is None
        result = mgr.get_candles("BTCUSDT", "1m")
        assert result == []

    def test_missing_symbol_returns_empty_list(self):
        c = _make_candle(symbol="BTCUSDT")
        mgr = _make_manager_with_candles([c])
        result = mgr.get_candles("ETHUSDT", "1m")
        assert result == []


# ── Ordering ──────────────────────────────────────────────────────────────────

class TestGetCandlesOrdering:
    def _btc_sequence(self, n: int) -> list[CandleRow]:
        base = 1_700_000_000_000
        return [
            _make_candle(open_time_ms=base + i * 60_000, close=65_000 + i)
            for i in range(n)
        ]

    def test_candles_ordered_by_open_time_ascending(self):
        candles = self._btc_sequence(10)
        # Insert in reverse to test that sorting is applied
        mgr = _make_manager_with_candles(list(reversed(candles)))
        result = mgr.get_candles("BTCUSDT", "1m")
        times = [r["time"] for r in result]
        assert times == sorted(times), "Candles must be ascending by open_time"

    def test_latest_candle_is_last(self):
        candles = self._btc_sequence(5)
        mgr = _make_manager_with_candles(candles)
        result = mgr.get_candles("BTCUSDT", "1m")
        assert result[-1]["close"] == 65_004.0   # last candle in sequence


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestGetCandlesDeduplication:
    def test_duplicate_open_time_keeps_last_written(self):
        """Two CandleRows with the same open_time — last-write wins."""
        t = 1_700_000_000_000
        first  = _make_candle(open_time_ms=t, close=65_000.0)
        second = _make_candle(open_time_ms=t, close=65_999.0)  # same open_time
        mgr = _make_manager_with_candles([first, second])
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1
        assert result[0]["close"] == 65_999.0, "Last-write should win for duplicate open_time"

    def test_different_open_times_both_present(self):
        t = 1_700_000_000_000
        c1 = _make_candle(open_time_ms=t,            close=65_000.0)
        c2 = _make_candle(open_time_ms=t + 60_000,   close=65_100.0)
        mgr = _make_manager_with_candles([c1, c2])
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 2


# ── Limit parameter ───────────────────────────────────────────────────────────

class TestGetCandlesLimit:
    def test_limit_truncates_to_most_recent(self):
        base = 1_700_000_000_000
        candles = [_make_candle(open_time_ms=base + i * 60_000) for i in range(50)]
        mgr = _make_manager_with_candles(candles)
        result = mgr.get_candles("BTCUSDT", "1m", limit=10)
        assert len(result) == 10
        # Should be the LAST 10 (most recent)
        expected_last_time = (base + 49 * 60_000) // 1000
        assert result[-1]["time"] == expected_last_time

    def test_limit_larger_than_buffer_returns_all(self):
        base = 1_700_000_000_000
        candles = [_make_candle(open_time_ms=base + i * 60_000) for i in range(5)]
        mgr = _make_manager_with_candles(candles)
        result = mgr.get_candles("BTCUSDT", "1m", limit=200)
        assert len(result) == 5


# ── Multi-symbol isolation ────────────────────────────────────────────────────

class TestMultiSymbolIsolation:
    def test_btc_candles_do_not_appear_in_eth_query(self):
        btc = _make_candle(symbol="BTCUSDT", close=65_000.0)
        eth = _make_candle(symbol="ETHUSDT", close=3_500.0)
        mgr = _make_manager_with_candles([btc, eth])
        btc_result = mgr.get_candles("BTCUSDT", "1m")
        eth_result = mgr.get_candles("ETHUSDT", "1m")
        assert len(btc_result) == 1
        assert len(eth_result) == 1
        assert btc_result[0]["close"] == 65_000.0
        assert eth_result[0]["close"] == 3_500.0

    def test_interval_isolation(self):
        """Same symbol, different intervals — separate buffers."""
        c1m  = _make_candle(interval="1m",  close=65_000.0)
        c1h  = _make_candle(interval="1h",  close=64_000.0)
        mgr = _make_manager_with_candles([c1m, c1h])
        assert mgr.get_candles("BTCUSDT", "1m")[0]["close"] == 65_000.0
        assert mgr.get_candles("BTCUSDT", "1h")[0]["close"] == 64_000.0

    def test_multiple_symbols_all_accessible(self):
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        closes  = [65_000.0,   3_500.0,   140.0]
        candles = [_make_candle(symbol=s, close=c) for s, c in zip(symbols, closes)]
        mgr = _make_manager_with_candles(candles)
        for sym, expected in zip(symbols, closes):
            result = mgr.get_candles(sym, "1m")
            assert len(result) == 1
            assert result[0]["close"] == expected


# ── Chart update deduplication invariant ─────────────────────────────────────

class TestChartUpdateInvariant:
    """Verify the REST → chart.setData and WS → chart.updateCandle are consistent.

    Both use time = open_time_sec.  A WS candle update with the same open_time
    as the last REST candle must match (so the frontend can update in-place).
    """
    def test_rest_time_matches_ws_time_formula(self):
        open_ms = 1_700_000_000_000
        c = _make_candle(open_time_ms=open_ms)
        mgr = _make_manager_with_candles([c])
        rest_time = mgr.get_candles("BTCUSDT", "1m")[0]["time"]

        # WS event delivers open_time as an int ms timestamp.
        # Frontend applies: Math.floor(ev.open_time / 1000)
        ws_time = open_ms // 1000   # Python equivalent

        assert rest_time == ws_time, (
            "REST and WS must produce the same `time` value for the same candle "
            "so chart.updateCandle() can deduplicate correctly."
        )
