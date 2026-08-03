"""High-level storage API — all DB interactions go through here."""
from __future__ import annotations

import math
from pathlib import Path

from .database import Database
from .models import JobRecord, MonitoringEvent, SessionRecord, StrategyResult


def _safe(v):
    """Replace nan/inf with None for SQLite storage."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


class ResearchStorage:
    """CRUD interface to the research SQLite database."""

    def __init__(self, db_path: str | Path = "research.db") -> None:
        self.db = Database(db_path)
        self.db.connect()

    # ── Sessions ──────────────────────────────────────────────────────────────

    def save_session(self, s: SessionRecord) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, started_at, finished_at, status, symbols, intervals,
                start_date, end_date, n_strategies_run, n_passed, n_rejected,
                n_errors, elapsed_secs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s.session_id, s.started_at, s.finished_at, s.status,
             s.symbols, s.intervals, s.start_date, s.end_date,
             s.n_strategies_run, s.n_passed, s.n_rejected, s.n_errors,
             _safe(s.elapsed_secs)),
        )
        self.db.commit()

    def update_session(self, session_id: str, **fields) -> None:
        if not fields:
            return
        parts = ", ".join(f"{k}=?" for k in fields)
        vals  = tuple(_safe(v) for v in fields.values()) + (session_id,)
        self.db.execute(f"UPDATE sessions SET {parts} WHERE session_id=?", vals)
        self.db.commit()

    def get_session(self, session_id: str) -> SessionRecord | None:
        row = self.db.fetchone(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        )
        return _row_to_session(row) if row else None

    def get_sessions(self, limit: int = 50) -> list[SessionRecord]:
        rows = self.db.fetchall(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_session(r) for r in rows]

    # ── Strategy results ─────────────────────────────────────────────────────

    def save_strategy_result(self, r: StrategyResult) -> int:
        cur = self.db.execute(
            """INSERT INTO strategy_results
               (session_id, strategy_class, strategy_name, params, symbol,
                interval, start_date, end_date, gate_decision, gate_score,
                total_trades, net_profit, total_return, max_drawdown_pct,
                sharpe_ratio, sortino_ratio, calmar_ratio, cagr, win_rate,
                profit_factor, avg_trade_pnl, walk_forward_return,
                mc_median_return, mc_pct5_return, mc_pct95_return,
                mc_prob_positive, equity_curve_json, created_at,
                degradation_score, robustness_score, stability_score,
                wf_n_folds, wf_efficiency, wf_consistency,
                regime_json, rolling_json, degradation_json,
                distribution_json, bootstrap_json, robustness_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                       ?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r.session_id, r.strategy_class, r.strategy_name, r.params,
             r.symbol, r.interval, r.start_date, r.end_date,
             r.gate_decision, _safe(r.gate_score),
             r.total_trades, _safe(r.net_profit), _safe(r.total_return),
             _safe(r.max_drawdown_pct), _safe(r.sharpe_ratio),
             _safe(r.sortino_ratio), _safe(r.calmar_ratio),
             _safe(r.cagr), _safe(r.win_rate), _safe(r.profit_factor),
             _safe(r.avg_trade_pnl), _safe(r.walk_forward_return),
             _safe(r.mc_median_return), _safe(r.mc_pct5_return),
             _safe(r.mc_pct95_return), _safe(r.mc_prob_positive),
             r.equity_curve_json, r.created_at,
             _safe(r.degradation_score), _safe(r.robustness_score),
             _safe(r.stability_score), r.wf_n_folds,
             _safe(r.wf_efficiency), _safe(r.wf_consistency),
             r.regime_json, r.rolling_json, r.degradation_json,
             r.distribution_json, r.bootstrap_json, r.robustness_json),
        )
        self.db.commit()
        return cur.lastrowid

    def get_strategy_results(
        self,
        session_id: str | None = None,
        decision: str | None   = None,
        limit: int             = 200,
    ) -> list[StrategyResult]:
        where, params = [], []
        if session_id:
            where.append("session_id=?")
            params.append(session_id)
        if decision:
            where.append("gate_decision=?")
            params.append(decision)
        clause = "WHERE " + " AND ".join(where) if where else ""
        params.append(limit)
        rows = self.db.fetchall(
            f"SELECT * FROM strategy_results {clause} "
            f"ORDER BY sharpe_ratio DESC LIMIT ?",
            tuple(params),
        )
        return [_row_to_result(r) for r in rows]

    def get_best_by(
        self,
        metric: str = "sharpe_ratio",
        limit: int  = 10,
        min_trades: int = 5,
    ) -> list[StrategyResult]:
        safe_metrics = {
            "sharpe_ratio", "calmar_ratio", "sortino_ratio", "cagr",
            "total_return", "net_profit", "win_rate", "profit_factor",
            "max_drawdown_pct",
        }
        if metric not in safe_metrics:
            metric = "sharpe_ratio"
        asc = "ASC" if metric == "max_drawdown_pct" else "DESC"
        rows = self.db.fetchall(
            f"SELECT * FROM strategy_results "
            f"WHERE total_trades >= ? AND gate_decision != 'REJECT' "
            f"ORDER BY {metric} {asc} LIMIT ?",
            (min_trades, limit),
        )
        return [_row_to_result(r) for r in rows]

    def get_stats(self) -> dict:
        row = self.db.fetchone(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN gate_decision='PROMISING' THEN 1 ELSE 0 END) promising,
                      SUM(CASE WHEN gate_decision='NEEDS IMPROVEMENT' THEN 1 ELSE 0 END) needs_imp,
                      SUM(CASE WHEN gate_decision='REJECT' THEN 1 ELSE 0 END) rejected,
                      AVG(sharpe_ratio) avg_sharpe,
                      MAX(sharpe_ratio) best_sharpe,
                      MIN(max_drawdown_pct) best_dd
               FROM strategy_results"""
        )
        if not row:
            return {}
        return dict(row)

    # ── Jobs ─────────────────────────────────────────────────────────────────

    def save_job(self, j: JobRecord) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO jobs
               (job_id, session_id, job_type, status, params, result_json,
                error, created_at, started_at, finished_at, retry_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (j.job_id, j.session_id, j.job_type, j.status, j.params,
             j.result_json, j.error, j.created_at,
             j.started_at, j.finished_at, j.retry_count),
        )
        self.db.commit()

    def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        parts = ", ".join(f"{k}=?" for k in fields)
        vals  = tuple(fields.values()) + (job_id,)
        self.db.execute(f"UPDATE jobs SET {parts} WHERE job_id=?", vals)
        self.db.commit()

    def get_jobs(
        self,
        status: str | None = None,
        limit: int         = 100,
    ) -> list[JobRecord]:
        if status:
            rows = self.db.fetchall(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [_row_to_job(r) for r in rows]

    # ── Monitoring events ─────────────────────────────────────────────────────

    def log_event(
        self,
        stage: str,
        event_type: str,
        session_id: str | None  = None,
        value_float: float | None = None,
        value_text: str | None  = None,
    ) -> None:
        """Record one instrumentation event (non-blocking, never raises)."""
        from datetime import datetime, timezone
        try:
            self.db.execute(
                """INSERT INTO monitoring_events
                   (session_id, stage, event_type, value_float, value_text, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (session_id, stage, event_type,
                 _safe(value_float) if value_float is not None else None,
                 value_text,
                 datetime.now(timezone.utc).isoformat()),
            )
            self.db.commit()
        except Exception:
            pass  # monitoring must never break the main pipeline

    def get_monitoring_events(
        self,
        session_id: str | None = None,
        stage: str | None      = None,
        limit: int             = 500,
    ) -> list[MonitoringEvent]:
        where, params = [], []
        if session_id:
            where.append("session_id=?")
            params.append(session_id)
        if stage:
            where.append("stage=?")
            params.append(stage)
        clause = "WHERE " + " AND ".join(where) if where else ""
        params.append(limit)
        rows = self.db.fetchall(
            f"SELECT * FROM monitoring_events {clause} "
            f"ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        return [
            MonitoringEvent(
                id          = r["id"],
                session_id  = r["session_id"],
                stage       = r["stage"],
                event_type  = r["event_type"],
                value_float = r["value_float"],
                value_text  = r["value_text"],
                created_at  = r["created_at"],
            )
            for r in rows
        ]

    def close(self) -> None:
        self.db.close()


