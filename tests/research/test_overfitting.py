"""Tests for research.overfitting — analyze_overfitting and scoring logic."""
from __future__ import annotations

import pytest

from research.overfitting import (
    OverfittingReport,
    OverfittingSignal,
    analyze_overfitting,
)


# ── Happy path — minimal args ─────────────────────────────────────────────────

def test_returns_report():
    report = analyze_overfitting(total_trades=100, sharpe_ratio=1.5)
    assert isinstance(report, OverfittingReport)
    assert 0.0 <= report.overfitting_score <= 100.0
    assert report.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert len(report.signals) >= 1


def test_to_dict_keys():
    report = analyze_overfitting(total_trades=200, sharpe_ratio=2.0)
    d = report.to_dict()
    for key in ("overfitting_score", "risk_level", "signals", "summary"):
        assert key in d
    assert isinstance(d["signals"], list)


# ── Sample size signal ────────────────────────────────────────────────────────

def test_very_few_trades_high_risk():
    report = analyze_overfitting(total_trades=5, sharpe_ratio=3.0)
    ss = next(s for s in report.signals if s.name == "Sample Size")
    assert ss.score == 100.0
    assert report.risk_level in ("MEDIUM", "HIGH")


def test_many_trades_low_sample_risk():
    report = analyze_overfitting(total_trades=500, sharpe_ratio=1.0)
    ss = next(s for s in report.signals if s.name == "Sample Size")
    assert ss.score == 0.0


def test_medium_trades_40_score():
    report = analyze_overfitting(total_trades=75, sharpe_ratio=1.0)
    ss = next(s for s in report.signals if s.name == "Sample Size")
    assert ss.score == 40.0


def test_low_trades_70_score():
    report = analyze_overfitting(total_trades=25, sharpe_ratio=1.0)
    ss = next(s for s in report.signals if s.name == "Sample Size")
    assert ss.score == 70.0


# ── Walk-forward efficiency ───────────────────────────────────────────────────

def test_good_wf_efficiency_zero_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, wf_efficiency=0.85
    )
    wf = next(s for s in report.signals if s.name == "Walk-Forward Efficiency")
    assert wf.score == 0.0


def test_negative_wf_efficiency_max_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, wf_efficiency=-0.5
    )
    wf = next(s for s in report.signals if s.name == "Walk-Forward Efficiency")
    assert wf.score == 100.0
    # Composite depends on all signals; with 200 trades (zero sample risk)
    # the overall level may be MEDIUM rather than HIGH — what matters is the WF signal max score
    assert report.risk_level in ("MEDIUM", "HIGH")


def test_moderate_wf_efficiency():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, wf_efficiency=0.5
    )
    wf = next(s for s in report.signals if s.name == "Walk-Forward Efficiency")
    assert wf.score == 40.0


# ── WF efficiency computed from IS/OOS ───────────────────────────────────────

def test_wf_computed_from_is_oos():
    report = analyze_overfitting(
        total_trades=150,
        sharpe_ratio=2.0,
        in_sample_sharpe=2.0,
        out_of_sample_sharpe=1.6,
    )
    wf = next((s for s in report.signals if s.name == "Walk-Forward Efficiency"), None)
    assert wf is not None
    assert wf.score == 0.0   # 1.6/2.0 = 0.8 >= 0.7


def test_negative_oos_sharpe_not_divided():
    # Should not raise — negative IS Sharpe skips the WF signal
    report = analyze_overfitting(
        total_trades=100,
        sharpe_ratio=0.0,
        in_sample_sharpe=-1.0,
        out_of_sample_sharpe=0.5,
    )
    # No WF efficiency signal when IS is not positive
    names = [s.name for s in report.signals]
    assert "Walk-Forward Efficiency" not in names


# ── Monte Carlo spread ────────────────────────────────────────────────────────

def test_narrow_mc_spread_zero_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=2.0, mc_sharpe_ci_width=0.5
    )
    mc = next(s for s in report.signals if s.name == "Monte Carlo Spread")
    assert mc.score == 0.0


def test_wide_mc_spread_high_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.0, mc_sharpe_ci_width=5.0
    )
    mc = next(s for s in report.signals if s.name == "Monte Carlo Spread")
    assert mc.score == 90.0


