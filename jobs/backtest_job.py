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
    bars: pd.DataFrame          # pre-loaded OHLCV; shared across jobs in same process
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

        # Institutional metrics
        metrics = calculate_research_metrics(
            equity_curve  = result.equity_curve,
            trades        = result.trades,
            bars_per_year = bpy,
        )

        # Quality gate
        gate_decision = "REJECT"
        gate_score    = 0.0
        if result.trades:
            gm   = gate_metrics(result.trades, "$")
            gate = evaluate_gate(gm)
            gate_decision = gate.decision.value
            gate_score    = gate.overall_score

        # Sample equity curve for storage (≤ 300 points)
        eq = result.equity_curve.tolist()
        if len(eq) > 300:
            step = len(eq) // 300
            eq   = eq[::step]

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
            "net_profit"      : result.net_profit,
            "total_return"    : result.total_return,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio"    : _safe(metrics.sharpe_ratio),
            "sortino_ratio"   : _safe(metrics.sortino_ratio),
            "calmar_ratio"    : _safe(metrics.calmar_ratio),
            "cagr"            : _safe(metrics.cagr),
            "win_rate"        : metrics.win_rate,
            "profit_factor"   : _safe(metrics.profit_factor),
            "avg_trade_pnl"   : metrics.avg_trade_pnl,
            "equity_curve_json": json.dumps(eq),
            "starting_capital": p.starting_capital,
        }


def _safe(v: float) -> float:
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return v
