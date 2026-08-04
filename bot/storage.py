"""SQLite persistence layer for the paper trading bot.

All bot data lives in a separate database (default: bot.db) to avoid
polluting the Research Lab's research.db.

Schema
------
bot_orders        — order records (full lifecycle)
bot_positions     — position records (open + closed)
bot_fills         — individual fill events
bot_daily_stats   — per-day aggregated statistics
bot_balance_hist  — equity/balance snapshots over time
bot_runtime       — runtime metrics snapshots
bot_errors        — error log
bot_heartbeat     — heartbeat log (last N entries)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_orders (
    order_id        TEXT    PRIMARY KEY,
    symbol          TEXT    NOT NULL,
    side            TEXT    NOT NULL,   -- BUY | SELL
    order_type      TEXT    NOT NULL,   -- MARKET | LIMIT | STOP_MARKET | STOP_LIMIT | TAKE_PROFIT
    status          TEXT    NOT NULL,   -- NEW | ACCEPTED | FILLED | CANCELLED | REJECTED | EXPIRED
    price           REAL,               -- limit price (null for market)
    stop_price      REAL,               -- stop trigger price
    qty             REAL    NOT NULL,
    filled_qty      REAL    NOT NULL DEFAULT 0,
    avg_fill_price  REAL,
    total_fee       REAL    NOT NULL DEFAULT 0,
    time_in_force   TEXT    NOT NULL DEFAULT 'GTC',
    reduce_only     INTEGER NOT NULL DEFAULT 0,
    reject_reason   TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bo_symbol ON bot_orders(symbol);
CREATE INDEX IF NOT EXISTS idx_bo_status ON bot_orders(status);
CREATE INDEX IF NOT EXISTS idx_bo_created ON bot_orders(created_at DESC);

CREATE TABLE IF NOT EXISTS bot_positions (
    position_id       TEXT    PRIMARY KEY,
    symbol            TEXT    NOT NULL,
    direction         TEXT    NOT NULL,   -- long | short
    status            TEXT    NOT NULL,   -- open | closed
    size              REAL    NOT NULL,
    entry_price       REAL    NOT NULL,
    avg_entry_price   REAL    NOT NULL,
    exit_price        REAL,
    realized_pnl      REAL    NOT NULL DEFAULT 0,
    entry_fee         REAL    NOT NULL DEFAULT 0,
    exit_fee          REAL    NOT NULL DEFAULT 0,
    equity_at_entry   REAL,
    entry_order_id    TEXT,
    exit_order_id     TEXT,
    opened_at         TEXT    NOT NULL,
    closed_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_bpos_symbol ON bot_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_bpos_status ON bot_positions(status);
CREATE INDEX IF NOT EXISTS idx_bpos_opened ON bot_positions(opened_at DESC);

CREATE TABLE IF NOT EXISTS bot_fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    fill_price      REAL    NOT NULL,
    fill_qty        REAL    NOT NULL,
    fee             REAL    NOT NULL,
    is_maker        INTEGER NOT NULL DEFAULT 0,
    filled_at       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bf_order ON bot_fills(order_id);
CREATE INDEX IF NOT EXISTS idx_bf_filled ON bot_fills(filled_at DESC);

CREATE TABLE IF NOT EXISTS bot_daily_stats (
    date_utc        TEXT    PRIMARY KEY,   -- YYYY-MM-DD
    n_trades        INTEGER NOT NULL DEFAULT 0,
    n_winners       INTEGER NOT NULL DEFAULT 0,
    n_losers        INTEGER NOT NULL DEFAULT 0,
    gross_profit    REAL    NOT NULL DEFAULT 0,
    gross_loss      REAL    NOT NULL DEFAULT 0,
    net_pnl         REAL    NOT NULL DEFAULT 0,
    total_fees      REAL    NOT NULL DEFAULT 0,
    starting_equity REAL,
    ending_equity   REAL,
    max_drawdown    REAL    NOT NULL DEFAULT 0,
    win_rate        REAL,
    profit_factor   REAL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_balance_hist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    equity      REAL    NOT NULL,
    cash        REAL    NOT NULL,
    unrealized  REAL    NOT NULL DEFAULT 0,
    drawdown    REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_bbh_ts ON bot_balance_hist(ts DESC);

CREATE TABLE IF NOT EXISTS bot_runtime (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    uptime_s        REAL    NOT NULL,
    candles_total   INTEGER NOT NULL DEFAULT 0,
    reconnects      INTEGER NOT NULL DEFAULT 0,
    missed_candles  INTEGER NOT NULL DEFAULT 0,
    memory_mb       REAL,
    cpu_pct         REAL,
    avg_latency_ms  REAL
);

CREATE INDEX IF NOT EXISTS idx_brt_ts ON bot_runtime(ts DESC);

CREATE TABLE IF NOT EXISTS bot_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_berr_ts ON bot_errors(ts DESC);

CREATE TABLE IF NOT EXISTS bot_heartbeat (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    uptime_s        REAL    NOT NULL,
    active_symbols  INTEGER NOT NULL DEFAULT 0,
    candles_recv    INTEGER NOT NULL DEFAULT 0
);
"""


