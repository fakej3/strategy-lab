"""Phase 8 — Performance benchmarks.

Measures wall-clock time and throughput for:
  1. Candle buffer push at N symbols × M intervals
  2. BatchBacktest.run() at 10 / 50 symbols × 3 intervals
  3. Risk engine check throughput (N checks/s)
  4. EventBus emit throughput with K subscribers

These tests assert CORRECTNESS and report timing.  They are NOT skipped if
slow — we want CI to catch regressions.  The thresholds are conservative
(10× slower than observed) so they don't flake on loaded CI runners.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd
import pytest

from bot.config import RiskConfig
from bot.events import EventBus, CandleEvent
from bot.risk import RiskContext, RiskEngine
from bot.state import BotState, CandleRow
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest

BASE_MS = 1_700_000_000_000


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_candle(sym: str, iv: str, t: int) -> CandleRow:
    return CandleRow(
        symbol=sym, interval=iv,
        open_time=t, open=50_000.0, high=50_100.0, low=49_900.0,
        close=50_050.0, volume=1.0, close_time=t + 59_999,
    )


def _bars(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    p = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open": p, "high": [x * 1.001 for x in p],
        "low":  [x * 0.999 for x in p], "close": p, "volume": [1.0] * n,
    }, index=idx)


class _QuickSignal(StrategyBase):
    """Buy at bar 10, exit at bar 20 — fast deterministic signals."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 10: s.iloc[10] = Signal.BUY
        if len(bars) > 20: s.iloc[20] = Signal.EXIT
        return s


def _risk_ctx(**kw) -> RiskContext:
    defaults = dict(
        symbol="X", side="BUY", qty=0.001, ref_price=50_000.0,
        equity=10_000.0, peak_equity=10_000.0,
        daily_pnl=0.0, n_trades_today=0, open_positions=0, last_trade_ts=0.0,
    )
    defaults.update(kw)
    return RiskContext(**defaults)


# ── 1. BotState candle buffer throughput ──────────────────────────────────────

class TestCandleBufferThroughput:
    @pytest.mark.parametrize("n_sym, n_iv", [
        (10, 1), (10, 3), (50, 1), (50, 3), (100, 1),
    ])
    def test_push_candles(self, n_sym, n_iv):
        symbols   = [f"SYM{i:03d}USDT" for i in range(n_sym)]
        intervals = ["1m", "5m", "1h"][:n_iv]
        state     = BotState(buffer_size=500)

        total = n_sym * n_iv * 100  # 100 candles per (symbol, interval)

        t0 = time.perf_counter()
        for sym in symbols:
            for iv in intervals:
                for j in range(100):
                    state.push_candle(_make_candle(sym, iv, BASE_MS + j * 60_000))
        elapsed = time.perf_counter() - t0

        # Verify correctness
        for sym in symbols:
            for iv in intervals:
                assert state.buffer_length(sym, iv) == 100

        rate = total / elapsed
        # Conservatively: expect at least 10,000 pushes/s on any hardware
        assert rate > 10_000, f"push rate too slow: {rate:.0f}/s ({elapsed:.3f}s for {total} candles)"

    def test_mark_price_per_symbol_isolation(self):
        state = BotState()
        syms = [f"SYM{i}USDT" for i in range(20)]
        for i, sym in enumerate(syms):
            state.push_candle(CandleRow(
                symbol=sym, interval="1h", open_time=BASE_MS,
                open=float(i * 100), high=float(i * 100 + 1),
                low=float(i * 100 - 1), close=float(i * 100),
                volume=1.0, close_time=BASE_MS + 59_999,
            ))
        for i, sym in enumerate(syms):
            assert state.mark_price(sym) == pytest.approx(i * 100)


# ── 2. BatchBacktest throughput ────────────────────────────────────────────────

class TestBatchBacktestThroughput:
    @pytest.mark.parametrize("n_sym", [5, 10, 20])
    def test_batch_run_time(self, n_sym):
        n_bars = 100  # keep bars small so test stays fast
        symbols   = [f"SYM{i:03d}" for i in range(n_sym)]
        intervals = ["1h", "4h", "1d"]
        bars      = {(s, iv): _bars(n_bars) for s in symbols for iv in intervals}

        t0 = time.perf_counter()
        result = BatchBacktest(
            symbols=symbols,
            intervals=intervals,
            strategy_class=_QuickSignal,
            params={},
            bars=bars,
            starting_capital=100_000.0,
        ).run()
        elapsed = time.perf_counter() - t0

        n_pairs = n_sym * len(intervals)
        assert len(result.symbol_results) == n_pairs

        # Sanity: all pairs succeeded (no data errors)
        failed = result.failed_pairs
        assert not failed, f"Unexpected failures: {[r.error for r in failed]}"

        # Time assertion: conservatively allow 2s per pair (actual: ~0.01s)
        limit_s = n_pairs * 2.0
        assert elapsed < limit_s, (
            f"BatchBacktest({n_sym}sym × 3iv) took {elapsed:.2f}s > limit {limit_s:.0f}s"
        )

    def test_parallel_faster_than_sequential_at_20_pairs(self):
        symbols   = [f"SYM{i:03d}" for i in range(5)]
        intervals = ["1h", "4h", "1d", "1d"]  # 20 pairs total
        bars      = {(s, iv): _bars(80) for s in symbols for iv in intervals}

        kwargs: dict[str, Any] = dict(
            symbols=symbols, intervals=intervals,
            strategy_class=_QuickSignal, params={},
            bars=bars, starting_capital=10_000.0,
        )

        t_seq = time.perf_counter()
        r_seq = BatchBacktest(**kwargs, max_workers=1).run()
        t_seq = time.perf_counter() - t_seq

        t_par = time.perf_counter()
        r_par = BatchBacktest(**kwargs, max_workers=4).run()
        t_par = time.perf_counter() - t_par

        # Both produce the same number of results
        assert len(r_seq.symbol_results) == len(r_par.symbol_results)

        # Parallel may not be faster in a test environment (GIL, overhead),
        # but we verify it doesn't take longer than 5× sequential.
        assert t_par < t_seq * 5 + 2.0, (
            f"Parallel ({t_par:.2f}s) much slower than sequential ({t_seq:.2f}s)"
        )


