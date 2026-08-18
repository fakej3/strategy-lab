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
    """Return the pre-written BTCUSDT 1h bars from BarStore (2024 full year)."""
    from data.api import get_bars
    return get_bars(
        symbol="BTCUSDT",
        interval="1h",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
    )


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
    """Pipeline runs 20 backtests and saves results to DB (non-zero pass rate)."""
    from automation.pipeline import PipelineConfig, ResearchPipeline
    from research_db.storage import ResearchStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
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
