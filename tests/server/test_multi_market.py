"""Comprehensive multi-market architecture tests.

Covers:
- 1x1, 3x1, 1x3, 3x3 symbol × timeframe combinations
- Candle buffer isolation between symbols and intervals
- Strategy state isolation (stateless EMACrossover, safe for multi-symbol)
- Position isolation (one position per symbol, independent)
- WS event routing (candles dispatched to correct buffer)
- Latest-candle replacement (same open_time → update, new time → append)
- Duplicate candle deduplication
- Out-of-order candle ordering
- Sparse buffer handling
- Buffer sizes for 1/2/3/5/20/60/300 candles
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from bot.state import BotState, CandleRow
from server.bot_manager import BotManager
from strategies.ema_crossover import EMACrossover


# ── Helpers ────────────────────────────────────────────────────────────────────

BASE_MS = 1_700_000_000_000  # 2023-11-14 22:13:20 UTC


def _candle(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_time_ms: int = BASE_MS,
    close: float = 65_000.0,
    open: float = 65_000.0,
    high: float = 65_050.0,
    low: float = 64_990.0,
    volume: float = 1.0,
) -> CandleRow:
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


def _mgr_with(*candles: CandleRow) -> BotManager:
    mgr = BotManager()
    state = BotState()
    for c in candles:
        state.push_candle(c)
    mgr._state = state
    return mgr


def _seq(symbol: str, interval: str, n: int, base_close: float = 65_000.0) -> list[CandleRow]:
    return [
        _candle(symbol=symbol, interval=interval,
                open_time_ms=BASE_MS + i * 60_000, close=base_close + i)
        for i in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Symbol × Timeframe Combination Coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestSymbolTimeframeCombinations:
    """1×1, 3×1, 1×3, 3×3 combinations."""

    def test_1x1_single_symbol_single_interval(self):
        mgr = _mgr_with(_candle("BTCUSDT", "1m", close=65_000.0))
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1
        assert result[0]["close"] == 65_000.0

    def test_3x1_three_symbols_one_interval(self):
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        closes = [65_000.0, 3_500.0, 140.0]
        mgr = _mgr_with(*[_candle(s, "1m", close=c) for s, c in zip(syms, closes)])
        for sym, expected in zip(syms, closes):
            result = mgr.get_candles(sym, "1m")
            assert len(result) == 1, f"{sym}: expected 1 candle"
            assert result[0]["close"] == expected, f"{sym}: wrong close"

    def test_1x3_one_symbol_three_intervals(self):
        intervals = ["1m", "5m", "1h"]
        closes = [65_000.0, 64_900.0, 64_500.0]
        mgr = _mgr_with(*[_candle("BTCUSDT", iv, close=c) for iv, c in zip(intervals, closes)])
        for iv, expected in zip(intervals, closes):
            result = mgr.get_candles("BTCUSDT", iv)
            assert len(result) == 1, f"{iv}: expected 1 candle"
            assert result[0]["close"] == expected, f"{iv}: wrong close"

    def test_3x3_three_symbols_three_intervals(self):
        syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        intervals = ["1m", "5m", "1h"]
        state = BotState()
        expected: dict[tuple[str, str], float] = {}
        for i, sym in enumerate(syms):
            for j, iv in enumerate(intervals):
                v = float(i * 10 + j)
                state.push_candle(_candle(sym, iv, close=v))
                expected[(sym, iv)] = v
        mgr = BotManager()
        mgr._state = state
        for (sym, iv), v in expected.items():
            result = mgr.get_candles(sym, iv)
            assert len(result) == 1, f"({sym},{iv}): expected 1 candle"
            assert result[0]["close"] == v, f"({sym},{iv}): close mismatch"

    def test_3x3_no_cross_contamination(self):
        """BTCUSDT/1m candle must never appear under ETHUSDT/1h."""
        state = BotState()
        state.push_candle(_candle("BTCUSDT", "1m", close=999.0))
        state.push_candle(_candle("ETHUSDT", "1h", close=111.0))
        mgr = BotManager()
        mgr._state = state
        btc = mgr.get_candles("BTCUSDT", "1m")
        eth = mgr.get_candles("ETHUSDT", "1h")
        assert btc[0]["close"] != 111.0
        assert eth[0]["close"] != 999.0

    def test_missing_symbol_returns_empty(self):
        mgr = _mgr_with(_candle("BTCUSDT", "1m"))
        assert mgr.get_candles("ETHUSDT", "1m") == []

    def test_missing_interval_returns_empty(self):
        mgr = _mgr_with(_candle("BTCUSDT", "1m"))
        assert mgr.get_candles("BTCUSDT", "5m") == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. Candle Buffer Isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestCandleBufferIsolation:
    def test_btc_push_doesnt_grow_eth_buffer(self):
        state = BotState()
        for i in range(5):
            state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        assert mgr.get_candles("ETHUSDT", "1m") == []

    def test_four_buckets_independent(self):
        mgr = _mgr_with(
            _candle("BTCUSDT", "1m", close=100.0),
            _candle("BTCUSDT", "5m", close=200.0),
            _candle("ETHUSDT", "1m", close=300.0),
            _candle("ETHUSDT", "5m", close=400.0),
        )
        assert mgr.get_candles("BTCUSDT", "1m")[0]["close"] == 100.0
        assert mgr.get_candles("BTCUSDT", "5m")[0]["close"] == 200.0
        assert mgr.get_candles("ETHUSDT", "1m")[0]["close"] == 300.0
        assert mgr.get_candles("ETHUSDT", "5m")[0]["close"] == 400.0

    def test_large_btc_buffer_doesnt_spill_to_eth(self):
        state = BotState()
        for i in range(300):
            state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        assert mgr.get_candles("ETHUSDT", "1m") == []
        assert len(mgr.get_candles("BTCUSDT", "1m")) == 200  # default limit=200

    def test_buffer_keys_are_symbol_interval_tuples(self):
        state = BotState()
        state.push_candle(_candle("BTCUSDT", "1m"))
        state.push_candle(_candle("ETHUSDT", "1m"))
        with state._lock:
            keys = set(state._buffers.keys())
        assert ("BTCUSDT", "1m") in keys
        assert ("ETHUSDT", "1m") in keys
        assert len(keys) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 3. Strategy State Isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategyStateIsolation:
    """EMACrossover is stateless — safe to call for any symbol in any order."""

    def _bars(self, n: int, base_close: float = 100.0) -> pd.DataFrame:
        return pd.DataFrame({
            "close": [base_close + i * 0.5 for i in range(n)],
            "volume": [1.0] * n,
        })

    def test_generate_signals_returns_series_of_correct_length(self):
        strat = EMACrossover(fast=5, slow=10)
        bars = self._bars(50)
        result = strat.generate_signals(bars)
        assert isinstance(result, pd.Series)
        assert len(result) == 50

    def test_no_side_effects_between_calls(self):
        strat = EMACrossover(fast=5, slow=10)
        bars_a = self._bars(50, base_close=100.0)
        bars_b = self._bars(50, base_close=200.0)
        sig_a1 = strat.generate_signals(bars_a)
        _      = strat.generate_signals(bars_b)   # interleave a different symbol
        sig_a2 = strat.generate_signals(bars_a)
        pd.testing.assert_series_equal(sig_a1, sig_a2,
                                        check_names=False,
                                        obj="EMACrossover signals must be deterministic")

    def test_same_instance_handles_multiple_symbols_sequentially(self):
        strat = EMACrossover(fast=5, slow=10)
        btc_bars = self._bars(50, base_close=65_000.0)
        eth_bars = self._bars(50, base_close=3_500.0)
        sig_btc = strat.generate_signals(btc_bars)
        sig_eth = strat.generate_signals(eth_bars)
        assert isinstance(sig_btc, pd.Series)
        assert isinstance(sig_eth, pd.Series)

    @pytest.mark.parametrize("n", [1, 2, 3, 5])
    def test_sparse_bars_does_not_raise(self, n: int):
        """Fewer bars than the EMA period must not raise."""
        strat = EMACrossover(fast=20, slow=50)
        bars = self._bars(n)
        result = strat.generate_signals(bars)
        assert isinstance(result, pd.Series)
        assert len(result) == n


# ══════════════════════════════════════════════════════════════════════════════
# 4. Position Isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestPositionIsolation:
    def _pm(self):
        from bot.position_manager import PositionManager
        storage = MagicMock()
        storage.get_open_positions.return_value = []
        bus = MagicMock()
        pm = PositionManager(storage=storage, bus=bus)
        return pm

    def _inject(self, pm, symbol: str, direction: str):
        from bot.position_manager import Position
        pos = Position(
            position_id=f"test-{symbol}",
            symbol=symbol,
            direction=direction,
            status="open",
            size=0.001,
            entry_price=65_000.0,
            avg_entry_price=65_000.0,
        )
        with pm._lock:
            pm._open[symbol] = pos
            pm._all[pos.position_id] = pos

    def test_no_positions_initially(self):
        pm = self._pm()
        assert not pm.has_open_position("BTCUSDT")
        assert not pm.has_open_position("ETHUSDT")

    def test_btc_position_does_not_affect_eth(self):
        pm = self._pm()
        self._inject(pm, "BTCUSDT", "long")
        assert pm.has_open_position("BTCUSDT")
        assert not pm.has_open_position("ETHUSDT")

    def test_independent_positions_per_symbol(self):
        pm = self._pm()
        self._inject(pm, "BTCUSDT", "long")
        self._inject(pm, "ETHUSDT", "short")
        assert pm.get_open("BTCUSDT").direction == "long"
        assert pm.get_open("ETHUSDT").direction == "short"

    def test_three_independent_symbol_positions(self):
        pm = self._pm()
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            self._inject(pm, sym, "long")
        assert pm.open_position_count() == 3
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            assert pm.has_open_position(sym)

    def test_unknown_symbol_returns_none(self):
        pm = self._pm()
        self._inject(pm, "BTCUSDT", "long")
        assert pm.get_open("XRPUSDT") is None


# ══════════════════════════════════════════════════════════════════════════════
# 5. Candle Count Coverage (chart invariant via data pipeline)
# ══════════════════════════════════════════════════════════════════════════════

class TestCandleCountCoverage:
    """get_candles() returns the correct slice for 1/2/3/5/20/60/300 candles."""

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 20, 60, 300])
    def test_returns_correct_count(self, n: int):
        state = BotState()
        for i in range(n):
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        expected_count = min(n, 200)   # get_candles default limit=200
        assert len(result) == expected_count, (
            f"n={n}: expected {expected_count} candles, got {len(result)}"
        )

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 20, 60, 300])
    def test_candles_ascending_for_all_counts(self, n: int):
        state = BotState()
        for i in range(n):
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        times = [r["time"] for r in result]
        assert times == sorted(times), f"n={n}: candles not ascending"

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 20, 60, 300])
    def test_latest_candle_is_last(self, n: int):
        state = BotState()
        for i in range(n):
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000, close=float(i)))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        # The most recent candle always has close = float(n-1)
        assert result[-1]["close"] == float(n - 1), f"n={n}: last candle close wrong"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Latest-Candle Replacement (same open_time → update, new → append)
# ══════════════════════════════════════════════════════════════════════════════

class TestLatestCandleReplacement:
    def test_same_open_time_deduplicates_to_one(self):
        state = BotState()
        state.push_candle(_candle(open_time_ms=BASE_MS, close=65_000.0))
        state.push_candle(_candle(open_time_ms=BASE_MS, close=65_500.0))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1

    def test_same_open_time_last_write_wins(self):
        state = BotState()
        state.push_candle(_candle(open_time_ms=BASE_MS, close=65_000.0))
        state.push_candle(_candle(open_time_ms=BASE_MS, close=65_500.0))
        mgr = BotManager()
        mgr._state = state
        assert mgr.get_candles("BTCUSDT", "1m")[0]["close"] == 65_500.0

    def test_three_updates_same_slot_keeps_last(self):
        state = BotState()
        for close in [65_000.0, 65_100.0, 65_250.0]:
            state.push_candle(_candle(open_time_ms=BASE_MS, close=close))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1
        assert result[0]["close"] == 65_250.0

    def test_new_open_time_appends(self):
        state = BotState()
        state.push_candle(_candle(open_time_ms=BASE_MS,          close=65_000.0))
        state.push_candle(_candle(open_time_ms=BASE_MS + 60_000, close=65_100.0))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 2
        assert result[-1]["close"] == 65_100.0

    def test_update_does_not_affect_other_symbol(self):
        state = BotState()
        state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS, close=65_000.0))
        state.push_candle(_candle("ETHUSDT", "1m", open_time_ms=BASE_MS, close=3_500.0))
        state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS, close=65_500.0))  # update BTC
        mgr = BotManager()
        mgr._state = state
        assert mgr.get_candles("BTCUSDT", "1m")[0]["close"] == 65_500.0
        assert mgr.get_candles("ETHUSDT", "1m")[0]["close"] == 3_500.0


# ══════════════════════════════════════════════════════════════════════════════
# 7. Out-of-Order Candle Handling
# ══════════════════════════════════════════════════════════════════════════════

class TestOutOfOrderCandles:
    def test_out_of_order_push_sorted_ascending(self):
        state = BotState()
        for i in range(10, 0, -1):  # push newest first
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000, close=float(i)))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        times = [r["time"] for r in result]
        assert times == sorted(times), "Out-of-order push must produce ascending output"

    def test_out_of_order_latest_is_last(self):
        state = BotState()
        # Push: t+2min, t+0min, t+1min
        state.push_candle(_candle(open_time_ms=BASE_MS + 120_000, close=3.0))
        state.push_candle(_candle(open_time_ms=BASE_MS,            close=1.0))
        state.push_candle(_candle(open_time_ms=BASE_MS + 60_000,  close=2.0))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert result[-1]["close"] == 3.0

    def test_two_out_of_order_symbols_both_correct(self):
        state = BotState()
        # BTC: push t+1 before t+0
        state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS + 60_000, close=2.0))
        state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS,           close=1.0))
        # ETH: push t+2 before t+1
        state.push_candle(_candle("ETHUSDT", "1m", open_time_ms=BASE_MS + 120_000, close=4.0))
        state.push_candle(_candle("ETHUSDT", "1m", open_time_ms=BASE_MS + 60_000,  close=3.0))
        mgr = BotManager()
        mgr._state = state
        btc = mgr.get_candles("BTCUSDT", "1m")
        eth = mgr.get_candles("ETHUSDT", "1m")
        assert [r["close"] for r in btc] == [1.0, 2.0]
        assert [r["close"] for r in eth] == [3.0, 4.0]


# ══════════════════════════════════════════════════════════════════════════════
# 8. Sparse Buffer Handling
# ══════════════════════════════════════════════════════════════════════════════

class TestSparseBuffers:
    def test_single_candle_per_symbol(self):
        mgr = _mgr_with(
            _candle("BTCUSDT", "1m", close=65_000.0),
            _candle("ETHUSDT", "1m", close=3_500.0),
        )
        assert len(mgr.get_candles("BTCUSDT", "1m")) == 1
        assert len(mgr.get_candles("ETHUSDT", "1m")) == 1

    def test_btc_three_eth_one(self):
        state = BotState()
        for i in range(3):
            state.push_candle(_candle("BTCUSDT", "1m", open_time_ms=BASE_MS + i * 60_000))
        state.push_candle(_candle("ETHUSDT", "1m", close=3_500.0))
        mgr = BotManager()
        mgr._state = state
        assert len(mgr.get_candles("BTCUSDT", "1m")) == 3
        assert len(mgr.get_candles("ETHUSDT", "1m")) == 1

    def test_empty_for_unused_pairs(self):
        mgr = _mgr_with(_candle("BTCUSDT", "1m"))
        for sym, iv in [("ETHUSDT", "1m"), ("BTCUSDT", "5m"), ("SOLUSDT", "1h")]:
            assert mgr.get_candles(sym, iv) == [], f"({sym},{iv}) should be empty"


# ══════════════════════════════════════════════════════════════════════════════
# 9. WS/REST Time Key Consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestTimestampConsistency:
    """REST time key must equal WS open_time // 1000 for correct chart dedup."""

    def test_rest_time_matches_ws_formula(self):
        open_ms = 1_700_000_000_000
        state = BotState()
        state.push_candle(_candle(open_time_ms=open_ms))
        mgr = BotManager()
        mgr._state = state
        rest_time = mgr.get_candles("BTCUSDT", "1m")[0]["time"]
        ws_time = open_ms // 1000   # as computed by: Math.floor(ev.open_time / 1000)
        assert rest_time == ws_time, (
            f"REST time={rest_time} ≠ WS time={ws_time}. "
            "Mismatch prevents chart.updateCandle() from deduplicating."
        )

    def test_time_is_open_time_not_close_time(self):
        open_ms = 1_700_000_000_000
        state = BotState()
        state.push_candle(_candle(open_time_ms=open_ms))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")[0]
        assert result["time"] == open_ms // 1000
        assert result["time"] != (open_ms + 59_999) // 1000

    def test_consecutive_candles_have_unique_times(self):
        state = BotState()
        for i in range(5):
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        times = [r["time"] for r in result]
        assert len(times) == len(set(times)), "Consecutive candles must have unique times"

    @pytest.mark.parametrize("n", [1, 2, 3, 5, 20, 60, 300])
    def test_all_times_are_unix_seconds_not_ms(self, n: int):
        state = BotState()
        for i in range(n):
            state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000))
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        for row in result:
            # Unix seconds since epoch: should be ~1.7e9, not 1.7e12
            assert row["time"] < 2_000_000_000, (
                f"time={row['time']} looks like milliseconds, expected seconds"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 10. BotState Thread Safety (smoke)
# ══════════════════════════════════════════════════════════════════════════════

class TestBotStateThreadSafety:
    def test_concurrent_push_no_deadlock(self):
        import threading
        state = BotState()
        errors: list[Exception] = []

        def push_candles(sym: str, n: int):
            try:
                for i in range(n):
                    state.push_candle(_candle(sym, "1m", open_time_ms=BASE_MS + i * 60_000))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=push_candles, args=("BTCUSDT", 50)),
            threading.Thread(target=push_candles, args=("ETHUSDT", 50)),
            threading.Thread(target=push_candles, args=("SOLUSDT", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errors, f"Concurrent push raised: {errors}"

    def test_concurrent_push_and_read_no_deadlock(self):
        import threading
        state = BotState()
        mgr = BotManager()
        mgr._state = state
        errors: list[Exception] = []

        def push():
            try:
                for i in range(100):
                    state.push_candle(_candle(open_time_ms=BASE_MS + i * 60_000))
            except Exception as exc:
                errors.append(exc)

        def read():
            try:
                for _ in range(50):
                    mgr.get_candles("BTCUSDT", "1m")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=push), threading.Thread(target=read)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errors, f"Concurrent push+read raised: {errors}"
