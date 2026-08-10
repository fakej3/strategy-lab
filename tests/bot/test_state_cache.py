"""Phase 2A regression tests — BotState candle buffer cache.

Covers every cache-correctness scenario from the Phase 2H specification:

  - cache hit (no push between calls)
  - cache invalidation (push invalidates cache)
  - duplicate candle (same open_time, last-write-wins)
  - out-of-order candle (backfill / reconnect)
  - deque repair after sort+dedup
  - reconnect / backfill correctness
  - maxlen / buffer overflow
  - symbol isolation
  - interval isolation
  - mutation safety (caller cannot corrupt cached DataFrame)
  - same-open_time in-place update (live kline partial close)
  - is_ordered flag lifecycle
"""
from __future__ import annotations

import threading
import time

import pandas as pd
import pytest

from bot.state import BotState, CandleRow

BASE_MS  = 1_700_000_000_000
IV_MS    = 60_000           # 1-minute interval in ms


# ── Helpers ────────────────────────────────────────────────────────────────────

def _c(
    i: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    close: float = 50_000.0,
) -> CandleRow:
    """Return a CandleRow at sequential time slot *i*."""
    t = BASE_MS + i * IV_MS
    return CandleRow(
        symbol=symbol, interval=interval,
        open_time=t,
        open=50_000.0, high=50_100.0, low=49_900.0,
        close=close, volume=1.0,
        close_time=t + IV_MS - 1,
    )


def _push_seq(state: BotState, n: int, symbol="BTCUSDT", interval="1h") -> None:
    """Push *n* in-order candles."""
    for i in range(n):
        state.push_candle(_c(i, symbol=symbol, interval=interval))


# ── 1. Cache hit ───────────────────────────────────────────────────────────────

class TestCacheHit:
    def test_repeated_get_returns_equal_data(self):
        """get_buffer_df with no push between calls must return identical data."""
        state = BotState(buffer_size=100)
        _push_seq(state, 10)

        df1 = state.get_buffer_df("BTCUSDT", "1h")
        df2 = state.get_buffer_df("BTCUSDT", "1h")
        # Returns a defensive copy each time — data must be equal, not same object.
        assert df1.equals(df2), "cache hit must return equal DataFrame content"

    def test_cache_hit_is_fast(self):
        """10 000 repeated reads (no push) must complete in under 1.0 s.

        Each cache hit returns df.copy() for mutation safety, so this is O(N)
        per call, not O(1).  The threshold is generous — a cold rebuild of
        500 candles takes ~45 s for 10k calls; the cache makes it ~8× faster.
        """
        state = BotState(buffer_size=500)
        _push_seq(state, 500)
        state.get_buffer_df("BTCUSDT", "1h")  # warm cache

        n = 10_000
        t0 = time.perf_counter()
        for _ in range(n):
            state.get_buffer_df("BTCUSDT", "1h")
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"10k cache-hits took {elapsed:.3f}s (expected < 1.0s)"

    def test_cache_valid_flag_set_after_build(self):
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        state.get_buffer_df("BTCUSDT", "1h")
        assert state._buf_valid[("BTCUSDT", "1h")] is True


# ── 2. Cache invalidation ──────────────────────────────────────────────────────

class TestCacheInvalidation:
    def test_push_invalidates_cache(self):
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        state.get_buffer_df("BTCUSDT", "1h")        # build cache
        assert state._buf_valid[("BTCUSDT", "1h")]  # cached

        state.push_candle(_c(5))                     # push → invalidate
        assert not state._buf_valid[("BTCUSDT", "1h")]

    def test_get_after_push_returns_new_data(self):
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        df1 = state.get_buffer_df("BTCUSDT", "1h")

        state.push_candle(_c(5, close=99_999.0))
        df2 = state.get_buffer_df("BTCUSDT", "1h")

        assert len(df2) == len(df1) + 1
        assert df2.iloc[-1]["close"] == pytest.approx(99_999.0)

    def test_each_push_invalidates_independently_per_key(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(0, symbol="BTCUSDT"))
        state.push_candle(_c(0, symbol="ETHUSDT"))
        state.get_buffer_df("BTCUSDT", "1h")
        state.get_buffer_df("ETHUSDT", "1h")

        # Push only BTC
        state.push_candle(_c(1, symbol="BTCUSDT"))
        assert not state._buf_valid[("BTCUSDT", "1h")]
        assert state._buf_valid[("ETHUSDT", "1h")]   # ETH cache still valid


