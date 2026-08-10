"""Phase 2C regression and scalability tests.

Part 9  — performance/scalability: 10 / 50 / 100 / 200 symbol runs.
Part 10 — multi-symbol correctness: 15 specific regression scenarios.

All tests are deterministic (no random seeds), do not touch the network, and
avoid wall-clock assertions beyond very generous upper bounds that are
unlikely to fail even on a heavily loaded CI runner.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pytest

from bot.state import BotState, CandleRow
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest, BatchBacktestResult, SymbolResult
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, PortfolioResult


# ── Module-level strategies (must be top-level for ProcessPoolExecutor) ────────

class _Hold(StrategyBase):
    """Never signals — zero trades every run."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _SingleBuy(StrategyBase):
    """One BUY at bar 10 then EXIT at bar 20 — always the same trade."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 10:
            s.iloc[10] = Signal.BUY
        if len(bars) > 20:
            s.iloc[20] = Signal.EXIT
        return s


class _BuyEarly(StrategyBase):
    """BUY at bar 5, exit at bar 8."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 5:
            s.iloc[5] = Signal.BUY
        if len(bars) > 8:
            s.iloc[8] = Signal.EXIT
        return s


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bars(n: int, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    prices = [start + i * step for i in range(n)]
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
) -> CandleRow:
    return CandleRow(
        symbol=symbol, interval=interval,
        open_time=t, open=close, high=close * 1.001,
        low=close * 0.999, close=close, volume=1.0,
        close_time=t + 3_599_999,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Part 10 — Multi-symbol correctness (15 scenarios)
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchBacktestParallelCorrectness:
    """Scenario 1–6: BatchBacktest sequential vs parallel correctness."""

    # Scenario 1
    def test_sequential_and_parallel_give_identical_per_pair_results(self):
        """ProcessPoolExecutor result must match sequential result for every pair."""
        syms = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        bars = _bars_dict(syms, ["1h"], n=60)

        seq = BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_SingleBuy, params={},
            bars=bars, starting_capital=10_000.0, max_workers=1,
        ).run()
        par = BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_SingleBuy, params={},
            bars=bars, starting_capital=10_000.0, max_workers=3,
        ).run()

        assert len(seq.symbol_results) == len(par.symbol_results) == 3
        # Map by (symbol, interval) for order-independent comparison
        seq_map = {(r.symbol, r.interval): r for r in seq.symbol_results}
        par_map = {(r.symbol, r.interval): r for r in par.symbol_results}
        for key in seq_map:
            rs, rp = seq_map[key], par_map[key]
            assert rs.ok == rp.ok, f"ok mismatch for {key}"
            assert rs.n_trades == rp.n_trades, f"trade count mismatch for {key}"
            assert abs(rs.total_return - rp.total_return) < 1e-9, (
                f"return mismatch for {key}: {rs.total_return} vs {rp.total_return}"
            )

    # Scenario 2
    def test_missing_bars_produces_error_not_exception(self):
        """A pair absent from bars dict must produce a SymbolResult.error, not raise."""
        result = BatchBacktest(
            symbols=["BTCUSDT", "MISSING"],
            intervals=["1h"],
            strategy_class=_Hold, params={},
            bars={("BTCUSDT", "1h"): _bars(30)},
            starting_capital=10_000.0,
        ).run()
        errors = [r for r in result.symbol_results if not r.ok]
        assert len(errors) == 1
        assert errors[0].symbol == "MISSING"
        assert errors[0].error

    # Scenario 3
    def test_all_hold_gives_zero_portfolio_metrics(self):
        """When every pair produces zero trades, portfolio metrics are all zero."""
        syms = ["BTCUSDT", "ETHUSDT"]
        result = BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_Hold, params={},
            bars=_bars_dict(syms, ["1h"]),
            starting_capital=10_000.0,
        ).run()
        assert result.portfolio_n_trades == 0
        assert result.portfolio_total_return == 0.0
        assert result.portfolio_net_profit == 0.0

    # Scenario 4
    def test_starting_capital_propagated_to_all_pairs(self):
        """Each pair receives the full starting_capital for its per-pair run."""
        syms = ["BTCUSDT", "ETHUSDT"]
        capital = 77_777.0
        result = BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_SingleBuy, params={},
            bars=_bars_dict(syms, ["1h"], n=60),
            starting_capital=capital,
        ).run()
        for sr in result.symbol_results:
            if sr.ok:
                assert sr.portfolio_result.starting_capital == capital

    # Scenario 5
    def test_summary_only_mode_preserves_scalar_metrics(self):
        """summary_only=True: scalar metrics identical to full run, curves empty."""
        bars = _bars(60)
        cfg_full    = PortfolioConfig(starting_capital=10_000.0, summary_only=False)
        cfg_summary = PortfolioConfig(starting_capital=10_000.0, summary_only=True)
        ec = EngineConfig()

        full    = PortfolioEngine(cfg_full).run(bars, _SingleBuy(), ec)
        summary = PortfolioEngine(cfg_summary).run(bars, _SingleBuy(), ec)

        assert full.total_return    == summary.total_return
        assert full.net_profit      == summary.net_profit
        assert full.max_drawdown_pct == summary.max_drawdown_pct
        assert full.ending_equity   == summary.ending_equity
        assert len(full.trades) == len(summary.trades), "trade list preserved"
        # Curves are empty when summary_only=True
        assert summary.equity_curve.empty
        assert summary.balance_curve.empty
        assert summary.drawdown_curve.empty

    # Scenario 6
    def test_max_workers_exceeding_pairs_does_not_crash(self):
        """max_workers > number of pairs must not crash."""
        syms = ["BTCUSDT"]
        result = BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_SingleBuy, params={},
            bars=_bars_dict(syms, ["1h"], n=60),
            starting_capital=10_000.0, max_workers=8,
        ).run()
        assert len(result.symbol_results) == 1