# ── Yearly consistency ────────────────────────────────────────────────────────

def test_consistent_positive_years_low_score():
    report = analyze_overfitting(
        total_trades=200,
        sharpe_ratio=1.5,
        yearly_returns=[0.20, 0.22, 0.18, 0.21],
    )
    yc = next(s for s in report.signals if s.name == "Yearly Consistency")
    assert yc.score == 0.0


def test_highly_variable_years_high_score():
    report = analyze_overfitting(
        total_trades=200,
        sharpe_ratio=1.5,
        yearly_returns=[0.80, -0.60, 1.20, -0.90],
    )
    yc = next(s for s in report.signals if s.name == "Yearly Consistency")
    assert yc.score >= 55.0


def test_fewer_than_2_years_skips_signal():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, yearly_returns=[0.20]
    )
    names = [s.name for s in report.signals]
    # Only 1 year — signal is skipped (requires >= 2)
    assert "Yearly Consistency" not in names


# ── Parameter space size ──────────────────────────────────────────────────────

def test_large_param_space_high_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, n_params_tested=500
    )
    ps = next(s for s in report.signals if s.name == "Search Space Size")
    assert ps.score == 70.0


def test_small_param_space_low_score():
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, n_params_tested=5
    )
    ps = next(s for s in report.signals if s.name == "Search Space Size")
    assert ps.score == 5.0


def test_n_params_1_no_signal():
    report = analyze_overfitting(total_trades=200, sharpe_ratio=1.5, n_params_tested=1)
    names = [s.name for s in report.signals]
    assert "Search Space Size" not in names


# ── Symbol concentration ──────────────────────────────────────────────────────

def test_single_symbol_adds_signal():
    report = analyze_overfitting(total_trades=200, sharpe_ratio=1.5, n_symbols=1)
    names = [s.name for s in report.signals]
    assert "Symbol Concentration" in names


def test_multi_symbol_no_signal():
    report = analyze_overfitting(total_trades=200, sharpe_ratio=1.5, n_symbols=3)
    names = [s.name for s in report.signals]
    assert "Symbol Concentration" not in names


# ── Risk levels ───────────────────────────────────────────────────────────────

def test_low_risk_large_good_dataset():
    report = analyze_overfitting(
        total_trades=500,
        sharpe_ratio=1.5,
        wf_efficiency=0.9,
        mc_sharpe_ci_width=0.3,
        yearly_returns=[0.20, 0.22, 0.21, 0.19],
        n_symbols=3,
    )
    assert report.risk_level == "LOW"
    assert report.overfitting_score < 30


def test_high_risk_thin_sample_poor_wf():
    report = analyze_overfitting(
        total_trades=10,
        sharpe_ratio=5.0,
        wf_efficiency=-0.3,
        mc_sharpe_ci_width=10.0,
        n_params_tested=1000,
        n_symbols=1,
    )
    assert report.risk_level == "HIGH"
    assert report.overfitting_score >= 60


# ── Composite score bounds ────────────────────────────────────────────────────

def test_score_always_in_range():
    for n in [1, 10, 50, 200]:
        for sharpe in [-1.0, 0.0, 0.5, 2.0]:
            r = analyze_overfitting(total_trades=n, sharpe_ratio=sharpe)
            assert 0.0 <= r.overfitting_score <= 100.0


# ── Robustness data integration ───────────────────────────────────────────────

def test_robustness_data_used():
    rob = {
        "stability_score"    : 20.0,   # low stability = high risk
        "robustness_score"   : 10.0,
        "n_neighbors"        : 8,
        "neighbor_sharpe_std": 0.3,
        "neighbor_sharpe_mean": 0.2,
    }
    report = analyze_overfitting(
        total_trades=200,
        sharpe_ratio=2.0,
        robustness_data=rob,
    )
    ps = next(s for s in report.signals if s.name == "Parameter Sensitivity")
    assert ps.score > 30.0


def test_zero_neighbors_returns_default_signal():
    rob = {"stability_score": 80, "robustness_score": 80, "n_neighbors": 0}
    report = analyze_overfitting(
        total_trades=200, sharpe_ratio=1.5, robustness_data=rob
    )
    ps = next(s for s in report.signals if s.name == "Parameter Sensitivity")
    assert ps.score == 20.0