# ── 3. Duplicate candle (same open_time) ──────────────────────────────────────

class TestDuplicateCandle:
    def test_same_open_time_last_write_wins(self):
        """Two pushes with the same open_time → last value survives."""
        state = BotState(buffer_size=100)
        state.push_candle(_c(0, close=100.0))
        state.push_candle(_c(0, close=200.0))  # same open_time
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 1
        assert df.iloc[0]["close"] == pytest.approx(200.0)

    def test_same_open_time_inplace_update_preserves_order(self):
        """In-place update of the latest candle must not disturb other rows."""
        state = BotState(buffer_size=100)
        _push_seq(state, 5)                        # candles 0..4
        state.push_candle(_c(4, close=99_000.0))   # update candle 4
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 5
        assert df.iloc[-1]["close"] == pytest.approx(99_000.0)

    def test_is_ordered_stays_true_after_same_t_update(self):
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        state.push_candle(_c(4, close=1.0))   # update last candle
        assert state._buf_ordered[("BTCUSDT", "1h")] is True

    def test_df_index_unique_after_duplicate_push(self):
        state = BotState(buffer_size=100)
        for _ in range(3):
            state.push_candle(_c(0, close=float(_)))
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 1
        assert len(df.index.unique()) == 1


# ── 4. Out-of-order candle ────────────────────────────────────────────────────

class TestOutOfOrderCandle:
    def test_out_of_order_push_sets_is_ordered_false(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(5))
        state.push_candle(_c(3))   # out of order
        assert state._buf_ordered[("BTCUSDT", "1h")] is False

    def test_df_sorted_ascending_after_out_of_order_push(self):
        state = BotState(buffer_size=100)
        # Push in reverse order
        for i in reversed(range(10)):
            state.push_candle(_c(i))
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 10
        ts = df.index.tolist()
        assert ts == sorted(ts), "DataFrame must be in ascending order"

    def test_deque_repaired_after_unordered_build(self):
        """After get_buffer_df on an unordered buffer, deque must be repaired."""
        state = BotState(buffer_size=100)
        for i in reversed(range(10)):
            state.push_candle(_c(i))
        assert state._buf_ordered[("BTCUSDT", "1h")] is False

        state.get_buffer_df("BTCUSDT", "1h")   # triggers repair
        assert state._buf_ordered[("BTCUSDT", "1h")] is True

    def test_post_repair_ordered_push_uses_fast_path(self):
        """After deque repair, the next in-order push keeps is_ordered=True."""
        state = BotState(buffer_size=100)
        for i in reversed(range(10)):
            state.push_candle(_c(i))
        state.get_buffer_df("BTCUSDT", "1h")   # repair
        state.push_candle(_c(10))              # in-order push after repair
        assert state._buf_ordered[("BTCUSDT", "1h")] is True


# ── 5. Reconnect / backfill ───────────────────────────────────────────────────

class TestReconnectBackfill:
    def test_re_backfill_deduplicates(self):
        """Re-backfill after reconnect must not produce duplicate rows in the DF."""
        state = BotState(buffer_size=200)
        # Initial backfill
        for i in range(10):
            state.push_candle(_c(i))
        # Live candle
        state.push_candle(_c(10))
        # Re-backfill (same candles again)
        for i in range(10):
            state.push_candle(_c(i))
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == len(df.index.unique()), "No duplicate index after re-backfill"

    def test_re_backfill_last_write_wins(self):
        """Last-written value for each open_time must survive dedup."""
        state = BotState(buffer_size=200)
        state.push_candle(_c(0, close=100.0))
        state.push_candle(_c(0, close=999.0))   # re-backfill with different value
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert df.iloc[0]["close"] == pytest.approx(999.0)

    def test_re_backfill_does_not_lose_live_candles(self):
        """Live candles at higher open_times must survive re-backfill."""
        state = BotState(buffer_size=200)
        # Backfill
        for i in range(8):
            state.push_candle(_c(i))
        # Live
        state.push_candle(_c(8))
        state.push_candle(_c(9))
        df_before = state.get_buffer_df("BTCUSDT", "1h")

        # Re-backfill (same 8 candles)
        for i in range(8):
            state.push_candle(_c(i))
        df_after = state.get_buffer_df("BTCUSDT", "1h")

        assert len(df_after) >= len(df_before)

    def test_ascending_order_after_re_backfill(self):
        state = BotState(buffer_size=200)
        for i in range(5):
            state.push_candle(_c(i))
        # Re-push 3 older candles (reconnect simulated)
        for i in range(3):
            state.push_candle(_c(i))
        df = state.get_buffer_df("BTCUSDT", "1h")
        ts = df.index.tolist()
        assert ts == sorted(ts)