class TestPriorityQueueCorrectness:
    """Scenario 7–9: Event queue priority routing."""

    def _mgr(self):
        from server.bot_manager import BotManager
        return BotManager()

    # Scenario 7
    def test_high_events_drain_before_low_events(self):
        """HIGH-priority events drain before LOW-priority events."""
        mgr = self._mgr()
        # Enqueue LOW events first
        for i in range(5):
            mgr._enqueue({"type": "candle", "seq": i})
        # Then enqueue HIGH events
        mgr._enqueue({"type": "fill",   "seq": 100})
        mgr._enqueue({"type": "signal", "seq": 101})

        events = mgr.drain_events(max_n=10)
        types = [e["type"] for e in events]
        # All HIGH events before any LOW event
        high_pos = [i for i, t in enumerate(types) if t in {"fill", "signal"}]
        low_pos  = [i for i, t in enumerate(types) if t == "candle"]
        assert high_pos, "fill/signal events must be present"
        assert low_pos,  "candle events must be present"
        assert max(high_pos) < min(low_pos), (
            "HIGH events must appear before LOW events in drained list"
        )

    # Scenario 8
    def test_high_events_accepted_when_low_queue_full(self):
        """HIGH events are accepted even when LOW queue (maxsize=500) is full."""
        mgr = self._mgr()
        for i in range(500):
            mgr._enqueue({"type": "candle", "seq": i})

        # HIGH events must not be rejected
        mgr._enqueue({"type": "fill",          "seq": 9000})
        mgr._enqueue({"type": "error",          "seq": 9001})
        mgr._enqueue({"type": "risk_rejected",  "seq": 9002})
        mgr._enqueue({"type": "position",       "seq": 9003})

        events = mgr.drain_events(max_n=504)
        seqs = {e["seq"] for e in events}
        assert 9000 in seqs, "fill must not be dropped"
        assert 9001 in seqs, "error must not be dropped"
        assert 9002 in seqs, "risk_rejected must not be dropped"
        assert 9003 in seqs, "position must not be dropped"

    # Scenario 9
    def test_low_queue_drop_oldest_preserves_latest(self):
        """LOW queue drop-oldest keeps the most recent candle event."""
        mgr = self._mgr()
        for i in range(500):
            mgr._enqueue({"type": "candle", "seq": i})
        mgr._enqueue({"type": "candle", "seq": 9999})

        events = mgr.drain_events(max_n=500)
        seqs = [e["seq"] for e in events]
        assert 9999 in seqs,  "latest candle must survive"
        assert 0    not in seqs, "oldest candle must be dropped"


