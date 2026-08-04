"""Paper Trading Bot — production-quality paper trading on live Binance data.

Architecture rule: this package imports ONLY from ``lab/`` and ``shared/``.
It must never import from engine, portfolio, research, jobs, automation,
data, pipeline, or server directly.

See ARCHITECTURE.md for the full integration guide.
See bot_trade.py for the entry point.
"""
from .config import BotConfig, FeedConfig, RiskConfig
from .events import EventBus, BotEvent

__all__ = ["BotConfig", "FeedConfig", "RiskConfig", "EventBus", "BotEvent"]