# ── 6. Buffer overflow (maxlen) ───────────────────────────────────────────────

class TestMaxlen:
    def test_buffer_bounded_by_buffer_size(self):
        state = BotState(buffer_size=50)
        for i in range(200):
            state.push_candle(_c(i))
        assert state.buffer_length("BTCUSDT", "1h") == 50

    def test_df_length_bounded_by_buffer_size(self):
        state = BotState(buffer_size=50)
        for i in range(200):
            state.push_candle(_c(i))
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 50

    def test_most_recent_candles_retained_after_overflow(self):
        """After overflow, the MOST RECENT candles are kept (oldest dropped)."""
        state = BotState(buffer_size=10)
        for i in range(20):
            state.push_candle(_c(i))
        df = state.get_buffer_df("BTCUSDT", "1h")
        # First retained candle should be candle 10 (candles 0-9 were dropped)
        expected_first_t = (BASE_MS + 10 * IV_MS + IV_MS - 1)  # close_time of candle 10
        assert df.index[0] == pd.Timestamp(expected_first_t * 1_000_000, tz="UTC")

    def test_ordered_flag_survives_buffer_overflow(self):
        """Buffer overflow (maxlen drop) must not corrupt the ordered flag."""
        state = BotState(buffer_size=5)
        for i in range(20):   # overflow repeatedly
            state.push_candle(_c(i))
        assert state._buf_ordered[("BTCUSDT", "1h")] is True


# ── 7. Symbol isolation ───────────────────────────────────────────────────────

class TestSymbolIsolation:
    def test_btc_push_does_not_affect_eth_cache(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(0, symbol="BTCUSDT"))
        state.push_candle(_c(0, symbol="ETHUSDT"))
        state.get_buffer_df("BTCUSDT", "1h")
        state.get_buffer_df("ETHUSDT", "1h")

        state.push_candle(_c(1, symbol="BTCUSDT"))
        # ETH cache must still be valid
        assert state._buf_valid[("ETHUSDT", "1h")] is True

    def test_out_of_order_btc_does_not_contaminate_eth(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(5, symbol="BTCUSDT"))
        state.push_candle(_c(3, symbol="BTCUSDT"))   # OOO → BTC unordered
        state.push_candle(_c(0, symbol="ETHUSDT"))   # ETH in-order

        assert state._buf_ordered[("BTCUSDT", "1h")] is False
        assert state._buf_ordered[("ETHUSDT", "1h")] is True

    def test_100_symbols_all_isolated(self):
        """Each of 100 symbols has its own independent buffer and cache."""
        state = BotState(buffer_size=50)
        symbols = [f"SYM{i:03d}USDT" for i in range(100)]
        for s in symbols:
            state.push_candle(_c(0, symbol=s, close=float(symbols.index(s))))
        for s in symbols:
            df = state.get_buffer_df(s, "1h")
            assert len(df) == 1
            assert df.iloc[0]["close"] == pytest.approx(float(symbols.index(s)))


# ── 8. Interval isolation ─────────────────────────────────────────────────────

class TestIntervalIsolation:
    def test_1h_push_does_not_invalidate_4h_cache(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(0, interval="1h"))
        state.push_candle(_c(0, interval="4h"))
        state.get_buffer_df("BTCUSDT", "1h")
        state.get_buffer_df("BTCUSDT", "4h")

        state.push_candle(_c(1, interval="1h"))
        assert state._buf_valid[("BTCUSDT", "4h")] is True   # unchanged

    def test_three_intervals_all_independent(self):
        state = BotState(buffer_size=100)
        for iv in ("1m", "5m", "1h"):
            for i in range(5):
                state.push_candle(_c(i, interval=iv))
        for iv in ("1m", "5m", "1h"):
            df = state.get_buffer_df("BTCUSDT", iv)
            assert len(df) == 5


# ── 9. Mutation safety (CoW) ──────────────────────────────────────────────────

