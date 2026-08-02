"""SQLite database connection and schema migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT NOT NULL DEFAULT 'running',
    symbols           TEXT NOT NULL,
    intervals         TEXT NOT NULL,
    start_date        TEXT NOT NULL,
    end_date          TEXT NOT NULL,
    n_strategies_run  INTEGER NOT NULL DEFAULT 0,
    n_passed          INTEGER NOT NULL DEFAULT 0,
    n_rejected        INTEGER NOT NULL DEFAULT 0,
    n_errors          INTEGER NOT NULL DEFAULT 0,
    elapsed_secs      REAL
);

CREATE TABLE IF NOT EXISTS strategy_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT    NOT NULL REFERENCES sessions(session_id),
    strategy_class      TEXT    NOT NULL,
    strategy_name       TEXT    NOT NULL,
    params              TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    interval            TEXT    NOT NULL,
    start_date          TEXT    NOT NULL,
    end_date            TEXT    NOT NULL,
    gate_decision       TEXT    NOT NULL,
    gate_score          REAL,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    net_profit          REAL    NOT NULL DEFAULT 0,
    total_return        REAL    NOT NULL DEFAULT 0,
    max_drawdown_pct    REAL    NOT NULL DEFAULT 0,
    sharpe_ratio        REAL    NOT NULL DEFAULT 0,
    sortino_ratio       REAL    NOT NULL DEFAULT 0,
    calmar_ratio        REAL    NOT NULL DEFAULT 0,
    cagr                REAL    NOT NULL DEFAULT 0,
    win_rate            REAL    NOT NULL DEFAULT 0,
    profit_factor       REAL    NOT NULL DEFAULT 0,
    avg_trade_pnl       REAL    NOT NULL DEFAULT 0,
    walk_forward_return REAL,
    mc_median_return    REAL,
    mc_pct5_return      REAL,
    mc_pct95_return     REAL,
    mc_prob_positive    REAL,
    equity_curve_json   TEXT,
    created_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sr_session    ON strategy_results(session_id);
CREATE INDEX IF NOT EXISTS idx_sr_decision   ON strategy_results(gate_decision);
CREATE INDEX IF NOT EXISTS idx_sr_sharpe     ON strategy_results(sharpe_ratio DESC);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT    NOT NULL UNIQUE,
    session_id   TEXT,
    job_type     TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',
    params       TEXT    NOT NULL,
    result_json  TEXT,
    error        TEXT,
    created_at   TEXT    NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    retry_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class Database:
    """Thin SQLite wrapper with automatic schema migration."""

    def __init__(self, path: str | Path = "research.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _migrate(self) -> None:
        conn = self._conn
        for stmt in _SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def executemany(self, sql: str, params) -> sqlite3.Cursor:
        return self.connect().executemany(sql, params)

    def commit(self) -> None:
        self.connect().commit()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()
