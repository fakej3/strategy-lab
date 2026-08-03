"""Tests for research.confidence — calculate_confidence and ConfidenceReport."""
from __future__ import annotations

import pytest

from research.confidence import (
    ConfidenceReport,
    EvidenceDimension,
    calculate_confidence,
)


# ── Minimal call ──────────────────────────────────────────────────────────────

def test_no_args_returns_report():
    report = calculate_confidence()
    assert isinstance(report, ConfidenceReport)
    assert 0.0 <= report.confidence_score <= 100.0
    assert report.recommendation in ("APPROVE", "PROMISING", "NEEDS_WORK", "REJECT")


def test_to_dict_shape():
    report = calculate_confidence()
    d = report.to_dict()
    for key in ("confidence_score", "recommendation", "overrides",
                "strengths", "weaknesses", "dimensions", "summary"):
        assert key in d


def test_dimensions_always_present():
    report = calculate_confidence()
    names = {d.name for d in report.dimensions}
    expected = {
        "Data Integrity", "Accounting Verification", "Statistical Confidence",
        "Walk-Forward Stability", "Monte Carlo Robustness",
        "Stress Test Resilience", "Parameter Stability",
    }
    assert names == expected


# ── Contribution arithmetic ───────────────────────────────────────────────────

def test_contributions_non_negative():
    report = calculate_confidence(
        data_integrity_score=90.0,
        accounting_passed=True,
        sharpe_ratio=1.5,
        total_trades=200,
    )
    for d in report.dimensions:
        assert d.contribution >= 0.0


def test_contribution_bounded_by_weight():
    report = calculate_confidence(data_integrity_score=100.0)
    for d in report.dimensions:
        assert d.contribution <= d.weight + 1e-9


def test_score_bounded_0_100():
    for _ in range(20):
        r = calculate_confidence(
            data_integrity_score=85.0,
            accounting_passed=True,
            sharpe_ratio=2.0,
            total_trades=300,
            wf_efficiency=0.8,
            mc_score=80.0,
            stress_score=75.0,
            robustness_score=70.0,
            overfitting_score=10.0,
        )
        assert 0.0 <= r.confidence_score <= 100.0


# ── Accounting override ───────────────────────────────────────────────────────

def test_accounting_failure_forces_reject():
    report = calculate_confidence(
        data_integrity_score=95.0,
        accounting_passed=False,
        sharpe_ratio=3.0,
        total_trades=500,
        stress_score=90.0,
    )
    assert report.recommendation == "REJECT"
    assert any("ACCOUNTING" in o for o in report.overrides)


def test_accounting_passed_no_override():
    report = calculate_confidence(accounting_passed=True)
    assert not any("ACCOUNTING" in o for o in report.overrides)


def test_accounting_not_assessed_neutral():
    report = calculate_confidence()
    acct = next(d for d in report.dimensions if d.name == "Accounting Verification")
    assert acct.score == 50.0


# ── Data integrity override ───────────────────────────────────────────────────

def test_very_low_integrity_forces_reject():
    report = calculate_confidence(
        data_integrity_score=40.0,   # < 60 threshold
        accounting_passed=True,
        sharpe_ratio=5.0,
        total_trades=1000,
    )
    assert report.recommendation == "REJECT"
    assert any("DATA INTEGRITY" in o for o in report.overrides)


def test_integrity_60_passes_override():
    report = calculate_confidence(
        data_integrity_score=61.0,
        accounting_passed=True,
        sharpe_ratio=2.0,
        total_trades=200,
    )
    # No data integrity override (≥ 60)
    assert not any("DATA INTEGRITY" in o for o in report.overrides)


# ── Overfitting penalty ───────────────────────────────────────────────────────

def test_high_overfitting_applies_penalty():
    base = calculate_confidence(
        accounting_passed=True,
        sharpe_ratio=2.0,
        total_trades=200,
        stress_score=80.0,
        overfitting_score=0.0,
    )
    penalised = calculate_confidence(
        accounting_passed=True,
        sharpe_ratio=2.0,
        total_trades=200,
        stress_score=80.0,
        overfitting_score=100.0,
    )
    assert penalised.confidence_score < base.confidence_score


def test_overfitting_high_and_low_stress_reject():
    report = calculate_confidence(
        accounting_passed=True,
        overfitting_risk_level="HIGH",
        stress_score=30.0,   # < 40
    )
    assert report.recommendation == "REJECT"
    assert any("CURVE-FIT" in o for o in report.overrides)


def test_low_overfitting_no_penalty():
    r1 = calculate_confidence(
        accounting_passed=True,
        sharpe_ratio=1.5,
        total_trades=200,
        overfitting_score=20.0,
    )
    r2 = calculate_confidence(
        accounting_passed=True,
        sharpe_ratio=1.5,
        total_trades=200,
        overfitting_score=0.0,
    )
    # Both should be very close (score 20 is in the "no penalty" zone)
    assert abs(r1.confidence_score - r2.confidence_score) < 10.0


