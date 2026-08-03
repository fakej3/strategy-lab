"""Tests for research.stress — run_stress_tests and scoring logic."""
from __future__ import annotations

import math
from typing import Sequence
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from research.stress import (
    StressScenario,
    StressResult,
    StressTestReport,
    run_stress_tests,
    _DEFAULT_SCENARIOS,
)


# ── Minimal strategy fixture ──────────────────────────────────────────────────

from engine.strategy import StrategyBase, Signal


class _AlwaysBuy(StrategyBase):
    """Trivial strategy: always BUY on every bar."""
    def generate_signals(self, bars: pd.DataFrame):
        return pd.Series([Signal.BUY] * len(bars), index=bars.index)


class _AlwaysHold(StrategyBase):
    """Strategy that never enters a trade."""
    def generate_signals(self, bars: pd.DataFrame):
        return pd.Series([Signal.HOLD] * len(bars), index=bars.index)


def _make_bars(n: int = 500) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    np.random.seed(1)
    close = 100.0 * np.cumprod(1 + np.random.randn(n) * 0.005)
    df = pd.DataFrame(
        {
            "open"  : close * 0.999,
            "high"  : close * 1.005,
            "low"   : close * 0.995,
            "close" : close,
            "volume": 1000.0,
        },
        index=idx,
    )
    return df


# ── StressScenario dataclass ──────────────────────────────────────────────────

def test_scenario_defaults():
    sc = StressScenario("test")
    assert sc.fee_multiplier == 1.0
    assert sc.slippage_multiplier == 1.0
    assert sc.skip_pct == 0.0
    assert sc.fill_penalty == 0.0


def test_scenario_frozen():
    sc = StressScenario("test", fee_multiplier=2.0)
    with pytest.raises(Exception):
        sc.fee_multiplier = 3.0  # type: ignore[misc]


# ── Default scenarios list ────────────────────────────────────────────────────

def test_default_scenarios_count():
    assert len(_DEFAULT_SCENARIOS) == 7


def test_default_scenarios_names():
    names = {sc.name for sc in _DEFAULT_SCENARIOS}
    assert "2x Fee" in names
    assert "5x Slippage" in names
    assert "10% Skipped Trades" in names


# ── StressResult ─────────────────────────────────────────────────────────────

def test_stress_result_to_dict():
    sr = StressResult(
        scenario="2x Fee",
        baseline_sharpe=1.5,
        stressed_sharpe=1.0,
        baseline_net_pnl=10000.0,
        stressed_net_pnl=7000.0,
        baseline_max_dd=0.1,
        stressed_max_dd=0.12,
        n_trades=50,
        sharpe_degradation_pct=-33.3,
        pnl_degradation_pct=-30.0,
        survived=True,
    )
    d = sr.to_dict()
    assert d["scenario"] == "2x Fee"
    assert d["survived"] is True
    assert "sharpe_degradation_pct" in d


# ── StressTestReport ──────────────────────────────────────────────────────────

def test_report_to_dict():
    report = StressTestReport(
        stress_score=75.0,
        risk_level="LOW",
        scenarios=[],
        n_survived=0,
        summary="ok",
    )
    d = report.to_dict()
    assert d["stress_score"] == 75.0
    assert d["risk_level"] == "LOW"
    assert d["n_scenarios"] == 0


# ── run_stress_tests: baseline failure ───────────────────────────────────────

def test_baseline_failure_returns_zero_score():
    """When baseline produces no trades, score=0 and risk=HIGH."""
    bars = _make_bars(50)
    report = run_stress_tests(
        bars              = bars,
        strategy_class    = _AlwaysHold,
        params            = {},
        baseline_fee      = 0.001,
        baseline_slippage = 0.0005,
    )
    assert report.stress_score == 0.0
    assert report.risk_level == "HIGH"
    assert report.scenarios == []
    assert "could not run" in report.summary.lower()


# ── run_stress_tests: integration with real bars ──────────────────────────────

@pytest.fixture(scope="module")
def stress_report():
    """Run once for the full default-scenario suite."""
    bars = _make_bars(1000)
    return run_stress_tests(
        bars              = bars,
        strategy_class    = _AlwaysBuy,
        params            = {},
        baseline_fee      = 0.001,
        baseline_slippage = 0.0005,
        starting_capital  = 100_000.0,
    )


