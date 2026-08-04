"""EdgeLab web server — main FastAPI application.

All pages are server-side rendered with Jinja2.
Authentication is enforced via session cookies on every route except /login.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from research_db.storage import ResearchStorage
from server.auth import (
    SECRET_KEY, USING_DEFAULT_CREDS,
    authenticate, require_auth,
)
from server.background import job_manager, dict_to_config
from server.bot_manager import bot_manager
from server.jobs import get_available_strategies
from server.notify import notification_manager
from server import api as api_module
from server import websocket as ws_module

# ── Paths ─────────────────────────────────────────────────────────────────────
_DB_PATH     = Path(os.environ.get("EDGELAB_DB",      "research.db"))
_REPORTS_DIR = Path(os.environ.get("EDGELAB_REPORTS", "reports"))
_DATA_DIR    = Path(os.environ.get("EDGELAB_DATA_DIR","data/bars"))
_LOG_PATH    = Path(os.environ.get("EDGELAB_LOG",     "logs/research.log"))
_SCHED_FILE  = Path(__file__).parent / "schedules.json"

_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    application = FastAPI(
        title     = "EdgeLab",
        docs_url  = None,
        redoc_url = None,
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key  = SECRET_KEY,
        session_cookie = "edgelab_session",
        https_only  = False,        # set True behind HTTPS proxy
        same_site   = "lax",
    )
    application.include_router(api_module.router)
    application.include_router(ws_module.router)
    _register_routes(application)
    _start_scheduler_thread()
    return application


# ── Jinja2 setup ──────────────────────────────────────────────────────────────

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _render(request: Request, template: str, ctx: dict | None = None) -> HTMLResponse:
    data: dict = {"notifications": notification_manager.in_app.list()[:5]}
    if ctx:
        data.update(ctx)
    return templates.TemplateResponse(request, template, data)


def _fmt(v: float | None, d: int = 4, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.2f}%"
    return f"{v:.{d}f}"


def _store() -> ResearchStorage:
    return ResearchStorage(str(_DB_PATH))


# ── Auth routes ───────────────────────────────────────────────────────────────

def _register_routes(app: FastAPI) -> None:

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/") -> HTMLResponse:
        if request.session.get("user"):
            return RedirectResponse("/", status_code=302)
        return _render(request, "login.html", {
            "next":    next,
            "warning": USING_DEFAULT_CREDS,
        })

    @app.post("/login")
    def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        next: str     = Form("/"),
    ):
        if authenticate(username, password):
            request.session["user"] = username
            safe_next = next if next.startswith("/") else "/"
            return RedirectResponse(safe_next, status_code=302)
        return _render(request, "login.html", {
            "next":  next,
            "error": "Invalid username or password.",
            "warning": USING_DEFAULT_CREDS,
        })

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        require_auth(request)
        store = _store()
        stats = store.get_stats()
        sessions = store.get_sessions(limit=5)
        store.close()

        jobs = job_manager.list_jobs()
        running = [j for j in jobs if j.status == "running"]

        return _render(request, "dashboard.html", {
            "stats":    stats,
            "sessions": sessions,
            "running_jobs": running,
            "n_running": len(running),
        })

    # ── Research ──────────────────────────────────────────────────────────────

    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request):
        require_auth(request)
        strategies = get_available_strategies()
        return _render(request, "research.html", {
            "strategies":  strategies,
            "today":       str(date.today()),
            "default_start": "2024-01-01",
            "n_workers_default": max(1, (os.cpu_count() or 1)),
        })

    @app.post("/research/run")
    async def research_run(request: Request):
        """Accept multipart form, submit job, redirect to job detail page."""
        require_auth(request)
        form_data = await request.form()
        raw = dict(form_data)

        # Checkboxes — absent means unchecked (HTML sends nothing when unchecked)
        for checkbox in ("run_walk_forward", "run_monte_carlo",
                         "run_robustness", "fast_mode", "verbose"):
            raw[checkbox] = checkbox in raw

        job_id = job_manager.submit(raw)
        return RedirectResponse(f"/jobs/{job_id}", status_code=302)

    # ── Jobs ──────────────────────────────────────────────────────────────────

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(request: Request):
        require_auth(request)
        jobs = job_manager.list_jobs()
        return _render(request, "jobs.html", {"jobs": jobs})

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: str):
        require_auth(request)
        info = job_manager.get_job(job_id)
        if not info:
            raise HTTPException(status_code=404, detail="Job not found")
        return _render(request, "job_detail.html", {
            "job":    info,
            "config": info.config,
        })

    @app.post("/jobs/{job_id}/cancel")
    def job_cancel(request: Request, job_id: str):
        require_auth(request)
        job_manager.cancel(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=302)

    @app.post("/jobs/{job_id}/restart")
    def job_restart(request: Request, job_id: str):
        require_auth(request)
        new_id = job_manager.restart(job_id)
        if not new_id:
            raise HTTPException(status_code=404, detail="Job not found")
        return RedirectResponse(f"/jobs/{new_id}", status_code=302)

    # ── Reports ───────────────────────────────────────────────────────────────

    @app.get("/reports", response_class=HTMLResponse)
    def reports_page(request: Request):
        require_auth(request)
        rdir = _REPORTS_DIR
        html_files: list[dict] = []
        if rdir.exists():
            for f in sorted(rdir.glob("*.html"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
                # Try to find companion JSON for metadata
                meta: dict = {}
                json_path = f.with_suffix(".json")
                if json_path.exists():
                    try:
                        meta = json.loads(json_path.read_text())
                    except Exception:
                        pass
                html_files.append({
                    "name":     f.name,
                    "size_kb":  f.stat().st_size // 1024,
                    "modified": datetime.fromtimestamp(
                        f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "symbol":   meta.get("symbol", ""),
                    "interval": meta.get("interval", ""),
                    "n_passed": meta.get("n_passed", ""),
                    "sharpe":   meta.get("best_sharpe", ""),
                })
        return _render(request, "reports.html", {"files": html_files})

    @app.get("/reports/view/{filename}")
    def view_report(request: Request, filename: str):
        require_auth(request)
        safe = Path(filename).name
        path = _REPORTS_DIR / safe
        if not path.exists() or path.suffix != ".html":
            raise HTTPException(status_code=404, detail="Report not found")
        return FileResponse(str(path), media_type="text/html")

    @app.get("/reports/download/{filename}")
    def download_report(request: Request, filename: str):
        require_auth(request)
        safe = Path(filename).name
        path = _REPORTS_DIR / safe
        if not path.exists():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(
            str(path),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={safe}"},
        )

    @app.post("/reports/delete/{filename}")
    def delete_report(request: Request, filename: str):
        require_auth(request)
        safe = Path(filename).name
        path = _REPORTS_DIR / safe
        if path.exists():
            path.unlink()
        return RedirectResponse("/reports", status_code=302)

    # ── History ───────────────────────────────────────────────────────────────

    @app.get("/history", response_class=HTMLResponse)
    def history_page(request: Request, limit: int = 50):
        require_auth(request)
        store    = _store()
        sessions = store.get_sessions(limit=min(limit, 200))
        store.close()
        return _render(request, "history.html", {"sessions": sessions})

    # ── Strategies ────────────────────────────────────────────────────────────

    @app.get("/strategies", response_class=HTMLResponse)
    def strategies_page(
        request: Request,
        metric:   str = "sharpe_ratio",
        decision: str = "",
        limit:    int = 100,
    ):
        require_auth(request)
        _VALID = {"sharpe_ratio", "cagr", "max_drawdown_pct",
                  "win_rate", "profit_factor", "total_return"}
        if metric not in _VALID:
            metric = "sharpe_ratio"
        store   = _store()
        results = store.get_best_by(metric=metric, limit=min(limit, 500))
        store.close()
        if decision:
            results = [r for r in results
                       if r.gate_decision.upper() == decision.upper()]
        return _render(request, "strategies.html", {
            "results":  results,
            "metric":   metric,
            "decision": decision,
            "fmt":      _fmt,
        })

    # ── Scheduler ─────────────────────────────────────────────────────────────

    @app.get("/scheduler", response_class=HTMLResponse)
    def scheduler_page(request: Request):
        require_auth(request)
        schedules = _load_schedules()
        strategies = get_available_strategies()
        return _render(request, "scheduler.html", {
            "schedules": schedules,
            "strategies": strategies,
            "today": str(date.today()),
        })

    @app.post("/scheduler/create")
    async def scheduler_create(request: Request):
        require_auth(request)
        form = await request.form()
        raw  = dict(form)

        schedule = {
            "id":        str(uuid.uuid4()),
            "name":      raw.get("name", "Scheduled Research")[:100],
            "frequency": raw.get("frequency", "daily"),
            "hour":      int(raw.get("hour", 2)),
            "minute":    int(raw.get("minute", 0)),
            "day_of_week":  int(raw.get("day_of_week", 1)),
            "day_of_month": int(raw.get("day_of_month", 1)),
            "enabled":   True,
            "last_run":  None,
            "config":    {k: v for k, v in raw.items()
                         if k not in ("name", "frequency", "hour", "minute",
                                      "day_of_week", "day_of_month")},
        }
        schedules = _load_schedules()
        schedules.append(schedule)
        _save_schedules(schedules)
        return RedirectResponse("/scheduler", status_code=302)

    @app.post("/scheduler/{sched_id}/delete")
    def scheduler_delete(request: Request, sched_id: str):
        require_auth(request)
        schedules = [s for s in _load_schedules() if s["id"] != sched_id]
        _save_schedules(schedules)
        return RedirectResponse("/scheduler", status_code=302)

    @app.post("/scheduler/{sched_id}/toggle")
    def scheduler_toggle(request: Request, sched_id: str):
        require_auth(request)
        schedules = _load_schedules()
        for s in schedules:
            if s["id"] == sched_id:
                s["enabled"] = not s.get("enabled", True)
        _save_schedules(schedules)
        return RedirectResponse("/scheduler", status_code=302)

    @app.post("/scheduler/{sched_id}/run-now")
    def scheduler_run_now(request: Request, sched_id: str):
        require_auth(request)
        schedules = _load_schedules()
        for s in schedules:
            if s["id"] == sched_id:
                job_id = job_manager.submit(s.get("config", {}))
                return RedirectResponse(f"/jobs/{job_id}", status_code=302)
        raise HTTPException(status_code=404, detail="Schedule not found")

    # ── Settings ──────────────────────────────────────────────────────────────

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        require_auth(request)
        env_vars = {k: v for k, v in sorted(os.environ.items())
                    if k.startswith("EDGELAB_")}
        return _render(request, "settings.html", {
            "db_path":     str(_DB_PATH),
            "reports_dir": str(_REPORTS_DIR),
            "data_dir":    str(_DATA_DIR),
            "log_path":    str(_LOG_PATH),
            "env_vars":    env_vars,
            "using_default_creds": USING_DEFAULT_CREDS,
        })

    # ── Paper Trading Bot ─────────────────────────────────────────────────────

    @app.get("/bot", response_class=HTMLResponse)
    def bot_page(request: Request):
        require_auth(request)
        from server.jobs import get_available_strategies as _strats
        return _render(request, "bot.html", {
            "status":     bot_manager.get_status(),
            "strategies": _strats(),
        })

    @app.post("/bot/start")
    async def bot_start(request: Request):
        require_auth(request)
        form = await request.form()
        capital  = float(form.get("capital",  "25"))
        raw_syms = str(form.get("symbols",  "BTCUSDT"))
        symbols  = [s.strip() for s in raw_syms.split(",") if s.strip()]
        interval = str(form.get("interval", "1h"))
        strategy = str(form.get("strategy", "EMACrossover"))
        recover  = "recover" in form

        ok, err = bot_manager.start(
            capital=capital, symbols=symbols, interval=interval,
            strategy=strategy, recover=recover,
        )
        if not ok:
            return _render(request, "bot.html", {
                "status":     bot_manager.get_status(),
                "strategies": get_available_strategies(),
                "error":      err,
            })
        return RedirectResponse("/bot", status_code=302)

    @app.post("/bot/stop")
    def bot_stop(request: Request):
        require_auth(request)
        bot_manager.stop()
        return RedirectResponse("/bot", status_code=302)

    # ── Logs ──────────────────────────────────────────────────────────────────

    @app.get("/logs", response_class=HTMLResponse)
    def logs_page(request: Request, lines: int = 200):
        require_auth(request)
        log_lines: list[str] = []
        if _LOG_PATH.exists():
            try:
                all_lines = _LOG_PATH.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                log_lines = all_lines[-min(lines, 2000):]
            except Exception:
                pass
        return _render(request, "logs.html", {"log_lines": log_lines})


# ── Schedule storage ──────────────────────────────────────────────────────────

def _load_schedules() -> list[dict]:
    if not _SCHED_FILE.exists():
        return []
    try:
        return json.loads(_SCHED_FILE.read_text())
    except Exception:
        return []


def _save_schedules(schedules: list[dict]) -> None:
    _SCHED_FILE.write_text(json.dumps(schedules, indent=2))


# ── Scheduler background thread ───────────────────────────────────────────────

def _scheduler_tick() -> None:
    """Check once per minute whether any schedule is due."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            schedules = _load_schedules()
            changed = False
            for s in schedules:
                if not s.get("enabled", True):
                    continue
                if _is_due(s, now):
                    job_manager.submit(s.get("config", {}))
                    s["last_run"] = now.isoformat()
                    changed = True
            if changed:
                _save_schedules(schedules)
        except Exception:
            pass
        time.sleep(60)


def _is_due(s: dict, now: datetime) -> bool:
    """True if the schedule should fire right now (within a 1-minute window)."""
    freq   = s.get("frequency", "daily")
    hour   = s.get("hour", 2)
    minute = s.get("minute", 0)

    if now.hour != hour or now.minute != minute:
        return False

    last = s.get("last_run")
    if last:
        last_dt = datetime.fromisoformat(last)
        if (now - last_dt).total_seconds() < 3600:
            return False         # fired within the last hour

    if freq == "daily":
        return True
    if freq == "weekly":
        return now.weekday() == s.get("day_of_week", 0)
    if freq == "monthly":
        return now.day == s.get("day_of_month", 1)
    return False


def _start_scheduler_thread() -> None:
    t = threading.Thread(target=_scheduler_tick, daemon=True, name="scheduler")
    t.start()


# ── Application singleton ─────────────────────────────────────────────────────

app = create_app()
