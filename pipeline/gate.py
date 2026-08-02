"""
Quality Gate — evaluates a strategy against predefined rules and produces
a structured verdict.

Scoring model
─────────────
Three categories, each with weighted rules:

  Capital Preservation (35% of overall) — highest priority by design
    Max Drawdown            40%
    Return / Max Drawdown   35%
    Consecutive Losses      15%
    Loss Concentration      10%

  Profitability (30% of overall)
    Profit Factor           40%
    Expectancy              35%
    Net Profit              25%

  Robustness (35% of overall)
    Sample Size             40%
    Risk / Reward           35%
    Win Rate                25%

Each rule returns a score of 100 (PASS), 50 (WARNING), or 0 (FAIL).
Category scores are the weighted average of their rules.
Overall score is the weighted average of category scores.

Decision thresholds
───────────────────
  REJECT           : overall < 45  OR  any critical failure (net profit ≤ 0)
  NEEDS IMPROVEMENT: 45 ≤ overall < 70
  PROMISING        : overall ≥ 70

The negative-profit rule is a hard gate — a strategy that loses money is
always REJECT regardless of other scores.
"""
from __future__ import annotations

import math
from typing import Optional

from .models import (
    CategoryResult,
    Decision,
    GateResult,
    Metrics,
    RuleResult,
    RuleStatus,
)

# ── Next-experiment suggestion library ────────────────────────────────────────
# Maps a rule key → {experiment description, measurable goal}

_SUGGESTIONS: dict[str, dict[str, str]] = {
    "net_profit": {
        "experiment": (
            "The strategy has no demonstrable edge. Strip back to the core entry signal, "
            "remove all filters and optimisations, and verify that the base idea generates "
            "positive expectancy on at least 30 trades with fixed parameters."
        ),
        "goal": (
            "Achieve positive net profit and a positive expectancy across ≥ 30 trades "
            "before introducing any secondary conditions."
        ),
    },
    "sample_size": {
        "experiment": (
            "Extend the backtest period to accumulate more trades. If the timeframe or "
            "symbol cannot provide sufficient history, test the same logic on a lower "
            "timeframe or a correlated instrument with deeper data."
        ),
        "goal": (
            "Reach ≥ 100 closed trades before drawing any statistical conclusions. "
            "Current sample is too small for reliable inference."
        ),
    },
    "max_drawdown": {
        "experiment": (
            "Reduce position size to 50% of current and add a portfolio-level maximum "
            "drawdown circuit breaker at 15%. Test whether the strategy edge survives "
            "with reduced exposure before addressing root causes."
        ),
        "goal": (
            "Target max drawdown ≤ 15% while preserving the same entry and exit logic. "
            "Only then investigate whether tighter stops or filters can reduce it further."
        ),
    },
    "profit_factor": {
        "experiment": (
            "Add a trend filter (e.g. 200-period EMA) to prevent taking trades against "
            "the primary trend. Test with this single addition and no other changes."
        ),
        "goal": (
            "Target profit factor ≥ 1.5 by eliminating low-quality counter-trend setups. "
            "Accept a lower trade count if quality improves."
        ),
    },
    "return_over_drawdown": {
        "experiment": (
            "Add a trailing stop or time-based exit to lock in open profits earlier, "
            "reducing the depth of peak-to-trough equity swings. Compare equity curves "
            "with and without the change."
        ),
        "goal": (
            "Target return / max drawdown ratio ≥ 3.0. "
            "The current drawdown is not justified by the returns it enables."
        ),
    },
    "risk_reward": {
        "experiment": (
            "Adjust take-profit and stop-loss placement: either widen the target or "
            "tighten the stop. Test one change at a time to isolate the effect. "
            "Aim for average win ≥ 1.5× average loss."
        ),
        "goal": (
            "Target risk/reward ratio ≥ 1.5. "
            "Below 1.0, the strategy requires an unrealistically high win rate to be profitable."
        ),
    },
    "consecutive_losses": {
        "experiment": (
            "Introduce a consecutive-loss limit: pause trading after 5 consecutive losses "
            "and resume only after a qualifying setup confirmation in the next session. "
            "Log each pause to evaluate whether it improves long-run performance."
        ),
        "goal": (
            "Target max consecutive losses ≤ 5. "
            "Long losing streaks compound drawdowns and are psychologically unsustainable."
        ),
    },
    "win_rate": {
        "experiment": (
            "Add a single entry confirmation filter — for example, require RSI to be "
            "below 40 before a long entry, or volume to exceed the 20-period average. "
            "Accept fewer trades in exchange for higher-quality setups."
        ),
        "goal": (
            "Target win rate ≥ 45% without reducing profit factor. "
            "If win rate improves but profit factor falls, the filter is filtering out "
            "big winners and should be revised."
        ),
    },
    "loss_concentration": {
        "experiment": (
            "Identify the largest losing trades by date and market condition. "
            "Add a per-trade maximum loss limit of 2× average loss and test its effect "
            "on both drawdown and overall profit factor."
        ),
        "goal": (
            "Target largest single loss ≤ 3× average loss. "
            "Outlier losses destabilise performance and indicate poor risk control."
        ),
    },
    "expectancy": {
        "experiment": (
            "Increase the take-profit target to allow winners to run further, or add a "
            "partial-close rule to secure profits on a portion of the position. "
            "The goal is to raise average win without sacrificing win rate significantly."
        ),
        "goal": (
            "Target expectancy ≥ 0.10R (earning at least 10 cents per dollar risked per trade). "
            "Low expectancy strategies are fragile under real-world commission and slippage."
        ),
    },
}

