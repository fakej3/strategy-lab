"""Centralised configuration for the Strategy Research Lab.

Re-exports all existing config dataclasses from their canonical packages so
that consumers (and the Trading Bot via lab/) can import everything from one
place without knowing internal package structure.

Also defines placeholder configs for subsystems that don't yet have their own
(DataConfig, ResearchConfig, ServerConfig, TradingBotConfig).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ── Re-exports from canonical packages ────────────────────────────────────────

from automation.pipeline import PipelineConfig
from engine.models import EngineConfig
from portfolio.models import PortfolioConfig, SizingMode

__all__ = [
    # re-exported from existing packages
    "EngineConfig",
    "PortfolioConfig",
    "SizingMode",
    "PipelineConfig",
    # new shared configs
    "DataConfig",
    "ResearchConfig",
    "ServerConfig",
    "TradingBotConfig",
]


@dataclass
class DataConfig:
    """Configuration for the market data layer."""

    data_dir: str          = "market_data"
    default_provider: str  = "binance"
    cache_enabled: bool    = True
    request_timeout_s: int = 30
    max_retries: int       = 3


@dataclass
class ResearchConfig:
    """Configuration for the research / analysis layer."""

    bars_per_year: int   = 252
    min_history_bars: int = 504
    benchmark_symbol: str = "SPY"


@dataclass
class ServerConfig:
    """Configuration for the web API server."""

    host: str  = "0.0.0.0"
    port: int  = 8000
    debug: bool = False
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class TradingBotConfig:
    """Placeholder configuration for the future Trading Bot.

    Fields here are intentionally minimal — the bot has not been implemented.
    This dataclass reserves the namespace and establishes the config contract.
    """

    exchange: str          = "paper"        # "paper" | "binance" | "kraken" …
    api_key: str           = ""
    api_secret: str        = ""
    dry_run: bool          = True
    max_open_positions: int = 1
    risk_per_trade: float  = 0.01           # fraction of equity at risk per trade
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    engine: EngineConfig       = field(default_factory=EngineConfig)