# ── Bonus ─────────────────────────────────────────────────────────────────────

def test_perfect_data_and_accounting_earns_bonus():
    with_bonus = calculate_confidence(
        data_integrity_score=96.0,
        accounting_passed=True,
        accounting_score=100.0,
        sharpe_ratio=2.0,
        total_trades=200,
        stress_score=80.0,
        wf_efficiency=0.9,
        mc_score=90.0,
        robustness_score=80.0,
        overfitting_score=5.0,
    )
    without_bonus = calculate_confidence(
        data_integrity_score=85.0,   # < 95, no bonus
        accounting_passed=True,
        sharpe_ratio=2.0,
        total_trades=200,
        stress_score=80.0,
        wf_efficiency=0.9,
        mc_score=90.0,
        robustness_score=80.0,
        overfitting_score=5.0,
    )
    assert with_bonus.confidence_score >= without_bonus.confidence_score


# ── Recommendation thresholds ─────────────────────────────────────────────────

def test_approve_threshold():
    report = calculate_confidence(
        data_integrity_score=95.0,
        accounting_passed=True,
        accounting_score=100.0,
        sharpe_ratio=2.5,
        total_trades=500,
        wf_efficiency=0.85,
        mc_score=90.0,
        stress_score=80.0,
        robustness_score=85.0,
        stability_score=80.0,
        overfitting_score=5.0,
    )
    assert report.recommendation == "APPROVE"


def test_reject_low_score():
    report = calculate_confidence(
        data_integrity_score=61.0,
        accounting_passed=True,
        sharpe_ratio=0.1,
        total_trades=5,
        wf_efficiency=-0.5,
        stress_score=10.0,
        overfitting_score=90.0,
    )
    assert report.recommendation == "REJECT"


# ── Strengths and weaknesses ──────────────────────────────────────────────────

def test_strengths_high_scoring_dims():
    report = calculate_confidence(
        data_integrity_score=95.0,
        accounting_passed=True,
        sharpe_ratio=2.0,
        total_trades=500,
    )
    assert "Data Integrity" in report.strengths or "Accounting Verification" in report.strengths


def test_weaknesses_low_scoring_dims():
    report = calculate_confidence(
        stress_score=10.0,   # very low
        wf_efficiency=-0.8,  # very poor
    )
    assert "Stress Test Resilience" in report.weaknesses or "Walk-Forward Stability" in report.weaknesses


# ── Walk-forward via score vs efficiency ──────────────────────────────────────

def test_wf_score_preferred_over_efficiency():
    """When both wf_score and wf_efficiency are given, wf_score takes precedence."""
    r_with_score = calculate_confidence(wf_score=90.0, wf_efficiency=0.1)
    r_without    = calculate_confidence(wf_efficiency=0.1)
    # With a high wf_score the WF dimension should be better
    wf_with    = next(d for d in r_with_score.dimensions if d.name == "Walk-Forward Stability")
    wf_without = next(d for d in r_without.dimensions    if d.name == "Walk-Forward Stability")
    assert wf_with.score > wf_without.score


# ── Monte Carlo: score vs ci_width ───────────────────────────────────────────

def test_mc_score_used_when_given():
    r = calculate_confidence(mc_score=100.0)
    mc = next(d for d in r.dimensions if d.name == "Monte Carlo Robustness")
    assert mc.score == 100.0


def test_mc_ci_width_fallback():
    r_narrow = calculate_confidence(mc_sharpe_ci_width=0.2, sharpe_ratio=2.0)
    r_wide   = calculate_confidence(mc_sharpe_ci_width=5.0, sharpe_ratio=1.0)
    mc_narrow = next(d for d in r_narrow.dimensions if d.name == "Monte Carlo Robustness")
    mc_wide   = next(d for d in r_wide.dimensions   if d.name == "Monte Carlo Robustness")
    assert mc_narrow.score > mc_wide.score


# ── Stress: score vs risk_level fallback ─────────────────────────────────────

def test_stress_risk_level_fallback():
    r_low  = calculate_confidence(stress_risk_level="LOW")
    r_high = calculate_confidence(stress_risk_level="HIGH")
    st_low  = next(d for d in r_low.dimensions  if d.name == "Stress Test Resilience")
    st_high = next(d for d in r_high.dimensions if d.name == "Stress Test Resilience")
    assert st_low.score > st_high.score


# ── Summary is non-empty string ───────────────────────────────────────────────

def test_summary_non_empty():
    report = calculate_confidence(accounting_passed=False)
    assert isinstance(report.summary, str)
    assert len(report.summary) > 10
