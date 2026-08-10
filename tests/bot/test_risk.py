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


class TestTotalExposureLimit:
    """Phase 2: portfolio-level total exposure cap."""

    def test_disabled_when_zero(self):
        cfg = RiskConfig(max_total_exposure_usd=0.0, max_open_positions=10,
                         max_position_size_usd=1_000_000.0)
        risk = RiskEngine(cfg)
        # Huge existing exposure — still passes when limit is 0 (disabled)
        assert risk.check(_ctx(total_exposure=1_000_000.0, qty=1.0, ref_price=50_000.0)) == ""

    def test_passes_within_limit(self):
        cfg = RiskConfig(max_total_exposure_usd=200.0, max_open_positions=10,
                         max_position_size_usd=200.0)
        risk = RiskEngine(cfg)
        # existing=100, new order=50 → total=150 < 200
        assert risk.check(_ctx(total_exposure=100.0, qty=0.001, ref_price=50_000.0)) == ""

    def test_rejected_when_projected_exceeds_limit(self):
        cfg = RiskConfig(max_total_exposure_usd=150.0, max_open_positions=10,
                         max_position_size_usd=200.0)
        risk = RiskEngine(cfg)
        # existing=100, new order notional=60 → total=160 > 150
        reason = risk.check(_ctx(total_exposure=100.0, qty=0.001, ref_price=60_000.0))
        assert reason != ""
        assert "exposure" in reason

    def test_exactly_at_limit_is_rejected(self):
        cfg = RiskConfig(max_total_exposure_usd=150.0, max_open_positions=10,
                         max_position_size_usd=200.0)
        risk = RiskEngine(cfg)
        # existing=100, new=50 → projected=150 which is NOT > 150 → passes
        assert risk.check(_ctx(total_exposure=100.0, qty=0.001, ref_price=50_000.0)) == ""

    def test_exposure_check_before_position_size_check(self):
        # exposure check fires first when both would reject
        cfg = RiskConfig(
            max_total_exposure_usd=50.0,
            max_position_size_usd=30.0,
            max_open_positions=10,
        )
        risk = RiskEngine(cfg)
        # new order notional=40 > position size limit=30 AND > exposure headroom
        reason = risk.check(_ctx(total_exposure=20.0, qty=0.001, ref_price=40_000.0))
        assert "exposure" in reason  # total exposure fires first


class TestMaxOpenPositionsConfigurable:
    """Phase 2: max_open_positions must be independently configurable."""

    def test_single_symbol_mode(self):
        cfg = RiskConfig(max_open_positions=1, max_position_size_usd=50_000.0)
        risk = RiskEngine(cfg)
        assert risk.check(_ctx(open_positions=0)) == ""
        assert risk.check(_ctx(open_positions=1)) != ""

    def test_three_symbol_mode(self):
        cfg = RiskConfig(max_open_positions=3, max_position_size_usd=50_000.0)
        risk = RiskEngine(cfg)
        assert risk.check(_ctx(open_positions=2)) == ""
        assert risk.check(_ctx(open_positions=3)) != ""

    def test_fifty_symbol_mode(self):
        cfg = RiskConfig(max_open_positions=50, max_position_size_usd=50_000.0)
        risk = RiskEngine(cfg)
        assert risk.check(_ctx(open_positions=49)) == ""
        assert risk.check(_ctx(open_positions=50)) != ""


class TestBotManagerMaxOpenPositions:
    """Phase 2: BotManager.start() defaults max_open_positions to len(symbols)."""

    def _start_and_get_config(self, symbols, max_open_positions=None):
        from server.bot_manager import BotManager
        mgr = BotManager()
        # Intercept config before the thread starts
        captured = {}
        original_run = mgr._run_in_thread

        def _capture():
            with mgr._lock:
                captured['cfg'] = mgr._config
            # Don't actually run the bot thread
        mgr._run_in_thread = _capture

        kwargs = dict(capital=200.0, symbols=symbols)
        if max_open_positions is not None:
            kwargs['max_open_positions'] = max_open_positions
        mgr.start(**kwargs)
        mgr._thread.join(timeout=2)
        return captured.get('cfg')

    def test_single_symbol_defaults_to_one(self):
        cfg = self._start_and_get_config(["BTCUSDT"])
        assert cfg is not None
        assert cfg.risk.max_open_positions == 1

    def test_three_symbols_defaults_to_three(self):
        cfg = self._start_and_get_config(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
        assert cfg is not None
        assert cfg.risk.max_open_positions == 3

    def test_explicit_override(self):
        cfg = self._start_and_get_config(
            ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            max_open_positions=1,
        )
        assert cfg is not None
        assert cfg.risk.max_open_positions == 1

    def test_total_exposure_cap_set(self):
        cfg = self._start_and_get_config(["BTCUSDT", "ETHUSDT"])
        assert cfg is not None
        # 80% of 200 USDT capital
        assert cfg.risk.max_total_exposure_usd == pytest.approx(160.0, rel=0.01)
