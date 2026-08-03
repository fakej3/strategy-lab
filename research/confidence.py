"""Confidence Engine — evidence-weighted approval score for strategies.

Combines signals from every validation layer into a single score in [0, 100]
and a structured recommendation.  The score is *not* a simple average; each
dimension is weighted by its epistemic value and penalised asymmetrically when
critical guarantees are broken.

Scoring model
-------------
Evidence dimensions and their maximum contribution:

  Dimension                  Max pts  Notes
  ─────────────────────────  ───────  ─────────────────────────────────────────
  Data Integrity               15     Missing/corrupt data degrades all other
                                      signals — weighted first.
  Accounting Verification      20     Non-negotiable: wrong P&L = wrong strategy.
  Statistical Confidence       15     Sharpe significance + sample adequacy.
  Walk-Forward Stability       15     IS→OOS degradation.
  Monte Carlo Robustness       10     Trade-order sensitivity.
  Stress Test Resilience       15     Real-cost + adverse-condition survival.
  Parameter Stability           5     Narrow peaks = curve-fitted.
  Overfitting Risk             -X     Penalty applied after base score is summed.
                                      Deducts up to 30 pts for HIGH overfitting.
  ─────────────────────────  ───────
  Subtotal (before penalty)   95
  Bonus (perfect data + acct)  5     Awarded only when both are 100%.
  Maximum                     100

Recommendation thresholds
--------------------------
  APPROVE       score ≥ 75 AND accounting passed AND data integrity ≥ 80
  PROMISING     score ≥ 55 AND accounting passed
  NEEDS_WORK    score ≥ 35
  REJECT        score < 35 OR accounting failed OR data integrity < 60

Critical overrides
------------------
  - Accounting failure → REJECT (no score threshold can save it).
  - Data integrity < 60 → REJECT (backtesting on corrupt data is meaningless).
  - Overfitting risk HIGH AND stress score < 40 → REJECT.

Public API
----------
- ``EvidenceDimension``   — one scored dimension.
- ``ConfidenceReport``    — full confidence breakdown.
- ``calculate_confidence`` — main entry point.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EvidenceDimension:
    """A single evidence dimension contributing to the confidence score."""
    name        : str
    score       : float   # raw evidence score, 0-100
    weight      : float   # maximum contribution in points
    contribution: float   # actual points contributed (score/100 * weight)
    detail      : str     # human-readable explanation


@dataclass
class ConfidenceReport:
    """Full confidence breakdown for a strategy.

    Attributes
    ----------
    confidence_score : float
        Evidence-weighted score in [0, 100].
    recommendation : str
        One of ``"APPROVE"``, ``"PROMISING"``, ``"NEEDS_WORK"``, ``"REJECT"``.
    dimensions : list[EvidenceDimension]
        Per-dimension breakdown showing how the score was built.
    overrides : list[str]
        Critical rules that forced REJECT regardless of score.
    strengths : list[str]
        Dimensions with strong evidence (score ≥ 75).
    weaknesses : list[str]
        Dimensions with weak evidence (score < 40).
    summary : str
        One-paragraph human-readable verdict.
    """
    confidence_score : float
    recommendation   : str
    dimensions       : list[EvidenceDimension]
    overrides        : list[str]
    strengths        : list[str]
    weaknesses       : list[str]
    summary          : str

    def to_dict(self) -> dict:
        return {
            "confidence_score": self.confidence_score,
            "recommendation"  : self.recommendation,
            "overrides"       : self.overrides,
            "strengths"       : self.strengths,
            "weaknesses"      : self.weaknesses,
            "dimensions"      : [
                {
                    "name"        : d.name,
                    "score"       : d.score,
                    "weight"      : d.weight,
                    "contribution": d.contribution,
                    "detail"      : d.detail,
                }
                for d in self.dimensions
            ],
            "summary": self.summary,
        }


# ── Main function ─────────────────────────────────────────────────────────────

def calculate_confidence(
    *,
    # Data integrity
    data_integrity_score   : float | None = None,   # 0-100
    # Accounting / financial verification
    accounting_passed      : bool  | None = None,   # True/False
    accounting_score       : float | None = None,   # 0-100 (optional detail)
    # Statistical confidence
    sharpe_ratio           : float | None = None,
    total_trades           : int   | None = None,
    sharpe_pvalue          : float | None = None,   # from MC or t-test
    # Walk-forward
    wf_efficiency          : float | None = None,   # OOS/IS Sharpe
    wf_score               : float | None = None,   # 0-100 from walk_forward module
    # Monte Carlo
    mc_score               : float | None = None,   # 0-100 from mc module
    mc_sharpe_ci_width     : float | None = None,
    # Stress testing
    stress_score           : float | None = None,   # 0-100 from stress module
    stress_risk_level      : str   | None = None,   # "LOW"/"MEDIUM"/"HIGH"
    # Parameter stability / robustness
    robustness_score       : float | None = None,   # 0-100 from robustness module
    stability_score        : float | None = None,   # 0-100
    # Overfitting
    overfitting_score      : float | None = None,   # 0-100
    overfitting_risk_level : str   | None = None,   # "LOW"/"MEDIUM"/"HIGH"
) -> ConfidenceReport:
    """Calculate an evidence-weighted confidence score for a strategy.

    All arguments are optional so the engine gracefully handles partial
    evidence (earlier pipeline stages may not have run).  Missing evidence
    receives a neutral score of 50 with reduced weight so it neither
    strongly supports nor condemns the strategy.

    Returns:
        :class:`ConfidenceReport` with score, recommendation, and narrative.
    """
    dimensions: list[EvidenceDimension] = []
    overrides : list[str] = []

    # ── Dimension 1: Data Integrity (max 15 pts) ──────────────────────────────
    dim_integrity = _dim_data_integrity(data_integrity_score)
    dimensions.append(dim_integrity)

    # ── Dimension 2: Accounting Verification (max 20 pts) ────────────────────
    dim_accounting = _dim_accounting(accounting_passed, accounting_score)
    dimensions.append(dim_accounting)

    # ── Dimension 3: Statistical Confidence (max 15 pts) ─────────────────────
    dim_stat = _dim_statistical(sharpe_ratio, total_trades, sharpe_pvalue)
    dimensions.append(dim_stat)

    # ── Dimension 4: Walk-Forward Stability (max 15 pts) ─────────────────────
    dim_wf = _dim_walk_forward(wf_efficiency, wf_score)
    dimensions.append(dim_wf)

    # ── Dimension 5: Monte Carlo Robustness (max 10 pts) ─────────────────────
    dim_mc = _dim_monte_carlo(mc_score, mc_sharpe_ci_width, sharpe_ratio)
    dimensions.append(dim_mc)

    # ── Dimension 6: Stress Test Resilience (max 15 pts) ─────────────────────
    dim_stress = _dim_stress(stress_score, stress_risk_level)
    dimensions.append(dim_stress)

    # ── Dimension 7: Parameter Stability (max 5 pts) ─────────────────────────
    dim_param = _dim_parameter_stability(robustness_score, stability_score)
    dimensions.append(dim_param)

    # ── Base score (sum of contributions, capped at 95) ───────────────────────
    base_score = sum(d.contribution for d in dimensions)

    # Bonus: +5 if both data integrity and accounting are near-perfect
    bonus = 0.0
    if (data_integrity_score is not None and data_integrity_score >= 95
            and accounting_passed is True
            and (accounting_score is None or accounting_score >= 95)):
        bonus = 5.0

    raw_score = min(95.0, base_score) + bonus

    # ── Overfitting penalty (deduct up to 30 pts) ─────────────────────────────
    penalty = 0.0
    if overfitting_score is not None:
        if overfitting_score >= 60:
            penalty = 30.0 * (overfitting_score - 60) / 40.0
            penalty = min(30.0, penalty)
        elif overfitting_score >= 30:
            penalty = 10.0 * (overfitting_score - 30) / 30.0

    confidence_score = round(max(0.0, min(100.0, raw_score - penalty)), 1)

    # ── Critical overrides ────────────────────────────────────────────────────
    if accounting_passed is False:
        overrides.append(
            "ACCOUNTING FAILURE: P&L reconciliation failed — "
            "the strategy result cannot be trusted regardless of other metrics."
        )
    if data_integrity_score is not None and data_integrity_score < 60:
        overrides.append(
            f"DATA INTEGRITY CRITICAL: score={data_integrity_score:.1f}/100 — "
            "backtesting on severely degraded data produces unreliable signals."
        )
    if (overfitting_risk_level == "HIGH"
            and stress_score is not None and stress_score < 40):
        overrides.append(
            "CURVE-FIT + FRAGILE: strategy shows high overfitting risk "
            "AND collapses under stress — very likely to fail live."
        )

    # ── Recommendation ────────────────────────────────────────────────────────
    if overrides:
        recommendation = "REJECT"
    elif (confidence_score >= 75
          and accounting_passed is not False
          and (data_integrity_score is None or data_integrity_score >= 80)):
        recommendation = "APPROVE"
    elif confidence_score >= 55 and accounting_passed is not False:
        recommendation = "PROMISING"
    elif confidence_score >= 35:
        recommendation = "NEEDS_WORK"
    else:
        recommendation = "REJECT"

    # ── Strengths and weaknesses ──────────────────────────────────────────────
    strengths  = [d.name for d in dimensions if d.score >= 75]
    weaknesses = [d.name for d in dimensions if d.score < 40]

    summary = _build_summary(
        confidence_score, recommendation, dimensions, overrides,
        strengths, weaknesses, penalty,
    )

    return ConfidenceReport(
        confidence_score = confidence_score,
        recommendation   = recommendation,
        dimensions       = dimensions,
        overrides        = overrides,
        strengths        = strengths,
        weaknesses       = weaknesses,
        summary          = summary,
    )


# ── Dimension helpers ─────────────────────────────────────────────────────────

def _dim_data_integrity(score: float | None) -> EvidenceDimension:
    max_weight = 15.0
    if score is None:
        return EvidenceDimension(
            name="Data Integrity", score=50.0, weight=max_weight,
            contribution=round(0.5 * max_weight, 2),
            detail="Data integrity not assessed — neutral assumption.",
        )
    contribution = round(score / 100.0 * max_weight, 2)
    if score >= 95:
        detail = f"Excellent data quality (score={score:.1f}/100). Backtest foundation is solid."
    elif score >= 80:
        detail = f"Adequate data quality (score={score:.1f}/100). Minor gaps or anomalies present."
    elif score >= 60:
        detail = f"Degraded data quality (score={score:.1f}/100). Results may be affected by data issues."
    else:
        detail = f"Severely degraded data (score={score:.1f}/100). Backtest results are unreliable."
    return EvidenceDimension(
        name="Data Integrity", score=score, weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_accounting(
    passed: bool | None,
    acct_score: float | None,
) -> EvidenceDimension:
    max_weight = 20.0
    if passed is None:
        return EvidenceDimension(
            name="Accounting Verification", score=50.0, weight=max_weight,
            contribution=round(0.5 * max_weight, 2),
            detail="Accounting verification not run — treat results with caution.",
        )
    if not passed:
        return EvidenceDimension(
            name="Accounting Verification", score=0.0, weight=max_weight,
            contribution=0.0,
            detail=(
                "FAILED: P&L accounting does not reconcile. "
                "The strategy result cannot be trusted."
            ),
        )
    eff_score = acct_score if acct_score is not None else 100.0
    contribution = round(eff_score / 100.0 * max_weight, 2)
    if eff_score >= 99:
        detail = "Perfect accounting: all P&L, fees, and equity reconcile to the penny."
    else:
        detail = f"Accounting passed with score {eff_score:.1f}/100."
    return EvidenceDimension(
        name="Accounting Verification", score=eff_score, weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_statistical(
    sharpe: float | None,
    n_trades: int | None,
    pvalue: float | None,
) -> EvidenceDimension:
    max_weight = 15.0
    sub_scores = []

    # Sub-score A: Sharpe ratio quality
    if sharpe is not None:
        if sharpe >= 2.0:
            sub_scores.append(100.0)
        elif sharpe >= 1.5:
            sub_scores.append(85.0)
        elif sharpe >= 1.0:
            sub_scores.append(65.0)
        elif sharpe >= 0.5:
            sub_scores.append(40.0)
        elif sharpe > 0:
            sub_scores.append(20.0)
        else:
            sub_scores.append(0.0)

    # Sub-score B: sample size
    if n_trades is not None:
        if n_trades >= 200:
            sub_scores.append(100.0)
        elif n_trades >= 100:
            sub_scores.append(70.0)
        elif n_trades >= 50:
            sub_scores.append(40.0)
        elif n_trades >= 20:
            sub_scores.append(15.0)
        else:
            sub_scores.append(0.0)

    # Sub-score C: p-value (if available from MC or t-test)
    if pvalue is not None:
        if pvalue <= 0.01:
            sub_scores.append(100.0)
        elif pvalue <= 0.05:
            sub_scores.append(75.0)
        elif pvalue <= 0.10:
            sub_scores.append(45.0)
        else:
            sub_scores.append(10.0)

    if not sub_scores:
        score = 50.0
        detail = "No statistical data available — neutral assumption."
    else:
        score = sum(sub_scores) / len(sub_scores)
        parts = []
        if sharpe is not None:
            parts.append(f"Sharpe={sharpe:.2f}")
        if n_trades is not None:
            parts.append(f"trades={n_trades}")
        if pvalue is not None:
            parts.append(f"p-value={pvalue:.3f}")
        summary_str = ", ".join(parts)
        if score >= 75:
            detail = f"Strong statistical evidence ({summary_str})."
        elif score >= 50:
            detail = f"Moderate statistical evidence ({summary_str}). More trades or higher Sharpe would strengthen the case."
        else:
            detail = f"Weak statistical evidence ({summary_str}). Results may be due to chance."

    contribution = round(score / 100.0 * max_weight, 2)
    return EvidenceDimension(
        name="Statistical Confidence", score=round(score, 1), weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_walk_forward(
    efficiency: float | None,
    wf_score: float | None,
) -> EvidenceDimension:
    max_weight = 15.0

    if efficiency is None and wf_score is None:
        return EvidenceDimension(
            name="Walk-Forward Stability", score=50.0, weight=max_weight,
            contribution=round(0.5 * max_weight, 2),
            detail="Walk-forward analysis not available — neutral assumption.",
        )

    # Prefer wf_score (already on 0-100 scale) if provided
    if wf_score is not None:
        score = wf_score
    else:
        # Convert efficiency to 0-100
        eff = efficiency  # type: ignore[assignment]
        if eff >= 0.8:
            score = 100.0
        elif eff >= 0.6:
            score = 75.0
        elif eff >= 0.4:
            score = 50.0
        elif eff >= 0.0:
            score = 20.0
        else:
            score = 0.0

    contribution = round(score / 100.0 * max_weight, 2)

    if efficiency is not None:
        eff_str = f"WF efficiency={efficiency:.2f}"
    else:
        eff_str = f"WF score={wf_score:.1f}"

    if score >= 75:
        detail = f"Strong walk-forward stability ({eff_str}). OOS tracks IS performance well."
    elif score >= 50:
        detail = f"Moderate walk-forward stability ({eff_str}). Some IS→OOS degradation."
    else:
        detail = f"Poor walk-forward stability ({eff_str}). Strong IS→OOS degradation — likely overfitting."

    return EvidenceDimension(
        name="Walk-Forward Stability", score=round(score, 1), weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_monte_carlo(
    mc_score: float | None,
    ci_width: float | None,
    sharpe: float | None,
) -> EvidenceDimension:
    max_weight = 10.0

    if mc_score is not None:
        score = mc_score
    elif ci_width is not None and sharpe is not None and sharpe > 0:
        relative = ci_width / sharpe
        if relative <= 0.5:
            score = 100.0
        elif relative <= 1.0:
            score = 75.0
        elif relative <= 2.0:
            score = 45.0
        else:
            score = 15.0
    elif ci_width is not None:
        # No Sharpe to normalise against — use absolute CI width
        if ci_width <= 0.5:
            score = 80.0
        elif ci_width <= 1.5:
            score = 50.0
        else:
            score = 20.0
    else:
        score = 50.0

    contribution = round(score / 100.0 * max_weight, 2)

    if score >= 75:
        detail = "Monte Carlo simulation shows narrow outcome spread — performance is driven by strategy edge, not trade ordering."
    elif score >= 45:
        detail = "Monte Carlo shows moderate spread — some trade-order sensitivity, but edge is broadly present."
    elif score == 50.0 and mc_score is None and ci_width is None:
        detail = "Monte Carlo not available — neutral assumption."
    else:
        detail = "Wide Monte Carlo spread — performance is highly sensitive to trade order. May be luck-driven."

    return EvidenceDimension(
        name="Monte Carlo Robustness", score=round(score, 1), weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_stress(
    stress_score: float | None,
    risk_level: str | None,
) -> EvidenceDimension:
    max_weight = 15.0

    if stress_score is not None:
        score = stress_score
    elif risk_level is not None:
        mapping = {"LOW": 85.0, "MEDIUM": 55.0, "HIGH": 20.0}
        score = mapping.get(risk_level.upper(), 50.0)
    else:
        score = 50.0

    contribution = round(score / 100.0 * max_weight, 2)

    if score >= 70:
        detail = f"Strong stress resilience (score={score:.1f}/100). Strategy survives realistic cost increases."
    elif score >= 40:
        detail = f"Moderate stress resilience (score={score:.1f}/100). Some scenarios cause significant degradation."
    elif score == 50.0 and stress_score is None and risk_level is None:
        detail = "Stress testing not available — neutral assumption."
    else:
        detail = f"Poor stress resilience (score={score:.1f}/100). Strategy collapses under realistic cost scenarios."

    return EvidenceDimension(
        name="Stress Test Resilience", score=round(score, 1), weight=max_weight,
        contribution=contribution, detail=detail,
    )


def _dim_parameter_stability(
    robustness: float | None,
    stability: float | None,
) -> EvidenceDimension:
    max_weight = 5.0

    scores = []
    if robustness is not None:
        scores.append(robustness)
    if stability is not None:
        scores.append(stability)

    if not scores:
        score = 50.0
        detail = "Parameter stability not assessed — neutral assumption."
    else:
        score = sum(scores) / len(scores)
        parts = []
        if robustness is not None:
            parts.append(f"robustness={robustness:.1f}%")
        if stability is not None:
            parts.append(f"stability={stability:.1f}")
        summary_str = ", ".join(parts)
        if score >= 70:
            detail = f"Good parameter stability ({summary_str}). Performance persists across nearby parameters."
        elif score >= 40:
            detail = f"Moderate parameter stability ({summary_str}). Performance sensitive to exact parameter values."
        else:
            detail = f"Poor parameter stability ({summary_str}). Strategy sits on a sharp peak — classic overfitting signature."

    contribution = round(score / 100.0 * max_weight, 2)
    return EvidenceDimension(
        name="Parameter Stability", score=round(score, 1), weight=max_weight,
        contribution=contribution, detail=detail,
    )


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_summary(
    score: float,
    recommendation: str,
    dimensions: list[EvidenceDimension],
    overrides: list[str],
    strengths: list[str],
    weaknesses: list[str],
    penalty: float,
) -> str:
    rec_labels = {
        "APPROVE"    : "APPROVED",
        "PROMISING"  : "PROMISING",
        "NEEDS_WORK" : "NEEDS IMPROVEMENT",
        "REJECT"     : "REJECTED",
    }
    label = rec_labels.get(recommendation, recommendation)

    intro = f"Confidence score: {score:.0f}/100 — strategy is {label}."

    if overrides:
        intro += "  CRITICAL: " + "  ".join(overrides)
        return intro

    if penalty > 0:
        intro += f"  (Overfitting penalty applied: -{penalty:.1f} pts)"

    if strengths:
        intro += f"  Strengths: {', '.join(strengths)}."
    if weaknesses:
        intro += f"  Weaknesses requiring attention: {', '.join(weaknesses)}."

    if recommendation == "APPROVE":
        intro += (
            "  Multiple independent evidence streams converge on a genuine edge. "
            "Strategy is cleared for further consideration."
        )
    elif recommendation == "PROMISING":
        intro += (
            "  The strategy shows real potential but has gaps in the evidence chain. "
            "Address weak dimensions before allocating real capital."
        )
    elif recommendation == "NEEDS_WORK":
        intro += (
            "  Significant evidence gaps prevent approval. "
            "Expand testing, improve data quality, or redesign the strategy."
        )
    else:
        intro += (
            "  Evidence does not support approving this strategy. "
            "Revise and re-submit after addressing critical weaknesses."
        )

    return intro
