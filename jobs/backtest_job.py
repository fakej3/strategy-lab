"""Single-strategy backtest job — runs the full pipeline for one parameter set."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Type

import pandas as pd

from engine.models import EngineConfig
from engine.strategy import StrategyBase
from pipeline.gate import evaluate_gate
from pipeline.metrics import calculate_metrics as gate_metrics
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig
from research.metrics import calculate_research_metrics

from .base import BaseJob

# Bars-per-year table (mirrors run.py)
BARS_PER_YEAR: dict[str, int] = {
    "1m": 525_600, "3m": 175_200, "5m": 105_120,
    "15m": 35_040, "30m": 17_520, "1h": 8_760,
    "2h": 4_380,   "4h": 2_190,   "6h": 1_460,
    "8h": 1_095,   "12h": 730,    "1d": 365,
    "3d": 121,     "1w": 52,
}


@dataclass
class BacktestParams:
    bars: pd.DataFrame
    strategy_class: Type[StrategyBase]
    params: dict[str, Any]
    symbol: str
    interval: str
    start_date: date
    end_date: date
    starting_capital: float     = 100_000.0
    fee_rate: float             = 0.001
    slippage_pct: float         = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class BacktestJob(BaseJob):
    """Run backtest → metrics → quality gate for one strategy+param combination."""

    def __init__(self, p: BacktestParams) -> None:
        self.p = p

    def execute(self) -> dict[str, Any]:
        p = self.p
        bpy = BARS_PER_YEAR.get(p.interval, 252)

        strategy = p.strategy_class(**p.params)

        eng_cfg = EngineConfig(
            fee_rate        = p.fee_rate,
            slippage_pct    = p.slippage_pct,
            stop_loss_pct   = p.stop_loss_pct,
            take_profit_pct = p.take_profit_pct,
        )
        port_cfg = PortfolioConfig(starting_capital=p.starting_capital)
        result   = PortfolioEngine(port_cfg).run(p.bars, strategy, eng_cfg)

        accounting = _verify_accounting(result)

        metrics = calculate_research_metrics(
            equity_curve  = result.equity_curve,
            trades        = result.trades,
            bars_per_year = bpy,
        )

        gate_decision = "REJECT"
        gate_score    = 0.0
        if result.trades:
            gm   = gate_metrics(result.trades, "$")
            gate = evaluate_gate(gm)
            gate_decision = gate.decision.value
            gate_score    = gate.overall_score

        eq_series = result.equity_curve
        if len(eq_series) > 300:
            step     = len(eq_series) // 300
            eq_series = eq_series.iloc[::step]
        eq = [{"equity": round(float(v), 2)} for v in eq_series]

        trade_pnls = [t.net_pnl for t in result.trades]

        regime_json      = None
        rolling_json     = None
        degradation_json = None
        distribution_json = None
        bootstrap_json   = None
        degradation_score = None

        if result.trades:
            try:
                from research.regime import analyze_per_regime
                regime_data = analyze_per_regime(bars=p.bars, trades=result.trades, equity_curve=result.equity_curve)
                regime_json = json.dumps(regime_data)
            except Exception:
                pass

            try:
                from research.rolling import compute_rolling_metrics
                rolling_data = compute_rolling_metrics(equity_curve=result.equity_curve, trades=result.trades, bars_per_year=bpy)
                rolling_json = json.dumps(rolling_data)
            except Exception:
                pass

            try:
                from research.degradation import analyze_degradation
                deg_data = analyze_degradation(trades=result.trades)
                degradation_score = deg_data.get("degradation_score")
                degradation_json  = json.dumps(deg_data)
            except Exception:
                pass

            try:
                from research.distribution import analyze_distribution
                dist_data = analyze_distribution(pnls=trade_pnls, equity_curve=result.equity_curve)
                distribution_json = json.dumps(dist_data)
            except Exception:
                pass

            try:
                from research.bootstrap import bootstrap_confidence_intervals
                bs_data = bootstrap_confidence_intervals(pnls=trade_pnls, starting_capital=p.starting_capital, n_simulations=200)
                bootstrap_json = json.dumps(bs_data)
            except Exception:
                pass

        return {
            "strategy_name"   : p.strategy_class.__name__,
            "strategy_class"  : p.strategy_class.__name__,
            "params"          : json.dumps(p.params),
            "symbol"          : p.symbol,
            "interval"        : p.interval,
            "start_date"      : str(p.start_date),
            "end_date"        : str(p.end_date),
            "gate_decision"   : gate_decision,
            "gate_score"      : gate_score,
            "total_trades"    : len(result.trades),
            "trade_pnls"      : trade_pnls,
            "net_profit"      : result.net_profit,
            "total_return"    : result.total_return,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio"    : _safe(metrics.sharpe_ratio),
            "sortino_ratio"   : _safe(metrics.sortino_ratio),
            "calmar_ratio"    : _safe(metrics.calmar_ratio),
            "cagr"            : _safe(metrics.cagr),
            "win_rate"        : metrics.win_rate,
            "profit_factor"   : _safe(metrics.profit_factor),
            "avg_trade_pnl"    : metrics.avg_trade_pnl,
            "equity_curve_json": json.dumps(eq),
            "starting_capital" : p.starting_capital,
            "accounting_passed": accounting["passed"],
            "accounting_json"  : json.dumps(accounting),
            "regime_json"      : regime_json,
            "rolling_json"     : rolling_json,
            "degradation_json" : degradation_json,
            "distribution_json": distribution_json,
            "bootstrap_json"   : bootstrap_json,
            "degradation_score": degradation_score,
        }


def _verify_accounting(result: Any, tolerance: float = 1e-8) -> dict[str, Any]:
    """Verify that reported profit, trade PnL and equity agree.

    This is evidence used by the research provenance boundary; it is deliberately
    independent of the quality gate so a passing gate can never imply accounting.
    """
    starting = float(result.starting_capital)
    ending = float(result.ending_equity)
    reported_profit = float(result.net_profit)
    trade_profit = sum(float(t.net_pnl) for t in result.trades)
    curve_end = ending
    if len(result.equity_curve):
        curve_end = float(result.equity_curve.iloc[-1])

    checks = {
        "ending_equity_matches_curve": math.isclose(ending, curve_end, rel_tol=tolerance, abs_tol=tolerance),
        "reported_profit_matches_equity": math.isclose(reported_profit, ending - starting, rel_tol=tolerance, abs_tol=tolerance),
        "trade_pnl_matches_profit": math.isclose(trade_profit, reported_profit, rel_tol=tolerance, abs_tol=tolerance),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "starting_capital": starting,
        "ending_equity": ending,
        "reported_net_profit": reported_profit,
        "sum_trade_net_pnl": trade_profit,
        "equity_curve_end": curve_end,
    }


def _safe(v: float) -> float:
    """Map NaN/Inf to 0.0 so NOT NULL columns in the DB always receive a number."""
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return v
