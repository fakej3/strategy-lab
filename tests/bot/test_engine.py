"""Integration tests for BotEngine signal→order pipeline."""
from __future__ import annotations

import pandas as pd
import pytest

from bot.config import BotConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, EventBus, FillEvent, SignalEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import PaperExchange
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskEngine
from bot.state import BotState
from bot.storage import BotStorage
from engine.strategy import Signal


# ── Minimal strategy fixtures ─────────────────────────────────────────────────

class AlwaysBuy:
    """Strategy that signals BUY on every bar."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.BUY] * len(bars), index=bars.index)


class AlwaysSell:
    """Strategy that signals EXIT on every bar."""
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.EXIT] * len(bars), index=bars.index)


class AlwaysHold:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.HOLD] * len(bars), index=bars.index)


@pytest.fixture
def storage(tmp_path):
    s = BotStorage(tmp_path / "test.db")
    s.connect()
    return s


@pytest.fixture
def components(storage):
    # Use paper_capital=1000 so that the default equity_fraction (10%) produces
    # a notional of 100 USDT, which is well above the 10 USDT MIN_NOTIONAL.
    # With paper_capital=25 the notional would be 2.5 USDT — correctly rejected
    # by the at-fill notional check introduced in Phase 4.
    cfg  = BotConfig(paper_capital=1000.0)
    bus  = EventBus()
    ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
    om   = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm   = PositionManager(storage=storage, bus=bus)
    pf   = Portfolio(starting_capital=cfg.paper_capital, storage=storage, bus=bus)
    risk = RiskEngine(cfg.risk, bus=bus)
    state = BotState(buffer_size=100)
    return cfg, bus, om, pm, pf, risk, state, storage


def _make_engine(strategy, components):
    cfg, bus, om, pm, pf, risk, state, storage = components
    return BotEngine(
        config=cfg, strategy=strategy,
        state=state, orders=om, positions=pm,
        portfolio=pf, risk=risk, storage=storage, bus=bus,
    )


def _emit_candles(bus, n=70, symbol="BTCUSDT", interval="1h", price=50000.0):
    """Emit n closed candle events to fill the buffer."""
    import time as _time
    base_ms = 1700000000000
    interval_ms = 3_600_000
    for i in range(n):
        open_ms  = base_ms + i * interval_ms
        close_ms = open_ms + interval_ms - 1
        bus.emit(CandleEvent(
            symbol=symbol, interval=interval,
            open_time=open_ms, open=price, high=price * 1.01,
            low=price * 0.99, close=price, volume=100.0,
            close_time=close_ms,
        ))


class TestBotEngine:
    def test_buy_signal_submits_order(self, components):
        engine = _make_engine(AlwaysBuy(), components)
        _, bus, om, *_ = components
        _emit_candles(bus, n=65)
        # At least one open or filled order
        orders = om.get_open_orders("BTCUSDT")
        all_orders = om.exchange.get_all_orders("BTCUSDT")
        assert len(all_orders) > 0

    def test_hold_does_not_submit_order(self, components):
        engine = _make_engine(AlwaysHold(), components)
        _, bus, om, *_ = components
        _emit_candles(bus, n=65)
        all_orders = om.exchange.get_all_orders("BTCUSDT")
        assert len(all_orders) == 0

    def test_signal_event_emitted(self, components):
        engine = _make_engine(AlwaysBuy(), components)
        _, bus, *_ = components
        signals = []
        bus.subscribe(SignalEvent, signals.append)
        _emit_candles(bus, n=65)
        assert len(signals) > 0
        assert signals[-1].signal == "BUY"

    def test_fill_updates_portfolio(self, components):
        cfg, bus, om, pm, pf, *_ = components
        engine = _make_engine(AlwaysBuy(), components)
        initial_cash = pf.cash
        # Emit candles: first 60 fill buffer; candle 61 triggers BUY order;
        # candle 62's open fills the market order
        _emit_candles(bus, n=65)
        # After fill, cash should be reduced
        assert pf.cash < initial_cash

    def test_no_double_entry(self, components):
        """Once a position is open, another BUY signal is ignored."""
        _, bus, om, pm, pf, *_ = components
        engine = _make_engine(AlwaysBuy(), components)
        _emit_candles(bus, n=70)
        open_positions = pm.get_all_open()
        assert len(open_positions) <= 1   # only one open at a time

    def test_risk_blocks_when_no_trades_allowed(self, components):
        """Risk engine blocks all entries when max_daily_trades=0."""
        cfg, bus, om, pm, pf, risk, state, storage = components
        cfg.risk.max_daily_trades = 0   # no trades allowed today
        engine = _make_engine(AlwaysBuy(), components)
        _emit_candles(bus, n=65)
        # Risk blocks before submission, so no orders reach the exchange
        all_orders = om.exchange.get_all_orders("BTCUSDT")
        assert len(all_orders) == 0
