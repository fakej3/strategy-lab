"""
Report generators — terminal (plain text), JSON, and Markdown.

Each renderer is a pure function: given Metrics and GateResult, it returns
a string (or dict for JSON). No I/O happens here; writing to disk or stdout
is the caller's responsibility.
"""
from __future__ import annotations

import json
import math
from datetime import datetime

from .models import Decision, GateResult, Metrics, RuleStatus

_WIDTH = 52
_SEP  = "=" * _WIDTH
_DASH = "─" * _WIDTH

_STATUS_SYMBOL = {
    RuleStatus.PASS:    "✓",
    RuleStatus.WARNING: "⚠",
    RuleStatus.FAIL:    "✗",
}

_DECISION_LABEL = {
    Decision.PROMISING:         "PROMISING",
    Decision.NEEDS_IMPROVEMENT: "NEEDS IMPROVEMENT",
    Decision.REJECT:            "REJECT",
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _fv(value: float, unit: str) -> str:
    """Format a metric value with its unit."""
    if math.isinf(value):
        return "∞"
    return f"{value:.2f}{unit}" if unit == "%" else f"{value:.2f}"


def _fs(score: float) -> str:
    return f"{round(score)}/100"


def _wrap(text: str, indent: str, width: int) -> list[str]:
    """Word-wrap text to width, with the given indent on every line."""
    words  = text.split()
    lines  = []
    line   = indent
    for word in words:
        candidate = line + word + " "
        if len(candidate) > width and line.strip():
            lines.append(line.rstrip())
            line = indent + word + " "
        else:
            line = candidate
    if line.strip():
        lines.append(line.rstrip())
    return lines


# ── Terminal report ────────────────────────────────────────────────────────────

def render_terminal(metrics: Metrics, gate: GateResult) -> str:
    """Return a formatted plain-text report for terminal output."""
    u = metrics.profit_unit
    L: list[str] = []

    def add(line: str = "") -> None:
        L.append(line)

    add(_SEP)
    add("STRATEGY RESEARCH LAB — PIPELINE REPORT")
    add(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    add(_SEP)
    add()

    # ── Decision ──────────────────────────────────────────────────────────
    add("DECISION")
    add(_DASH)
    add(f"  {_DECISION_LABEL[gate.decision]}")
    if gate.critical_failures:
        add(f"  ← Hard failure: {', '.join(gate.critical_failures)}")
    add()

    # ── Score breakdown ───────────────────────────────────────────────────
    add("SCORE BREAKDOWN")
    add(_DASH)
    add(f"  {'Overall Score':<26} {_fs(gate.overall_score)}")
    for cat in gate.categories:
        add(f"  {cat.name:<26} {_fs(cat.score)}")
    add()

    # ── Metrics ───────────────────────────────────────────────────────────
    add("METRICS")
    add(_DASH)

    def row(label: str, value: str) -> str:
        return f"  {label:<28} {value}"

    add(row("Total Trades",           str(metrics.total_trades)))
    add(row("Winning / Losing",       f"{metrics.winning_trades} / {metrics.losing_trades}"))
    add(row("Win Rate",               f"{metrics.win_rate * 100:.1f}%"))
    add()
    add(row("Net Profit",             _fv(metrics.net_profit, u)))
    add(row("Gross Profit",           _fv(metrics.gross_profit, u)))
    add(row("Gross Loss",             _fv(metrics.gross_loss, u)))
    add(row("Profit Factor",          "∞" if math.isinf(metrics.profit_factor)
                                           else f"{metrics.profit_factor:.2f}"))
    add()
    add(row("Average Win",            _fv(metrics.avg_win, u)))
    add(row("Average Loss",           _fv(metrics.avg_loss, u)))
    add(row("Risk / Reward",          "∞" if math.isinf(metrics.risk_reward)
                                           else f"{metrics.risk_reward:.2f}"))
    add(row("Average Trade",          _fv(metrics.avg_trade, u)))
    add(row("Expectancy",             _fv(metrics.expectancy, u)))
    add()
    add(row("Largest Win",            _fv(metrics.largest_win, u)))
    add(row("Largest Loss",           _fv(metrics.largest_loss, u)))
    add(row("Max Consecutive Wins",   str(metrics.max_consecutive_wins)))
    add(row("Max Consecutive Losses", str(metrics.max_consecutive_losses)))
    add()
    add(row("Max Drawdown",           _fv(metrics.max_drawdown, u)))
    add(row("Return / Max Drawdown",  "∞" if math.isinf(metrics.return_over_max_drawdown)
                                           else f"{metrics.return_over_max_drawdown:.2f}"))
    add()

    # ── Quality gate ──────────────────────────────────────────────────────
    add("QUALITY GATE")
    add(_DASH)
    for cat in gate.categories:
        add(f"  [{cat.name}]")
        for rule in cat.rules:
            sym = _STATUS_SYMBOL[rule.status]
            add(f"    {sym} {rule.name}: {rule.detail}")
        add()

    # ── Analysis ──────────────────────────────────────────────────────────
    add("WEAKEST AREA")
    add(_DASH)
    add(f"  {gate.weakest_category}")
    add()

    add("SUGGESTED NEXT EXPERIMENT")
    add(_DASH)
    for line in _wrap(gate.next_experiment, "  ", _WIDTH):
        add(line)
    add()

    add("EXPECTED GOAL")
    add(_DASH)
    for line in _wrap(gate.expected_goal, "  ", _WIDTH):
        add(line)
    add()

    add(_SEP)
    return "\n".join(L)


# ── JSON report ────────────────────────────────────────────────────────────────

def render_json(metrics: Metrics, gate: GateResult) -> dict:
    """Return a JSON-serialisable dict of all pipeline results."""

    def sf(v: float) -> float | str:
        """Safe float — convert infinity to the string 'Infinity'."""
        return "Infinity" if math.isinf(v) else round(v, 4)

    return {
        "generated_at": datetime.now().isoformat(),
        "decision": gate.decision.value,
        "scores": {
            "overall": gate.overall_score,
            **{cat.name: round(cat.score, 1) for cat in gate.categories},
        },
        "metrics": {
            "total_trades":             metrics.total_trades,
            "winning_trades":           metrics.winning_trades,
            "losing_trades":            metrics.losing_trades,
            "breakeven_trades":         metrics.breakeven_trades,
            "profit_unit":              metrics.profit_unit,
            "net_profit":               sf(metrics.net_profit),
            "gross_profit":             sf(metrics.gross_profit),
            "gross_loss":               sf(metrics.gross_loss),
            "profit_factor":            sf(metrics.profit_factor),
            "win_rate":                 round(metrics.win_rate, 4),
            "avg_win":                  sf(metrics.avg_win),
            "avg_loss":                 sf(metrics.avg_loss),
            "risk_reward":              sf(metrics.risk_reward),
            "largest_win":              sf(metrics.largest_win),
            "largest_loss":             sf(metrics.largest_loss),
            "max_consecutive_wins":     metrics.max_consecutive_wins,
            "max_consecutive_losses":   metrics.max_consecutive_losses,
            "avg_trade":                sf(metrics.avg_trade),
            "expectancy":               sf(metrics.expectancy),
            "max_drawdown":             sf(metrics.max_drawdown),
            "return_over_max_drawdown": sf(metrics.return_over_max_drawdown),
        },
        "quality_gate": {
            "categories": [
                {
                    "name":   cat.name,
                    "score":  round(cat.score, 1),
                    "weight": cat.weight,
                    "rules": [
                        {
                            "name":   rule.name,
                            "status": rule.status.value,
                            "score":  rule.score,
                            "detail": rule.detail,
                            "weight": rule.weight,
                        }
                        for rule in cat.rules
                    ],
                }
                for cat in gate.categories
            ],
            "weakest_category":  gate.weakest_category,
            "critical_failures": gate.critical_failures,
        },
        "next_steps": {
            "primary_failure":   gate.primary_failure,
            "next_experiment":   gate.next_experiment,
            "expected_goal":     gate.expected_goal,
        },
    }


# ── Markdown report ────────────────────────────────────────────────────────────

def render_markdown(metrics: Metrics, gate: GateResult) -> str:
    """Return a Markdown-formatted report."""
    u = metrics.profit_unit
    L: list[str] = []

    def add(line: str = "") -> None:
        L.append(line)

    add("# Strategy Research Lab — Pipeline Report")
    add(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    add()

    # Decision
    _badge = {
        Decision.PROMISING:         "🟢 **PROMISING**",
        Decision.NEEDS_IMPROVEMENT: "🟡 **NEEDS IMPROVEMENT**",
        Decision.REJECT:            "🔴 **REJECT**",
    }
    add(f"## Decision: {_badge[gate.decision]}")
    if gate.critical_failures:
        add()
        add(f"> **Hard failure:** `{', '.join(gate.critical_failures)}`")
    add()

    # Scores
    add("## Score Breakdown")
    add()
    add("| Category | Score |")
    add("|---|---|")
    add(f"| **Overall** | **{gate.overall_score:.0f} / 100** |")
    for cat in gate.categories:
        add(f"| {cat.name} | {cat.score:.0f} / 100 |")
    add()

    # Metrics
    add("## Metrics")
    add()
    add("| Metric | Value |")
    add("|---|---|")

    def mr(label: str, value: str) -> str:
        return f"| {label} | {value} |"

    add(mr("Total Trades",           str(metrics.total_trades)))
    add(mr("Winning / Losing",       f"{metrics.winning_trades} / {metrics.losing_trades}"))
    add(mr("Win Rate",               f"{metrics.win_rate * 100:.1f}%"))
    add(mr("Net Profit",             _fv(metrics.net_profit, u)))
    add(mr("Gross Profit",           _fv(metrics.gross_profit, u)))
    add(mr("Gross Loss",             _fv(metrics.gross_loss, u)))
    add(mr("Profit Factor",          "∞" if math.isinf(metrics.profit_factor)
                                          else f"{metrics.profit_factor:.2f}"))
    add(mr("Average Win",            _fv(metrics.avg_win, u)))
    add(mr("Average Loss",           _fv(metrics.avg_loss, u)))
    add(mr("Risk / Reward",          "∞" if math.isinf(metrics.risk_reward)
                                          else f"{metrics.risk_reward:.2f}"))
    add(mr("Average Trade",          _fv(metrics.avg_trade, u)))
    add(mr("Expectancy",             _fv(metrics.expectancy, u)))
    add(mr("Largest Win",            _fv(metrics.largest_win, u)))
    add(mr("Largest Loss",           _fv(metrics.largest_loss, u)))
    add(mr("Max Consecutive Wins",   str(metrics.max_consecutive_wins)))
    add(mr("Max Consecutive Losses", str(metrics.max_consecutive_losses)))
    add(mr("Max Drawdown",           _fv(metrics.max_drawdown, u)))
    add(mr("Return / Max Drawdown",  "∞" if math.isinf(metrics.return_over_max_drawdown)
                                          else f"{metrics.return_over_max_drawdown:.2f}"))
    add()

    # Quality gate
    add("## Quality Gate")
    add()
    _sym_md = {RuleStatus.PASS: "✓", RuleStatus.WARNING: "⚠", RuleStatus.FAIL: "✗"}
    for cat in gate.categories:
        add(f"### {cat.name} — {cat.score:.0f}/100")
        add()
        for rule in cat.rules:
            sym = _sym_md[rule.status]
            add(f"- {sym} **{rule.name}:** {rule.detail}")
        add()

    # Analysis
    add("## Analysis")
    add()
    add(f"**Weakest Area:** {gate.weakest_category}")
    add()
    add("**Suggested Next Experiment:**")
    add()
    add(gate.next_experiment)
    add()
    add("**Expected Goal:**")
    add()
    add(gate.expected_goal)
    add()

    return "\n".join(L)