class TestMutationSafety:
    def test_caller_adding_column_does_not_corrupt_cache(self):
        """Pandas 3.0 CoW: adding a column on the returned DF must not corrupt cache."""
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        df = state.get_buffer_df("BTCUSDT", "1h")
        df["new_col"] = 42   # CoW triggers copy on the caller's side

        df2 = state.get_buffer_df("BTCUSDT", "1h")
        assert "new_col" not in df2.columns, "Cache must not be mutated by caller"

    def test_original_df_length_unchanged_after_caller_mutation(self):
        state = BotState(buffer_size=100)
        _push_seq(state, 5)
        df = state.get_buffer_df("BTCUSDT", "1h")
        # Simulate mutation attempt (CoW makes this a no-op on the cache)
        try:
            df.iloc[0, 0] = -1.0
        except Exception:
            pass   # pandas may raise on CoW; either way cache is protected

        df2 = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df2) == 5
        assert df2.iloc[0]["open"] == pytest.approx(50_000.0)


# ── 10. is_ordered flag lifecycle ─────────────────────────────────────────────

class TestIsOrderedLifecycle:
    def test_new_buffer_is_ordered(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(0))
        assert state._buf_ordered[("BTCUSDT", "1h")] is True

    def test_sequential_pushes_keep_ordered(self):
        state = BotState(buffer_size=100)
        for i in range(20):
            state.push_candle(_c(i))
        assert state._buf_ordered[("BTCUSDT", "1h")] is True

    def test_out_of_order_clears_ordered(self):
        state = BotState(buffer_size=100)
        state.push_candle(_c(10))
        state.push_candle(_c(5))    # OOO
        assert state._buf_ordered[("BTCUSDT", "1h")] is False

    def test_ordered_restored_after_repair(self):
        state = BotState(buffer_size=100)
        for i in reversed(range(10)):
            state.push_candle(_c(i))
        assert state._buf_ordered[("BTCUSDT", "1h")] is False
        state.get_buffer_df("BTCUSDT", "1h")   # triggers repair
        assert state._buf_ordered[("BTCUSDT", "1h")] is True

    def test_ordered_not_regressed_by_next_sequential_push(self):
        state = BotState(buffer_size=100)
        for i in reversed(range(10)):
            state.push_candle(_c(i))
        state.get_buffer_df("BTCUSDT", "1h")   # repair
        state.push_candle(_c(10))              # in-order
        assert state._buf_ordered[("BTCUSDT", "1h")] is True


# ── 11. Thread safety ─────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_push_and_read_no_exception(self):
        """Concurrent pushes and get_buffer_df calls must not raise."""
        state  = BotState(buffer_size=200)
        errors: list[Exception] = []
        stop   = threading.Event()

        def pusher():
            i = 0
            while not stop.is_set():
                try:
                    state.push_candle(_c(i % 300))
                    i += 1
                except Exception as exc:
                    errors.append(exc)

        def reader():
            while not stop.is_set():
                try:
                    state.get_buffer_df("BTCUSDT", "1h")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=pusher) for _ in range(3)] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent access raised: {errors[:3]}"

    def test_multi_symbol_concurrent_no_exception(self):
        """50 symbols pushed concurrently — no corruption or exception."""
        state   = BotState(buffer_size=100)
        errors: list[Exception] = []
        symbols = [f"SYM{i:02d}USDT" for i in range(50)]

        def worker(sym: str, n: int):
            try:
                for i in range(n):
                    state.push_candle(_c(i, symbol=sym))
                state.get_buffer_df(sym, "1h")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(s, 50)) for s in symbols]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent workers raised: {errors[:3]}"
        # All 50 symbols must have data
        for s in symbols:
            assert state.buffer_length(s, "1h") > 0


# ── 12. Edge cases ────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_buffer_returns_empty_df(self):
        state = BotState()
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert df.empty

    def test_single_candle_df(self):
        state = BotState()
        state.push_candle(_c(0, close=42.0))
        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 1
        assert df.iloc[0]["close"] == pytest.approx(42.0)

    def test_get_missing_symbol_returns_empty(self):
        state = BotState()
        state.push_candle(_c(0, symbol="BTCUSDT"))
        df = state.get_buffer_df("ETHUSDT", "1h")
        assert df.empty

    def test_get_missing_interval_returns_empty(self):
        state = BotState()
        state.push_candle(_c(0, interval="1h"))
        df = state.get_buffer_df("BTCUSDT", "4h")
        assert df.empty
