"""REST JSON API — prefix /api.

All endpoints require authentication (session cookie).
Input is validated; no raw SQL; all DB access via ResearchStorage.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse

from research_db.storage import ResearchStorage
from server.auth import AuthUser, authenticate
from server.background import job_manager, dict_to_config
from server.bot_manager import bot_manager
from server.jobs import get_available_strategies
from server.notify import notification_manager

router = APIRouter(prefix="/api")

_SCHED_FILE = Path(__file__).parent / "schedules.json"

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
def api_history(_: AuthUser, limit: int = 50) -> JSONResponse:
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
    _: AuthUser,
    metric: str = "sharpe_ratio",
    limit:  int = 100,
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
def api_available_strategies(_: AuthUser) -> JSONResponse:
    return JSONResponse(get_available_strategies())


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/notifications")
def api_notifications(_: AuthUser) -> JSONResponse:
    return JSONResponse(notification_manager.in_app.list())


@router.delete("/notifications")
def api_clear_notifications(_: AuthUser) -> JSONResponse:
    notification_manager.in_app.clear()
    return JSONResponse({"cleared": True})


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get("/logs")
def api_logs(_: AuthUser, lines: int = 200) -> JSONResponse:
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
def api_stats(_: AuthUser) -> JSONResponse:
    store = _store()
    stats = store.get_stats()
    store.close()
    return JSONResponse(stats)


# ── Paper Trading Bot ─────────────────────────────────────────────────────────

@router.get("/bot/status")
def api_bot_status(_: AuthUser) -> JSONResponse:
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
    _: AuthUser,
    symbol:   str = "BTCUSDT",
    interval: str = "1h",
    limit:    int = 200,
) -> JSONResponse:
    candles = bot_manager.get_candles(
        symbol=symbol, interval=interval, limit=min(limit, 500)
    )
    return JSONResponse(candles)


@router.get("/bot/counters")
def api_bot_counters(_: AuthUser) -> JSONResponse:
    return JSONResponse(bot_manager.get_counters())


@router.post("/bot/active-pair")
async def api_bot_set_active_pair(request: Request, _: AuthUser) -> JSONResponse:
    """Tell the server which (symbol, interval) the browser is currently viewing.

    Once set, full OHLCV candle events are only sent for that pair.  All other
    pairs send lightweight tick events for the Market Watch table.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    symbol   = str(body.get("symbol",   "")).strip()
    interval = str(body.get("interval", "")).strip()
    if not symbol or not interval:
        raise HTTPException(status_code=422, detail="symbol and interval are required")
    bot_manager.set_active_pair(symbol, interval)
    return JSONResponse({"ok": True})


# ── Auth JSON endpoints ────────────────────────────────────────────────────────

@router.get("/auth/me")
def api_auth_me(request: Request) -> JSONResponse:
    """Return current session user, or 401 if not authenticated."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return JSONResponse({"username": user})


@router.post("/auth/login")
async def api_auth_login(request: Request) -> JSONResponse:
    """Authenticate with JSON {username, password} and set session cookie."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not authenticate(username, password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user"] = username
    return JSONResponse({"ok": True, "username": username})


@router.post("/auth/logout")
def api_auth_logout(request: Request) -> JSONResponse:
    """Clear session cookie."""
    request.session.clear()
    return JSONResponse({"ok": True})


# ── Scheduler JSON endpoints ───────────────────────────────────────────────────

def _load_schedules() -> list[dict]:
    if not _SCHED_FILE.exists():
        return []
    try:
        return json.loads(_SCHED_FILE.read_text())
    except Exception:
        return []


def _save_schedules(schedules: list[dict]) -> None:
    tmp = _SCHED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(schedules, indent=2))
    tmp.replace(_SCHED_FILE)


@router.get("/scheduler")
def api_scheduler_list(_: AuthUser) -> JSONResponse:
    return JSONResponse(_load_schedules())


@router.post("/scheduler")
async def api_scheduler_create(request: Request, _: AuthUser) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    schedule = {
        "id":           str(uuid.uuid4()),
        "name":         str(body.get("name", "Scheduled Research"))[:100],
        "frequency":    str(body.get("frequency", "daily")),
        "hour":         int(body.get("hour", 2)),
        "minute":       int(body.get("minute", 0)),
        "day_of_week":  int(body.get("day_of_week", 1)),
        "day_of_month": int(body.get("day_of_month", 1)),
        "enabled":      True,
        "last_run":     None,
        "config":       body.get("config", {}),
    }
    schedules = _load_schedules()
    schedules.append(schedule)
    _save_schedules(schedules)
    return JSONResponse(schedule, status_code=201)


@router.delete("/scheduler/{sched_id}")
def api_scheduler_delete(sched_id: str, _: AuthUser) -> JSONResponse:
    schedules = _load_schedules()
    new = [s for s in schedules if s["id"] != sched_id]
    if len(new) == len(schedules):
        raise HTTPException(status_code=404, detail="Schedule not found")
    _save_schedules(new)
    return JSONResponse({"ok": True})


@router.post("/scheduler/{sched_id}/toggle")
def api_scheduler_toggle(sched_id: str, _: AuthUser) -> JSONResponse:
    schedules = _load_schedules()
    for s in schedules:
        if s["id"] == sched_id:
            s["enabled"] = not s.get("enabled", True)
            _save_schedules(schedules)
            return JSONResponse(s)
    raise HTTPException(status_code=404, detail="Schedule not found")


@router.post("/scheduler/{sched_id}/run-now")
def api_scheduler_run_now(sched_id: str, _: AuthUser) -> JSONResponse:
    schedules = _load_schedules()
    for s in schedules:
        if s["id"] == sched_id:
            job_id = job_manager.submit(s.get("config", {}))
            return JSONResponse({"job_id": job_id})
    raise HTTPException(status_code=404, detail="Schedule not found")


# ── Settings JSON endpoint ─────────────────────────────────────────────────────

_DB_PATH_SETTINGS     = Path(os.environ.get("EDGELAB_DB",      "research.db"))
_REPORTS_DIR_SETTINGS = Path(os.environ.get("EDGELAB_REPORTS", "reports"))
_DATA_DIR_SETTINGS    = Path(os.environ.get("EDGELAB_DATA_DIR","data/bars"))
_LOG_PATH_SETTINGS    = Path(os.environ.get("EDGELAB_LOG",     "logs/research.log"))


@router.get("/settings")
def api_settings(_: AuthUser) -> JSONResponse:
    env_vars = {k: v for k, v in sorted(os.environ.items()) if k.startswith("EDGELAB_")}
    return JSONResponse({
        "db_path":     str(_DB_PATH_SETTINGS),
        "reports_dir": str(_REPORTS_DIR_SETTINGS),
        "data_dir":    str(_DATA_DIR_SETTINGS),
        "log_path":    str(_LOG_PATH_SETTINGS),
        "env_vars":    env_vars,
    })
