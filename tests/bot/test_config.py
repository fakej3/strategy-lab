"""Tests for BotConfig."""
from __future__ import annotations

import os

import pytest

from bot.config import BotConfig, FeedConfig, RiskConfig


class TestBotConfig:
    def test_default_config_valid(self):
        cfg = BotConfig()
        assert cfg.paper_capital == 100_000.0
        assert cfg.fee_rate == 0.001
        assert 0 < cfg.equity_fraction <= 1.0
        assert isinstance(cfg.feed, FeedConfig)
        assert isinstance(cfg.risk, RiskConfig)

    def test_invalid_capital_raises(self):
        with pytest.raises(ValueError, match="paper_capital"):
            BotConfig(paper_capital=0.0)

    def test_invalid_equity_fraction_raises(self):
        with pytest.raises(ValueError, match="equity_fraction"):
            BotConfig(equity_fraction=0.0)

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("BOT_CAPITAL",   "50000")
        monkeypatch.setenv("BOT_FEE_RATE",  "0.002")
        monkeypatch.setenv("BOT_SYMBOLS",   "BTCUSDT,ETHUSDT")
        monkeypatch.setenv("BOT_INTERVALS", "1h")
        cfg = BotConfig.from_env()
        assert cfg.paper_capital == 50_000.0
        assert cfg.fee_rate      == 0.002
        assert cfg.feed.symbols  == ["BTCUSDT", "ETHUSDT"]

    def test_feed_defaults(self):
        cfg = FeedConfig()
        assert "BTCUSDT" in cfg.symbols
        assert cfg.backfill_bars == 300
        assert "binance" in cfg.ws_base_url

    def test_risk_defaults(self):
        cfg = RiskConfig()
        assert cfg.max_open_positions == 1
        assert cfg.max_drawdown_pct   == 0.20
