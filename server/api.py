"""REST JSON API — prefix /api.

All endpoints require authentication (session cookie).
Input is validated; no raw SQL; all DB access via ResearchStorage.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse

from research_db.storage import ResearchStorage
from server.auth import AuthUser
from server.background import job_manager, dict_to_config
from server.bot_manager import bot_manager
from server.jobs import get_available_strategies
from server.notify import notification_manager

router = APIRouter(prefix="/api")

_DB_PATH      = Path(os.environ.get("EDGELAB_DB",      "research.db"))
_REPORTS_DIR  = Path(os.environ.get("EDGELAB_REPORTS", "reports"))
_LOG_PATH     = Path(os.environ.get("EDGELAB_LOG",     "logs/research.log"))

_VALID_SORT_METRICS = {
    "sharpe_ratio", "cagr", "max_drawdown_pct",
    "win_rate", "profit_factor", "total_return",
}


def _store() -> ResearchStorage:
    return ResearchStorage(str(_DB_PATH))


# ── Research / Jobs ───────────────────────────────────────────────────────────

@router.post("/research/run")
async def api_run_research(request: Request, _: AuthUser) -> JSONResponse:
    """Accept JSON body, submit a background job, return job_id."""
    ct = request.headers.get("content-type", "")
    if "application/json" not in ct:
        raise HTTPException(status_code=415,
                            detail="Content-Type must be application/json")
    body = await request.body()
    try:
        raw: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    job_id = job_manager.submit(raw)
    return JSONResponse({"job_id": job_id}, status_code=202)


@router.get("/research/status/{job_id}")
def api_job_status(job_id: str, _: AuthUser) -> JSONResponse:
    info = job_manager.get_job(job_id)
    if not info:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({
        "job_id":       info.job_id,
        "status":       info.status,
        "progress_pct": info.progress_pct,
        "current_stage": info.current_stage,
        "started_at":   info.started_at,
        "finished_at":  info.finished_at,
        "n_tested":     info.n_tested,
        "n_passed":     info.n_passed,
        "elapsed_secs": info.elapsed_secs,
        "session_id":   info.session_id,
        "error":        info.error[:500] if info.error else "",
    })


@router.get("/jobs")
def api_list_jobs(_: AuthUser) -> JSONResponse:
    jobs = job_manager.list_jobs()
    return JSONResponse([
        {
            "job_id":   j.job_id,
            "status":   j.status,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "n_passed": j.n_passed,
            "n_tested": j.n_tested,
            "elapsed_secs": j.elapsed_secs,
        }
        for j in jobs
    ])


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str, _: AuthUser) -> JSONResponse:
    ok = job_manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or not running")
    return JSONResponse({"cancelled": True})


@router.post("/jobs/{job_id}/restart")
def api_restart_job(job_id: str, _: AuthUser) -> JSONResponse:
    new_id = job_manager.restart(job_id)
    if not new_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({"job_id": new_id})


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/reports")
def api_list_reports(_: AuthUser) -> JSONResponse:
    rdir = _REPORTS_DIR
    if not rdir.exists():
        return JSONResponse([])
    files = sorted(rdir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    return JSONResponse([
        {
            "name":     f.name,
            "size_kb":  f.stat().st_size // 1024,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in files
    ])


@router.get("/reports/{filename}")
def api_get_report(filename: str, _: AuthUser) -> FileResponse:
    safe = Path(filename).name           # strip any path traversal
    path = _REPORTS_DIR / safe
    if not path.exists() or path.suffix not in (".html", ".json", ".md"):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(path))


@router.delete("/reports/{filename}")
def api_delete_report(filename: str, _: AuthUser) -> JSONResponse:
    safe = Path(filename).name
    path = _REPORTS_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    path.unlink()
    return JSONResponse({"deleted": safe})


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history")
def api_history(limit: int = 50, _: AuthUser = None) -> JSONResponse:
    store    = _store()
    sessions = store.get_sessions(limit=min(limit, 200))
    store.close()
    return JSONResponse([
        {
            "session_id":       s.session_id,
            "started_at":       s.started_at,
            "status":           s.status,
            "n_strategies_run": s.n_strategies_run,
            "n_passed":         s.n_passed,
            "elapsed_secs":     s.elapsed_secs,
        }
        for s in sessions
    ])


# ── Strategies ────────────────────────────────────────────────────────────────

@router.get("/strategies")
def api_strategies(
    metric: str = "sharpe_ratio",
    limit:  int = 100,
    _: AuthUser = None,
) -> JSONResponse:
    if metric not in _VALID_SORT_METRICS:
        metric = "sharpe_ratio"
    store   = _store()
    results = store.get_best_by(metric=metric, limit=min(limit, 500))
    store.close()
    return JSONResponse([
        {
            "id":             r.id,
            "strategy_class": r.strategy_class,
            "params":         r.params,
            "symbol":         r.symbol,
            "interval":       r.interval,
            "sharpe_ratio":   r.sharpe_ratio,
            "cagr":           r.cagr,
            "max_drawdown_pct": r.max_drawdown_pct,
            "win_rate":       r.win_rate,
            "profit_factor":  r.profit_factor,
            "total_trades":   r.total_trades,
            "gate_decision":  r.gate_decision,
        }
        for r in results
    ])


# ── Available strategies for form ─────────────────────────────────────────────

@router.get("/available-strategies")
def api_available_strategies(_: AuthUser = None) -> JSONResponse:
    return JSONResponse(get_available_strategies())


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/notifications")
def api_notifications(_: AuthUser = None) -> JSONResponse:
    return JSONResponse(notification_manager.in_app.list())


@router.delete("/notifications")
def api_clear_notifications(_: AuthUser = None) -> JSONResponse:
    notification_manager.in_app.clear()
    return JSONResponse({"cleared": True})


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
def api_logs(lines: int = 200, _: AuthUser = None) -> JSONResponse:
    path = _LOG_PATH
    if not path.exists():
        return JSONResponse({"lines": []})
    try:
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = all_lines[-min(lines, 2000):]
        return JSONResponse({"lines": tail})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Stats (overview) ──────────────────────────────────────────────────────────

@router.get("/stats")
def api_stats(_: AuthUser = None) -> JSONResponse:
    store = _store()
    stats = store.get_stats()
    store.close()
    return JSONResponse(stats)


# ── Paper Trading Bot ─────────────────────────────────────────────────────────

@router.get("/bot/status")
def api_bot_status(_: AuthUser = None) -> JSONResponse:
    return JSONResponse(bot_manager.get_status())


@router.post("/bot/start")
async def api_bot_start(request: Request, _: AuthUser) -> JSONResponse:
    ct = request.headers.get("content-type", "")
    if "application/json" not in ct:
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    capital   = float(body.get("capital",  200.0))
    symbols   = body.get("symbols",   ["BTCUSDT"])
    interval  = body.get("interval",  None)
    intervals = body.get("intervals", None)
    strategy  = body.get("strategy",  "EMACrossover")
    db_path   = body.get("db_path",   "bot.db")
    log_path  = body.get("log_path",  "logs/bot.log")
    recover   = bool(body.get("recover",  True))

    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    if isinstance(intervals, str):
        intervals = [iv.strip() for iv in intervals.split(",") if iv.strip()]
    if not intervals and interval:
        intervals = [interval]
    if not intervals:
        intervals = ["1h"]

    if capital <= 0:
        raise HTTPException(status_code=422, detail="capital must be > 0")

    ok, err = bot_manager.start(
        capital=capital, symbols=symbols, intervals=intervals,
        strategy=strategy, db_path=db_path, log_path=log_path,
        recover=recover,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=err)
    return JSONResponse({"started": True})


@router.post("/bot/stop")
def api_bot_stop(_: AuthUser) -> JSONResponse:
    ok, err = bot_manager.stop()
    if not ok:
        raise HTTPException(status_code=409, detail=err)
    return JSONResponse({"stopped": True})


@router.get("/bot/candles")
def api_bot_candles(
    symbol:   str = "BTCUSDT",
    interval: str = "1h",
    limit:    int = 200,
    _: AuthUser = None,
) -> JSONResponse:
    candles = bot_manager.get_candles(
        symbol=symbol, interval=interval, limit=min(limit, 500)
    )
    return JSONResponse(candles)


@router.get("/bot/counters")
def api_bot_counters(_: AuthUser = None) -> JSONResponse:
    return JSONResponse(bot_manager.get_counters())
