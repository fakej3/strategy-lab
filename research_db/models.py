"""Data models mirroring the SQLite schema rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research.provenance import is_publishable


@dataclass
class SessionRecord:
    session_id: str
    started_at: str
    status: str          # 'running' | 'complete' | 'failed'
    symbols: str         # JSON list
    intervals: str       # JSON list
    start_date: str
    end_date: str
    finished_at: str | None       = None
    n_strategies_run: int         = 0
    n_passed: int                 = 0
    n_rejected: int               = 0
    n_errors: int                 = 0
    elapsed_secs: float | None    = None


@dataclass
class StrategyResult:
    session_id: str
    strategy_class: str
    strategy_name: str
    params: str          # JSON dict
    symbol: str
    interval: str
    start_date: str
    end_date: str
    gate_decision: str   # PROMISING | NEEDS IMPROVEMENT | REJECT
    gate_score: float | None      = None
    total_trades: int             = 0
    net_profit: float             = 0.0
    total_return: float           = 0.0
    max_drawdown_pct: float       = 0.0
    sharpe_ratio: float           = 0.0
    sortino_ratio: float          = 0.0
    calmar_ratio: float           = 0.0
    cagr: float                   = 0.0
    win_rate: float               = 0.0
    profit_factor: float          = 0.0
    avg_trade_pnl: float          = 0.0
    walk_forward_return: float | None = None
    mc_median_return: float | None    = None
    mc_pct5_return: float | None      = None
    mc_pct95_return: float | None     = None
    mc_prob_positive: float | None    = None
    equity_curve_json: str | None     = None  # sampled as JSON array
    created_at: str                   = ""
    id: int | None                    = None
    # Phase 7 — statistical analysis
    degradation_score: float | None   = None
    robustness_score: float | None    = None
    stability_score: float | None     = None
    wf_n_folds: int | None            = None
    wf_efficiency: float | None       = None
    wf_consistency: float | None      = None
    regime_json: str | None           = None
    rolling_json: str | None          = None
    degradation_json: str | None      = None
    distribution_json: str | None     = None
    bootstrap_json: str | None        = None
    robustness_json: str | None       = None
    # Phase 9 — hardening signals
    data_integrity_score: float | None    = None
    data_integrity_json: str | None       = None
    overfitting_score: float | None       = None
    overfitting_risk_level: str | None    = None
    overfitting_json: str | None          = None
    stress_score: float | None            = None
    stress_risk_level: str | None         = None
    stress_json: str | None               = None
    confidence_score: float | None        = None
    confidence_recommendation: str | None = None
    confidence_json: str | None           = None
    diagnostic_provenance_json: str | None = None

    @property
    def publishable(self) -> bool:
        return is_publishable(self.gate_decision, self.diagnostic_provenance_json)


@dataclass
class MonitoringEvent:
    """One instrumentation record — stage timing, memory, download metrics, etc."""

    stage      : str
    event_type : str
    created_at : str
    session_id : str | None   = None
    value_float: float | None = None
    value_text : str | None   = None
    id         : int | None   = None


@dataclass
class JobRecord:
    job_id: str
    job_type: str        # 'backtest' | 'optimization' | 'walkforward' | 'montecarlo'
    params: str          # JSON
    created_at: str
    session_id: str | None     = None
    status: str                = "pending"
    result_json: str | None    = None
    error: str | None          = None
    started_at: str | None     = None
    finished_at: str | None    = None
    retry_count: int           = 0
    id: int | None             = None
