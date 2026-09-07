from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

app = FastAPI(title="Strategy Lab API", version="2.1.0")
SESSION_COOKIE = "strategy_lab_session"


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


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", engine="strategy-labs-v2", computation="server-side-python")


@app.post("/api/auth/login")
def login(payload: dict[str, Any], response: Response):
    # Temporary demo authentication for the public test deployment.
    # Replace with real secret-backed authentication before any non-demo use.
    if payload.get("username") != "admin" or payload.get("password") != "admin":
        response.status_code = 401
        return {"ok": False, "message": "Invalid credentials"}
    response.set_cookie(SESSION_COOKIE, "demo-admin", httponly=True, samesite="lax", secure=True, max_age=86400)
    return {"ok": True, "user": {"username": "admin"}}


@app.get("/api/auth/me")
def me(request: Request):
    if not _authed(request):
        return Response(content='{"detail":"Unauthorized"}', status_code=401, media_type="application/json")
    return {"username": "admin", "authenticated": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.post("/api/research/validate")
def validate_request(request: ResearchRequest):
    return {"accepted": True, "request": request.model_dump(), "status": "queued-contract-only"}


@app.get("/api/stats")
def stats(request: Request):
    if not _authed(request):
        return Response(status_code=401)
    return {"total": 0}


@app.get("/api/jobs")
def jobs(request: Request):
    if not _authed(request):
        return Response(status_code=401)
    return []


@app.get("/api/logs")
def logs(request: Request):
    if not _authed(request):
        return Response(status_code=401)
    return {"lines": []}


@app.get("/api/strategies")
def strategies(request: Request):
    if not _authed(request):
        return Response(status_code=401)
    return []


@app.get("/api/bot/status")
def bot_status(request: Request):
    if not _authed(request):
        return Response(status_code=401)
    return {"running": False}


@app.get("/api")
def root():
    return {"name": "Strategy Lab", "status": "ok", "time": datetime.now(timezone.utc).isoformat()}
