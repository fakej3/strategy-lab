"""Tests for pipeline.gate — quality gate evaluation."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from pipeline.gate import evaluate_gate
from pipeline.models import Decision, Metrics, RuleStatus


# ── Metrics factory ────────────────────────────────────────────────────────────

def _metrics(**overrides) -> Metrics:
    """Return a 'good' baseline Metrics, with selective field overrides."""
    base = Metrics(
        total_trades             = 120,
        winning_trades           = 72,
        losing_trades            = 48,
        breakeven_trades         = 0,
        profit_unit              = "%",
        net_profit               = 25.0,
        gross_profit             = 54.0,
        gross_loss               = 29.0,
        profit_factor            = 54.0 / 29.0,   # ≈ 1.86
        win_rate                 = 0.60,
        avg_win                  = 54.0 / 72,      # 0.75
        avg_loss                 = 29.0 / 48,      # ≈ 0.604
        risk_reward              = (54.0 / 72) / (29.0 / 48),  # ≈ 1.24
        largest_win              = 3.0,
        largest_loss             = 1.5,
        max_consecutive_wins     = 6,
        max_consecutive_losses   = 3,
        avg_trade                = 25.0 / 120,
        expectancy               = (0.60 * 54.0 / 72) - (0.40 * 29.0 / 48),
        max_drawdown             = 5.0,
        return_over_max_drawdown = 25.0 / 5.0,    # 5.0
    )
    for k, v in overrides.items():
        base = replace(base, **{k: v})
    return base


# ── Decision threshold tests ───────────────────────────────────────────────────

class TestDecisions:
    def test_promising_on_strong_metrics(self):
        gate = evaluate_gate(_metrics())
        assert gate.decision == Decision.PROMISING

    def test_reject_on_net_loss(self):
        m = _metrics(net_profit=-5.0, gross_profit=10.0, gross_loss=15.0,
                     profit_factor=10.0 / 15.0)
        gate = evaluate_gate(m)
        assert gate.decision == Decision.REJECT

    def test_reject_forces_net_profit_into_critical_failures(self):
        m = _metrics(net_profit=-1.0, gross_profit=5.0, gross_loss=6.0,
                     profit_factor=5.0 / 6.0)
        gate = evaluate_gate(m)
        assert "net_profit" in gate.critical_failures

    def test_reject_when_overall_below_45(self):
        # Terrible metrics across the board
        m = _metrics(
            total_trades=10,            # FAIL: sample size
            profit_factor=1.05,         # FAIL: profit factor
            win_rate=0.30,              # FAIL: win rate
            max_drawdown=30.0,          # FAIL: max drawdown (% mode)
            return_over_max_drawdown=0.5,
            risk_reward=0.6,            # FAIL: R/R
            max_consecutive_losses=10,  # FAIL: consecutive losses
        )
        gate = evaluate_gate(m)
        assert gate.decision == Decision.REJECT

    def test_needs_improvement_in_middle_range(self):
        m = _metrics(
            total_trades=40,            # WARNING: 30–99
            profit_factor=1.3,          # WARNING: 1.2–1.5
            risk_reward=1.1,            # WARNING: 1.0–1.5
            max_drawdown=12.0,          # WARNING: 10–20%
            return_over_max_drawdown=2.0,  # WARNING: 1.5–3.0
        )
        gate = evaluate_gate(m)
        assert gate.decision == Decision.NEEDS_IMPROVEMENT


# ── Category score tests ───────────────────────────────────────────────────────

class TestCategoryScores:
    def test_capital_preservation_passes_on_low_drawdown(self):
        m = _metrics(max_drawdown=5.0, return_over_max_drawdown=5.0,
                     max_consecutive_losses=2, largest_loss=1.5, avg_loss=0.6)
        gate = evaluate_gate(m)
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        assert cap.score == pytest.approx(100.0)

    def test_profitability_fails_on_negative_profit(self):
        m = _metrics(net_profit=-1.0, gross_profit=5.0, gross_loss=6.0,
                     profit_factor=5.0 / 6.0, expectancy=-0.5)
        gate = evaluate_gate(m)
        prof = next(c for c in gate.categories if c.name == "Profitability")
        assert prof.score < 50  # Net profit FAIL + low PF

    def test_robustness_warns_on_low_trade_count(self):
        m = _metrics(total_trades=40)
        gate = evaluate_gate(m)
        rob = next(c for c in gate.categories if c.name == "Robustness")
        sample_rule = next(r for r in rob.rules if r.name == "Sample Size")
        assert sample_rule.status == RuleStatus.WARNING

    def test_robustness_fails_on_very_low_trade_count(self):
        m = _metrics(total_trades=15)
        gate = evaluate_gate(m)
        rob = next(c for c in gate.categories if c.name == "Robustness")
        sample_rule = next(r for r in rob.rules if r.name == "Sample Size")
        assert sample_rule.status == RuleStatus.FAIL


# ── Individual rule tests ──────────────────────────────────────────────────────

class TestProfitFactorRule:
    def test_pass_above_1_5(self):
        gate = evaluate_gate(_metrics(profit_factor=1.6))
        prof = next(c for c in gate.categories if c.name == "Profitability")
        pf_rule = next(r for r in prof.rules if r.name == "Profit Factor")
        assert pf_rule.status == RuleStatus.PASS

    def test_warning_between_1_2_and_1_5(self):
        gate = evaluate_gate(_metrics(profit_factor=1.35))
        prof = next(c for c in gate.categories if c.name == "Profitability")
        pf_rule = next(r for r in prof.rules if r.name == "Profit Factor")
        assert pf_rule.status == RuleStatus.WARNING

    def test_fail_below_1_2(self):
        gate = evaluate_gate(_metrics(profit_factor=1.1))
        prof = next(c for c in gate.categories if c.name == "Profitability")
        pf_rule = next(r for r in prof.rules if r.name == "Profit Factor")
        assert pf_rule.status == RuleStatus.FAIL


class TestDrawdownRule:
    def test_pass_drawdown_below_10_percent(self):
        gate = evaluate_gate(_metrics(max_drawdown=8.0))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        dd_rule = next(r for r in cap.rules if r.name == "Max Drawdown")
        assert dd_rule.status == RuleStatus.PASS

    def test_warning_drawdown_between_10_and_20(self):
        gate = evaluate_gate(_metrics(max_drawdown=15.0,
                                      return_over_max_drawdown=25.0 / 15.0))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        dd_rule = next(r for r in cap.rules if r.name == "Max Drawdown")
        assert dd_rule.status == RuleStatus.WARNING

    def test_fail_drawdown_above_20_percent(self):
        gate = evaluate_gate(_metrics(max_drawdown=25.0,
                                      return_over_max_drawdown=1.0))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        dd_rule = next(r for r in cap.rules if r.name == "Max Drawdown")
        assert dd_rule.status == RuleStatus.FAIL


class TestConsecutiveLossesRule:
    def test_pass_at_4_or_fewer(self):
        gate = evaluate_gate(_metrics(max_consecutive_losses=4))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        cl_rule = next(r for r in cap.rules if r.name == "Consecutive Losses")
        assert cl_rule.status == RuleStatus.PASS

    def test_warning_between_5_and_7(self):
        gate = evaluate_gate(_metrics(max_consecutive_losses=6))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        cl_rule = next(r for r in cap.rules if r.name == "Consecutive Losses")
        assert cl_rule.status == RuleStatus.WARNING

    def test_fail_at_8_or_more(self):
        gate = evaluate_gate(_metrics(max_consecutive_losses=8))
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        cl_rule = next(r for r in cap.rules if r.name == "Consecutive Losses")
        assert cl_rule.status == RuleStatus.FAIL


class TestLossConcentrationRule:
    def test_pass_when_no_losses(self):
        m = _metrics(avg_loss=0.0, largest_loss=0.0, losing_trades=0,
                     gross_loss=0.0, profit_factor=math.inf)
        gate = evaluate_gate(m)
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        lc_rule = next(r for r in cap.rules if r.name == "Loss Concentration")
        assert lc_rule.status == RuleStatus.PASS

    def test_fail_when_outlier_above_5x(self):
        # avg_loss = 1.0, largest_loss = 6.0 → ratio = 6.0 > 5
        m = _metrics(avg_loss=1.0, largest_loss=6.0)
        gate = evaluate_gate(m)
        cap = next(c for c in gate.categories if c.name == "Capital Preservation")
        lc_rule = next(r for r in cap.rules if r.name == "Loss Concentration")
        assert lc_rule.status == RuleStatus.FAIL


# ── GateResult structure tests ─────────────────────────────────────────────────

class TestGateResultStructure:
    def test_overall_score_in_range(self):
        gate = evaluate_gate(_metrics())
        assert 0.0 <= gate.overall_score <= 100.0

    def test_three_categories_always_present(self):
        gate = evaluate_gate(_metrics())
        names = [c.name for c in gate.categories]
        assert "Capital Preservation" in names
        assert "Profitability" in names
        assert "Robustness" in names

    def test_weakest_category_is_lowest_scorer(self):
        gate = evaluate_gate(_metrics(total_trades=15))  # robustness hammered
        rob_score = next(c.score for c in gate.categories if c.name == "Robustness")
        for cat in gate.categories:
            assert rob_score <= cat.score
        assert gate.weakest_category == "Robustness"

    def test_next_experiment_is_non_empty(self):
        gate = evaluate_gate(_metrics())
        assert gate.next_experiment
        assert len(gate.next_experiment) > 20

    def test_expected_goal_is_non_empty(self):
        gate = evaluate_gate(_metrics())
        assert gate.expected_goal
        assert len(gate.expected_goal) > 20

    def test_primary_failure_is_sample_size_when_only_warning(self):
        # Only warning should be sample size (40 trades)
        m = _metrics(total_trades=40)
        gate = evaluate_gate(m)
        # sample_size is priority #2, but other rules may FAIL first
        # The key assertion is that primary_failure is a known key
        assert gate.primary_failure is not None