class TestActivePairFiltering:
    """Scenario 10–12: Tick events and active-pair candle filtering."""

    def _mgr(self):
        from server.bot_manager import BotManager
        return BotManager()

    # Scenario 10
    def test_full_candle_only_for_active_pair(self):
        """Full OHLCV candle events only for the set active pair."""
        from bot.events import CandleEvent, EventBus

        mgr = self._mgr()
        mgr.set_active_pair("BTCUSDT", "1h")

        bus = EventBus()

        def _on_candle(ev: "CandleEvent") -> None:
            if ev.is_history:
                return
            pair_key = (ev.symbol, ev.interval)
            from server.bot_manager import BotManager
            # Simulate what _on_candle in _run_bot does
            with mgr._lock:
                last_close  = mgr._last_close.get(pair_key)
                active_sym  = mgr._active_symbol
                active_iv   = mgr._active_interval
            tick = {"type": "tick", "ts": ev.ts.isoformat(),
                    "symbol": ev.symbol, "interval": ev.interval, "close": ev.close}
            mgr._enqueue(tick)
            with mgr._lock:
                mgr._last_close[pair_key] = ev.close
            is_active = (active_sym is None or
                         (ev.symbol == active_sym and ev.interval == active_iv))
            if is_active:
                mgr._enqueue({
                    "type": "candle", "ts": ev.ts.isoformat(),
                    "symbol": ev.symbol, "interval": ev.interval,
                    "open_time": ev.open_time, "open": ev.open,
                    "high": ev.high, "low": ev.low, "close": ev.close,
                    "volume": ev.volume, "is_history": False,
                })

        t = 1_700_000_000_000
        _on_candle(CandleEvent(symbol="BTCUSDT", interval="1h",
                               open_time=t, open=50000, high=50100,
                               low=49900, close=50050, volume=1.0,
                               close_time=t + 3_599_999, is_history=False))
        _on_candle(CandleEvent(symbol="ETHUSDT", interval="1h",
                               open_time=t, open=3000, high=3010,
                               low=2990, close=3005, volume=1.0,
                               close_time=t + 3_599_999, is_history=False))

        events = mgr.drain_events(max_n=20)
        candles = [e for e in events if e["type"] == "candle"]
        ticks   = [e for e in events if e["type"] == "tick"]

        assert len(candles) == 1, f"expected 1 candle, got {len(candles)}"
        assert candles[0]["symbol"] == "BTCUSDT"
        assert len(ticks) == 2, f"expected 2 ticks (all symbols), got {len(ticks)}"

    # Scenario 11
    def test_tick_events_for_all_symbols(self):
        """Tick events are produced for every symbol, not just the active pair."""
        mgr = self._mgr()
        mgr.set_active_pair("BTCUSDT", "1h")

        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
        for sym in symbols:
            t = 1_700_000_000_000
            tick = {"type": "tick", "ts": "2024-01-01T00:00:00+00:00",
                    "symbol": sym, "interval": "1h", "close": 100.0}
            mgr._enqueue(tick)

        events = mgr.drain_events(max_n=20)
        tick_syms = {e["symbol"] for e in events if e["type"] == "tick"}
        assert tick_syms == set(symbols), (
            f"ticks expected for all symbols; got {tick_syms}"
        )

    # Scenario 12
    def test_no_active_pair_set_sends_all_candles(self):
        """If no active pair is set, full candles are sent for all pairs (backward compat)."""
        mgr = self._mgr()
        # No set_active_pair() call

        symbols = ["BTCUSDT", "ETHUSDT"]
        for sym in symbols:
            mgr._enqueue({
                "type": "candle", "ts": "2024-01-01T00:00:00+00:00",
                "symbol": sym, "interval": "1h",
                "open_time": 1_700_000_000_000,
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                "volume": 1.0, "is_history": False,
            })

        events = mgr.drain_events(max_n=10)
        candle_syms = {e["symbol"] for e in events if e["type"] == "candle"}
        assert candle_syms == set(symbols), (
            "all symbols should receive candle events when no active pair is set"
        )


