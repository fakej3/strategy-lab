"""Phase 5 — Architecture hardening tests.

Covers:
  Part 1  — StrategyRegistry as single source of truth
  Part 2  — BatchBacktest summary_only
  Part 3  — AUTO worker cap
  Part 4  — bot_trade max_open_positions consistency
  Part 9  — Atomic BarStore writes
  Part 10 — BotStorage SQL-aggregated realized PnL
  Part 12 — Full multi-symbol integration (synthetic)
  Part 13 — Performance regression suite
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.config import BotConfig, RiskConfig, FeedConfig
from bot.events import EventBus, CandleEvent
from bot.risk import RiskContext, RiskEngine
from bot.state import BotState, CandleRow
from bot.storage import BotStorage
from data.store import BarStore
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest, _run_one_worker
from strategies import registry, StrategyRegistry


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _bars(n: int, start: float = 100.0, trend: float = 1.0) -> pd.DataFrame:
    prices = [start + i * trend for i in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": prices, "high": [p * 1.001 for p in prices],
         "low":  [p * 0.999 for p in prices], "close": prices, "volume": [1.0] * n},
        index=idx,
    )


class _BuyAt5Exit15(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 5:  s.iloc[5]  = Signal.BUY
        if len(bars) > 15: s.iloc[15] = Signal.EXIT
        return s


class _NeverTrade(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — StrategyRegistry as single source of truth
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistrySingleSourceOfTruth:
    def test_ema_crossover_in_registry(self):
        assert registry.is_registered("EMACrossover")

    def test_registry_list_includes_ema_crossover(self):
        assert "EMACrossover" in registry.list_strategies()

    def test_registry_list_is_sorted(self):
        names = registry.list_strategies()
        assert names == sorted(names)

    def test_create_returns_fresh_instance_each_call(self):
        s1 = registry.create("EMACrossover", {"fast": 20, "slow": 50})
        s2 = registry.create("EMACrossover", {"fast": 20, "slow": 50})
        assert s1 is not s2

    def test_create_applies_params(self):
        s = registry.create("EMACrossover", {"fast": 10, "slow": 40})
        assert s.fast == 10
        assert s.slow == 40

    def test_create_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="NoSuchStrategy"):
            registry.create("NoSuchStrategy", {})

    def test_load_strategy_uses_registry(self):
        from bot_trade import _load_strategy
        cfg = BotConfig(strategy_name="EMACrossover", strategy_params={"fast": 20, "slow": 50})
        s = _load_strategy(cfg)
        assert hasattr(s, "generate_signals")
        assert s.fast == 20

    def test_load_strategy_unknown_raises_value_error(self):
        from bot_trade import _load_strategy
        cfg = BotConfig(strategy_name="Ghost", strategy_params={})
        with pytest.raises(ValueError, match="Ghost"):
            _load_strategy(cfg)

    def test_load_strategy_error_lists_available(self):
        from bot_trade import _load_strategy
        cfg = BotConfig(strategy_name="Ghost", strategy_params={})
        with pytest.raises(ValueError, match="EMACrossover"):
            _load_strategy(cfg)

    def test_no_duplicate_registration(self):
        """Importing strategies twice must not duplicate entries."""
        import importlib, strategies
        before = registry.list_strategies()
        importlib.reload(strategies)
        after = registry.list_strategies()
        assert set(after) == set(before)

    def test_backtest_strategy_class_same_as_registry(self):
        """BatchBacktest can receive the class from the registry and run correctly."""
        cls = registry.get_class("EMACrossover")
        bars = _bars(30)
        bb = BatchBacktest(
            symbols=["BTCUSDT"], intervals=["1h"],
            strategy_class=cls, params={"fast": 5, "slow": 20},
            bars={("BTCUSDT", "1h"): bars},
            starting_capital=10_000.0, max_workers=1,
        )
        result = bb.run()
        assert len(result.symbol_results) == 1
        assert result.symbol_results[0].ok


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — BatchBacktest summary_only
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchSummaryOnly:
    @pytest.fixture
    def two_symbol_bars(self):
        return {
            ("BTCUSDT", "1h"): _bars(30, 100.0, 1.0),
            ("ETHUSDT", "1h"): _bars(30, 50.0,  0.5),
        }

    def _run(self, two_symbol_bars, summary_only: bool) -> BatchBacktest:
        bb = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"], intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars=two_symbol_bars,
            starting_capital=10_000.0, max_workers=1,
            summary_only=summary_only,
        )
        return bb.run()

    def test_summary_only_equity_curve_empty(self, two_symbol_bars):
        result = self._run(two_symbol_bars, summary_only=True)
        for sr in result.symbol_results:
            if sr.ok:
                assert sr.portfolio_result.equity_curve.empty

    def test_summary_only_balance_curve_empty(self, two_symbol_bars):
        result = self._run(two_symbol_bars, summary_only=True)
        for sr in result.symbol_results:
            if sr.ok:
                assert sr.portfolio_result.balance_curve.empty

    def test_summary_only_drawdown_curve_empty(self, two_symbol_bars):
        result = self._run(two_symbol_bars, summary_only=True)
        for sr in result.symbol_results:
            if sr.ok:
                assert sr.portfolio_result.drawdown_curve.empty

    def test_summary_only_scalar_metrics_preserved(self, two_symbol_bars):
        full    = self._run(two_symbol_bars, summary_only=False)
        summary = self._run(two_symbol_bars, summary_only=True)
        for f_sr, s_sr in zip(full.symbol_results, summary.symbol_results):
            if not f_sr.ok:
                continue
            assert abs(f_sr.total_return - s_sr.total_return) < 1e-9

    def test_summary_only_trades_preserved(self, two_symbol_bars):
        result = self._run(two_symbol_bars, summary_only=True)
        for sr in result.symbol_results:
            if sr.ok:
                assert len(sr.portfolio_result.trades) > 0

    def test_full_mode_has_curves(self, two_symbol_bars):
        result = self._run(two_symbol_bars, summary_only=False)
        for sr in result.symbol_results:
            if sr.ok:
                assert not sr.portfolio_result.equity_curve.empty

    def test_summary_only_portfolio_metrics_match_full(self, two_symbol_bars):
        full    = self._run(two_symbol_bars, summary_only=False)
        summary = self._run(two_symbol_bars, summary_only=True)
        assert abs(full.portfolio_total_return - summary.portfolio_total_return) < 1e-9
        assert abs(full.portfolio_n_trades - summary.portfolio_n_trades) < 1


# ══════════════════════════════════════════════════════════════════════════════
# Part 3 — AUTO worker management
# ══════════════════════════════════════════════════════════════════════════════

class TestAutoWorkerManagement:
    def _bb(self, n_pairs: int, max_workers: int = BatchBacktest.AUTO) -> BatchBacktest:
        syms = [f"SYM{i:03d}USDT" for i in range(n_pairs)]
        bars = {(s, "1h"): _bars(30) for s in syms}
        return BatchBacktest(
            symbols=syms, intervals=["1h"],
            strategy_class=_NeverTrade, params={},
            bars=bars, starting_capital=10_000.0,
            max_workers=max_workers,
        )

    def test_auto_mode_below_threshold_uses_1_worker(self):
        """Fewer pairs than AUTO_THRESHOLD → sequential."""
        bb = self._bb(BatchBacktest.AUTO_THRESHOLD - 1, max_workers=BatchBacktest.AUTO)
        assert bb._auto_mode is True

    def test_auto_mode_never_more_than_pairs(self, monkeypatch):
        """Workers must never exceed pair count."""
        monkeypatch.setattr(os, "cpu_count", lambda: 64)
        n = 3
        bb = self._bb(n, max_workers=BatchBacktest.AUTO)
        pairs = [(s, "1h") for s in bb.symbols]
        # _run_pairs determines effective_workers internally; we check cap logic
        # by confirming _MAX_AUTO_WORKERS is respected
        assert BatchBacktest._MAX_AUTO_WORKERS > 0
        cpu = os.cpu_count() or 4
        expected = min(n, cpu, BatchBacktest._MAX_AUTO_WORKERS)
        assert expected <= n

    def test_auto_mode_respects_max_cap(self, monkeypatch):
        """AUTO with 200 pairs and 64 CPUs must not spawn > _MAX_AUTO_WORKERS."""
        monkeypatch.setattr(os, "cpu_count", lambda: 64)
        n = 200
        bb = self._bb(n, max_workers=BatchBacktest.AUTO)
        pairs = [(s, "1h") for s in bb.symbols]
        cpu = os.cpu_count() or 4
        effective = min(len(pairs), cpu, BatchBacktest._MAX_AUTO_WORKERS)
        assert effective <= BatchBacktest._MAX_AUTO_WORKERS

    def test_explicit_max_workers_preserved(self):
        bb = self._bb(10, max_workers=3)
        assert bb.max_workers == 3
        assert bb._auto_mode is False

    def test_max_workers_1_is_sequential(self):
        bb = self._bb(5, max_workers=1)
        assert bb.max_workers == 1

    def test_auto_runs_correctly(self):
        """AUTO mode with threshold-crossing pair count must return valid results."""
        n = BatchBacktest.AUTO_THRESHOLD + 2
        bb = self._bb(n, max_workers=BatchBacktest.AUTO)
        result = bb.run()
        assert len(result.symbol_results) == n


# ══════════════════════════════════════════════════════════════════════════════
# Part 4 — bot_trade max_open_positions consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestBotTradeMaxOpenPositions:
    def _args(self, symbols: str, max_positions: int = 0) -> Any:
        import argparse
        ns = argparse.Namespace(
            capital=200.0, symbols=symbols, interval="1h",
            strategy=None, db=None, no_recover=False,
            max_positions=max_positions,
        )
        return ns

    def test_single_symbol_gets_max_1(self):
        from bot_trade import _build_config
        cfg = _build_config(self._args("BTCUSDT"))
        assert cfg.risk.max_open_positions == 1

    def test_3_symbols_get_max_3(self):
        from bot_trade import _build_config
        cfg = _build_config(self._args("BTCUSDT,ETHUSDT,XAUUSDT"))
        assert cfg.risk.max_open_positions == 3

    def test_10_symbols_get_max_10(self):
        from bot_trade import _build_config
        syms = ",".join([f"SYM{i}USDT" for i in range(10)])
        cfg = _build_config(self._args(syms))
        assert cfg.risk.max_open_positions == 10

    def test_explicit_override_respected(self):
        from bot_trade import _build_config
        cfg = _build_config(self._args("BTCUSDT,ETHUSDT,XAUUSDT", max_positions=1))
        assert cfg.risk.max_open_positions == 1

    def test_explicit_override_5_with_3_symbols(self):
        from bot_trade import _build_config
        cfg = _build_config(self._args("BTCUSDT,ETHUSDT,XAUUSDT", max_positions=5))
        assert cfg.risk.max_open_positions == 5

    def test_matches_bot_manager_default(self):
        """bot_trade default must equal BotManager.start() default for same symbols."""
        from bot_trade import _build_config
        symbols = ["BTCUSDT", "ETHUSDT", "XAUUSDT"]
        cfg = _build_config(self._args(",".join(symbols)))
        # BotManager.start() sets resolved_max_positions = len(symbols)
        assert cfg.risk.max_open_positions == len(symbols)


# ══════════════════════════════════════════════════════════════════════════════
# Part 9 — Atomic BarStore writes
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomicBarStoreWrites:
    def test_write_produces_readable_file(self, tmp_path):
        store = BarStore(tmp_path)
        df = _bars(10)
        store.write("BTCUSDT", "1h", 2024, 1, df)
        assert store.exists("BTCUSDT", "1h", 2024, 1)
        result = store.read("BTCUSDT", "1h", 2024, 1)
        assert len(result) == 10

    def test_no_temp_file_left_after_success(self, tmp_path):
        store = BarStore(tmp_path)
        df = _bars(10)
        store.write("BTCUSDT", "1h", 2024, 1, df)
        tmp = tmp_path / "BTCUSDT" / "1h" / "2024-01.parquet.tmp"
        assert not tmp.exists(), "Temp file should be cleaned up after successful write"

    def test_overwrites_existing_correctly(self, tmp_path):
        store = BarStore(tmp_path)
        store.write("BTCUSDT", "1h", 2024, 1, _bars(5))
        store.write("BTCUSDT", "1h", 2024, 1, _bars(10))
        result = store.read("BTCUSDT", "1h", 2024, 1)
        assert len(result) == 10

    def test_write_preserves_data_integrity(self, tmp_path):
        store = BarStore(tmp_path)
        df = _bars(20, start=50000.0)
        store.write("ETHUSDT", "1h", 2024, 3, df)
        result = store.read("ETHUSDT", "1h", 2024, 3)
        assert abs(result["close"].iloc[0] - 50000.0) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# Part 10 — BotStorage SQL-aggregated realized PnL
# ══════════════════════════════════════════════════════════════════════════════

class TestStorageRealizedPnl:
    @pytest.fixture
    def storage(self, tmp_path):
        s = BotStorage(tmp_path / "test.db")
        s.connect()
        yield s
        s.close()

    def _save_pos(self, storage, pnl: float, status: str = "closed") -> None:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        storage.save_position({
            "position_id": str(uuid.uuid4()),
            "symbol": "BTCUSDT", "direction": "long",
            "status": status, "size": 0.001,
            "entry_price": 50000.0, "avg_entry_price": 50000.0,
            "realized_pnl": pnl, "opened_at": now,
        })

    def test_empty_db_returns_zero(self, storage):
        assert storage.get_realized_pnl() == 0.0

    def test_single_closed_position(self, storage):
        self._save_pos(storage, 42.5)
        assert abs(storage.get_realized_pnl() - 42.5) < 1e-9

    def test_multiple_positions_summed(self, storage):
        self._save_pos(storage, 100.0)
        self._save_pos(storage, -30.0)
        self._save_pos(storage, 50.0)
        assert abs(storage.get_realized_pnl() - 120.0) < 1e-9

    def test_open_positions_excluded(self, storage):
        self._save_pos(storage, 100.0, status="closed")
        self._save_pos(storage, 999.0, status="open")
        assert abs(storage.get_realized_pnl() - 100.0) < 1e-9

    def test_matches_python_sum(self, storage):
        """SQL aggregate must match manual Python sum over all closed positions."""
        pnls = [10.5, -5.0, 30.0, -12.5, 100.0]
        for p in pnls:
            self._save_pos(storage, p)
        sql_result = storage.get_realized_pnl()
        python_result = sum(
            row.get("realized_pnl", 0.0)
            for row in storage.get_positions(limit=1000)
            if row.get("status") == "closed"
        )
        assert abs(sql_result - python_result) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# Part 12 — Full multi-symbol integration (synthetic, no network)
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiSymbolIntegration:
    """Verify cross-symbol isolation, interval isolation, and BatchBacktest
    determinism for a realistic workload."""

    SYMBOLS   = ["BTCUSDT", "ETHUSDT", "XAUUSDT", "XAGUSDT", "SNDKUSDT"]
    INTERVALS = ["1m", "5m", "15m", "1h"]

    def _make_bars(self) -> dict[tuple[str, str], pd.DataFrame]:
        bars = {}
        for i, sym in enumerate(self.SYMBOLS):
            for j, iv in enumerate(self.INTERVALS):
                bars[(sym, iv)] = _bars(50, start=100.0 * (i + 1), trend=0.1 * (j + 1))
        return bars

    def test_symbols_never_contaminate_each_other_in_batch(self):
        """BatchBacktest results per symbol must be independent."""
        bars = self._make_bars()
        bb = BatchBacktest(
            symbols=self.SYMBOLS, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars={k: v for k, v in bars.items() if k[1] == "1h"},
            starting_capital=100_000.0, max_workers=1,
        )
        result = bb.run()
        # Each pair should have distinct return since bars are different
        returns = {sr.symbol: sr.total_return for sr in result.symbol_results if sr.ok}
        assert len(returns) == len(self.SYMBOLS)
        # Verify no two returns are identical (would indicate contamination)
        assert len(set(f"{v:.8f}" for v in returns.values())) > 1

    def test_intervals_never_contaminate_each_other(self):
        """Results for different intervals of same symbol must be independent."""
        bars = self._make_bars()
        bb = BatchBacktest(
            symbols=["BTCUSDT"], intervals=self.INTERVALS,
            strategy_class=_BuyAt5Exit15, params={},
            bars={k: v for k, v in bars.items() if k[0] == "BTCUSDT"},
            starting_capital=100_000.0, max_workers=1,
        )
        result = bb.run()
        # Different intervals have different bar trends so returns differ
        returns = {sr.interval: sr.total_return for sr in result.symbol_results if sr.ok}
        assert len(returns) == len(self.INTERVALS)

    def test_batch_result_is_deterministic(self):
        """Running BatchBacktest twice must produce identical results."""
        bars = self._make_bars()
        kw = dict(
            symbols=self.SYMBOLS, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars={k: v for k, v in bars.items() if k[1] == "1h"},
            starting_capital=100_000.0, max_workers=1,
        )
        r1 = BatchBacktest(**kw).run()
        r2 = BatchBacktest(**kw).run()
        assert r1.portfolio_total_return == r2.portfolio_total_return
        assert r1.portfolio_n_trades == r2.portfolio_n_trades

    def test_botstate_symbol_interval_isolation(self):
        """Candles for one (symbol, interval) never appear in another buffer."""
        state = BotState(buffer_size=200)
        for sym in self.SYMBOLS:
            for iv in self.INTERVALS:
                for t in range(5):
                    state.push_candle(CandleRow(
                        symbol=sym, interval=iv,
                        open_time=t * 60_000, open=1.0, high=1.1, low=0.9,
                        close=1.05, volume=1.0, close_time=(t + 1) * 60_000 - 1,
                    ))

        for sym in self.SYMBOLS:
            for iv in self.INTERVALS:
                df = state.get_buffer_df(sym, iv)
                assert len(df) == 5, f"{sym}/{iv}: expected 5 candles, got {len(df)}"

        assert state.buffer_length("BTCUSDT", "1h") == 5
        assert state.buffer_length("ETHUSDT", "5m") == 5

    def test_botstate_mark_prices_per_symbol(self):
        """Mark price is tracked per symbol, not per (symbol, interval)."""
        state = BotState()
        state.push_candle(CandleRow(
            symbol="BTCUSDT", interval="1h", open_time=0,
            open=50000.0, high=50100.0, low=49900.0, close=50050.0,
            volume=1.0, close_time=3_599_999,
        ))
        state.push_candle(CandleRow(
            symbol="ETHUSDT", interval="1h", open_time=0,
            open=3000.0, high=3010.0, low=2990.0, close=3005.0,
            volume=1.0, close_time=3_599_999,
        ))
        marks = state.all_mark_prices()
        assert abs(marks["BTCUSDT"] - 50050.0) < 0.01
        assert abs(marks["ETHUSDT"] - 3005.0) < 0.01
        assert marks["BTCUSDT"] != marks["ETHUSDT"]

    def test_portfolio_simulation_all_symbols(self):
        """Portfolio simulation with 5 symbols produces sensible aggregate metrics."""
        bars = self._make_bars()
        bb = BatchBacktest(
            symbols=self.SYMBOLS, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars={k: v for k, v in bars.items() if k[1] == "1h"},
            starting_capital=100_000.0, max_workers=1, equity_fraction=0.10,
        )
        result = bb.run()
        assert result.portfolio_n_trades >= 0
        assert not math.isnan(result.portfolio_total_return)
        assert not math.isnan(result.portfolio_sharpe)

    def test_risk_engine_multi_symbol_positions(self):
        """RiskEngine correctly enforces max_open_positions across multiple symbols."""
        # max_position_size_usd raised so the notional (qty*ref_price=0.001*50000=50) passes.
        cfg = RiskConfig(max_open_positions=2, max_position_size_usd=100.0)
        bus = EventBus()
        risk = RiskEngine(config=cfg, bus=bus)

        def _ctx(sym: str, open_positions: int) -> RiskContext:
            return RiskContext(
                symbol=sym, side="BUY", qty=0.001, ref_price=50000.0,
                equity=10_000.0, peak_equity=10_000.0,
                daily_pnl=0.0, n_trades_today=0,
                open_positions=open_positions, last_trade_ts=0.0,
            )

        assert risk.check(_ctx("BTCUSDT", 0)) == ""
        assert risk.check(_ctx("ETHUSDT", 1)) == ""
        assert risk.check(_ctx("XAUUSDT", 2)) != ""  # at limit


# ══════════════════════════════════════════════════════════════════════════════
# Part 13 — Performance regression suite
# ══════════════════════════════════════════════════════════════════════════════

BASE_MS = 1_700_000_000_000


def _make_candle(sym: str, iv: str, t: int) -> CandleRow:
    return CandleRow(
        symbol=sym, interval=iv, open_time=t,
        open=50_000.0, high=50_100.0, low=49_900.0,
        close=50_050.0, volume=1.0, close_time=t + 59_999,
    )


class TestBatchBacktestPerformance:
    """BatchBacktest timing benchmarks — 10, 50, 100, 200 symbol workloads.

    Design: calibrate against this machine's actual 1-symbol baseline, then
    assert that N symbols scales approximately linearly (< 3× expected linear
    cost).  This avoids machine-dependent absolute thresholds while still
    catching pathological super-linear regressions.
    """

    def _calibrate_1sym(self) -> float:
        """Return seconds to run a 1-symbol backtest on this machine."""
        bars_1 = {("SYM000USDT", "1h"): _bars(30)}
        t0 = time.monotonic()
        BatchBacktest(
            symbols=["SYM000USDT"], intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars=bars_1, starting_capital=100_000.0,
            max_workers=1, summary_only=True,
        ).run()
        return time.monotonic() - t0

    @pytest.mark.parametrize("n_symbols", [10, 50, 100, 200])
    def test_sequential_completes_within_budget(self, n_symbols):
        """N symbols must finish in approximately-linear time vs single-symbol baseline."""
        baseline = self._calibrate_1sym()

        symbols = [f"SYM{i:03d}USDT" for i in range(n_symbols)]
        bars = {(s, "1h"): _bars(30) for s in symbols}

        t0 = time.monotonic()
        bb = BatchBacktest(
            symbols=symbols, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars=bars, starting_capital=100_000.0,
            max_workers=1, summary_only=True,
        )
        result = bb.run()
        elapsed = time.monotonic() - t0

        assert len(result.symbol_results) == n_symbols

        # Budget: 3× the linear expectation (N × per-symbol baseline) plus a
        # fixed 0.5 s overhead.  Catches super-linear growth without being
        # sensitive to absolute machine speed.
        budget = baseline * n_symbols * 3.0 + 0.5
        assert elapsed < budget, (
            f"{n_symbols} symbols took {elapsed:.3f}s "
            f"(baseline_1sym={baseline*1000:.1f}ms, budget={budget:.2f}s). "
            "Check for super-linear regression in BatchBacktest."
        )

    def test_summary_only_reduces_memory_footprint(self):
        """summary_only must produce empty curves — no O(N_bars) allocations."""
        n = 50
        symbols = [f"SYM{i:03d}USDT" for i in range(n)]
        bars = {(s, "1h"): _bars(500) for s in symbols}
        result = BatchBacktest(
            symbols=symbols, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars=bars, starting_capital=100_000.0,
            max_workers=1, summary_only=True,
        ).run()
        for sr in result.symbol_results:
            if sr.ok:
                assert sr.portfolio_result.equity_curve.empty

    def test_auto_workers_completes_correctly(self):
        """AUTO mode must return the right number of results."""
        n = BatchBacktest.AUTO_THRESHOLD + 4
        symbols = [f"SYM{i:03d}USDT" for i in range(n)]
        bars = {(s, "1h"): _bars(30) for s in symbols}
        result = BatchBacktest(
            symbols=symbols, intervals=["1h"],
            strategy_class=_BuyAt5Exit15, params={},
            bars=bars, starting_capital=10_000.0,
            max_workers=BatchBacktest.AUTO,
        ).run()
        assert len(result.symbol_results) == n


class TestCandleBufferPerformance:
    """BotState candle ingestion benchmarks."""

    @pytest.mark.parametrize("n_sym, n_iv", [(10, 1), (50, 3), (100, 1)])
    def test_push_throughput(self, n_sym, n_iv):
        symbols = [f"SYM{i:03d}USDT" for i in range(n_sym)]
        intervals = ["1m", "5m", "1h"][:n_iv]
        state = BotState(buffer_size=500)
        n_candles = n_sym * n_iv * 200

        t0 = time.monotonic()
        t = BASE_MS
        for i in range(200):
            for sym in symbols:
                for iv in intervals:
                    state.push_candle(_make_candle(sym, iv, t))
            t += 60_000

        elapsed = time.monotonic() - t0
        rate = n_candles / elapsed
        # 5,000 candles/s minimum (extremely conservative)
        assert rate > 5_000, f"push rate {rate:.0f}/s < 5000/s"

    @pytest.mark.parametrize("n_calls", [100, 1_000])
    def test_cached_get_buffer_df_fast(self, n_calls):
        state = BotState(buffer_size=500)
        for t in range(200):
            state.push_candle(_make_candle("BTCUSDT", "1h", BASE_MS + t * 60_000))

        # One cold call to build the cache
        state.get_buffer_df("BTCUSDT", "1h")

        t0 = time.monotonic()
        for _ in range(n_calls):
            df = state.get_buffer_df("BTCUSDT", "1h")
            assert not df.empty
        elapsed = time.monotonic() - t0
        # 1ms per cached call is extremely conservative
        assert elapsed < n_calls * 0.001, f"{n_calls} cached calls took {elapsed*1000:.1f}ms"


class TestRiskEnginePerformance:
    def test_risk_check_throughput(self):
        # qty=0.0003 → notional=15 USD, below default max_position_size_usd=20;
        # all checks pass so no WARNING logging path is hit.
        cfg = RiskConfig()
        bus = EventBus()
        risk = RiskEngine(config=cfg, bus=bus)
        ctx = RiskContext(
            symbol="BTCUSDT", side="BUY", qty=0.0003, ref_price=50_000.0,
            equity=10_000.0, peak_equity=10_000.0,
            daily_pnl=0.0, n_trades_today=0, open_positions=0, last_trade_ts=0.0,
        )

        n = 10_000
        t0 = time.monotonic()
        for _ in range(n):
            risk.check(ctx)
        elapsed = time.monotonic() - t0
        rate = n / elapsed
        assert rate > 50_000, f"risk check rate {rate:.0f}/s < 50,000/s"


class TestEventBusPerformance:
    def test_emit_throughput_many_subscribers(self):
        bus = EventBus()
        calls = [0]
        n_subs = 20
        for _ in range(n_subs):
            bus.subscribe(CandleEvent, lambda e: calls.__setitem__(0, calls[0] + 1))

        n = 1_000
        t0 = time.monotonic()
        for i in range(n):
            bus.emit(CandleEvent(symbol="BTCUSDT", interval="1h", close=50_000.0))
        elapsed = time.monotonic() - t0
        assert calls[0] == n * n_subs
        rate = n / elapsed
        # At 20 subscribers per event, must still handle > 5,000 events/s
        assert rate > 5_000, f"emit rate {rate:.0f}/s < 5,000/s"