# Priority order for selecting the primary failure to fix
_PRIORITY_ORDER = [
    "net_profit",
    "sample_size",
    "max_drawdown",
    "profit_factor",
    "return_over_drawdown",
    "risk_reward",
    "consecutive_losses",
    "expectancy",
    "win_rate",
    "loss_concentration",
]


# ── Individual rule functions ──────────────────────────────────────────────────

def _rule_net_profit(m: Metrics) -> RuleResult:
    val = f"{m.net_profit:+.2f} {m.profit_unit}"
    if m.net_profit > 0:
        return RuleResult(
            "Net Profit", RuleStatus.PASS, 100.0,
            f"Positive net profit ({val})", 0.25,
        )
    return RuleResult(
        "Net Profit", RuleStatus.FAIL, 0.0,
        f"Net profit is negative ({val}) — no edge demonstrated", 0.25,
    )


def _rule_profit_factor(m: Metrics) -> RuleResult:
    pf = m.profit_factor
    s  = "∞" if math.isinf(pf) else f"{pf:.2f}"
    if pf >= 1.5:
        return RuleResult("Profit Factor", RuleStatus.PASS, 100.0,
                          f"Profit factor {s} — strong (target ≥ 1.5)", 0.40)
    if pf >= 1.2:
        return RuleResult("Profit Factor", RuleStatus.WARNING, 50.0,
                          f"Profit factor {s} — marginal (1.2–1.5); target ≥ 1.5", 0.40)
    return RuleResult("Profit Factor", RuleStatus.FAIL, 0.0,
                      f"Profit factor {s} — weak (< 1.2); losses nearly match or exceed gains", 0.40)


def _rule_expectancy(m: Metrics) -> RuleResult:
    if m.avg_loss > 0:
        ratio = m.expectancy / m.avg_loss
        label = f"{ratio:+.2f}R per trade"
    elif m.expectancy > 0:
        ratio = math.inf
        label = f"{m.expectancy:+.2f} {m.profit_unit} per trade (no losses)"
    else:
        ratio = 0.0
        label = f"{m.expectancy:.2f} {m.profit_unit} per trade"

    if ratio >= 0.10 or math.isinf(ratio):
        return RuleResult("Expectancy", RuleStatus.PASS, 100.0,
                          f"Positive expectancy — {label}", 0.35)
    if ratio >= 0.0:
        return RuleResult("Expectancy", RuleStatus.WARNING, 50.0,
                          f"Low expectancy — {label}; target ≥ 0.10R", 0.35)
    return RuleResult("Expectancy", RuleStatus.FAIL, 0.0,
                      f"Negative expectancy — {label}; strategy loses money on average", 0.35)


def _rule_sample_size(m: Metrics) -> RuleResult:
    n = m.total_trades
    if n >= 100:
        return RuleResult("Sample Size", RuleStatus.PASS, 100.0,
                          f"{n} trades — statistically meaningful (target ≥ 100)", 0.40)
    if n >= 30:
        return RuleResult("Sample Size", RuleStatus.WARNING, 50.0,
                          f"{n} trades — below ideal; results may not be reliable (target ≥ 100)", 0.40)
    return RuleResult("Sample Size", RuleStatus.FAIL, 0.0,
                      f"{n} trades — insufficient for any valid conclusion (minimum 30, target ≥ 100)", 0.40)


def _rule_risk_reward(m: Metrics) -> RuleResult:
    rr = m.risk_reward
    s  = "∞" if math.isinf(rr) else f"{rr:.2f}"
    if rr >= 1.5 or math.isinf(rr):
        return RuleResult("Risk / Reward", RuleStatus.PASS, 100.0,
                          f"Risk/reward {s} — strong (target ≥ 1.5)", 0.35)
    if rr >= 1.0:
        return RuleResult("Risk / Reward", RuleStatus.WARNING, 50.0,
                          f"Risk/reward {s} — marginal (1.0–1.5); target ≥ 1.5", 0.35)
    return RuleResult("Risk / Reward", RuleStatus.FAIL, 0.0,
                      f"Risk/reward {s} — unfavorable (< 1.0); average loss exceeds average win", 0.35)


