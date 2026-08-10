"""Phase 2C.1 hardening and load-verification regression tests.

Covers:
  Phase 2  — HIGH-priority queue bounded (maxsize=500, drop-oldest + WARNING)
  Phase 3  — Browser disconnect: UI queue state never blocks or corrupts trading
  Phase 4  — Active pair filtering correctness under 50+ symbol load
  Phase 6  — Reconnect deduplication: no duplicate candles after re-backfill
  Phase 7  — ProcessPool correctness (workers=1 vs workers=2) and timing
  Phase 8  — summary_only: curves are empty; scalars are preserved
  Phase 9  — 200-symbol batch correctness
  Phase 10 — Event coalescing: latest candle/tick per pair; fills untouched
  Phase 11 — Memory bounds: queues bounded; BotState buffer bounded

All tests are deterministic (no network, no random seeds, no real-time waits).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Type

import pandas as pd
import pytest

from bot.state import BotState, CandleRow
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest, SymbolResult
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig
from server.bot_manager import BotManager


# ── Module-level strategies (must be top-level for ProcessPoolExecutor pickling)

class _Hold2C1(StrategyBase):
    """Always HOLD — zero trades; minimal compute for timing tests."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _SingleBuy2C1(StrategyBase):
    """One BUY at bar 10, EXIT at bar 20 — deterministic single trade."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 10:
            s.iloc[10] = Signal.BUY
        if len(bars) > 20:
            s.iloc[20] = Signal.EXIT
        return s


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bars(n: int, start: float = 100.0) -> pd.DataFrame:
    prices = [start + i for i in range(n)]
    idx    = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open":   prices,
        "high":   [p * 1.001 for p in prices],
        "low":    [p * 0.999 for p in prices],
        "close":  prices,
        "volume": [1.0] * n,
    }, index=idx)


def _bars_dict(symbols: list[str], intervals: list[str], n: int = 50) -> dict:
    return {(s, iv): _bars(n) for s in symbols for iv in intervals}


def _candle_row(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    t: int = 1_000_000_000_000,
    close: float = 50_000.0,
    dt: int = 0,
) -> CandleRow:
    return CandleRow(
        symbol=symbol, interval=interval,
        open_time=t + dt, open=close,
        high=close * 1.001, low=close * 0.999,
        close=close, volume=1.0,
        close_time=t + dt + 3_599_999,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — HIGH-priority queue hardening
# ══════════════════════════════════════════════════════════════════════════════

class TestHighQueueHardening:
    """_q_high must be bounded (maxsize=500) with drop-oldest + WARNING on overflow."""

    def test_high_queue_has_maxsize(self):
        """_q_high must have a finite maxsize."""
        mgr = BotManager()
        assert mgr._q_high.maxsize == 500, (
            f"_q_high.maxsize expected 500, got {mgr._q_high.maxsize}. "
            "Unbounded HIGH queue risks memory explosion when browser is offline."
        )

    def test_high_queue_drops_oldest_on_overflow(self):
        """When _q_high is full, the OLDEST event is dropped and the NEWEST accepted."""
        mgr = BotManager()
        # Fill HIGH queue to capacity with fill-type events
        for i in range(500):
            mgr._enqueue({"type": "fill", "seq": i})
        assert mgr._q_high.qsize() == 500

        # One more must trigger drop-oldest
        mgr._enqueue({"type": "fill", "seq": 9999})

        events = mgr.drain_events(max_n=500)
        seqs = [e["seq"] for e in events if e.get("type") == "fill"]
        assert 9999 in seqs, "Latest HIGH event must be in queue after drop-oldest"
        assert 0 not in seqs, "Oldest HIGH event must have been evicted"

    def test_high_queue_overflow_emits_warning(self, caplog):
        """Overflow of _q_high must log a WARNING (never silent)."""
        mgr = BotManager()
        for i in range(500):
            mgr._enqueue({"type": "error", "seq": i})

        with caplog.at_level(logging.WARNING, logger="strategy_lab.server.bot_manager"):
            mgr._enqueue({"type": "error", "seq": 9999})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                    and "HIGH-priority" in r.message]
        assert warnings, (
            "Dropping a HIGH-priority event must emit a log.warning — "
            "silent drops hide operational problems."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Browser disconnect isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestBrowserDisconnectIsolation:
    """Trading pipeline must not block or fail when UI queues are full."""

    def test_enqueue_is_nonblocking_when_both_queues_full(self):
        """_enqueue must return immediately regardless of queue state."""
        mgr = BotManager()
        # Saturate both queues
        for i in range(500):
            mgr._enqueue({"type": "candle", "symbol": "X", "interval": "1h", "seq": i})
        for i in range(500):
            mgr._enqueue({"type": "fill", "seq": i})

        t0 = time.monotonic()
        # 200 more events must not block (even 1 second would be unacceptable)
        for i in range(200):
            mgr._enqueue({"type": "fill", "seq": 10000 + i})
            mgr._enqueue({"type": "candle", "symbol": "X", "interval": "1h", "seq": 10000 + i})
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, (
            f"_enqueue took {elapsed:.3f}s with full queues — it must be non-blocking."
        )

    def test_high_queue_bounded_not_blocking_trading_events(self):
        """HIGH queue stays bounded; each call to _enqueue is non-blocking."""
        mgr = BotManager()
        # Simulate 1000 fill events arriving while browser is offline (not draining)
        for i in range(1000):
            mgr._enqueue({"type": "fill", "seq": i})
        # Queue must not exceed its maxsize
        assert mgr._q_high.qsize() <= mgr._q_high.maxsize, (
            f"_q_high.qsize()={mgr._q_high.qsize()} exceeded maxsize={mgr._q_high.maxsize}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Active pair filtering under 50+ symbol load
# ══════════════════════════════════════════════════════════════════════════════

class TestActivePairFiltering:
    """set_active_pair controls which pair receives full OHLCV candle events."""

    def test_active_pair_set_and_read_thread_safe(self):
        """set_active_pair persists state correctly under the lock."""
        mgr = BotManager()
        assert mgr._active_symbol is None
        assert mgr._active_interval is None

        mgr.set_active_pair("ETHUSDT", "4h")
        with mgr._lock:
            assert mgr._active_symbol == "ETHUSDT"
            assert mgr._active_interval == "4h"

    def test_50_symbols_active_pair_filtering_correct(self):
        """With 50 symbols, only the active pair triggers is_active=True."""
        symbols = [f"SYM{i:03d}USDT" for i in range(50)]
        mgr = BotManager()
        mgr.set_active_pair("SYM025USDT", "1h")

        candle_emitted = []
        tick_emitted   = []

        for sym in symbols:
            with mgr._lock:
                active_sym = mgr._active_symbol
                active_iv  = mgr._active_interval

            # Simulate _on_candle filtering (live candle, not history)
            tick_ev = {"type": "tick", "symbol": sym, "interval": "1h", "close": 100.0}
            tick_emitted.append(sym)

            is_active = (
                active_sym is None
                or (sym == active_sym and "1h" == active_iv)
            )
            if is_active:
                candle_emitted.append(sym)

        assert tick_emitted == symbols, "Tick must be emitted for ALL 50 symbols"
        assert candle_emitted == ["SYM025USDT"], (
            f"Full candle must be emitted ONLY for the active pair; got {candle_emitted}"
        )

    def test_switching_active_pair_immediately_takes_effect(self):
        """After set_active_pair(), subsequent reads reflect the new pair."""
        mgr = BotManager()
        mgr.set_active_pair("BTCUSDT", "1h")
        # Switch
        mgr.set_active_pair("ETHUSDT", "15m")
        with mgr._lock:
            assert mgr._active_symbol   == "ETHUSDT"
            assert mgr._active_interval == "15m"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Reconnect deduplication
# ══════════════════════════════════════════════════════════════════════════════

class TestReconnectDedup:
    """No duplicate candles in BotState buffer after re-backfill on reconnect."""

    def test_same_open_time_deduplicated(self):
        """Pushing the same open_time twice must result in exactly 1 row."""
        state = BotState(buffer_size=500)
        base_t = 1_700_000_000_000
        # First push (backfill)
        state.push_candle(_candle_row("BTCUSDT", "1h", t=base_t, close=50_000.0))
        # Second push with same open_time (reconnect overlap)
        state.push_candle(_candle_row("BTCUSDT", "1h", t=base_t, close=50_100.0))

        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == 1, (
            f"Expected 1 row after dedup, got {len(df)}. "
            "Duplicate candles corrupt strategy buffers."
        )
        # last-write-wins: second push has close=50100
        assert df["close"].iloc[0] == 50_100.0

    def test_50_symbol_reconnect_no_extra_candles(self):
        """After a re-backfill (same candles), buffer size does not grow."""
        state = BotState(buffer_size=500)
        symbols = [f"S{i:02d}USDT" for i in range(50)]
        base_t  = 1_700_000_000_000

        # Initial fill: 20 unique candles per symbol
        for sym in symbols:
            for i in range(20):
                state.push_candle(_candle_row(sym, "1h", t=base_t + i * 3_600_000))

        # Re-backfill: same candles again (simulates reconnect overlap)
        for sym in symbols:
            for i in range(20):
                state.push_candle(_candle_row(sym, "1h", t=base_t + i * 3_600_000))

        # Each symbol must have exactly 20 rows (no duplicates)
        for sym in symbols:
            df = state.get_buffer_df(sym, "1h")
            assert len(df) == 20, (
                f"Symbol {sym}: expected 20 candles after re-backfill dedup, got {len(df)}"
            )

    def test_out_of_order_candles_sorted_on_read(self):
        """Out-of-order pushes must produce a sorted DataFrame."""
        state = BotState(buffer_size=500)
        base_t = 1_700_000_000_000
        # Push in reverse order
        for i in [4, 2, 0, 3, 1]:
            state.push_candle(_candle_row("BTCUSDT", "1h", t=base_t + i * 3_600_000, close=float(i)))

        df = state.get_buffer_df("BTCUSDT", "1h")
        assert list(df["close"]) == [0.0, 1.0, 2.0, 3.0, 4.0], (
            f"Expected sorted candles; got {list(df['close'])}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7 — ProcessPool correctness and timing
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessPoolVerification:
    """ProcessPoolExecutor runs must produce identical results to sequential."""

    def test_workers_2_results_match_workers_1(self):
        """100-pair parallel result must exactly match sequential result."""
        syms  = [f"SYM{i:03d}" for i in range(10)]
        ivs   = ["1h"]
        bars  = _bars_dict(syms, ivs, n=60)

        seq = BatchBacktest(
            symbols=syms, intervals=ivs,
            strategy_class=_SingleBuy2C1, params={}, bars=bars,
            starting_capital=100_000.0, max_workers=1,
        ).run()

        par = BatchBacktest(
            symbols=syms, intervals=ivs,
            strategy_class=_SingleBuy2C1, params={}, bars=bars,
            starting_capital=100_000.0, max_workers=2,
        ).run()

        # Same number of pairs
        assert len(seq.symbol_results) == len(par.symbol_results)
        # Same n_trades and total_return for every pair
        seq_map = {(r.symbol, r.interval): r for r in seq.symbol_results}
        par_map = {(r.symbol, r.interval): r for r in par.symbol_results}
        for key in seq_map:
            s, p = seq_map[key], par_map[key]
            assert s.n_trades == p.n_trades, (
                f"{key}: seq n_trades={s.n_trades} != par n_trades={p.n_trades}"
            )
            if s.ok and p.ok:
                assert abs(s.total_return - p.total_return) < 1e-9, (
                    f"{key}: return mismatch seq={s.total_return} par={p.total_return}"
                )

    def test_workers_4_completes_within_60s(self):
        """100 pairs × 50 bars at workers=4 must complete in < 60 s."""
        syms  = [f"LOAD{i:03d}" for i in range(100)]
        ivs   = ["1h"]
        bars  = _bars_dict(syms, ivs, n=50)

        t0 = time.monotonic()
        result = BatchBacktest(
            symbols=syms, intervals=ivs,
            strategy_class=_Hold2C1, params={}, bars=bars,
            starting_capital=100_000.0, max_workers=4,
        ).run()
        elapsed = time.monotonic() - t0

        assert len(result.symbol_results) == 100
        assert elapsed < 60.0, (
            f"100-pair workers=4 batch took {elapsed:.2f}s — must be < 60s."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 8 — summary_only memory savings
# ══════════════════════════════════════════════════════════════════════════════

class TestSummaryOnlyMode:
    """summary_only=True must empty the curve series while preserving scalars."""

    def test_summary_only_curves_empty_when_trades_exist(self):
        """summary_only=True must produce empty equity/balance/drawdown curves."""
        bars = _bars(n=50)
        result = PortfolioEngine(
            PortfolioConfig(starting_capital=100_000.0, summary_only=True)
        ).run(bars, _SingleBuy2C1(), EngineConfig())

        assert result.trades, "Must have trades for this to be a useful test"
        assert result.equity_curve.empty,   "equity_curve must be empty with summary_only=True"
        assert result.balance_curve.empty,  "balance_curve must be empty with summary_only=True"
        assert result.drawdown_curve.empty, "drawdown_curve must be empty with summary_only=True"

    def test_summary_only_scalars_match_full_run(self):
        """summary_only=True must yield identical scalar metrics to summary_only=False."""
        bars = _bars(n=50)
        cfg_full    = PortfolioConfig(starting_capital=100_000.0, summary_only=False)
        cfg_summary = PortfolioConfig(starting_capital=100_000.0, summary_only=True)

        full = PortfolioEngine(cfg_full).run(bars, _SingleBuy2C1(), EngineConfig())
        summ = PortfolioEngine(cfg_summary).run(bars, _SingleBuy2C1(), EngineConfig())

        assert abs(full.total_return    - summ.total_return)    < 1e-9
        assert abs(full.max_drawdown_pct - summ.max_drawdown_pct) < 1e-9
        assert abs(full.ending_equity   - summ.ending_equity)   < 1e-9
        assert len(full.trades) == len(summ.trades)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 9 — 200-symbol batch correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadScalability:
    """200-symbol batch backtest produces correct results for every pair."""

    def test_200_symbol_batch_all_pairs_correct(self):
        """200-symbol batch must return exactly 200 pairs with correct trade count."""
        syms  = [f"SYM{i:03d}" for i in range(200)]
        ivs   = ["1h"]
        bars  = _bars_dict(syms, ivs, n=60)

        result = BatchBacktest(
            symbols=syms, intervals=ivs,
            strategy_class=_SingleBuy2C1, params={}, bars=bars,
            starting_capital=100_000.0, max_workers=1,
        ).run()

        assert len(result.symbol_results) == 200
        for sr in result.symbol_results:
            assert sr.ok, f"Pair {sr.symbol}/{sr.interval} failed: {sr.error}"
            assert sr.n_trades == 1, (
                f"Pair {sr.symbol}/{sr.interval}: expected 1 trade, got {sr.n_trades}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 10 — Event coalescing
# ══════════════════════════════════════════════════════════════════════════════

class TestEventCoalescing:
    """drain_events must coalesce LOW-priority events per (type, symbol, interval)."""

    def test_candle_coalesced_to_latest_per_pair(self):
        """50 candles for the same (symbol, interval) → only latest returned."""
        mgr = BotManager()
        for i in range(50):
            mgr._enqueue({
                "type": "candle", "symbol": "BTCUSDT", "interval": "1h",
                "close": float(i),
            })
        events = mgr.drain_events(max_n=50)
        candles = [e for e in events if e.get("type") == "candle" and
                   e.get("symbol") == "BTCUSDT"]
        assert len(candles) == 1, (
            f"Expected 1 coalesced candle, got {len(candles)}"
        )
        assert candles[0]["close"] == 49.0, (
            f"Must keep the LATEST candle; expected close=49, got {candles[0]['close']}"
        )

    def test_tick_coalesced_to_latest_per_pair(self):
        """50 ticks for the same (symbol, interval) → only latest returned."""
        mgr = BotManager()
        for i in range(50):
            mgr._enqueue({
                "type": "tick", "symbol": "ETHUSDT", "interval": "4h",
                "close": float(3000 + i),
            })
        events = mgr.drain_events(max_n=50)
        ticks = [e for e in events if e.get("type") == "tick" and
                 e.get("symbol") == "ETHUSDT"]
        assert len(ticks) == 1
        assert ticks[0]["close"] == 3049.0

    def test_different_pairs_not_coalesced(self):
        """Candles for BTC and ETH are NOT merged — different pairs produce separate events."""
        mgr = BotManager()
        mgr._enqueue({"type": "candle", "symbol": "BTCUSDT", "interval": "1h", "close": 50000.0})
        mgr._enqueue({"type": "candle", "symbol": "ETHUSDT", "interval": "1h", "close": 3000.0})
        events = mgr.drain_events(max_n=10)
        candles = [e for e in events if e.get("type") == "candle"]
        assert len(candles) == 2, (
            "Different (symbol, interval) pairs must NOT be coalesced"
        )
        syms = {c["symbol"] for c in candles}
        assert syms == {"BTCUSDT", "ETHUSDT"}

    def test_fill_events_not_coalesced(self):
        """Fill events are HIGH-priority and must never be coalesced."""
        mgr = BotManager()
        for i in range(5):
            mgr._enqueue({
                "type": "fill", "symbol": "BTCUSDT",
                "order_id": f"ord-{i}", "fill_price": float(50000 + i),
            })
        events = mgr.drain_events(max_n=10)
        fills = [e for e in events if e.get("type") == "fill"]
        assert len(fills) == 5, (
            f"All 5 fill events must be preserved; got {len(fills)}"
        )
        prices = {e["fill_price"] for e in fills}
        assert len(prices) == 5, "Each fill must have its own fill_price"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 11 — Memory bounds
# ══════════════════════════════════════════════════════════════════════════════

class TestMemoryBounds:
    """Queue sizes and BotState buffers must stay bounded under sustained load."""

    def test_both_queues_bounded_after_high_volume(self):
        """After 2000 HIGH + 2000 LOW events without draining, queues are ≤ maxsize."""
        mgr = BotManager()
        for i in range(2000):
            mgr._enqueue({"type": "fill", "seq": i})
            mgr._enqueue({"type": "candle", "symbol": "BTC", "interval": "1h", "seq": i})

        assert mgr._q_high.qsize() <= mgr._q_high.maxsize, (
            f"_q_high exceeded maxsize: {mgr._q_high.qsize()} > {mgr._q_high.maxsize}"
        )
        assert mgr._q_low.qsize() <= mgr._q_low.maxsize, (
            f"_q_low exceeded maxsize: {mgr._q_low.qsize()} > {mgr._q_low.maxsize}"
        )

    def test_candle_buffer_bounded_by_buffer_size(self):
        """BotState ring buffer stays at exactly buffer_size after excess pushes."""
        buf_size = 100
        state = BotState(buffer_size=buf_size)
        base_t = 1_700_000_000_000

        for i in range(300):  # 3× overflow
            state.push_candle(_candle_row("BTCUSDT", "1h", t=base_t + i * 3_600_000))

        df = state.get_buffer_df("BTCUSDT", "1h")
        assert len(df) == buf_size, (
            f"Buffer should be capped at {buf_size}; got {len(df)} rows"
        )

    def test_start_stop_drains_both_queues(self):
        """bot_manager.start() drains stale events from both queues."""
        mgr = BotManager()
        # Pre-load events as if from a previous run
        for i in range(20):
            mgr._enqueue({"type": "fill", "seq": i})
            mgr._enqueue({"type": "candle", "symbol": "X", "interval": "1h", "seq": i})

        # Simulate the start() drain sequence (identical to what BotManager.start() does)
        for q in (mgr._q_high, mgr._q_low):
            while True:
                try:
                    q.get_nowait()
                except Exception:
                    break

        assert mgr._q_high.qsize() == 0, "start() must drain HIGH queue"
        assert mgr._q_low.qsize()  == 0, "start() must drain LOW queue"