def test_report_structure(stress_report):
    assert isinstance(stress_report, StressTestReport)
    assert 0.0 <= stress_report.stress_score <= 100.0
    assert stress_report.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert len(stress_report.scenarios) == 7


def test_all_scenario_names_present(stress_report):
    names = {r.scenario for r in stress_report.scenarios}
    expected = {sc.name for sc in _DEFAULT_SCENARIOS}
    assert names == expected


def test_n_survived_consistent(stress_report):
    counted = sum(1 for r in stress_report.scenarios if r.survived)
    assert stress_report.n_survived == counted


def test_stress_score_bounds(stress_report):
    assert 0.0 <= stress_report.stress_score <= 100.0


def test_degradation_pct_numeric(stress_report):
    for sr in stress_report.scenarios:
        if not math.isnan(sr.sharpe_degradation_pct):
            assert isinstance(sr.sharpe_degradation_pct, float)
        if not math.isnan(sr.pnl_degradation_pct):
            assert isinstance(sr.pnl_degradation_pct, float)


# ── Custom scenario override ──────────────────────────────────────────────────

def test_custom_scenarios():
    bars = _make_bars(500)
    custom = [
        StressScenario("Double Fee", fee_multiplier=2.0),
        StressScenario("Triple Slippage", slippage_multiplier=3.0),
    ]
    report = run_stress_tests(
        bars              = bars,
        strategy_class    = _AlwaysBuy,
        params            = {},
        baseline_fee      = 0.001,
        baseline_slippage = 0.0005,
        scenarios         = custom,
    )
    assert len(report.scenarios) == 2
    names = {r.scenario for r in report.scenarios}
    assert "Double Fee" in names
    assert "Triple Slippage" in names


# ── Risk level thresholds ─────────────────────────────────────────────────────

def test_risk_low_threshold():
    """Stress score >= 70 → LOW."""
    report = StressTestReport(stress_score=75.0, risk_level="LOW",
                              scenarios=[], n_survived=0, summary="")
    assert report.risk_level == "LOW"


def test_risk_medium_threshold():
    report = StressTestReport(stress_score=55.0, risk_level="MEDIUM",
                              scenarios=[], n_survived=0, summary="")
    assert report.risk_level == "MEDIUM"


def test_risk_high_threshold():
    report = StressTestReport(stress_score=30.0, risk_level="HIGH",
                              scenarios=[], n_survived=0, summary="")
    assert report.risk_level == "HIGH"


# ── Survived flag ─────────────────────────────────────────────────────────────

def test_survived_requires_positive_sharpe_and_pnl():
    sr = StressResult(
        scenario="x", baseline_sharpe=1.0, stressed_sharpe=-0.1,
        baseline_net_pnl=1000, stressed_net_pnl=500,
        baseline_max_dd=0.1, stressed_max_dd=0.1,
        n_trades=10,
        sharpe_degradation_pct=-110.0,
        pnl_degradation_pct=-50.0,
        survived=False,
    )
    assert not sr.survived


def test_survived_true_when_both_positive():
    sr = StressResult(
        scenario="x", baseline_sharpe=1.5, stressed_sharpe=0.5,
        baseline_net_pnl=1000, stressed_net_pnl=100,
        baseline_max_dd=0.1, stressed_max_dd=0.15,
        n_trades=20,
        sharpe_degradation_pct=-66.7,
        pnl_degradation_pct=-90.0,
        survived=True,
    )
    assert sr.survived


# ── Seed reproducibility ──────────────────────────────────────────────────────

def test_seed_reproducibility():
    bars = _make_bars(500)
    kwargs = dict(
        bars              = bars,
        strategy_class    = _AlwaysBuy,
        params            = {},
        baseline_fee      = 0.001,
        baseline_slippage = 0.0005,
        seed              = 123,
    )
    r1 = run_stress_tests(**kwargs)
    r2 = run_stress_tests(**kwargs)
    assert r1.stress_score == r2.stress_score
    assert r1.n_survived == r2.n_survived