def _rule_win_rate(m: Metrics) -> RuleResult:
    wr = m.win_rate * 100
    if wr >= 45:
        return RuleResult("Win Rate", RuleStatus.PASS, 100.0,
                          f"Win rate {wr:.1f}% — adequate (target ≥ 45%)", 0.25)
    if wr >= 35:
        return RuleResult("Win Rate", RuleStatus.WARNING, 50.0,
                          f"Win rate {wr:.1f}% — low; requires strong risk/reward to compensate", 0.25)
    return RuleResult("Win Rate", RuleStatus.FAIL, 0.0,
                      f"Win rate {wr:.1f}% — critically low; unsustainable without exceptional R/R", 0.25)


def _rule_max_drawdown(m: Metrics) -> RuleResult:
    dd   = m.max_drawdown
    unit = m.profit_unit

    if unit == "%":
        if dd <= 10:
            return RuleResult("Max Drawdown", RuleStatus.PASS, 100.0,
                              f"Max drawdown {dd:.2f}% — within acceptable range (target ≤ 10%)", 0.40)
        if dd <= 20:
            return RuleResult("Max Drawdown", RuleStatus.WARNING, 50.0,
                              f"Max drawdown {dd:.2f}% — elevated (10–20%); target ≤ 10%", 0.40)
        return RuleResult("Max Drawdown", RuleStatus.FAIL, 0.0,
                          f"Max drawdown {dd:.2f}% — high risk to capital (> 20%)", 0.40)

    # Absolute mode: express drawdown relative to net profit
    if m.net_profit > 0:
        ratio = dd / m.net_profit
        if ratio <= 0.5:
            return RuleResult("Max Drawdown", RuleStatus.PASS, 100.0,
                              f"Max drawdown {dd:.2f} {unit} ({ratio:.0%} of net profit) — controlled", 0.40)
        if ratio <= 1.0:
            return RuleResult("Max Drawdown", RuleStatus.WARNING, 50.0,
                              f"Max drawdown {dd:.2f} {unit} ({ratio:.0%} of net profit) — target < 50%", 0.40)
    return RuleResult("Max Drawdown", RuleStatus.FAIL, 0.0,
                      f"Max drawdown {dd:.2f} {unit} — equals or exceeds net profit", 0.40)


def _rule_return_over_drawdown(m: Metrics) -> RuleResult:
    rod = m.return_over_max_drawdown
    if math.isinf(rod):
        return RuleResult("Return / Max Drawdown", RuleStatus.PASS, 100.0,
                          "No drawdown recorded — perfect capital preservation", 0.35)
    if rod >= 3.0:
        return RuleResult("Return / Max Drawdown", RuleStatus.PASS, 100.0,
                          f"Return / max drawdown = {rod:.2f} — excellent (target ≥ 3.0)", 0.35)
    if rod >= 1.5:
        return RuleResult("Return / Max Drawdown", RuleStatus.WARNING, 50.0,
                          f"Return / max drawdown = {rod:.2f} — marginal (1.5–3.0); target ≥ 3.0", 0.35)
    return RuleResult("Return / Max Drawdown", RuleStatus.FAIL, 0.0,
                      f"Return / max drawdown = {rod:.2f} — poor; drawdown not justified by returns (target ≥ 1.5)", 0.35)


def _rule_consecutive_losses(m: Metrics) -> RuleResult:
    cl = m.max_consecutive_losses
    if cl <= 4:
        return RuleResult("Consecutive Losses", RuleStatus.PASS, 100.0,
                          f"Max {cl} consecutive loss(es) — acceptable (target ≤ 4)", 0.15)
    if cl <= 7:
        return RuleResult("Consecutive Losses", RuleStatus.WARNING, 50.0,
                          f"Max {cl} consecutive losses — elevated; compound drawdown risk during streaks", 0.15)
    return RuleResult("Consecutive Losses", RuleStatus.FAIL, 0.0,
                      f"Max {cl} consecutive losses — severe; add a loss-limit mechanism", 0.15)