# ── Row converters ─────────────────────────────────────────────────────────────

def _row_to_session(row) -> SessionRecord:
    return SessionRecord(
        session_id       = row["session_id"],
        started_at       = row["started_at"],
        finished_at      = row["finished_at"],
        status           = row["status"],
        symbols          = row["symbols"],
        intervals        = row["intervals"],
        start_date       = row["start_date"],
        end_date         = row["end_date"],
        n_strategies_run = row["n_strategies_run"],
        n_passed         = row["n_passed"],
        n_rejected       = row["n_rejected"],
        n_errors         = row["n_errors"],
        elapsed_secs     = row["elapsed_secs"],
    )


def _row_to_result(row) -> StrategyResult:
    keys = row.keys()
    def _get(col, default=None):
        return row[col] if col in keys else default

    return StrategyResult(
        id                  = row["id"],
        session_id          = row["session_id"],
        strategy_class      = row["strategy_class"],
        strategy_name       = row["strategy_name"],
        params              = row["params"],
        symbol              = row["symbol"],
        interval            = row["interval"],
        start_date          = row["start_date"],
        end_date            = row["end_date"],
        gate_decision       = row["gate_decision"],
        gate_score          = row["gate_score"],
        total_trades        = row["total_trades"],
        net_profit          = row["net_profit"],
        total_return        = row["total_return"],
        max_drawdown_pct    = row["max_drawdown_pct"],
        sharpe_ratio        = row["sharpe_ratio"],
        sortino_ratio       = row["sortino_ratio"],
        calmar_ratio        = row["calmar_ratio"],
        cagr                = row["cagr"],
        win_rate            = row["win_rate"],
        profit_factor       = row["profit_factor"],
        avg_trade_pnl       = row["avg_trade_pnl"],
        walk_forward_return = row["walk_forward_return"],
        mc_median_return    = row["mc_median_return"],
        mc_pct5_return      = row["mc_pct5_return"],
        mc_pct95_return     = row["mc_pct95_return"],
        mc_prob_positive    = row["mc_prob_positive"],
        equity_curve_json   = row["equity_curve_json"],
        created_at          = row["created_at"],
        # Phase 7 columns (may be absent in legacy rows)
        degradation_score   = _get("degradation_score"),
        robustness_score    = _get("robustness_score"),
        stability_score     = _get("stability_score"),
        wf_n_folds          = _get("wf_n_folds"),
        wf_efficiency       = _get("wf_efficiency"),
        wf_consistency      = _get("wf_consistency"),
        regime_json         = _get("regime_json"),
        rolling_json        = _get("rolling_json"),
        degradation_json    = _get("degradation_json"),
        distribution_json   = _get("distribution_json"),
        bootstrap_json      = _get("bootstrap_json"),
        robustness_json     = _get("robustness_json"),
    )


def _row_to_job(row) -> JobRecord:
    return JobRecord(
        id          = row["id"],
        job_id      = row["job_id"],
        session_id  = row["session_id"],
        job_type    = row["job_type"],
        status      = row["status"],
        params      = row["params"],
        result_json = row["result_json"],
        error       = row["error"],
        created_at  = row["created_at"],
        started_at  = row["started_at"],
        finished_at = row["finished_at"],
        retry_count = row["retry_count"],
    )