class BotStorage:
    """Thin SQLite wrapper for all bot persistence needs."""

    def __init__(self, path: str | Path = "bot.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ── Connection ──────────────────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "BotStorage":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Orders ──────────────────────────────────────────────────────────────

    def save_order(self, order: dict[str, Any]) -> None:
        now = _now()
        c = self.connect()
        c.execute("""
            INSERT OR REPLACE INTO bot_orders
            (order_id, symbol, side, order_type, status, price, stop_price,
             qty, filled_qty, avg_fill_price, total_fee, time_in_force,
             reduce_only, reject_reason, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            order["order_id"], order["symbol"], order["side"], order["order_type"],
            order["status"], order.get("price"), order.get("stop_price"),
            order["qty"], order.get("filled_qty", 0.0),
            order.get("avg_fill_price"), order.get("total_fee", 0.0),
            order.get("time_in_force", "GTC"),
            int(order.get("reduce_only", False)),
            order.get("reject_reason"),
            order.get("created_at", now), now,
        ))
        c.commit()

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM bot_orders WHERE status IN ('NEW','ACCEPTED','PARTIALLY_FILLED')"
        params: tuple = ()
        if symbol:
            sql += " AND symbol = ?"
            params = (symbol,)
        return [dict(r) for r in self.connect().execute(sql, params).fetchall()]

    def get_orders(self, symbol: str | None = None, limit: int = 200) -> list[dict]:
        if symbol:
            rows = self.connect().execute(
                "SELECT * FROM bot_orders WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self.connect().execute(
                "SELECT * FROM bot_orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Positions ───────────────────────────────────────────────────────────

    def save_position(self, pos: dict[str, Any]) -> None:
        now = _now()
        c = self.connect()
        c.execute("""
            INSERT OR REPLACE INTO bot_positions
            (position_id, symbol, direction, status, size,
             entry_price, avg_entry_price, exit_price, realized_pnl,
             entry_fee, exit_fee, equity_at_entry,
             entry_order_id, exit_order_id, opened_at, closed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pos["position_id"], pos["symbol"], pos["direction"], pos["status"],
            pos["size"], pos["entry_price"], pos.get("avg_entry_price", pos["entry_price"]),
            pos.get("exit_price"), pos.get("realized_pnl", 0.0),
            pos.get("entry_fee", 0.0), pos.get("exit_fee", 0.0),
            pos.get("equity_at_entry"),
            pos.get("entry_order_id"), pos.get("exit_order_id"),
            pos.get("opened_at", now), pos.get("closed_at"),
        ))
        c.commit()

    def get_open_positions(self) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM bot_positions WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_positions(self, limit: int = 200, symbol: str | None = None) -> list[dict]:
        if symbol:
            rows = self.connect().execute(
                "SELECT * FROM bot_positions WHERE symbol=? ORDER BY opened_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self.connect().execute(
                "SELECT * FROM bot_positions ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Fills ───────────────────────────────────────────────────────────────

    def save_fill(self, fill: dict[str, Any]) -> None:
        c = self.connect()
        c.execute("""
            INSERT INTO bot_fills
            (order_id, symbol, side, fill_price, fill_qty, fee, is_maker, filled_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            fill["order_id"], fill["symbol"], fill["side"],
            fill["fill_price"], fill["fill_qty"], fill["fee"],
            int(fill.get("is_maker", False)), fill.get("filled_at", _now()),
        ))
        c.commit()

    def get_fills(self, symbol: str | None = None, limit: int = 500) -> list[dict]:
        if symbol:
            rows = self.connect().execute(
                "SELECT * FROM bot_fills WHERE symbol=? ORDER BY filled_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self.connect().execute(
                "SELECT * FROM bot_fills ORDER BY filled_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Daily stats ─────────────────────────────────────────────────────────

    def upsert_daily_stats(self, stats: dict[str, Any]) -> None:
        now = _now()
        c = self.connect()
        c.execute("""
            INSERT OR REPLACE INTO bot_daily_stats
            (date_utc, n_trades, n_winners, n_losers, gross_profit, gross_loss,
             net_pnl, total_fees, starting_equity, ending_equity, max_drawdown,
             win_rate, profit_factor, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            stats["date_utc"],
            stats.get("n_trades", 0), stats.get("n_winners", 0), stats.get("n_losers", 0),
            stats.get("gross_profit", 0.0), stats.get("gross_loss", 0.0),
            stats.get("net_pnl", 0.0), stats.get("total_fees", 0.0),
            stats.get("starting_equity"), stats.get("ending_equity"),
            stats.get("max_drawdown", 0.0),
            stats.get("win_rate"), stats.get("profit_factor"),
            now,
        ))
        c.commit()

    def get_daily_stats(self, limit: int = 90) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM bot_daily_stats ORDER BY date_utc DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_stats_for(self, date_utc: str) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM bot_daily_stats WHERE date_utc=?", (date_utc,)
        ).fetchone()
        return dict(row) if row else None

    # ── Balance history ──────────────────────────────────────────────────────

    def save_balance_snapshot(
        self, equity: float, cash: float,
        unrealized: float = 0.0, drawdown: float = 0.0,
    ) -> None:
        c = self.connect()
        c.execute(
            "INSERT INTO bot_balance_hist (ts, equity, cash, unrealized, drawdown) VALUES (?,?,?,?,?)",
            (_now(), equity, cash, unrealized, drawdown),
        )
        c.commit()

    def get_balance_history(self, limit: int = 1000) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM bot_balance_hist ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ── Runtime metrics ──────────────────────────────────────────────────────

    def save_runtime_snapshot(self, snap: dict[str, Any]) -> None:
        c = self.connect()
        c.execute("""
            INSERT INTO bot_runtime
            (ts, uptime_s, candles_total, reconnects, missed_candles,
             memory_mb, cpu_pct, avg_latency_ms)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            _now(),
            snap.get("uptime_s", 0.0), snap.get("candles_total", 0),
            snap.get("reconnects", 0), snap.get("missed_candles", 0),
            snap.get("memory_mb"), snap.get("cpu_pct"), snap.get("avg_latency_ms"),
        ))
        # Keep only last 1440 rows (24h of 1-min snapshots)
        c.execute("DELETE FROM bot_runtime WHERE id NOT IN (SELECT id FROM bot_runtime ORDER BY id DESC LIMIT 1440)")
        c.commit()

    def get_runtime_history(self, limit: int = 60) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM bot_runtime ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ── Errors ───────────────────────────────────────────────────────────────

    def log_error(self, source: str, message: str, detail: str = "") -> None:
        c = self.connect()
        c.execute(
            "INSERT INTO bot_errors (ts, source, message, detail) VALUES (?,?,?,?)",
            (_now(), source, message, detail),
        )
        # Keep only last 10000 errors
        c.execute("DELETE FROM bot_errors WHERE id NOT IN (SELECT id FROM bot_errors ORDER BY id DESC LIMIT 10000)")
        c.commit()

    def get_errors(self, limit: int = 100) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM bot_errors ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def save_heartbeat(self, uptime_s: float, active_symbols: int, candles_recv: int) -> None:
        c = self.connect()
        c.execute(
            "INSERT INTO bot_heartbeat (ts, uptime_s, active_symbols, candles_recv) VALUES (?,?,?,?)",
            (_now(), uptime_s, active_symbols, candles_recv),
        )
        c.execute("DELETE FROM bot_heartbeat WHERE id NOT IN (SELECT id FROM bot_heartbeat ORDER BY id DESC LIMIT 1000)")
        c.commit()

    def get_last_heartbeat(self) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM bot_heartbeat ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ── Private ──────────────────────────────────────────────────────────────

    def _create_schema(self) -> None:
        c = self._conn
        for stmt in _SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)
        c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