def _rule_loss_concentration(m: Metrics) -> RuleResult:
    if m.avg_loss == 0:
        return RuleResult("Loss Concentration", RuleStatus.PASS, 100.0,
                          "No losses — loss concentration N/A", 0.10)
    ratio = m.largest_loss / m.avg_loss
    if ratio <= 3.0:
        return RuleResult("Loss Concentration", RuleStatus.PASS, 100.0,
                          f"Largest loss = {ratio:.1f}× average loss — no dangerous outliers (target ≤ 3×)", 0.10)
    if ratio <= 5.0:
        return RuleResult("Loss Concentration", RuleStatus.WARNING, 50.0,
                          f"Largest loss = {ratio:.1f}× average loss — outlier present; investigate cause", 0.10)
    return RuleResult("Loss Concentration", RuleStatus.FAIL, 0.0,
                      f"Largest loss = {ratio:.1f}× average loss — extreme outlier; add a per-trade loss cap", 0.10)


# ── Category builders ─────────────────────────────────────────────────────────

def _weighted_score(rules: list[RuleResult]) -> float:
    total_weight = sum(r.weight for r in rules)
    if total_weight == 0:
        return 0.0
    return sum(r.score * r.weight for r in rules) / total_weight


def _build_capital_preservation(m: Metrics) -> CategoryResult:
    rules = [
        _rule_max_drawdown(m),
        _rule_return_over_drawdown(m),
        _rule_consecutive_losses(m),
        _rule_loss_concentration(m),
    ]
    return CategoryResult("Capital Preservation", _weighted_score(rules), 0.35, rules)


def _build_profitability(m: Metrics) -> CategoryResult:
    rules = [
        _rule_profit_factor(m),
        _rule_expectancy(m),
        _rule_net_profit(m),
    ]
    return CategoryResult("Profitability", _weighted_score(rules), 0.30, rules)


def _build_robustness(m: Metrics) -> CategoryResult:
    rules = [
        _rule_sample_size(m),
        _rule_risk_reward(m),
        _rule_win_rate(m),
    ]
    return CategoryResult("Robustness", _weighted_score(rules), 0.35, rules)


# ── Gate evaluation ───────────────────────────────────────────────────────────

def evaluate_gate(metrics: Metrics) -> GateResult:
    """
    Run all quality gate rules against the supplied Metrics and return
    a complete GateResult with decision, scores, and next experiment.
    """
    capital    = _build_capital_preservation(metrics)
    profit     = _build_profitability(metrics)
    robustness = _build_robustness(metrics)
    categories = [capital, profit, robustness]

    overall = sum(c.score * c.weight for c in categories)

    # Hard-fail conditions that force REJECT regardless of score
    critical_failures: list[str] = []
    if metrics.net_profit <= 0:
        critical_failures.append("net_profit")

    if critical_failures or overall < 45:
        decision = Decision.REJECT
    elif overall >= 70:
        decision = Decision.PROMISING
    else:
        decision = Decision.NEEDS_IMPROVEMENT

    weakest = min(categories, key=lambda c: c.score)
    primary = _find_primary_failure(metrics, categories, critical_failures)
    suggestion = _SUGGESTIONS.get(primary, {})

    return GateResult(
        decision         = decision,
        overall_score    = round(overall, 1),
        categories       = categories,
        weakest_category = weakest.name,
        primary_failure  = primary,
        next_experiment  = suggestion.get(
            "experiment", "Review the weakest category and design a targeted experiment."
        ),
        expected_goal    = suggestion.get(
            "goal", "Improve the primary failure metric in the next backtest iteration."
        ),
        critical_failures = critical_failures,
    )


def _find_primary_failure(
    metrics: Metrics,
    categories: list[CategoryResult],
    critical_failures: list[str],
) -> str:
    """Return the key of the highest-priority issue to address next."""
    # Critical failures trump everything
    for key in _PRIORITY_ORDER:
        if key in critical_failures:
            return key

    # Flatten all rules for lookup
    rules_by_key: dict[str, RuleResult] = {}
    for cat in categories:
        for rule in cat.rules:
            key = _name_to_key(rule.name)
            rules_by_key[key] = rule

    # First FAIL in priority order
    for key in _PRIORITY_ORDER:
        rule = rules_by_key.get(key)
        if rule and rule.status == RuleStatus.FAIL:
            return key

    # Then first WARNING in priority order
    for key in _PRIORITY_ORDER:
        rule = rules_by_key.get(key)
        if rule and rule.status == RuleStatus.WARNING:
            return key

    return _PRIORITY_ORDER[0]


def _name_to_key(name: str) -> str:
    _map = {
        "Net Profit":             "net_profit",
        "Profit Factor":          "profit_factor",
        "Expectancy":             "expectancy",
        "Sample Size":            "sample_size",
        "Risk / Reward":          "risk_reward",
        "Win Rate":               "win_rate",
        "Max Drawdown":           "max_drawdown",
        "Return / Max Drawdown":  "return_over_drawdown",
        "Consecutive Losses":     "consecutive_losses",
        "Loss Concentration":     "loss_concentration",
    }
    return _map.get(name, name.lower().replace(" ", "_").replace("/", "_"))
