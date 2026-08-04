"""Tests for RiskEngine."""
from __future__ import annotations

import time

import pytest

from bot.config import RiskConfig
from bot.events import EventBus
from bot.risk import RiskContext, RiskEngine


@pytest.fixture
def cfg():
    return RiskConfig(
        max_risk_pct=0.02,
        max_position_size_usd=50_000.0,
        max_daily_loss_usd=2_000.0,
        max_drawdown_pct=0.20,
        max_leverage=1.0,
        max_open_positions=1,
        trading_cooldown_s=0.0,
        max_daily_trades=50,
    )


@pytest.fixture
def risk(cfg):
    return RiskEngine(cfg, bus=EventBus())


def _ctx(**kwargs):
    defaults = dict(
        symbol="BTCUSDT", side="BUY", qty=0.1, ref_price=50000.0,
        equity=100_000.0, peak_equity=100_000.0,
        daily_pnl=0.0, n_trades_today=0,
        open_positions=0, last_trade_ts=0.0,
    )
    defaults.update(kwargs)
    return RiskContext(**defaults)


class TestRiskEngine:
    def test_clean_order_passes(self, risk):
        assert risk.check(_ctx()) == ""

    def test_daily_loss_halt(self, risk):
        reason = risk.check(_ctx(daily_pnl=-2001.0))
        assert reason != ""
        assert "daily loss" in reason

    def test_daily_loss_not_triggered_below_limit(self, risk):
        assert risk.check(_ctx(daily_pnl=-1999.0)) == ""

    def test_max_drawdown_halt(self, risk):
        # Equity dropped 25% from peak
        reason = risk.check(_ctx(equity=75_000.0, peak_equity=100_000.0))
        assert reason != ""
        assert "drawdown" in reason

    def test_max_daily_trades(self, risk):
        reason = risk.check(_ctx(n_trades_today=50))
        assert "daily trades" in reason

    def test_max_open_positions(self, risk):
        reason = risk.check(_ctx(open_positions=1))
        assert "open positions" in reason

    def test_max_position_size(self, risk):
        # qty=2, ref_price=50000 → notional=100_000 > 50_000
        reason = risk.check(_ctx(qty=2.0, ref_price=50000.0))
        assert "position size" in reason

    def test_cooldown(self, cfg):
        cfg.trading_cooldown_s = 60.0
        risk = RiskEngine(cfg)
        # last trade 10 seconds ago
        reason = risk.check(_ctx(last_trade_ts=time.monotonic() - 10))
        assert "cooldown" in reason

    def test_cooldown_expired(self, cfg):
        cfg.trading_cooldown_s = 5.0
        risk = RiskEngine(cfg)
        reason = risk.check(_ctx(last_trade_ts=time.monotonic() - 10))
        assert reason == ""

    def test_zero_peak_equity_skips_drawdown(self, risk):
        assert risk.check(_ctx(equity=0.0, peak_equity=0.0)) == ""
