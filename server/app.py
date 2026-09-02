"""EdgeLab web server — React SPA frontend + REST/WebSocket API.

Routing architecture:
  /api/*                  — JSON REST API  (server/api.py)
  /ws/*                   — WebSocket      (server/websocket.py)
  /assets/*               — React build static assets
  /reports/view/{f}       — Serve HTML report file in browser
  /reports/download/{f}   — Download report file
  /bot                    — 301 redirect → /paper-trading
  /{any other path}       — React SPA (frontend/dist/index.html)

The React application (React Router) handles all UI routing.
Jinja2 templates are preserved in server/templates/ for reference
but are NOT mounted or rendered as the active UI.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from server.auth import SECRET_KEY, require_auth
from server.background import job_manager
from server import api as api_module
from server import websocket as ws_module

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPORTS_DIR = Path(os.environ.get("EDGELAB_REPORTS", "reports"))
_SCHED_FILE  = Path(__file__).parent / "schedules.json"
_SPA_DIST    = Path(__file__).parent.parent / "frontend" / "dist"

# Local development can run over HTTP. Production deployments should set this
# explicitly to true so the session cookie is never sent over cleartext HTTP.
_HTTPS_ONLY = os.environ.get("EDGELAB_HTTPS_ONLY", "false").strip().lower() in {
    "1", "true", "yes", "on"
}


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    application = FastAPI(title="EdgeLab", docs_url=None, redoc_url=None)

    application.add_middleware(
        SessionMiddleware,
        secret_key     = SECRET_KEY,
        session_cookie = "edgelab_session",
        https_only     = _HTTPS_ONLY,
        same_site      = "lax",
    )

    # JSON API and WebSocket (highest priority — matched before catch-all)
    application.include_router(api_module.router)
    application.include_router(ws_module.router)

    # Backward-compat redirect — /bot → /paper-trading
    @application.get("/bot", include_in_schema=False)
    def bot_redirect() -> RedirectResponse:
        return RedirectResponse("/paper-trading", status_code=301)

    # Report file endpoints (served by backend — not React routes)
    @application.get("/reports/view/{filename}", include_in_schema=False)
    def view_report(filename: str, request: Request) -> FileResponse:
        require_auth(request)
        safe = Path(filename).name
        path = _REPORTS_DIR / safe
        if not path.exists() or path.suffix != ".html":
            raise HTTPException(status_code=404, detail="Report not found")
        return FileResponse(str(path), media_type="text/html")

    @application.get("/reports/download/{filename}", include_in_schema=False)
    def download_report(filename: str, request: Request) -> FileResponse:
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

    # React build assets — must be mounted before the catch-all
    _assets = _SPA_DIST / "assets"
    if _assets.is_dir():
        application.mount("/assets", StaticFiles(directory=str(_assets)), name="spa-assets")

    # SPA catch-all — serves index.html for every unmatched path so React
    # Router can handle /dashboard, /research, /paper-trading, etc.
    @application.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa_index(full_path: str) -> HTMLResponse:  # noqa: ARG001
        index = _SPA_DIST / "index.html"
        if not index.exists():
            raise HTTPException(
                status_code=503,
                detail="Frontend not built. Run: cd frontend && npm run build",
            )
        return HTMLResponse(index.read_text())

    _start_scheduler_thread()
    return application


# ── Schedule storage (shared with api.py) ────────────────────────────────────

def _load_schedules() -> list[dict]:
    if not _SCHED_FILE.exists():
        return []
    try:
        return json.loads(_SCHED_FILE.read_text())
    except Exception:
        logger.exception("Failed to load schedules from %s", _SCHED_FILE)
        return []


def _save_schedules(schedules: list[dict]) -> None:
    tmp = _SCHED_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(schedules, indent=2))
    tmp.replace(_SCHED_FILE)


# ── Scheduler background thread ───────────────────────────────────────────────

def _scheduler_tick() -> None:
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
            logger.exception("Scheduler tick failed")
        time.sleep(60)


def _is_due(s: dict, now: datetime) -> bool:
    freq   = s.get("frequency", "daily")
    hour   = s.get("hour", 2)
    minute = s.get("minute", 0)
    if now.hour != hour or now.minute != minute:
        return False
    last = s.get("last_run")
    if last:
        if (now - datetime.fromisoformat(last)).total_seconds() < 3600:
            return False
    if freq == "daily":
        return True
    if freq == "weekly":
        return now.weekday() == s.get("day_of_week", 0)
    if freq == "monthly":
        return now.day == s.get("day_of_month", 1)
    return False


# ── Scheduler startup ─────────────────────────────────────────────────────────

def _start_scheduler_thread() -> None:
    t = threading.Thread(target=_scheduler_tick, daemon=True, name="scheduler")
    t.start()


# ── Application singleton ─────────────────────────────────────────────────────

app = create_app()