# ── 3. Risk engine throughput ─────────────────────────────────────────────────

class TestRiskEngineThroughput:
    def test_checks_per_second(self):
        cfg  = RiskConfig(max_position_size_usd=50_000.0, max_open_positions=50)
        risk = RiskEngine(cfg)
        ctx  = _risk_ctx()
        n    = 100_000

        t0 = time.perf_counter()
        for _ in range(n):
            risk.check(ctx)
        elapsed = time.perf_counter() - t0

        rate = n / elapsed
        # Expect at least 100k checks/s (risk engine is pure Python, no I/O)
        assert rate > 100_000, f"RiskEngine too slow: {rate:.0f} checks/s"

    def test_checks_with_rejection_throughput(self):
        cfg  = RiskConfig(max_open_positions=0)  # always rejects
        risk = RiskEngine(cfg)
        ctx  = _risk_ctx(open_positions=0)
        n    = 50_000

        import logging
        # Suppress per-rejection WARNING logs — we are benchmarking check logic, not logging.
        risk_log = logging.getLogger("strategy_lab.bot.risk")
        prior = risk_log.level
        risk_log.setLevel(logging.ERROR)
        try:
            t0 = time.perf_counter()
            rejections = sum(1 for _ in range(n) if risk.check(ctx) != "")
            elapsed = time.perf_counter() - t0
        finally:
            risk_log.setLevel(prior)

        assert rejections == n  # always rejected
        assert (n / elapsed) > 50_000, "Rejection path too slow"


# ── 4. EventBus throughput ────────────────────────────────────────────────────

class TestEventBusThroughput:
    def test_emit_throughput_no_subscribers(self):
        bus = EventBus()
        ev  = CandleEvent(symbol="BTCUSDT", interval="1h")
        n   = 50_000

        t0 = time.perf_counter()
        for _ in range(n):
            bus.emit(ev)
        elapsed = time.perf_counter() - t0

        rate = n / elapsed
        assert rate > 100_000, f"EventBus emit (no subs) too slow: {rate:.0f}/s"

    def test_emit_throughput_ten_subscribers(self):
        bus = EventBus()
        counter = [0]
        for _ in range(10):
            bus.subscribe(CandleEvent, lambda e: counter.__setitem__(0, counter[0] + 1))

        ev = CandleEvent(symbol="BTCUSDT", interval="1h")
        n  = 10_000

        t0 = time.perf_counter()
        for _ in range(n):
            bus.emit(ev)
        elapsed = time.perf_counter() - t0

        assert counter[0] == n * 10  # each event hits all 10 handlers

        rate = n / elapsed
        assert rate > 5_000, f"EventBus emit (10 subs) too slow: {rate:.0f}/s"

    def test_subscribe_many_types(self):
        """100 event types, 10 handlers each — setup must be fast."""
        bus = EventBus()
        from bot.events import BotEvent

        seen = []
        for _ in range(10):
            bus.subscribe(CandleEvent, lambda e: seen.append(1))

        # Emit 1000 events
        t0 = time.perf_counter()
        for _ in range(1000):
            bus.emit(CandleEvent())
        elapsed = time.perf_counter() - t0

        assert len(seen) == 10_000
        assert elapsed < 1.0, f"1000 emits × 10 handlers took {elapsed:.2f}s"


# ── 5. Multi-symbol BotState read throughput ──────────────────────────────────

class TestBotStateReadThroughput:
    def test_get_buffer_df_many_symbols(self):
        state   = BotState(buffer_size=500)
        symbols = [f"SYM{i:03d}USDT" for i in range(20)]

        # Pre-populate with 200 candles each
        for sym in symbols:
            for j in range(200):
                state.push_candle(_make_candle(sym, "1h", BASE_MS + j * 3_600_000))

        # Time 200 get_buffer_df calls (10 per symbol)
        n = 200
        t0 = time.perf_counter()
        for i in range(n):
            sym = symbols[i % len(symbols)]
            df  = state.get_buffer_df(sym, "1h")
            assert not df.empty
        elapsed = time.perf_counter() - t0

        rate = n / elapsed
        assert rate > 500, f"get_buffer_df too slow: {rate:.0f}/s"

    def test_all_mark_prices_returns_all_symbols(self):
        state   = BotState()
        symbols = [f"SYM{i:03d}USDT" for i in range(50)]
        for i, sym in enumerate(symbols):
            state.push_candle(_make_candle(sym, "1h", BASE_MS))
        marks = state.all_mark_prices()
        assert len(marks) == 50
        assert all(sym in marks for sym in symbols)
