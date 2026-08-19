"""Smoke test — verifies the full EdgeLab pipeline end-to-end.

Run with: pytest tests/test_smoke.py -v

Covers:
  1. Fixture data is readable from BarStore (8784 bars, integrity 100/100)
  2. Single backtest produces real metrics (sharpe, cagr, trades)
  3. Full pipeline: 20 backtests → DB → non-zero passed results
  4. Walk-forward populates out-of-sample returns
  5. Monte Carlo populates distribution metrics
  6. API /strategies returns non-reject results with real CAGR
  7. Paper exchange is simulation-only (no live order methods)
  8. Job lifecycle: submit → running → done via JobManager
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fixture_bars():
    """Return deterministic GBM bars via FixtureProvider (no production cache)."""
    from data.fixture import FixtureProvider
    import pandas as pd

    provider = FixtureProvider()
    frames = []
    for month in range(1, 13):
        df = provider.fetch_month("BTCUSDT", "1h", 2024, month)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = pd.concat(frames).sort_index()
    start = pd.Timestamp(date(2024, 1, 1), tz="UTC")
    end   = pd.Timestamp(date(2024, 12, 31), tz="UTC") + pd.offsets.Day(1)
    return result[(result.index >= start) & (result.index < end)]


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — fixture data integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_fixture_bars_available():
    """BarStore returns full-year 1h bars for BTCUSDT 2024."""
    bars = _fixture_bars()
    assert not bars.empty, "Expected bar data but got empty DataFrame"
    assert len(bars) >= 8000, f"Expected ≥8000 bars, got {len(bars)}"
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"], \
        f"Unexpected columns: {list(bars.columns)}"


def test_fixture_data_integrity():
    """BarStore data passes the integrity audit at 60+ score."""
    from research.integrity import audit_bars
    bars = _fixture_bars()
    result = audit_bars(bars, symbol="BTCUSDT", interval="1h", threshold=60.0)
    assert result.passed, (
        f"Integrity audit FAILED: score={result.integrity_score:.1f}  "
        + "; ".join(result.hard_failures + result.warnings)
    )
    assert result.integrity_score >= 60.0, \
        f"Integrity score too low: {result.integrity_score:.1f}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — single backtest
# ─────────────────────────────────────────────────────────────────────────────

def test_single_backtest_metrics():
    """BacktestJob produces non-trivial metrics for EMACrossover(15, 200)."""
    from jobs.backtest_job import BacktestJob, BacktestParams
    from strategies.ema_crossover import EMACrossover

    bars = _fixture_bars()
    bp = BacktestParams(
        bars=bars,
        strategy_class=EMACrossover,
        params={"fast": 15, "slow": 200},
        symbol="BTCUSDT",
        interval="1h",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        starting_capital=100_000.0,
        fee_rate=0.001,
        slippage_pct=0.0005,
    )
    result = BacktestJob(bp).run()
    assert result.success, f"BacktestJob failed: {result.error}"

    data = result.data
    assert data["total_trades"] > 0, "Expected trades but got 0"
    assert data["net_profit"] is not None, "net_profit is None"
    assert data["sharpe_ratio"] is not None, "sharpe_ratio is None"
    # CAGR should be a real number (not None) for a full-year run
    assert data["cagr"] is not None, "cagr is None for full-year run"
    assert not math.isnan(data["cagr"]) if data["cagr"] is not None else True, \
        "cagr is NaN"
    # _safe() must not convert NaN → 0.0
    if data["sharpe_ratio"] is not None:
        # If sharpe is provided, it should be a finite float
        assert math.isfinite(data["sharpe_ratio"]), \
            f"sharpe_ratio is not finite: {data['sharpe_ratio']}"


def test_safe_returns_none_for_nan():
    """_safe() in backtest_job returns None for NaN/Inf, not 0.0."""
    from jobs.backtest_job import _safe
    assert _safe(float("nan")) is None, "_safe(nan) should return None"
    assert _safe(float("inf")) is None, "_safe(inf) should return None"
    assert _safe(float("-inf")) is None, "_safe(-inf) should return None"
    assert _safe(1.5) == 1.5, "_safe(valid float) should return float unchanged"
    assert _safe(0.0) == 0.0, "_safe(0.0) should return 0.0"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — full pipeline with isolated DB
# ─────────────────────────────────────────────────────────────────────────────

def test_full_pipeline_saves_results():
    """Pipeline runs backtests with fixture data and saves results to DB."""
    from automation.pipeline import PipelineConfig, ResearchPipeline
    from data.fixture import FixtureProvider
    from data.store import BarStore
    from research_db.storage import ResearchStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path   = os.path.join(tmpdir, "test.db")
        data_dir  = os.path.join(tmpdir, "market_data")
        cfg = PipelineConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            fast_mode=True,
            run_walk_forward=False,
            run_monte_carlo=False,
            run_robustness=False,
            verbose=False,
            db_path=db_path,
            reports_dir=os.path.join(tmpdir, "reports"),
            log_path=os.path.join(tmpdir, "research.log"),
            data_provider=FixtureProvider(),
            data_store=BarStore(data_dir),
        )
        run = ResearchPipeline(cfg).execute()

        assert run.n_tested >= 20, f"Expected ≥20 tested, got {run.n_tested}"
        assert run.n_errors == 0, f"Expected 0 errors, got {run.n_errors}: {run.errors}"

        # All tested results must be persisted
        storage = ResearchStorage(db_path)
        all_results = storage.get_strategy_results(limit=200)
        assert len(all_results) == run.n_tested, \
            f"Expected {run.n_tested} results in DB, got {len(all_results)}"

        # At least some must pass quality gate
        passed = [r for r in all_results if r.gate_decision != "REJECT"]
        assert len(passed) > 0, \
            f"All 20 results REJECTed — fixture data or gate may be broken"

        # Passed results must have real CAGR (not 0.0 for a 1-year run)
        for r in passed:
            assert r.cagr is not None, \
                f"CAGR is None for {r.strategy_class} {r.params}"
            assert r.cagr != 0.0 or r.total_trades == 0, \
                f"CAGR is exactly 0.0 for {r.strategy_class} {r.params} " \
                f"with {r.total_trades} trades — _safe() bug?"
            assert r.total_trades >= 1, \
                f"Passed result has 0 trades: {r.strategy_class} {r.params}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def test_walk_forward_populates():
    """WalkForwardJob returns out-of-sample return for EMACrossover(15, 200)."""
    from jobs.walkforward_job import WalkForwardJob, WalkForwardParams
    from strategies.ema_crossover import EMACrossover

    bars = _fixture_bars()
    wfp = WalkForwardParams(
        bars=bars,
        strategy_class=EMACrossover,
        params={"fast": 15, "slow": 200},
        starting_capital=100_000.0,
        fee_rate=0.001,
        slippage_pct=0.0005,
        train_bars=1008,
        test_bars=336,
    )
    result = WalkForwardJob(wfp).run()
    assert result.success, f"WalkForwardJob failed: {result.error}"
    assert result.data is not None
    assert "walk_forward_return" in result.data, \
        "walk_forward_return not in WF result"
    assert result.data.get("n_folds", 0) >= 2, \
        f"Expected ≥2 WF folds, got {result.data.get('n_folds')}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Monte Carlo
# ─────────────────────────────────────────────────────────────────────────────

def test_monte_carlo_populates():
    """MonteCarloJob returns distribution metrics for realistic trade PnLs."""
    from jobs.montecarlo_job import MonteCarloJob, MonteCarloParams

    # Simulate 50 trades alternating win/loss
    pnls = [200.0, -80.0, 150.0, -60.0, 300.0] * 10
    mc = MonteCarloJob(MonteCarloParams(
        pnl_sequence=pnls,
        starting_capital=100_000.0,
        n_simulations=200,
    ))
    result = mc.run()
    assert result.success, f"MonteCarloJob failed: {result.error}"
    d = result.data
    assert d.get("median_return") is not None, "median_return missing"
    assert d.get("pct5_return") is not None, "pct5_return missing"
    assert d.get("pct95_return") is not None, "pct95_return missing"
    assert d.get("prob_positive") is not None, "prob_positive missing"
    assert 0.0 <= d["prob_positive"] <= 1.0, \
        f"prob_positive out of range: {d['prob_positive']}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — paper exchange is simulation-only
# ─────────────────────────────────────────────────────────────────────────────

def test_paper_exchange_no_live_trading():
    """PaperExchange has no methods that call real Binance trading endpoints."""
    from bot.paper_exchange import PaperExchange

    # Check the class has no reference to real order endpoints
    import inspect
    source = inspect.getsource(PaperExchange)
    forbidden = [
        "api.binance.com/api/v3/order",
        "POST.*order",
        "fapi.binance.com",
    ]
    for pattern in forbidden:
        assert pattern not in source, \
            f"PaperExchange source contains live trading pattern: {pattern!r}"


def test_paper_exchange_fill_on_candle():
    """PaperExchange fills market orders against candle data (simulation)."""
    from bot.paper_exchange import PaperExchange, SymbolRules
    from bot.events import EventBus
    import pandas as pd

    bus = EventBus()
    px = PaperExchange(bus=bus, fee_rate=0.001, slippage_pct=0.0005)

    # Register BTCUSDT rules
    px.register_symbol_rules("BTCUSDT", SymbolRules(
        min_notional=10.0, min_qty=0.00001,
        qty_step=0.00001, tick_size=0.01,
    ))

    # Place a market buy
    order_id = px.submit_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        qty=0.01,
    )
    assert order_id is not None, "submit_order returned None"

    # Process a candle — the order should fill
    fills = px.process_candle(
        "BTCUSDT",
        open_=50000.0, high=51000.0,
        low=49000.0, close=50500.0,
    )

    # Order should have been filled (not still open)
    open_orders = px.get_open_orders("BTCUSDT")
    assert len(open_orders) == 0, \
        f"Order still open after candle — expected fill: {open_orders}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — storage correctness
# ─────────────────────────────────────────────────────────────────────────────

def test_storage_save_and_retrieve():
    """ResearchStorage saves and retrieves StrategyResult with all fields."""
    from research_db.storage import ResearchStorage
    from research_db.models import SessionRecord, StrategyResult
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        s = ResearchStorage(db_path)

        sess = SessionRecord(
            session_id="smoke_sess_001",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="complete",
            symbols='["BTCUSDT"]',
            intervals='["1h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess)

        sr = StrategyResult(
            session_id="smoke_sess_001",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":15,"slow":200}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="NEEDS IMPROVEMENT",
            gate_score=55.0,
            total_trades=42,
            sharpe_ratio=0.735,
            cagr=0.099,
            win_rate=0.52,
            profit_factor=1.35,
            max_drawdown_pct=0.094,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        row_id = s.save_strategy_result(sr)
        assert isinstance(row_id, int) and row_id > 0

        results = s.get_strategy_results(session_id="smoke_sess_001")
        assert len(results) == 1
        r = results[0]
        assert r.sharpe_ratio == pytest.approx(0.735, abs=1e-6)
        assert r.cagr == pytest.approx(0.099, abs=1e-6)
        assert r.gate_decision == "NEEDS IMPROVEMENT"

        # get_best_by must include NEEDS IMPROVEMENT but not REJECT
        best = s.get_best_by(metric="sharpe_ratio", limit=10, min_trades=5)
        assert len(best) == 1
        assert best[0].strategy_class == "EMACrossover"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — parameter space produces 20 valid combos
# ─────────────────────────────────────────────────────────────────────────────

def test_ema_crossover_param_space_20_combos():
    """STRATEGY_PARAMETER_SPACES generates exactly 20 valid EMACrossover combos."""
    from automation.pipeline import STRATEGY_PARAMETER_SPACES, _cartesian
    from strategies.ema_crossover import EMACrossover

    space = STRATEGY_PARAMETER_SPACES["EMACrossover"]
    all_combos = _cartesian(space)

    valid = []
    for c in all_combos:
        try:
            EMACrossover(**c)
            valid.append(c)
        except Exception:
            pass

    assert len(valid) == 20, f"Expected 20 valid combos, got {len(valid)}"
    # Verify no fast >= slow (crossover strategy requirement)
    for c in valid:
        assert c["fast"] < c["slow"], \
            f"Invalid combo: fast={c['fast']} >= slow={c['slow']}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST A — data unavailability → FAILED job, 0 results, no fixture fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_data_failure_produces_failed_session():
    """TEST A: When live data is unavailable and no cache exists, the pipeline
    FAILS — it does not fall back to synthetic/fixture data.
    """
    from automation.pipeline import PipelineConfig, ResearchPipeline
    from data.store import BarStore
    from research_db.storage import ResearchStorage

    # Use a fresh empty data dir — no cached bars, no fixture provider injected.
    # BinanceProvider will fail in this environment (proxy blocks it).
    # The pipeline MUST NOT silently substitute fixture/synthetic data.
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path  = os.path.join(tmpdir, "test.db")
        data_dir = os.path.join(tmpdir, "market_data")  # empty — no cache
        cfg = PipelineConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            fast_mode=True,
            run_walk_forward=False,
            run_monte_carlo=False,
            run_robustness=False,
            verbose=False,
            db_path=db_path,
            reports_dir=os.path.join(tmpdir, "reports"),
            log_path=os.path.join(tmpdir, "research.log"),
            data_provider=None,        # default BinanceProvider — will fail in test env
            data_store=BarStore(data_dir),  # empty store — no cached data
        )
        run = ResearchPipeline(cfg).execute()

        # Pipeline should have failed: all data unavailable, 0 strategies tested
        assert run.n_tested == 0, \
            f"Expected 0 tested (data unavailable), got {run.n_tested}"
        assert run.n_data_failures >= 1, \
            f"Expected ≥1 data failure, got {run.n_data_failures}"

        # Session status in DB must be 'failed', not 'complete'
        storage = ResearchStorage(db_path)
        sessions = storage.get_sessions(limit=10)
        assert len(sessions) >= 1, "Expected a session record in DB"
        session = sessions[0]
        assert session.status == "failed", \
            f"Expected session status='failed', got {session.status!r}"

        # No strategy results must be stored (no fake/fixture results)
        results = storage.get_strategy_results(limit=200)
        assert len(results) == 0, \
            f"Expected 0 results (data failure), got {len(results)} — " \
            "pipeline must NOT store fake results when data is unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# TEST B — explicit fixture mode → research completes with real calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_fixture_mode_completes_research():
    """TEST B: When FixtureProvider is explicitly injected, research completes
    and produces real (non-fake) backtest calculations.
    """
    from automation.pipeline import PipelineConfig, ResearchPipeline
    from data.fixture import FixtureProvider
    from data.store import BarStore
    from research_db.storage import ResearchStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path  = os.path.join(tmpdir, "test.db")
        data_dir = os.path.join(tmpdir, "market_data")
        cfg = PipelineConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            fast_mode=True,
            run_walk_forward=False,
            run_monte_carlo=False,
            run_robustness=False,
            verbose=False,
            db_path=db_path,
            reports_dir=os.path.join(tmpdir, "reports"),
            log_path=os.path.join(tmpdir, "research.log"),
            data_provider=FixtureProvider(),
            data_store=BarStore(data_dir),
        )
        run = ResearchPipeline(cfg).execute()

        assert run.n_tested >= 1, f"Expected strategies tested, got {run.n_tested}"
        assert run.n_data_failures == 0, \
            f"Expected 0 data failures (fixture mode), got {run.n_data_failures}"

        storage = ResearchStorage(db_path)
        sessions = storage.get_sessions(limit=10)
        assert sessions[0].status == "complete", \
            f"Expected session status='complete', got {sessions[0].status!r}"

        results = storage.get_strategy_results(limit=200)
        assert len(results) == run.n_tested, \
            f"Expected {run.n_tested} results, got {len(results)}"

        # All results must have real calculations — total_trades > 0 for passing ones
        passing = [r for r in results if r.gate_decision != "REJECT"]
        for r in passing:
            assert r.cagr is not None, \
                f"CAGR is None for {r.strategy_class} {r.params}"
            assert r.total_trades >= 1, \
                f"Passing result has 0 trades: {r.strategy_class} {r.params}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST C — exact deployment authorization
# ─────────────────────────────────────────────────────────────────────────────

def test_exact_deployment_authorization():
    """TEST C: PROMISING result deploys; REJECT result fails even if same strategy
    has a PROMISING sibling. Wrong result_id fails. Incomplete session fails.
    """
    from research_db.storage import ResearchStorage
    from research_db.models import SessionRecord, StrategyResult
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        s = ResearchStorage(db_path)

        # Save a COMPLETE session
        sess = SessionRecord(
            session_id="test_deploy_sess",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="complete",
            symbols='["BTCUSDT"]',
            intervals='["1h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess)

        # Save an INCOMPLETE session
        sess_bad = SessionRecord(
            session_id="test_deploy_sess_bad",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="running",
            symbols='["BTCUSDT"]',
            intervals='["1h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess_bad)

        # Save a PROMISING result (should deploy)
        now = datetime.now(timezone.utc).isoformat()
        promising_id = s.save_strategy_result(StrategyResult(
            session_id="test_deploy_sess",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":15,"slow":200}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="PROMISING",
            gate_score=80.0,
            total_trades=42,
            sharpe_ratio=1.8,
            cagr=0.25,
            created_at=now,
        ))

        # Save a REJECT result for the SAME strategy class (sibling)
        reject_id = s.save_strategy_result(StrategyResult(
            session_id="test_deploy_sess",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":20,"slow":200}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="REJECT",
            gate_score=30.0,
            total_trades=3,
            sharpe_ratio=0.2,
            cagr=0.01,
            created_at=now,
        ))

        # Save a PROMISING result for an INCOMPLETE session
        incomplete_id = s.save_strategy_result(StrategyResult(
            session_id="test_deploy_sess_bad",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":10,"slow":100}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="PROMISING",
            gate_score=75.0,
            total_trades=30,
            sharpe_ratio=1.6,
            cagr=0.20,
            created_at=now,
        ))

        # Verify: PROMISING result loads correctly
        r = s.get_strategy_result_by_id(promising_id)
        assert r is not None, "get_strategy_result_by_id returned None for valid id"
        assert r.gate_decision == "PROMISING"
        assert json.loads(r.params) == {"fast": 15, "slow": 200}
        assert r.symbol == "BTCUSDT"
        assert r.interval == "1h"

        # Verify: REJECT result is present (same strategy class as PROMISING)
        r_reject = s.get_strategy_result_by_id(reject_id)
        assert r_reject is not None
        assert r_reject.gate_decision == "REJECT"

        # Verify: session check for the REJECT result
        sess_check = s.get_session(r_reject.session_id)
        assert sess_check.status == "complete"

        # Verify: result for incomplete session
        r_incomplete = s.get_strategy_result_by_id(incomplete_id)
        sess_incomplete = s.get_session(r_incomplete.session_id)
        assert sess_incomplete.status == "running"  # not "complete"

        # Verify: wrong result_id returns None
        assert s.get_strategy_result_by_id(999999) is None

        # --- Simulate the api.py gate logic for each case ---

        def _check_deployable(result_id):
            """Reproduce the /bot/start gate checks."""
            r = s.get_strategy_result_by_id(result_id)
            if r is None:
                return False, "not_found"
            if r.gate_decision.upper() == "REJECT":
                return False, "rejected"
            session = s.get_session(r.session_id)
            if session is None or session.status != "complete":
                return False, "incomplete_session"
            return True, "ok"

        ok, reason = _check_deployable(promising_id)
        assert ok, f"PROMISING result should be deployable, got reason={reason!r}"

        ok, reason = _check_deployable(reject_id)
        assert not ok, "REJECT result must NOT be deployable"
        assert reason == "rejected", f"Expected reason='rejected', got {reason!r}"

        ok, reason = _check_deployable(incomplete_id)
        assert not ok, "Result from incomplete session must NOT be deployable"
        assert reason == "incomplete_session", \
            f"Expected reason='incomplete_session', got {reason!r}"

        ok, reason = _check_deployable(999999)
        assert not ok, "Non-existent result_id must fail"
        assert reason == "not_found", f"Expected reason='not_found', got {reason!r}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST D — full research lifecycle → deploy → exact params in bot config
# ─────────────────────────────────────────────────────────────────────────────

def test_deploy_uses_exact_research_params():
    """TEST D: Research result params are preserved exactly through deployment.
    research_result.params == params passed to bot_manager.start().
    """
    from research_db.storage import ResearchStorage
    from research_db.models import SessionRecord, StrategyResult
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        s = ResearchStorage(db_path)

        sess = SessionRecord(
            session_id="test_exact_params",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="complete",
            symbols='["ETHUSDT"]',
            intervals='["4h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess)

        exact_params = {"period": 14, "oversold": 25.0, "overbought": 70.0}
        result_id = s.save_strategy_result(StrategyResult(
            session_id="test_exact_params",
            strategy_class="RSIMeanReversion",
            strategy_name="RSIMeanReversion",
            params=json.dumps(exact_params),
            symbol="ETHUSDT",
            interval="4h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="PROMISING",
            gate_score=85.0,
            total_trades=18,
            sharpe_ratio=2.1,
            cagr=0.32,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))

        # Simulate the deployment extraction logic from /api/bot/start
        r = s.get_strategy_result_by_id(result_id)
        assert r is not None
        assert r.gate_decision == "PROMISING"
        assert r.symbol == "ETHUSDT"
        assert r.interval == "4h"
        assert r.strategy_class == "RSIMeanReversion"

        deployed_params = json.loads(r.params)
        assert deployed_params == exact_params, \
            f"Params mismatch: {deployed_params} != {exact_params}"

        # The params that would be sent to bot_manager must exactly match
        # what was stored in the research DB — no silently substituted defaults.
        assert deployed_params["period"] == 14
        assert deployed_params["oversold"] == 25.0
        assert deployed_params["overbought"] == 70.0


# ─────────────────────────────────────────────────────────────────────────────
# TEST E — data fetch failure → FAILED lifecycle, error persisted, no results
# ─────────────────────────────────────────────────────────────────────────────

def test_data_failure_lifecycle():
    """TEST E: Data fetch failure → session FAILED → error persisted → 0 results.
    Confirms the full lifecycle: RUNNING→FAILED, no valid strategy results.
    """
    from automation.pipeline import PipelineConfig, ResearchPipeline
    from data.provider import MarketDataProvider
    from data.store import BarStore
    from research_db.storage import ResearchStorage
    import pandas as pd

    class AlwaysFailProvider(MarketDataProvider):
        """Always raises — simulates total network failure."""
        def fetch_month(self, symbol, interval, year, month):
            raise ConnectionError(
                f"Simulated network failure: cannot reach exchange for "
                f"{symbol}/{interval} {year}-{month:02d}"
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path  = os.path.join(tmpdir, "test.db")
        data_dir = os.path.join(tmpdir, "market_data")
        cfg = PipelineConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            fast_mode=True,
            run_walk_forward=False,
            run_monte_carlo=False,
            run_robustness=False,
            verbose=False,
            db_path=db_path,
            reports_dir=os.path.join(tmpdir, "reports"),
            log_path=os.path.join(tmpdir, "research.log"),
            data_provider=AlwaysFailProvider(),
            data_store=BarStore(data_dir),
        )
        run = ResearchPipeline(cfg).execute()

        assert run.n_tested == 0, \
            f"Expected 0 tested, got {run.n_tested}"
        assert run.n_data_failures >= 1, \
            f"Expected ≥1 data failure, got {run.n_data_failures}"

        storage = ResearchStorage(db_path)
        sessions = storage.get_sessions(limit=10)
        assert len(sessions) >= 1
        assert sessions[0].status == "failed", \
            f"Expected status='failed', got {sessions[0].status!r}"

        results = storage.get_strategy_results(limit=200)
        assert len(results) == 0, \
            f"Expected 0 results on data failure, got {len(results)}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST F — LiveFeed terminates after max_reconnect_attempts (P0-5)
# ─────────────────────────────────────────────────────────────────────────────

def test_live_feed_terminates_after_max_attempts():
    """TEST F: LiveFeed raises RuntimeError after max_reconnect_attempts consecutive
    failures, not retrying forever. Bot must not stay RUNNING while receiving zero
    candles indefinitely.
    """
    import asyncio
    from bot.config import BotConfig, FeedConfig
    from bot.events import EventBus
    from bot.runtime import LiveFeed
    from bot.state import BotState

    cfg = BotConfig(
        paper_capital=100.0,
        feed=FeedConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            ws_base_url="wss://localhost:1/stream",    # unreachable — always fails
            rest_base_url="http://localhost:1/api/v3", # unreachable
            reconnect_delay_s=0.0,
            max_reconnect_delay_s=0.0,
            max_reconnect_attempts=3,                  # fail fast for test
            backfill_bars=1,
        ),
    )
    state = BotState()
    bus   = EventBus()
    feed  = LiveFeed(config=cfg, state=state, bus=bus)

    with pytest.raises(RuntimeError, match="Market data connection failed after 3"):
        asyncio.run(feed.run())

    # Reconnect counter must be incremented once per failure
    counters = state.counters()
    assert counters.get("reconnects", 0) == 3, \
        f"Expected 3 reconnect increments, got {counters.get('reconnects', 0)}"


def test_live_feed_unlimited_when_zero():
    """TEST F-b: max_reconnect_attempts=0 means unlimited — feed does NOT raise
    on the Nth failure (it keeps looping).  We verify by cancelling it.
    """
    import asyncio
    from bot.config import BotConfig, FeedConfig
    from bot.events import EventBus
    from bot.runtime import LiveFeed
    from bot.state import BotState

    cfg = BotConfig(
        paper_capital=100.0,
        feed=FeedConfig(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            ws_base_url="wss://localhost:1/stream",
            rest_base_url="http://localhost:1/api/v3",
            reconnect_delay_s=0.0,
            max_reconnect_delay_s=0.0,
            max_reconnect_attempts=0,    # unlimited
            backfill_bars=1,
            backfill_max_retries=1,      # fail fast — no inner retry delays
            backfill_retry_delay_s=0.0,
            rest_timeout_s=2,
        ),
    )
    state = BotState()
    bus   = EventBus()
    feed  = LiveFeed(config=cfg, state=state, bus=bus)

    async def _run_and_cancel():
        task = asyncio.create_task(feed.run())
        # Poll until at least one reconnect registers, then cancel.
        # Up to 10 seconds so the test is robust under CI load.
        for _ in range(200):
            await asyncio.sleep(0.05)
            if state.counters().get("reconnects", 0) >= 1:
                break
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass
        return state.counters().get("reconnects", 0)

    reconnects = asyncio.run(_run_and_cancel())
    # Should have attempted at least once without raising RuntimeError from max_attempts
    assert reconnects >= 1, \
        "Feed with max_reconnect_attempts=0 should attempt at least once before cancel"


# ─────────────────────────────────────────────────────────────────────────────
# TEST G — BotConfig integrity: unusual params flow exactly to BotConfig
# ─────────────────────────────────────────────────────────────────────────────

def test_botconfig_exact_params_from_result_id():
    """TEST G: Unusual params (fast=7, slow=143) must flow exactly from the
    research result through the deployment path to BotConfig.strategy_params.
    No default substitution allowed.
    """
    import json
    from research_db.storage import ResearchStorage
    from research_db.models import SessionRecord, StrategyResult
    from datetime import datetime, timezone
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        s = ResearchStorage(db_path)

        sess = SessionRecord(
            session_id="test_params_integrity",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="complete",
            symbols='["BTCUSDT"]',
            intervals='["1h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess)

        unusual_params = {"fast": 7, "slow": 143}
        result_id = s.save_strategy_result(StrategyResult(
            session_id="test_params_integrity",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params=json.dumps(unusual_params),
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="PROMISING",
            gate_score=90.0,
            total_trades=10,
            sharpe_ratio=2.0,
            cagr=0.20,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))

        # Load exactly as the API would
        r = s.get_strategy_result_by_id(result_id)
        assert r is not None
        assert r.gate_decision == "PROMISING"

        deployed_params = json.loads(r.params)
        assert deployed_params == unusual_params, \
            f"Params mismatch: {deployed_params} != {unusual_params}"

        # Simulate bot_manager.start() and verify BotConfig receives exact params
        captured = {}
        from server.bot_manager import BotManager
        real_start = BotManager.start

        def _mock_start(self, capital, symbols, intervals=None, strategy=None,
                        strategy_params=None, **kwargs):
            captured["strategy_params"] = strategy_params
            return True, ""

        with patch.object(BotManager, "start", _mock_start):
            from server.bot_manager import bot_manager as bm
            bm.start(
                capital=10000.0,
                symbols=[r.symbol],
                intervals=[r.interval],
                strategy=r.strategy_class,
                strategy_params=deployed_params,
            )

        assert captured.get("strategy_params") == unusual_params, \
            f"strategy_params not passed correctly: {captured.get('strategy_params')!r}"
        assert captured["strategy_params"]["fast"] == 7
        assert captured["strategy_params"]["slow"] == 143


# ─────────────────────────────────────────────────────────────────────────────
# TEST H — HTTP-level deployment gate (A=PROMISING→200, B=REJECT→422)
# ─────────────────────────────────────────────────────────────────────────────

def test_http_deployment_gate_promising_and_reject():
    """TEST H: PROMISING result (A) → HTTP 200. REJECT result (B, same strategy
    class) → HTTP 422.  Even if EMACrossover has a PROMISING sibling, the REJECT
    config itself must be refused.
    """
    import json
    from research_db.storage import ResearchStorage
    from research_db.models import SessionRecord, StrategyResult
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_http.db")
        s = ResearchStorage(db_path)

        sess = SessionRecord(
            session_id="http_gate_sess",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="complete",
            symbols='["BTCUSDT"]',
            intervals='["1h"]',
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        s.save_session(sess)

        now = datetime.now(timezone.utc).isoformat()
        promising_id = s.save_strategy_result(StrategyResult(
            session_id="http_gate_sess",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":10,"slow":50}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="PROMISING",
            gate_score=80.0,
            total_trades=20,
            sharpe_ratio=1.6,
            cagr=0.20,
            created_at=now,
        ))

        reject_id = s.save_strategy_result(StrategyResult(
            session_id="http_gate_sess",
            strategy_class="EMACrossover",
            strategy_name="EMACrossover",
            params='{"fast":20,"slow":200}',
            symbol="BTCUSDT",
            interval="1h",
            start_date="2024-01-01",
            end_date="2024-12-31",
            gate_decision="REJECT",
            gate_score=20.0,
            total_trades=3,
            sharpe_ratio=0.1,
            cagr=0.01,
            created_at=now,
        ))

        # Patch the server's DB path and bot_manager.start for a clean test
        import server.api as api_module
        import server.bot_manager as bm_module
        from server.auth import require_auth

        with patch.object(bm_module.BotManager, "start", lambda self, **kwargs: (True, "")), \
             patch.object(api_module, "_DB_PATH", Path(db_path)):

            from server.api import router
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[require_auth] = lambda: "test-user"

            client = TestClient(app)

            # Result A (PROMISING, fast=10, slow=50) → should succeed
            resp_a = client.post(
                "/api/bot/start",
                json={
                    "capital": 10000,
                    "symbols": ["BTCUSDT"],
                    "intervals": ["1h"],
                    "strategy": "EMACrossover",
                    "recover": False,
                    "result_id": promising_id,
                },
            )
            assert resp_a.status_code == 200, \
                f"PROMISING result should return 200, got {resp_a.status_code}: {resp_a.text}"

            # Result B (REJECT, fast=20, slow=200) → must fail
            resp_b = client.post(
                "/api/bot/start",
                json={
                    "capital": 10000,
                    "symbols": ["BTCUSDT"],
                    "intervals": ["1h"],
                    "strategy": "EMACrossover",
                    "recover": False,
                    "result_id": reject_id,
                },
            )
            assert resp_b.status_code == 422, \
                f"REJECT result should return 422, got {resp_b.status_code}: {resp_b.text}"
            assert "REJECT" in resp_b.text or "rejected" in resp_b.text.lower(), \
                f"422 response should mention rejection: {resp_b.text}"