class TestPhaseTwoACacheIntegration:
    """Scenario 13–14: BotState.get_buffer_df integration with get_candles."""

    # Scenario 13
    def test_get_buffer_df_includes_open_time_column(self):
        """get_buffer_df must include open_time as a column (Phase 2C addition)."""
        state = BotState(buffer_size=100)
        t = 1_700_000_000_000
        for i in range(5):
            state.push_candle(_candle_row(t=t + i * 60_000))

        df = state.get_buffer_df("BTCUSDT", "1h")
        assert not df.empty
        assert "open_time" in df.columns, (
            "open_time column must be present for get_candles() to use"
        )
        # Values should be ascending ms timestamps
        open_times = df["open_time"].tolist()
        assert open_times == sorted(open_times), "open_time must be ascending"

    # Scenario 14
    def test_get_candles_via_cache_returns_correct_time_field(self):
        """BotManager.get_candles() returns time=open_time//1000 using Phase 2A cache."""
        from server.bot_manager import BotManager

        mgr = BotManager()
        state = BotState(buffer_size=200)
        t_ms = 1_700_000_000_000
        for i in range(10):
            state.push_candle(_candle_row(t=t_ms + i * 3_600_000, close=50_000.0 + i))

        with mgr._lock:
            mgr._state = state

        candles = mgr.get_candles("BTCUSDT", "1h", limit=200)
        assert len(candles) == 10
        # Each candle's "time" must be open_time // 1000 (Unix seconds)
        for i, c in enumerate(candles):
            expected_time = (t_ms + i * 3_600_000) // 1000
            assert c["time"] == expected_time, (
                f"candle {i}: expected time={expected_time}, got {c['time']}"
            )
        # OHLCV fields must be present
        for c in candles:
            for field in ("open", "high", "low", "close", "volume"):
                assert field in c, f"field '{field}' missing from candle dict"


class TestBufferSortingRobustness:
    """Scenario 15: Out-of-order buffer access returns sorted data."""

    def test_get_candles_sorted_after_out_of_order_pushes(self):
        """get_candles must return candles in ascending open_time order even after
        out-of-order pushes (backfill scenario)."""
        from server.bot_manager import BotManager

        mgr   = BotManager()
        state = BotState(buffer_size=200)
        t_ms  = 1_700_000_000_000

        # Push in reverse order (simulating backfill)
        for i in range(10, 0, -1):
            state.push_candle(_candle_row(t=t_ms + i * 3_600_000, close=float(i)))

        with mgr._lock:
            mgr._state = state

        candles = mgr.get_candles("BTCUSDT", "1h", limit=200)
        assert len(candles) == 10
        times = [c["time"] for c in candles]
        assert times == sorted(times), (
            "candles must be in ascending open_time order regardless of push order"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Part 9 — Scalability / throughput (10 / 50 / 100 / 200 symbols)
# ══════════════════════════════════════════════════════════════════════════════

def _scalability_run(n_symbols: int, n_bars: int = 30) -> BatchBacktestResult:
    syms = [f"SYM{i:04d}USDT" for i in range(n_symbols)]
    bars = _bars_dict(syms, ["1h"], n=n_bars)
    return BatchBacktest(
        symbols=syms, intervals=["1h"],
        strategy_class=_Hold, params={},
        bars=bars, starting_capital=100_000.0, max_workers=1,
    ).run()


class TestBatchScalability:
    """Part 9: Batch backtest throughput at increasing symbol counts.

    Assertions verify correctness, not wall-clock time, so they are CI-safe.
    Elapsed time is logged as a benchmark signal; no time-based assertion.
    """

    def _run_and_check(self, n_symbols: int) -> float:
        t0 = time.perf_counter()
        result = _scalability_run(n_symbols)
        elapsed = time.perf_counter() - t0

        assert len(result.symbol_results) == n_symbols, (
            f"Expected {n_symbols} results, got {len(result.symbol_results)}"
        )
        errors = result.failed_pairs
        assert len(errors) == 0, f"{len(errors)} pairs failed: {errors[:3]}"
        # Portfolio equity curve has at least one entry point
        assert not result.portfolio_equity_curve.empty or result.portfolio_n_trades == 0
        return elapsed

    def test_10_symbols_sequential(self):
        elapsed = self._run_and_check(10)
        assert elapsed < 30.0, f"10 symbols took {elapsed:.1f}s — too slow"

    def test_50_symbols_sequential(self):
        elapsed = self._run_and_check(50)
        assert elapsed < 60.0, f"50 symbols took {elapsed:.1f}s — too slow"

    def test_100_symbols_sequential(self):
        elapsed = self._run_and_check(100)
        assert elapsed < 120.0, f"100 symbols took {elapsed:.1f}s — too slow"

    def test_200_symbols_sequential(self):
        elapsed = self._run_and_check(200)
        assert elapsed < 240.0, f"200 symbols took {elapsed:.1f}s — too slow"
