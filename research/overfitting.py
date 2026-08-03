"""Overfitting detection — automatically flags curve-fitted strategies.

An OverfittingRisk score in [0, 100] is produced from multiple independent
signals.  A score of 0 means "no evidence of overfitting"; 100 means "almost
certainly overfit".  Strategies with scores >= 60 are flagged as HIGH RISK.

Signals evaluated
-----------------
1. **Sample size**          — too few trades → unreliable statistics.
2. **Parameter sensitivity** — narrow sensitivity manifold → curve-fit peak.
3. **Temporal concentration** — most profit in one time slice → not robust.
4. **Walk-forward stability** — WF efficiency far below 1.0 → IS overfitting.
5. **Monte Carlo spread**   — wide CI interval for Sharpe → luck-dependent.
6. **Yearly return consistency** — high CV of yearly returns → regime-specific.
7. **Symbol concentration** — if only one symbol was tested (flags the need).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OverfittingSignal:
    """A single piece of evidence about overfitting risk."""
    name   : str
    score  : float    # 0-100: how much this signal contributes to risk
    weight : float    # relative importance
    detail : str      # human-readable explanation


@dataclass(frozen=True)
class OverfittingReport:
    """Result of the overfitting detection analysis.

    Attributes
    ----------
    overfitting_score : float
        Composite risk in [0, 100].  0 = no evidence; 100 = extreme risk.
    risk_level : str
        ``"LOW"`` (< 30), ``"MEDIUM"`` (30-60), ``"HIGH"`` (≥ 60).
    signals : list[OverfittingSignal]
        Individual signals that contributed to the score.
    summary : str
        One-paragraph human-readable explanation.
    """
    overfitting_score : float
    risk_level        : str
    signals           : list[OverfittingSignal]
    summary           : str

    def to_dict(self) -> dict:
        return {
            "overfitting_score": self.overfitting_score,
            "risk_level"       : self.risk_level,
            "signals"          : [
                {
                    "name"  : s.name,
                    "score" : s.score,
                    "weight": s.weight,
                    "detail": s.detail,
                }
                for s in self.signals
            ],
            "summary": self.summary,
        }


# ── Main function ─────────────────────────────────────────────────────────────

def analyze_overfitting(
    total_trades         : int,
    sharpe_ratio         : float,
    robustness_data      : dict[str, Any] | None = None,
    wf_efficiency        : float | None = None,
    mc_sharpe_ci_width   : float | None = None,
    yearly_returns       : list[float] | None = None,
    in_sample_sharpe     : float | None = None,
    out_of_sample_sharpe : float | None = None,
    n_params_tested      : int = 1,
    n_symbols            : int = 1,
) -> OverfittingReport:
    """Compute overfitting risk from available evidence.

    Args:
        total_trades:          Number of completed trades in the backtest.
        sharpe_ratio:          In-sample Sharpe ratio.
        robustness_data:       Dict from ``research.robustness.analyze_robustness``.
                               Used for parameter sensitivity signals.
        wf_efficiency:         Walk-forward efficiency = OOS_Sharpe / IS_Sharpe.
                               Values << 1 suggest IS overfitting.
        mc_sharpe_ci_width:    Width of the 90% CI for Sharpe from Monte Carlo
                               (95th_pct − 5th_pct).  Wide = luck-dependent.
        yearly_returns:        List of per-year returns (as fractions, e.g. 0.25).
                               Used to detect temporal concentration.
        in_sample_sharpe:      Sharpe on the training period of walk-forward.
        out_of_sample_sharpe:  Sharpe on the test period of walk-forward.
        n_params_tested:       Total number of parameter combinations tested.
                               High number increases curve-fitting risk.
        n_symbols:             Number of symbols backtested simultaneously.

    Returns:
        :class:`OverfittingReport`.
    """
    signals: list[OverfittingSignal] = []

    # ── Signal 1: Sample size ─────────────────────────────────────────────────
    sig1 = _signal_sample_size(total_trades)
    signals.append(sig1)

    # ── Signal 2: Parameter sensitivity (robustness data) ────────────────────
    if robustness_data is not None:
        sig2 = _signal_parameter_sensitivity(robustness_data, sharpe_ratio)
        signals.append(sig2)

    # ── Signal 3: Walk-forward efficiency ─────────────────────────────────────
    if wf_efficiency is not None:
        sig3 = _signal_wf_efficiency(wf_efficiency)
        signals.append(sig3)
    elif in_sample_sharpe is not None and out_of_sample_sharpe is not None:
        if in_sample_sharpe > 0:
            eff = out_of_sample_sharpe / in_sample_sharpe
            sig3 = _signal_wf_efficiency(eff)
            signals.append(sig3)

    # ── Signal 4: Monte Carlo CI width ────────────────────────────────────────
    if mc_sharpe_ci_width is not None:
        sig4 = _signal_mc_spread(mc_sharpe_ci_width, sharpe_ratio)
        signals.append(sig4)

    # ── Signal 5: Yearly return consistency ───────────────────────────────────
    if yearly_returns and len(yearly_returns) >= 2:
        sig5 = _signal_yearly_consistency(yearly_returns)
        signals.append(sig5)

    # ── Signal 6: Parameter space size ────────────────────────────────────────
    if n_params_tested > 1:
        sig6 = _signal_param_space_size(n_params_tested)
        signals.append(sig6)

    # ── Signal 7: Symbol diversification ─────────────────────────────────────
    if n_symbols == 1:
        signals.append(OverfittingSignal(
            name   = "Symbol Concentration",
            score  = 20.0,
            weight = 0.5,
            detail = (
                "Strategy was only tested on 1 symbol. "
                "Results may be specific to that instrument's characteristics."
            ),
        ))

    # ── Composite score ───────────────────────────────────────────────────────
    total_weight = sum(s.weight for s in signals)
    if total_weight > 0:
        composite = sum(s.score * s.weight for s in signals) / total_weight
    else:
        composite = 0.0
    composite = round(min(100.0, max(0.0, composite)), 1)

    if composite < 30:
        risk_level = "LOW"
    elif composite < 60:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    summary = _build_summary(composite, risk_level, signals)

    return OverfittingReport(
        overfitting_score = composite,
        risk_level        = risk_level,
        signals           = signals,
        summary           = summary,
    )


# ── Individual signal computations ────────────────────────────────────────────

def _signal_sample_size(total_trades: int) -> OverfittingSignal:
    if total_trades >= 200:
        score  = 0.0
        detail = f"{total_trades} trades — large sample, low size-related risk."
    elif total_trades >= 100:
        score  = 15.0
        detail = f"{total_trades} trades — adequate but limited statistical power."
    elif total_trades >= 50:
        score  = 40.0
        detail = (
            f"{total_trades} trades — small sample.  Results may not generalise. "
            "Target ≥ 100 trades for reliable statistics."
        )
    elif total_trades >= 20:
        score  = 70.0
        detail = (
            f"{total_trades} trades — very small sample.  High probability that "
            "any positive result is due to chance.  Minimum 30 recommended."
        )
    else:
        score  = 100.0
        detail = (
            f"{total_trades} trades — insufficient for any statistical conclusion. "
            "The result is essentially random."
        )
    return OverfittingSignal(
        name="Sample Size", score=score, weight=2.0, detail=detail
    )


def _signal_parameter_sensitivity(
    robustness_data: dict,
    focal_sharpe: float,
) -> OverfittingSignal:
    stability = robustness_data.get("stability_score", 100.0) or 100.0
    robustness_score = robustness_data.get("robustness_score", 100.0) or 100.0
    n_neighbors = robustness_data.get("n_neighbors", 0) or 0
    neighbor_sharpe_std = robustness_data.get("neighbor_sharpe_std")
    neighbor_sharpe_mean = robustness_data.get("neighbor_sharpe_mean")

    if n_neighbors == 0:
        return OverfittingSignal(
            name   = "Parameter Sensitivity",
            score  = 20.0,
            weight = 1.5,
            detail = "No neighbor parameter combos available for sensitivity analysis.",
        )

    # Low stability = sharp peak in parameter space = high overfitting risk
    # High robustness score (% profitable neighbors) = lower risk
    risk_from_stability  = max(0.0, 100.0 - stability)
    risk_from_robustness = max(0.0, 100.0 - robustness_score)

    # If focal Sharpe is much higher than neighbors' mean, that's a red flag
    peak_excess_risk = 0.0
    if neighbor_sharpe_mean is not None and focal_sharpe > 0:
        excess = focal_sharpe - neighbor_sharpe_mean
        if excess > 0.5 * focal_sharpe:
            peak_excess_risk = min(40.0, excess / focal_sharpe * 50.0)

    score = (risk_from_stability * 0.4 + risk_from_robustness * 0.4
             + peak_excess_risk * 0.2)
    score = min(100.0, score)

    if score < 25:
        detail = (
            f"Low parameter sensitivity risk — stability={stability:.0f}, "
            f"robustness={robustness_score:.0f}%."
        )
    elif score < 60:
        detail = (
            f"Moderate parameter sensitivity — stability={stability:.0f}, "
            f"robustness={robustness_score:.0f}%. "
            "Performance changes noticeably with small parameter adjustments."
        )
    else:
        detail = (
            f"High parameter sensitivity — stability={stability:.0f}, "
            f"robustness={robustness_score:.0f}%. "
            "Strategy sits on a sharp peak in parameter space — a classic "
            "overfitting signature.  Small changes in parameters cause large "
            "performance drops."
        )

    return OverfittingSignal(
        name="Parameter Sensitivity", score=score, weight=1.5, detail=detail
    )


def _signal_wf_efficiency(efficiency: float) -> OverfittingSignal:
    if efficiency >= 0.7:
        score  = 0.0
        detail = (
            f"Walk-forward efficiency = {efficiency:.2f} — OOS performance "
            "closely tracks IS performance.  Low IS overfitting evidence."
        )
    elif efficiency >= 0.4:
        score  = 40.0
        detail = (
            f"Walk-forward efficiency = {efficiency:.2f} — OOS performance "
            "degrades moderately vs IS.  Some evidence of IS overfitting."
        )
    elif efficiency >= 0.0:
        score  = 75.0
        detail = (
            f"Walk-forward efficiency = {efficiency:.2f} — OOS performance "
            "degrades severely vs IS.  Strong evidence of IS overfitting."
        )
    else:
        score  = 100.0
        detail = (
            f"Walk-forward efficiency = {efficiency:.2f} — OOS performance is "
            "negative while IS is positive.  Extreme IS overfitting."
        )

    return OverfittingSignal(
        name="Walk-Forward Efficiency", score=score, weight=2.0, detail=detail
    )


def _signal_mc_spread(ci_width: float, sharpe: float) -> OverfittingSignal:
    # CI width relative to the Sharpe estimate
    if sharpe > 0:
        relative_width = ci_width / sharpe
    else:
        relative_width = ci_width if ci_width >= 0 else 0.0

    if relative_width <= 0.5:
        score  = 0.0
        detail = (
            f"Monte Carlo Sharpe CI width = {ci_width:.2f} "
            f"(relative: {relative_width:.1f}×) — narrow spread suggests "
            "performance is driven by the strategy, not luck."
        )
    elif relative_width <= 1.5:
        score  = 35.0
        detail = (
            f"Monte Carlo Sharpe CI width = {ci_width:.2f} "
            f"(relative: {relative_width:.1f}×) — moderate spread.  "
            "Some performance variability across trade orderings."
        )
    elif relative_width <= 3.0:
        score  = 65.0
        detail = (
            f"Monte Carlo Sharpe CI width = {ci_width:.2f} "
            f"(relative: {relative_width:.1f}×) — wide spread.  "
            "Performance is highly sensitive to trade order.  May be luck-driven."
        )
    else:
        score  = 90.0
        detail = (
            f"Monte Carlo Sharpe CI width = {ci_width:.2f} "
            f"(relative: {relative_width:.1f}×) — very wide spread.  "
            "The result is essentially random; the strategy has no robust edge."
        )

    return OverfittingSignal(
        name="Monte Carlo Spread", score=score, weight=1.5, detail=detail
    )


def _signal_yearly_consistency(yearly_returns: list[float]) -> OverfittingSignal:
    n = len(yearly_returns)
    if n < 2:
        return OverfittingSignal(
            name="Yearly Consistency", score=30.0, weight=1.0,
            detail="Insufficient data for yearly consistency analysis."
        )

    mean_return = statistics.mean(yearly_returns)
    std_return  = statistics.stdev(yearly_returns)

    # Coefficient of variation
    if abs(mean_return) > 1e-9:
        cv = abs(std_return / mean_return)
    else:
        cv = float("inf")

    # Count negative years
    n_negative = sum(1 for r in yearly_returns if r < 0)
    neg_pct    = n_negative / n

    if cv <= 0.5 and neg_pct == 0:
        score  = 0.0
        detail = (
            f"Yearly returns are consistent (CV={cv:.2f}, "
            f"negative years={n_negative}/{n}).  Low temporal concentration risk."
        )
    elif cv <= 1.5 and neg_pct <= 0.25:
        score  = 30.0
        detail = (
            f"Some yearly return variability (CV={cv:.2f}, "
            f"negative years={n_negative}/{n}).  Moderate temporal risk."
        )
    elif math.isinf(cv) or cv > 3.0:
        score  = 80.0
        detail = (
            f"Highly variable yearly returns (CV=∞ or {cv:.1f}, "
            f"negative years={n_negative}/{n}).  Performance likely concentrated "
            "in specific periods — high temporal overfitting risk."
        )
    else:
        score  = 55.0
        detail = (
            f"Variable yearly returns (CV={cv:.2f}, "
            f"negative years={n_negative}/{n}).  Elevated temporal concentration."
        )

    return OverfittingSignal(
        name="Yearly Consistency", score=score, weight=1.0, detail=detail
    )


def _signal_param_space_size(n_params: int) -> OverfittingSignal:
    # The larger the parameter space searched, the higher the probability
    # of finding a good result by chance (multiple comparisons problem).
    if n_params <= 10:
        score  = 5.0
        detail = f"{n_params} parameter combinations — small search space."
    elif n_params <= 50:
        score  = 20.0
        detail = (
            f"{n_params} combinations tested.  "
            "Multiple comparisons inflate the chance of a spurious peak."
        )
    elif n_params <= 200:
        score  = 45.0
        detail = (
            f"{n_params} combinations tested.  "
            "Large search space significantly increases curve-fitting risk."
        )
    else:
        score  = 70.0
        detail = (
            f"{n_params} combinations tested.  "
            "Very large search space — any high-Sharpe result should be "
            "validated on genuinely out-of-sample data before trusting it."
        )

    return OverfittingSignal(
        name="Search Space Size", score=score, weight=0.5, detail=detail
    )


def _build_summary(
    score: float,
    risk_level: str,
    signals: list[OverfittingSignal],
) -> str:
    top_signals = sorted(signals, key=lambda s: -s.score)[:3]
    top_names   = [s.name for s in top_signals if s.score > 20]

    if risk_level == "LOW":
        intro = (
            f"Overfitting risk is LOW (score={score:.0f}/100).  "
            "Multiple independent validation signals are consistent with a "
            "genuine edge."
        )
    elif risk_level == "MEDIUM":
        intro = (
            f"Overfitting risk is MEDIUM (score={score:.0f}/100).  "
            "Some signals raise concern.  Additional out-of-sample validation "
            "is recommended before trusting this strategy."
        )
    else:
        intro = (
            f"Overfitting risk is HIGH (score={score:.0f}/100).  "
            "Multiple signals are consistent with a curve-fitted result.  "
            "This strategy should NOT be approved without substantially more evidence."
        )

    if top_names:
        concerns = " | ".join(top_names)
        return f"{intro}  Primary concerns: {concerns}."
    return intro
