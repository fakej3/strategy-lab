"""Strategy Labs web API entry point.

The browser is only a client. Quantitative computation remains in Python so
pandas/numpy/scipy-style numerical research can run server-side rather than on
the user's phone or laptop.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Strategy Labs API", version="2.0.0")


class HealthResponse(BaseModel):
    status: str
    engine: str
    computation: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine="strategy-labs-v2",
        computation="server-side-python",
    )


class ResearchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=1, max_length=16)
    start: str
    end: str
    initial_capital: float = Field(gt=0)


@app.post("/api/research/validate")
def validate_request(request: ResearchRequest):
    """Validate the shape of a research request before adding job execution.

    Actual backtests are intentionally not run here yet; the endpoint is a
    stable seam for the web client while the V2 engine is being hardened.
    """
    return {
        "accepted": True,
        "request": request.model_dump(),
        "status": "queued-contract-only",
    }
