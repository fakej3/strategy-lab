from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

app = FastAPI(title="Strategy Lab API", version="2.2.0")
SESSION_COOKIE = "strategy_lab_session"

# Keep the web contract independent from the research pipeline import. The
# pipeline is intentionally too heavy to load for every Vercel request.
PARAM_SPACES: dict[str, dict[str, list[Any]]] = {
    "EMACrossover": {"fast": [5, 10, 15, 20], "slow": [30, 40, 50, 100, 200]},
    "RSIMeanReversion": {"period": [7, 14, 21], "oversold": [25.0, 30.0], "overbought": [65.0, 70.0, 75.0]},
    "BollingerBand": {"period": [10, 20, 30], "num_std": [1.5, 2.0, 2.5]},
    "MACDCrossover": {"fast": [8, 12], "slow": [21, 26], "signal": [7, 9]},
    "DonchianBreakout": {"entry_period": [10, 20, 30, 55], "exit_period": [5, 10, 20]},
}


class HealthResponse(BaseModel):
    status: str
    engine: str
    computation: str


class ResearchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    start: str
    end: str
    initial_capital: float = Field(gt=0)


def _authed(request: Request) -> bool:
    return request.cookies.get(SESSION_COOKIE) == "demo-admin"


def _unauthorized() -> Response:
    return Response(
        content='{"detail":"Unauthorized"}',
        status_code=401,
        media_type="application/json",
    )


def _strategy_catalog() -> list[dict[str, Any]]:
    # Import only the strategy package here. This gives the UI the actual
    # registered classes rather than a hard-coded fake list.
    from strategies import registry

    out: list[dict[str, Any]] = []
    for name in registry.list_strategies():
        cls = registry.get_class(name)
        sig = inspect.signature(cls)
        params: list[dict[str, Any]] = []
        for p in sig.parameters.values():
            if p.name == "self":
                continue
            default = None if p.default is inspect.Parameter.empty else p.default
            params.append({"name": p.name, "default": default, "type": str(p.annotation)})
        out.append({"name": name, "param_space": PARAM_SPACES.get(name, {}), "params": params})
    return out


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine="strategy-labs-v2",
        computation="server-side-python",
    )


@app.post("/api/auth/login")
def login(payload: dict[str, Any], response: Response):
    # Temporary demo authentication for the public test deployment.
    # Replace with real secret-backed authentication before any non-demo use.
    if payload.get("username") != "admin" or payload.get("password") != "admin":
        response.status_code = 401
        return {"ok": False, "message": "Invalid credentials"}
    response.set_cookie(
        SESSION_COOKIE,
        "demo-admin",
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=86400,
    )
    return {"ok": True, "user": {"username": "admin"}}


@app.get("/api/auth/me")
def me(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {"username": "admin", "authenticated": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/available-strategies")
def available_strategies(request: Request):
    if not _authed(request):
        return _unauthorized()
    return _strategy_catalog()


@app.post("/api/research/validate")
def validate_request(request: ResearchRequest):
    return {"accepted": True, "request": request.model_dump(), "status": "validated"}


@app.get("/api/stats")
def stats(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {"total": 0, "promising": 0, "needs_imp": 0, "rejected": 0, "best_sharpe": None, "avg_sharpe": None}


@app.get("/api/jobs")
def jobs(request: Request):
    if not _authed(request):
        return _unauthorized()
    # Persistent job execution belongs to the worker service, not a Vercel
    # request function. Returning an empty list is honest until that worker is
    # connected; the frontend must not manufacture completed research.
    return []


@app.get("/api/strategies")
def strategies(request: Request):
    if not _authed(request):
        return _unauthorized()
    return []


@app.get("/api/bot/status")
def bot_status(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {
        "running": False,
        "status": "stopped",
        "started_at": None,
        "stopped_at": None,
        "error": "No persistent paper-trading worker is connected to this Vercel deployment.",
        "symbols": [],
        "intervals": [],
        "interval": "1h",
        "strategy": "",
        "capital": 0,
        "cash": 0,
        "equity": 0,
        "unrealized_pnl": 0,
        "realized_pnl": 0,
        "drawdown": 0,
        "open_positions": [],
        "recent_trades": [],
        "log_tail": [],
        "mark_prices": {},
    }


@app.get("/api/bot/instances")
def bot_instances(request: Request):
    if not _authed(request):
        return _unauthorized()
    return []


@app.get("/api/bot/portfolio")
def bot_portfolio(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {
        "capital": 0,
        "cash": 0,
        "equity": 0,
        "unrealized_pnl": 0,
        "realized_pnl": 0,
        "n_instances": 0,
        "n_running": 0,
        "n_failed": 0,
    }


@app.get("/api/settings")
def settings(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {
        "db_path": "research.db",
        "reports_dir": "reports",
        "data_dir": "market_data",
        "log_path": "logs/research.log",
        "env_vars": {},
        "using_default_creds": True,
    }


@app.get("/api/scheduler")
def scheduler(request: Request):
    if not _authed(request):
        return _unauthorized()
    return []


@app.get("/api/logs")
def logs(request: Request):
    if not _authed(request):
        return _unauthorized()
    return {"lines": []}


@app.get("/api")
def root():
    return {"name": "Strategy Lab", "status": "ok", "time": datetime.now(timezone.utc).isoformat()}
