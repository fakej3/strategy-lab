"""Stress testing — measure strategy resilience under adverse conditions.

Every approved strategy is subjected to a battery of realistic stress scenarios:

1. **Fee stress**    — 2× and 3× the baseline fee.
2. **Slippage stress** — 2× and 5× the baseline slippage.
3. **Combined stress** — high fee AND high slippage simultaneously.
4. **Trade skip**    — randomly skip 10% of trades.
5. **Worse fills**   — entry fill 0.1% worse (simulates market impact).

For each scenario, the strategy is re-evaluated and the degradation is
measured against the baseline.  Strategies that collapse under realistic
conditions are rejected by the confidence engine.

Public API
----------
- ``StressScenario``   — configuration for one stress test.
- ``StressResult``     — result for one scenario.
- ``StressTestReport`` — aggregated multi-scenario result.
- ``run_stress_tests`` — run all scenarios and return the report.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Sequence, Type

import pandas as pd

from engine.models import EngineConfig
from engine.strategy import StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from research.metrics import calculate_research_metrics


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StressScenario:
    """Configuration for a single stress scenario."""
    name          : str
    fee_multiplier    : float = 1.0
    slippage_multiplier: float = 1.0
    skip_pct      : float = 0.0   # fraction of trades to skip (0-1)
    fill_penalty  : float = 0.0   # additional % added to entry slippage


@dataclass
class StressResult:
    """Result of running a single stress scenario."""
    scenario         : str
    baseline_sharpe  : float
    stressed_sharpe  : float
    baseline_net_pnl : float
    stressed_net_pnl : float
    baseline_max_dd  : float
    stressed_max_dd  : float
    n_trades         : int
    sharpe_degradation_pct  : float   # (stressed - baseline) / |baseline| * 100
    pnl_degradation_pct     : float
    survived         : bool    # True if stressed Sharpe > 0 and net_pnl > 0
    notes            : str = ""

    def to_dict(self) -> dict:
        return {
            "scenario"             : self.scenario,
            "baseline_sharpe"      : self.baseline_sharpe,
            "stressed_sharpe"      : self.stressed_sharpe,
            "baseline_net_pnl"     : self.baseline_net_pnl,
            "stressed_net_pnl"     : self.stressed_net_pnl,
            "baseline_max_dd"      : self.baseline_max_dd,
            "stressed_max_dd"      : self.stressed_max_dd,
            "n_trades"             : self.n_trades,
            "sharpe_degradation_pct": self.sharpe_degradation_pct,
            "pnl_degradation_pct"  : self.pnl_degradation_pct,
            "survived"             : self.survived,
            "notes"                : self.notes,
        }


@dataclass
class StressTestReport:
    """Aggregated result of all stress scenarios.

    Attributes
    ----------
    stress_score : float
        Resilience score in [0, 100].  100 = survived all scenarios perfectly.
        Lower scores indicate the strategy collapses under real conditions.
    risk_level : str
        ``"LOW"`` (score ≥ 70), ``"MEDIUM"`` (40-70), ``"HIGH"`` (< 40).
    scenarios : list[StressResult]
        Per-scenario results.
    n_survived : int
        Number of scenarios in which the strategy remained profitable.
    summary : str
        Human-readable summary.
    """
    stress_score : float
    risk_level   : str
    scenarios    : list[StressResult]
    n_survived   : int
    summary      : str

    def to_dict(self) -> dict:
        return {
            "stress_score": self.stress_score,
            "risk_level"  : self.risk_level,
            "n_survived"  : self.n_survived,
            "n_scenarios" : len(self.scenarios),
            "scenarios"   : [s.to_dict() for s in self.scenarios],
            "summary"     : self.summary,
        }


# ── Default scenario suite ────────────────────────────────────────────────────

_DEFAULT_SCENARIOS: list[StressScenario] = [
    StressScenario("2x Fee",                fee_multiplier=2.0),
    StressScenario("3x Fee",                fee_multiplier=3.0),
    StressScenario("2x Slippage",           slippage_multiplier=2.0),
    StressScenario("5x Slippage",           slippage_multiplier=5.0),
    StressScenario("2x Fee + 2x Slippage",  fee_multiplier=2.0, slippage_multiplier=2.0),
    StressScenario("10% Skipped Trades",    skip_pct=0.10),
    StressScenario("Worse Entry Fills",     fill_penalty=0.001),
]


# ── Main function ─────────────────────────────────────────────────────────────

def run_stress_tests(
    bars             : pd.DataFrame,
    strategy_class   : Type[StrategyBase],
    params           : dict,
    baseline_fee     : float,
    baseline_slippage: float,
    starting_capital : float = 100_000.0,
    bars_per_year    : int   = 8760,
    stop_loss_pct    : float | None = None,
    take_profit_pct  : float | None = None,
    scenarios        : list[StressScenario] | None = None,
    seed             : int = 42,
) -> StressTestReport:
    """Run all stress scenarios and return an aggregated report.

    Args:
        bars:             OHLCV DataFrame for the backtest.
        strategy_class:   Strategy class to instantiate.
        params:           Strategy parameters.
        baseline_fee:     The fee rate used in the original backtest.
        baseline_slippage: The slippage % used in the original backtest.
        starting_capital: Starting capital for each scenario.
        bars_per_year:    Annualisation factor.
        stop_loss_pct:    Optional stop-loss fraction.
        take_profit_pct:  Optional take-profit fraction.
        scenarios:        Override the default scenario list.
        seed:             RNG seed for reproducible trade-skipping.

    Returns:
        :class:`StressTestReport`.
    """
    scenario_list = scenarios if scenarios is not None else _DEFAULT_SCENARIOS

    # ── Baseline run ──────────────────────────────────────────────────────────
    baseline = _run_scenario(
        bars, strategy_class, params,
        fee=baseline_fee,
        slippage=baseline_slippage,
        starting_capital=starting_capital,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        bars_per_year=bars_per_year,
    )
    if baseline is None:
        return StressTestReport(
            stress_score=0.0,
            risk_level="HIGH",
            scenarios=[],
            n_survived=0,
            summary=(
                "Stress test could not run: baseline backtest failed or "
                "produced no trades."
            ),
        )

    baseline_sharpe  = baseline["sharpe"]
    baseline_net_pnl = baseline["net_pnl"]
    baseline_max_dd  = baseline["max_dd"]

    results: list[StressResult] = []

    for sc in scenario_list:
        stressed = _run_scenario_with_skip(
            bars, strategy_class, params,
            fee         = baseline_fee  * sc.fee_multiplier,
            slippage    = baseline_slippage * sc.slippage_multiplier + sc.fill_penalty,
            starting_capital=starting_capital,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            bars_per_year=bars_per_year,
            skip_pct    = sc.skip_pct,
            seed        = seed,
        )
        if stressed is None:
            results.append(StressResult(
                scenario        = sc.name,
                baseline_sharpe = baseline_sharpe,
                stressed_sharpe = float("nan"),
                baseline_net_pnl= baseline_net_pnl,
                stressed_net_pnl= float("nan"),
                baseline_max_dd = baseline_max_dd,
                stressed_max_dd = float("nan"),
                n_trades        = 0,
                sharpe_degradation_pct=float("nan"),
                pnl_degradation_pct   =float("nan"),
                survived=False,
                notes="Stressed backtest failed or produced no trades.",
            ))
            continue

        s_sharpe  = stressed["sharpe"]
        s_pnl     = stressed["net_pnl"]
        s_dd      = stressed["max_dd"]
        n_trades  = stressed["n_trades"]

        if abs(baseline_sharpe) > 1e-9:
            sharpe_deg = (s_sharpe - baseline_sharpe) / abs(baseline_sharpe) * 100
        else:
            sharpe_deg = 0.0 if abs(s_sharpe) < 1e-9 else -100.0

        if abs(baseline_net_pnl) > 1e-9:
            pnl_deg = (s_pnl - baseline_net_pnl) / abs(baseline_net_pnl) * 100
        else:
            pnl_deg = 0.0 if abs(s_pnl) < 1e-9 else -100.0

        survived = s_sharpe > 0 and s_pnl > 0

        notes = ""
        if sharpe_deg < -50:
            notes = f"Sharpe dropped {abs(sharpe_deg):.0f}% under {sc.name}."

        results.append(StressResult(
            scenario        = sc.name,
            baseline_sharpe = baseline_sharpe,
            stressed_sharpe = s_sharpe,
            baseline_net_pnl= baseline_net_pnl,
            stressed_net_pnl= s_pnl,
            baseline_max_dd = baseline_max_dd,
            stressed_max_dd = s_dd,
            n_trades        = n_trades,
            sharpe_degradation_pct = round(sharpe_deg, 1),
            pnl_degradation_pct    = round(pnl_deg, 1),
            survived        = survived,
            notes           = notes,
        ))

    # ── Aggregate score ───────────────────────────────────────────────────────
    n_survived = sum(1 for r in results if r.survived)
    n_total    = len(results)

    # Base survival rate
    survival_rate = n_survived / n_total if n_total > 0 else 0.0

    # Weighted by how mild the scenario is — mild stress should definitely survive
    mild_scenarios = {"2x Fee", "2x Slippage"}
    for r in results:
        if r.scenario in mild_scenarios and not r.survived:
            survival_rate = max(0.0, survival_rate - 0.15)

    # Average Sharpe retention across surviving scenarios
    sharpe_retentions = []
    for r in results:
        if not math.isnan(r.sharpe_degradation_pct):
            # Convert degradation % to retention ratio (100% deg = 0 retention)
            retention = max(0.0, 1.0 + r.sharpe_degradation_pct / 100.0)
            sharpe_retentions.append(min(1.0, retention))

    avg_retention = (sum(sharpe_retentions) / len(sharpe_retentions)
                     if sharpe_retentions else 0.0)

    stress_score = (survival_rate * 50 + avg_retention * 50)
    stress_score = round(max(0.0, min(100.0, stress_score)), 1)

    if stress_score >= 70:
        risk_level = "LOW"
    elif stress_score >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    summary = _build_summary(stress_score, risk_level, n_survived, n_total, results)

    return StressTestReport(
        stress_score = stress_score,
        risk_level   = risk_level,
        scenarios    = results,
        n_survived   = n_survived,
        summary      = summary,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_scenario(
    bars, strategy_class, params,
    fee, slippage, starting_capital, stop_loss_pct, take_profit_pct, bars_per_year,
) -> dict | None:
    try:
        strategy   = strategy_class(**params)
        engine_cfg = EngineConfig(
            position_size    = 1.0,
            fee_rate         = fee,
            slippage_pct     = slippage,
            stop_loss_pct    = stop_loss_pct,
            take_profit_pct  = take_profit_pct,
        )
        port_cfg = PortfolioConfig(
            starting_capital = starting_capital,
            sizing_mode      = SizingMode.FIXED_UNITS,
            position_size    = 1.0,
        )
        result = PortfolioEngine(port_cfg).run(bars, strategy, engine_config=engine_cfg)
        if not result.trades:
            return None
        metrics = calculate_research_metrics(
            result.equity_curve, result.trades, bars_per_year=bars_per_year
        )
        net_pnl  = float(result.equity_curve.iloc[-1]) - starting_capital
        max_dd   = metrics.max_drawdown_pct
        return {
            "sharpe"  : metrics.sharpe_ratio,
            "net_pnl" : net_pnl,
            "max_dd"  : max_dd,
            "n_trades": len(result.trades),
        }
    except Exception:
        return None


def _run_scenario_with_skip(
    bars, strategy_class, params,
    fee, slippage, starting_capital, stop_loss_pct, take_profit_pct,
    bars_per_year, skip_pct=0.0, seed=42,
) -> dict | None:
    if skip_pct <= 0.0:
        return _run_scenario(
            bars, strategy_class, params,
            fee=fee, slippage=slippage,
            starting_capital=starting_capital,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            bars_per_year=bars_per_year,
        )

    # Trade-skip: generate signals, null a random fraction of BUYs, then run
    # using a pre-computed signal wrapper strategy.
    try:
        from engine.strategy import Signal, StrategyBase as _StrategyBase

        strategy_instance = strategy_class(**params)
        signals = strategy_instance.generate_signals(bars)

        rng     = random.Random(seed)
        buy_idx = [i for i, s in enumerate(signals) if s == Signal.BUY]
        to_skip = set(rng.sample(buy_idx, k=int(len(buy_idx) * skip_pct)))

        modified = signals.copy()
        for idx in to_skip:
            modified.iloc[idx] = Signal.HOLD

        # Wrap the pre-computed signals in a strategy object the engine accepts
        _precomputed = modified

        class _PrecomputedStrategy(_StrategyBase):
            def generate_signals(self, b):
                return _precomputed

        engine_cfg = EngineConfig(
            position_size    = 1.0,
            fee_rate         = fee,
            slippage_pct     = slippage,
            stop_loss_pct    = stop_loss_pct,
            take_profit_pct  = take_profit_pct,
        )
        port_cfg = PortfolioConfig(
            starting_capital = starting_capital,
            sizing_mode      = SizingMode.FIXED_UNITS,
            position_size    = 1.0,
        )
        result = PortfolioEngine(port_cfg).run(bars, _PrecomputedStrategy(),
                                               engine_config=engine_cfg)
        if not result.trades:
            return None
        metrics = calculate_research_metrics(
            result.equity_curve, result.trades, bars_per_year=bars_per_year
        )
        net_pnl = float(result.equity_curve.iloc[-1]) - starting_capital
        return {
            "sharpe"  : metrics.sharpe_ratio,
            "net_pnl" : net_pnl,
            "max_dd"  : metrics.max_drawdown_pct,
            "n_trades": len(result.trades),
        }
    except Exception:
        return _run_scenario(
            bars, strategy_class, params,
            fee=fee, slippage=slippage,
            starting_capital=starting_capital,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            bars_per_year=bars_per_year,
        )


def _build_summary(
    score: float, risk_level: str,
    n_survived: int, n_total: int,
    results: list[StressResult],
) -> str:
    failed = [r for r in results if not r.survived]
    failed_names = [r.scenario for r in failed]

    if risk_level == "LOW":
        intro = (
            f"Stress resilience is HIGH (score={score:.0f}/100).  "
            f"Strategy survived {n_survived}/{n_total} stress scenarios "
            "with positive Sharpe and net profit."
        )
    elif risk_level == "MEDIUM":
        intro = (
            f"Stress resilience is MODERATE (score={score:.0f}/100).  "
            f"Strategy survived {n_survived}/{n_total} stress scenarios.  "
            "Some scenarios caused significant performance degradation."
        )
    else:
        intro = (
            f"Stress resilience is POOR (score={score:.0f}/100).  "
            f"Strategy survived only {n_survived}/{n_total} stress scenarios.  "
            "This strategy is fragile and likely relies on unrealistically "
            "favourable execution conditions."
        )

    if failed_names:
        intro += f"  Failed scenarios: {', '.join(failed_names)}."

    return intro
