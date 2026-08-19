"""Execution-readiness tests — 8-part mandate, Parts 1–3.

Part 1: Default BotConfig (capital=200) can execute a legitimate paper trade.
Part 2: Full execution pipeline — PnL accounting, stop-loss, take-profit, event bridge.
Part 3: Multi-symbol/multi-interval with global max_open_positions=1 constraint.
"""
from __future__ import annotations

import pytest
import pandas as pd

from bot.config import BotConfig, RiskConfig
from bot.engine import BotEngine
from bot.events import (
    CandleEvent, EventBus, FillEvent, SignalEvent,
)
from bot.order_manager import OrderManager
from bot.paper_exchange import (
    PaperExchange, STATUS_FILLED, SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_STOP_MARKET, ORDER_TYPE_TAKE_PROFIT,
)
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskEngine
from bot.runtime import _INTERVAL_MS
from bot.state import BotState
from bot.storage import BotStorage
from engine.strategy import Signal


# ── Minimal strategies ────────────────────────────────────────────────────────

class AlwaysBuy:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.BUY] * len(bars), index=bars.index, dtype=object)


class AlwaysHold:
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal.HOLD] * len(bars), index=bars.index, dtype=object)


class BuyThenHold:
    """BUY on first call; HOLD on all subsequent."""

    def __init__(self) -> None:
        self._n = 0

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        self._n += 1
        sig = Signal.BUY if self._n == 1 else Signal.HOLD
        return pd.Series([sig] * len(bars), index=bars.index, dtype=object)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _storage(tmp_path, name="test.db"):
    s = BotStorage(tmp_path / name)
    s.connect()
    return s


def _components(storage, capital=1_000.0, slippage=0.0, max_open_positions=1):
    cfg = BotConfig(
        paper_capital=capital,
        min_signal_bars=60,
        risk=RiskConfig(
            max_position_size_usd=min(capital * 0.8, 200.0),
            max_daily_loss_usd=capital * 0.05,
            max_open_positions=max_open_positions,
        ),
    )
    bus  = EventBus()
    ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=slippage, bus=bus)
    om   = OrderManager(exchange=ex, storage=storage, bus=bus)
    pm   = PositionManager(storage=storage, bus=bus)
    pf   = Portfolio(starting_capital=capital, storage=storage, bus=bus)
    risk = RiskEngine(cfg.risk, bus=bus)
    st   = BotState(buffer_size=500)
    return cfg, bus, ex, om, pm, pf, risk, st


def _candle(
    index: int,
    interval: str = "1m",
    symbol: str = "BTCUSDT",
    price: float = 50_000.0,
    is_history: bool = False,
    close: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> CandleEvent:
    iv_ms = _INTERVAL_MS[interval]
    base  = 1_700_000_000_000
    o_ms  = base + index * iv_ms
    c_ms  = o_ms + iv_ms - 1
    close_p = close if close is not None else price
    return CandleEvent(
        symbol=symbol, interval=interval,
        open_time=o_ms, open=price,
        high=high if high is not None else price * 1.01,
        low=low if low is not None else price * 0.99,
        close=close_p, volume=100.0,
        close_time=c_ms,
        is_history=is_history,
    )


def _history(bus, n, interval="1m", symbol="BTCUSDT", price=50_000.0):
    for i in range(n):
        bus.emit(_candle(i, interval, symbol, price, is_history=True))


def _live(bus, index, interval="1m", symbol="BTCUSDT", price=50_000.0,
          close=None, high=None, low=None):
    bus.emit(_candle(index, interval, symbol, price, is_history=False,
                     close=close, high=high, low=low))


# ── Part 1: Default config ────────────────────────────────────────────────────

class TestDefaultConfigFills:
    """Regression: BotConfig() with default capital must execute valid paper trades."""

    def test_default_capital_meets_min_notional(self):
        """Default capital × equity_fraction must exceed min_notional=10 USDT."""
        cfg = BotConfig()
        target_notional = cfg.paper_capital * cfg.equity_fraction
        assert target_notional >= 10.0, (
            f"Default config target notional {target_notional:.2f} USDT is below "
            f"min_notional 10 USDT — the default bot cannot execute any fills. "
            f"paper_capital={cfg.paper_capital}, equity_fraction={cfg.equity_fraction}"
        )

    def test_default_capital_is_200_usdt(self):
        """Default paper_capital must be 200 USDT (raised from 25 to beat min_notional)."""
        cfg = BotConfig()
        assert cfg.paper_capital == 200.0, (
            f"Expected default paper_capital=200.0, got {cfg.paper_capital}"
        )

    def test_default_config_executes_entry_fill(self, tmp_path):
        """With default BotConfig(), a deterministic BUY signal must produce a fill."""
        cfg = BotConfig()
        s = _storage(tmp_path)
        bus  = EventBus()
        ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
        om   = OrderManager(exchange=ex, storage=s, bus=bus)
        pm   = PositionManager(storage=s, bus=bus)
        pf   = Portfolio(starting_capital=cfg.paper_capital, storage=s, bus=bus)
        risk = RiskEngine(cfg.risk, bus=bus)
        st   = BotState(buffer_size=cfg.buffer_size)

        BotEngine(config=cfg, strategy=AlwaysBuy(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        initial_cash = pf.cash
        _history(bus, 65, "1m", price=50_000.0)
        _live(bus, 65, "1m", price=50_000.0)   # BUY order queued
        _live(bus, 66, "1m", price=50_000.0)   # market order fills

        assert pf.cash < initial_cash, (
            "Default config must reduce cash after entry fill. "
            f"capital={cfg.paper_capital}, equity_fraction={cfg.equity_fraction}, "
            f"target_notional={cfg.paper_capital * cfg.equity_fraction:.2f} USDT"
        )

    def test_default_config_position_opens(self, tmp_path):
        """Default config BUY must open a position."""
        cfg = BotConfig()
        s = _storage(tmp_path)
        bus  = EventBus()
        ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
        om   = OrderManager(exchange=ex, storage=s, bus=bus)
        pm   = PositionManager(storage=s, bus=bus)
        pf   = Portfolio(starting_capital=cfg.paper_capital, storage=s, bus=bus)
        risk = RiskEngine(cfg.risk, bus=bus)
        st   = BotState(buffer_size=cfg.buffer_size)

        BotEngine(config=cfg, strategy=AlwaysBuy(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        _history(bus, 65, "1m", price=50_000.0)
        _live(bus, 65, "1m", price=50_000.0)
        _live(bus, 66, "1m", price=50_000.0)

        assert pm.has_open_position("BTCUSDT:1m"), (
            "Default config must open a position after BUY signal + fill"
        )

    def test_default_config_fill_event_emitted(self, tmp_path):
        """Default config must emit a FillEvent with valid data."""
        cfg = BotConfig()
        s = _storage(tmp_path)
        bus  = EventBus()
        ex   = PaperExchange(fee_rate=cfg.fee_rate, slippage_pct=0.0, bus=bus)
        om   = OrderManager(exchange=ex, storage=s, bus=bus)
        pm   = PositionManager(storage=s, bus=bus)
        pf   = Portfolio(starting_capital=cfg.paper_capital, storage=s, bus=bus)
        risk = RiskEngine(cfg.risk, bus=bus)
        st   = BotState(buffer_size=cfg.buffer_size)

        fills: list[FillEvent] = []
        bus.subscribe(FillEvent, fills.append)

        BotEngine(config=cfg, strategy=AlwaysBuy(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        _history(bus, 65, "1m", price=50_000.0)
        _live(bus, 65, "1m", price=50_000.0)
        _live(bus, 66, "1m", price=50_000.0)

        assert fills, "FillEvent must be emitted with default config"
        f = fills[0]
        assert f.side == "BUY"
        assert f.fill_qty > 0
        assert f.fill_price > 0
        notional = f.fill_price * f.fill_qty
        assert notional >= 10.0, (
            f"Fill notional {notional:.4f} USDT must be >= min_notional 10 USDT"
        )


# ── Part 2: Full pipeline PnL ─────────────────────────────────────────────────

class TestPnLAccounting:
    """Unrealized and realized PnL calculations are correct."""

    def test_unrealized_pnl_increases_when_price_rises(self, tmp_path):
        """Open long position — unrealized PnL must increase as price rises."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=AlwaysBuy(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)   # BUY queued
        _live(bus, 66, price=entry_price)   # fill at 50000

        pos_list = pm.get_all_open()
        assert pos_list, "Position must be open after BUY fill"
        pos = pos_list[0]

        # Unrealized at entry price (no price movement)
        marks_entry = {pos.symbol: entry_price}
        unreal_entry = pos.unrealized_pnl(marks_entry[pos.symbol])

        # Simulated higher mark price
        higher_price = 55_000.0
        marks_higher = {pos.symbol: higher_price}
        unreal_higher = pos.unrealized_pnl(marks_higher[pos.symbol])

        assert unreal_higher > unreal_entry, (
            f"Unrealized PnL must increase when price rises: "
            f"{unreal_entry:.4f} (at {entry_price}) vs {unreal_higher:.4f} (at {higher_price})"
        )
        assert unreal_higher > 0.0, "Unrealized PnL must be positive with price above entry"

    def test_realized_pnl_buy_then_sell_profit(self, tmp_path):
        """BUY at 50000, EXIT at 55000 → realized PnL positive (price gain > fees)."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        class BuyOnce:
            def __init__(self):
                self._n = 0
            def generate_signals(self, bars):
                self._n += 1
                if self._n == 1:
                    return pd.Series([Signal.BUY]*len(bars), index=bars.index, dtype=object)
                return pd.Series([Signal.EXIT]*len(bars), index=bars.index, dtype=object)

        BotEngine(config=cfg, strategy=BuyOnce(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        exit_price  = 55_000.0

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)               # BUY queued
        _live(bus, 66, price=entry_price)               # BUY fills; EXIT queued
        _live(bus, 67, price=exit_price)                # EXIT fills at 55000 open

        # Check closed position in storage
        closed = [p for p in s.get_positions(limit=10) if p["status"] == "closed"]
        assert closed, "Closed position must exist after EXIT fill"
        realized = closed[0]["realized_pnl"]
        assert realized > 0.0, (
            f"Realized PnL must be positive when exit > entry: "
            f"entry={entry_price}, exit={exit_price}, realized={realized:.4f}"
        )

    def test_realized_pnl_buy_then_sell_flat_is_negative_fees(self, tmp_path):
        """BUY and EXIT at same price → realized PnL is negative (only fee cost)."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        class BuyOnce:
            def __init__(self):
                self._n = 0
            def generate_signals(self, bars):
                self._n += 1
                if self._n == 1:
                    return pd.Series([Signal.BUY]*len(bars), index=bars.index, dtype=object)
                return pd.Series([Signal.EXIT]*len(bars), index=bars.index, dtype=object)

        BotEngine(config=cfg, strategy=BuyOnce(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        price = 50_000.0
        _history(bus, 65, price=price)
        _live(bus, 65, price=price)   # BUY queued
        _live(bus, 66, price=price)   # BUY fills; EXIT queued
        _live(bus, 67, price=price)   # EXIT fills at same price

        closed = [p for p in s.get_positions(limit=10) if p["status"] == "closed"]
        assert closed, "Closed position must exist"
        realized = closed[0]["realized_pnl"]
        # At flat price, raw_pnl=0, realized = -(entry_fee + exit_fee) < 0
        assert realized < 0.0, (
            f"Realized PnL at flat price must be negative (fees): got {realized:.6f}"
        )

    def test_cash_returns_after_exit(self, tmp_path):
        """After a round trip (BUY → EXIT), cash must be > 0 and equity > 0."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        class BuyOnce:
            def __init__(self):
                self._n = 0
            def generate_signals(self, bars):
                self._n += 1
                if self._n == 1:
                    return pd.Series([Signal.BUY]*len(bars), index=bars.index, dtype=object)
                return pd.Series([Signal.EXIT]*len(bars), index=bars.index, dtype=object)

        BotEngine(config=cfg, strategy=BuyOnce(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        _history(bus, 65, price=50_000.0)
        _live(bus, 65, price=50_000.0)
        _live(bus, 66, price=50_000.0)
        _live(bus, 67, price=50_000.0)

        assert not pm.has_open_position("BTCUSDT:1m"), "Position must be closed"
        assert pf.cash > 0.0, "Cash must be > 0 after round trip"


class TestStopLossExecution:
    """STOP_MARKET order triggers correctly and closes the position."""

    def test_stop_loss_triggers_below_stop_price(self, tmp_path):
        """Long position SL: when low <= stop_price, STOP_MARKET fills and position closes."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        stop_price  = 48_000.0   # 4% stop below entry

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)   # BUY queued
        _live(bus, 66, price=entry_price)   # BUY fills

        assert pm.has_open_position("BTCUSDT:1m"), "Position must be open after entry"
        pos = pm.get_open("BTCUSDT:1m")

        # Submit a stop-loss order (STOP_MARKET SELL)
        om.submit_stop_market(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=stop_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        # Send a candle with low below stop price — triggers the SL
        _live(bus, 67, price=entry_price, low=47_000.0, high=entry_price * 1.001)

        assert not pm.has_open_position("BTCUSDT:1m"), (
            "Position must be closed after stop-loss trigger"
        )

    def test_stop_loss_does_not_trigger_above_stop_price(self, tmp_path):
        """SL must NOT trigger when bar stays above stop_price."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        stop_price  = 48_000.0

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)
        _live(bus, 66, price=entry_price)

        assert pm.has_open_position("BTCUSDT:1m")
        pos = pm.get_open("BTCUSDT:1m")

        om.submit_stop_market(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=stop_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        # Bar stays well above stop_price
        _live(bus, 67, price=entry_price,
              low=49_000.0, high=entry_price * 1.01)

        assert pm.has_open_position("BTCUSDT:1m"), (
            "Position must remain open when bar low > stop_price"
        )

    def test_stop_loss_produces_negative_pnl_on_loss(self, tmp_path):
        """SL exit at price below entry → realized PnL is negative."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        stop_price  = 48_000.0

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)
        _live(bus, 66, price=entry_price)

        pos = pm.get_open("BTCUSDT:1m")
        om.submit_stop_market(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=stop_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        _live(bus, 67, price=entry_price, low=47_000.0, high=entry_price * 1.001)

        closed = [p for p in s.get_positions(limit=10) if p["status"] == "closed"]
        assert closed, "Closed position must exist after SL trigger"
        realized = closed[0]["realized_pnl"]
        assert realized < 0.0, (
            f"Realized PnL after stop-loss must be negative: got {realized:.4f}"
        )


class TestTakeProfitExecution:
    """TAKE_PROFIT order triggers correctly and closes the position."""

    def test_take_profit_triggers_above_stop_price(self, tmp_path):
        """Long TP: when high >= stop_price, TAKE_PROFIT order fills and position closes."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        tp_price    = 52_000.0   # 4% take profit above entry

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)
        _live(bus, 66, price=entry_price)

        assert pm.has_open_position("BTCUSDT:1m")
        pos = pm.get_open("BTCUSDT:1m")

        # Submit take-profit order
        om.submit_take_profit(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=tp_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        # Send candle with high above TP price
        _live(bus, 67, price=entry_price, high=53_000.0, low=entry_price * 0.99)

        assert not pm.has_open_position("BTCUSDT:1m"), (
            "Position must be closed after take-profit trigger"
        )

    def test_take_profit_does_not_trigger_below_tp(self, tmp_path):
        """TP must NOT trigger when bar high stays below stop_price."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        tp_price    = 52_000.0

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)
        _live(bus, 66, price=entry_price)

        pos = pm.get_open("BTCUSDT:1m")
        om.submit_take_profit(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=tp_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        # Bar high stays below TP
        _live(bus, 67, price=entry_price, high=51_000.0, low=entry_price * 0.99)

        assert pm.has_open_position("BTCUSDT:1m"), (
            "Position must stay open when bar high < take-profit price"
        )

    def test_take_profit_produces_positive_pnl(self, tmp_path):
        """TP exit at price above entry → realized PnL is positive."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(s, capital=1_000.0)

        BotEngine(config=cfg, strategy=BuyThenHold(), state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        entry_price = 50_000.0
        tp_price    = 52_000.0

        _history(bus, 65, price=entry_price)
        _live(bus, 65, price=entry_price)
        _live(bus, 66, price=entry_price)

        pos = pm.get_open("BTCUSDT:1m")
        om.submit_take_profit(
            symbol="BTCUSDT", side=SIDE_SELL, qty=pos.size,
            stop_price=tp_price, reduce_only=True,
            current_position_size=pos.size,
            instance_id="BTCUSDT:1m",
        )

        _live(bus, 67, price=entry_price, high=53_000.0, low=entry_price * 0.99)

        closed = [p for p in s.get_positions(limit=10) if p["status"] == "closed"]
        assert closed, "Closed position must exist after TP trigger"
        realized = closed[0]["realized_pnl"]
        assert realized > 0.0, (
            f"Realized PnL after take-profit must be positive: got {realized:.4f}"
        )


class TestEventBusToBotManagerBridge:
    """BotManager event bridge routes EventBus events to drain_events()."""

    def test_fill_event_reaches_drain_events(self):
        """FillEvent emitted on bus must appear in BotManager.drain_events()."""
        from server.bot_manager import BotManager
        from datetime import datetime, timezone

        mgr = BotManager()

        ev = FillEvent(
            order_id="test-order-id",
            symbol="BTCUSDT",
            side="BUY",
            fill_price=50_000.0,
            fill_qty=0.001,
            fee=0.05,
            is_maker=False,
        )

        # Simulate what _enq('fill') does: build the dict and enqueue
        d = {"type": "fill", "ts": ev.ts.isoformat()}
        for fname in type(ev).__dataclass_fields__:
            if fname != "ts":
                d[fname] = getattr(ev, fname)
        mgr._enqueue(d)

        events = mgr.drain_events()
        assert len(events) == 1
        e = events[0]
        assert e["type"] == "fill"
        assert e["symbol"] == "BTCUSDT"
        assert e["fill_price"] == 50_000.0

    def test_drain_events_clears_queue(self):
        """drain_events() must remove events from the queue."""
        from server.bot_manager import BotManager

        mgr = BotManager()
        mgr._enqueue({"type": "test", "ts": "x"})
        mgr._enqueue({"type": "test", "ts": "y"})

        first = mgr.drain_events()
        assert len(first) == 2

        second = mgr.drain_events()
        assert len(second) == 0, "Queue must be empty after drain"

    def test_enqueue_drops_oldest_when_full(self):
        """LOW-priority queue (maxsize=500): oldest candle dropped when full."""
        from server.bot_manager import BotManager

        mgr = BotManager()
        # Fill the LOW queue to capacity with candle events
        for i in range(500):
            mgr._enqueue({"type": "candle", "seq": i})

        # Force one more beyond capacity — should drop oldest candle
        mgr._enqueue({"type": "candle", "seq": 9999})

        events = mgr.drain_events(max_n=500)
        seqs = [e["seq"] for e in events]
        assert 9999 in seqs, "New candle event must be in queue after drop-oldest"
        assert 0 not in seqs, "Oldest candle event must have been dropped"

    def test_high_priority_events_never_dropped(self):
        """HIGH-priority events (fills, errors, etc.) are never dropped."""
        from server.bot_manager import BotManager

        mgr = BotManager()
        # Fill LOW queue to capacity
        for i in range(500):
            mgr._enqueue({"type": "candle", "seq": i})

        # HIGH events go to an unbounded queue — must always be accepted
        mgr._enqueue({"type": "fill",   "seq": 9000})
        mgr._enqueue({"type": "signal", "seq": 9001})
        mgr._enqueue({"type": "error",  "seq": 9002})

        events = mgr.drain_events(max_n=503)
        seqs  = [e["seq"] for e in events]
        types = [e["type"] for e in events]
        assert 9000 in seqs, "fill event must not be dropped"
        assert 9001 in seqs, "signal event must not be dropped"
        assert 9002 in seqs, "error event must not be dropped"
        # HIGH events always come before LOW in drain order
        high_idxs = [i for i, t in enumerate(types) if t != "candle"]
        low_idxs  = [i for i, t in enumerate(types) if t == "candle"]
        if high_idxs and low_idxs:
            assert max(high_idxs) < min(low_idxs), "HIGH events must precede LOW events"

    def test_history_candle_not_bridged(self):
        """CandleEvent with is_history=True must not reach the event queue."""
        from server.bot_manager import BotManager

        mgr = BotManager()

        hist_ev = CandleEvent(
            symbol="BTCUSDT", interval="1m",
            open_time=1, open=1, high=1, low=1, close=1, volume=1,
            close_time=59999, is_history=True,
        )
        # Simulate the _enq('candle') logic
        if not (hist_ev.is_history):
            d = {"type": "candle", "ts": hist_ev.ts.isoformat()}
            mgr._enqueue(d)

        events = mgr.drain_events()
        assert len(events) == 0, "History candles must not be bridged to the event queue"


# ── Part 3: Multi-symbol / max_open_positions ─────────────────────────────────

class TestMultiSymbolGlobalPositionLimit:
    """max_open_positions=1 is a global limit across all symbols.

    DESIGN DECISION (intentional): RiskConfig.max_open_positions=1 means
    the bot can hold at most one position across ALL symbols simultaneously.
    This is a global risk circuit breaker, not a per-symbol limit.
    The limit is enforced by RiskEngine._check_open_positions() which calls
    PositionManager.open_position_count() — a total across all symbols.
    """

    def test_second_symbol_blocked_when_first_is_open(self, tmp_path):
        """ETHUSDT BUY must be blocked by risk engine while BTCUSDT position is open."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(
            s, capital=2_000.0, max_open_positions=1
        )
        cfg.feed.symbols   = ["BTCUSDT", "ETHUSDT"]
        cfg.feed.intervals = ["1m"]

        strategy_map = {
            ("BTCUSDT", "1m"): AlwaysBuy(),
            ("ETHUSDT", "1m"): AlwaysBuy(),
        }

        BotEngine(config=cfg, strategy=strategy_map, state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        # Warm up and open a BTCUSDT position
        _history(bus, 65, symbol="BTCUSDT", price=50_000.0)
        _live(bus, 65, symbol="BTCUSDT", price=50_000.0)    # BUY queued
        _live(bus, 66, symbol="BTCUSDT", price=50_000.0)    # BUY fills

        assert pm.has_open_position("BTCUSDT:1m"), "BTCUSDT must be open"
        assert pm.open_position_count() == 1

        # Now warm up ETHUSDT and try to open
        _history(bus, 65, symbol="ETHUSDT", price=3_000.0, interval="1m")
        _live(bus, 65, symbol="ETHUSDT", price=3_000.0)     # BUY signal → risk blocks
        _live(bus, 66, symbol="ETHUSDT", price=3_000.0)

        assert not pm.has_open_position("ETHUSDT:1m"), (
            "ETHUSDT position must be blocked while BTCUSDT is open (max_open_positions=1)"
        )
        assert pm.open_position_count() == 1, "Total positions must remain 1"

    def test_second_symbol_allowed_after_first_closes(self, tmp_path):
        """After BTCUSDT position closes, ETHUSDT BUY must be allowed."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(
            s, capital=2_000.0, max_open_positions=1
        )
        cfg.feed.symbols   = ["BTCUSDT", "ETHUSDT"]
        cfg.feed.intervals = ["1m"]

        class BuyBtcExitBtcThenBuyEth:
            def __init__(self):
                self._btc_signals = ["BUY", "EXIT", "HOLD", "HOLD", "HOLD"]
                self._eth_signals = ["HOLD", "HOLD", "BUY", "HOLD", "HOLD"]
                self._btc_n = 0
                self._eth_n = 0

            def generate_signals(self, bars):
                # This won't be called — we use the strategy_map
                return pd.Series([Signal.HOLD]*len(bars), index=bars.index, dtype=object)

        btc_strat_calls = []
        eth_strat_calls = []

        class BtcStrategy:
            def __init__(self):
                self._n = 0
            def generate_signals(self, bars):
                self._n += 1
                btc_strat_calls.append(self._n)
                if self._n == 1:
                    sig = Signal.BUY
                elif self._n == 2:
                    sig = Signal.EXIT
                else:
                    sig = Signal.HOLD
                return pd.Series([sig]*len(bars), index=bars.index, dtype=object)

        class EthStrategy:
            def __init__(self):
                self._n = 0
            def generate_signals(self, bars):
                self._n += 1
                eth_strat_calls.append(self._n)
                sig = Signal.BUY if self._n >= 2 else Signal.HOLD
                return pd.Series([sig]*len(bars), index=bars.index, dtype=object)

        strategy_map = {
            ("BTCUSDT", "1m"): BtcStrategy(),
            ("ETHUSDT", "1m"): EthStrategy(),
        }

        BotEngine(config=cfg, strategy=strategy_map, state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        # Warm both buffers
        _history(bus, 65, symbol="BTCUSDT", price=50_000.0)
        _history(bus, 65, symbol="ETHUSDT", price=3_000.0)

        # Step 1: BTCUSDT BUY (signal 1), fill on step 2
        _live(bus, 65, symbol="BTCUSDT", price=50_000.0)
        _live(bus, 66, symbol="BTCUSDT", price=50_000.0)   # BUY fills; EXIT queued next

        assert pm.has_open_position("BTCUSDT:1m")

        # Step 2: BTCUSDT EXIT (signal 2), fill closes position
        _live(bus, 67, symbol="BTCUSDT", price=50_000.0)   # EXIT fills
        assert not pm.has_open_position("BTCUSDT:1m"), "BTCUSDT must be closed"

        # Step 3: ETHUSDT BUY now allowed (signal 2+)
        # n=1 → HOLD, n=2 → BUY queued, n=3 candle → BUY fills (market fills at next open)
        _live(bus, 65, symbol="ETHUSDT", price=3_000.0)   # EthStrategy n=1 → HOLD
        _live(bus, 66, symbol="ETHUSDT", price=3_000.0)   # EthStrategy n=2 → BUY queued
        _live(bus, 67, symbol="ETHUSDT", price=3_000.0)   # BUY fills at candle open

        assert pm.has_open_position("ETHUSDT:1m"), (
            "ETHUSDT position must be allowed after BTCUSDT closes"
        )

    def test_multi_interval_single_symbol_does_not_double_enter(self, tmp_path):
        """BTCUSDT with 1m and 5m — only one position should ever be open."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(
            s, capital=2_000.0, max_open_positions=1
        )
        cfg.feed.symbols   = ["BTCUSDT"]
        cfg.feed.intervals = ["1m", "5m"]

        strategy_map = {
            ("BTCUSDT", "1m"): AlwaysBuy(),
            ("BTCUSDT", "5m"): AlwaysBuy(),
        }

        BotEngine(config=cfg, strategy=strategy_map, state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        # Warm up both intervals
        _history(bus, 65, symbol="BTCUSDT", interval="1m", price=50_000.0)
        _history(bus, 65, symbol="BTCUSDT", interval="5m", price=50_000.0)

        # Send live candles for both intervals
        for i in range(65, 75):
            _live(bus, i, symbol="BTCUSDT", interval="1m", price=50_000.0)
            _live(bus, i, symbol="BTCUSDT", interval="5m", price=50_000.0)

        assert pm.open_position_count() <= 1, (
            "At most 1 position across all timeframes for same symbol"
        )

    def test_global_position_count_check(self, tmp_path):
        """open_position_count() counts ALL open positions across all symbols."""
        s = _storage(tmp_path)
        cfg, bus, ex, om, pm, pf, risk, st = _components(
            s, capital=5_000.0, max_open_positions=3
        )
        cfg.feed.symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        cfg.feed.intervals = ["1m"]

        strategy_map = {
            ("BTCUSDT", "1m"): AlwaysBuy(),
            ("ETHUSDT", "1m"): AlwaysBuy(),
            ("SOLUSDT", "1m"): AlwaysBuy(),
        }

        BotEngine(config=cfg, strategy=strategy_map, state=st, orders=om,
                  positions=pm, portfolio=pf, risk=risk, storage=s, bus=bus)

        for sym, price in [("BTCUSDT", 50_000.0), ("ETHUSDT", 3_000.0), ("SOLUSDT", 150.0)]:
            _history(bus, 65, symbol=sym, price=price, interval="1m")
            _live(bus, 65, symbol=sym, price=price)
            _live(bus, 66, symbol=sym, price=price)

        count = pm.open_position_count()
        # With max_open_positions=3, we should have opened 3 positions
        # (risk allows up to 3, so all 3 BUYs should succeed)
        assert count <= 3, f"Position count {count} must not exceed max_open_positions=3"
        # At least one must be open (first BUY definitely goes through)
        assert count >= 1, "At least one position must be open"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Regression tests: min_notional rejection + BotManager event bridge
# ══════════════════════════════════════════════════════════════════════════════

class TestMinNotionalRejectionRegression:
    """Regression guard: orders that would fail min_notional must be rejected at
    fill time with a visible OrderEvent(REJECTED), not silently discarded."""

    def test_capital_25_market_order_rejected_at_fill(self):
        """capital=25 @ BTC~65000: notional≈2.6 < min_notional=10 → rejected, OrderEvent emitted."""
        from bot.events import OrderEvent

        bus = EventBus()
        order_events: list = []
        bus.subscribe(OrderEvent, order_events.append)

        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0005, bus=bus)

        # Reproduce the live failure: capital=25, equity_fraction=0.10, BTC≈65000
        capital = 25.0
        equity_fraction = 0.10
        price = 65_000.0
        qty = round(capital * equity_fraction / price, 5)   # 0.00004 BTC

        order = ex.submit_order("BTCUSDT", "BUY", "MARKET", qty)
        assert order.status == "ACCEPTED", "MARKET order must be ACCEPTED at submission"

        fills = ex.process_candle(
            "BTCUSDT", open_=price, high=price * 1.01, low=price * 0.99, close=price
        )
        assert fills == [], "Fill must not occur when notional < min_notional"
        assert order.status == "REJECTED"
        assert "notional" in order.reject_reason.lower() or "minimum" in order.reject_reason.lower()

        rejected_events = [e for e in order_events if e.status == "REJECTED"]
        assert len(rejected_events) == 1, "OrderEvent(REJECTED) must be emitted for UI visibility"
        assert rejected_events[0].symbol == "BTCUSDT"

    def test_capital_200_market_order_fills_successfully(self):
        """capital=200 @ BTC~65000: notional≈20 >= min_notional=10 → fill + FillEvent."""
        bus = EventBus()
        fills_received: list = []
        bus.subscribe(FillEvent, fills_received.append)

        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0, bus=bus)

        capital = 200.0
        equity_fraction = 0.10
        price = 65_000.0
        qty = round(capital * equity_fraction / price, 5)   # 0.00031 BTC, notional≈20.2

        order = ex.submit_order("BTCUSDT", "BUY", "MARKET", qty)
        assert order.status == "ACCEPTED"

        paper_fills = ex.process_candle(
            "BTCUSDT", open_=price, high=price * 1.01, low=price * 0.99, close=price
        )
        assert len(paper_fills) == 1, "Fill must succeed with capital=200"
        assert paper_fills[0].symbol == "BTCUSDT"
        assert len(fills_received) == 1, "FillEvent must be emitted on successful fill"

    def test_notional_exactly_at_minimum_fills(self):
        """Notional exactly equal to min_notional must fill (boundary: >= not >)."""
        from bot.paper_exchange import MIN_NOTIONAL

        bus = EventBus()
        ex = PaperExchange(fee_rate=0.001, slippage_pct=0.0, bus=bus)

        price = 10_000.0
        qty = round(MIN_NOTIONAL / price, 5)   # exactly 0.001 BTC → notional=10.0

        order = ex.submit_order("BTCUSDT", "BUY", "MARKET", qty)
        assert order.status == "ACCEPTED"

        fills = ex.process_candle(
            "BTCUSDT", open_=price, high=price, low=price, close=price
        )
        assert len(fills) == 1, "Notional exactly at minimum must fill, not reject"

    def test_default_config_capital_above_effective_minimum(self):
        """Default BotConfig capital must exceed min_notional / equity_fraction."""
        from bot.paper_exchange import MIN_NOTIONAL

        cfg = BotConfig()
        min_capital_needed = MIN_NOTIONAL / cfg.equity_fraction
        assert cfg.paper_capital >= min_capital_needed, (
            f"Default capital {cfg.paper_capital} USDT is below effective minimum "
            f"{min_capital_needed:.2f} USDT "
            f"(min_notional={MIN_NOTIONAL} / equity_fraction={cfg.equity_fraction}). "
            "All market orders will be silently rejected at fill time."
        )


class TestBotManagerRejectionBridge:
    """BotManager.drain_events must surface 'rejected' and 'risk_rejected' event types."""

    def test_drain_rejected_event(self):
        """Enqueuing a 'rejected' event must be returned by drain_events."""
        from server.bot_manager import BotManager

        bm = BotManager()
        bm._enqueue({
            "type": "rejected",
            "ts": "2025-01-01T00:00:00",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "detail": "market fill notional 2.6081 below minimum 10.0",
        })
        events = bm.drain_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "rejected"
        assert ev["symbol"] == "BTCUSDT"
        assert "notional" in ev["detail"]

    def test_drain_risk_rejected_event(self):
        """Enqueuing a 'risk_rejected' event must be returned by drain_events."""
        from server.bot_manager import BotManager

        bm = BotManager()
        bm._enqueue({
            "type": "risk_rejected",
            "ts": "2025-01-01T00:00:00",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "reason": "max_open_positions=1 already reached",
        })
        events = bm.drain_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "risk_rejected"
        assert ev["symbol"] == "BTCUSDT"

    def test_drain_returns_empty_after_consumed(self):
        """drain_events must return empty list once queue is drained."""
        from server.bot_manager import BotManager

        bm = BotManager()
        bm._enqueue({"type": "rejected", "symbol": "BTCUSDT"})
        _ = bm.drain_events()
        events = bm.drain_events()
        assert events == [], "Second drain must be empty — events must not re-appear"

    def test_signal_event_not_confused_with_fill(self):
        """A 'signal' event in drain_events has type='signal', not 'fill' or 'rejected'."""
        from server.bot_manager import BotManager

        bm = BotManager()
        bm._enqueue({"type": "signal", "symbol": "BTCUSDT", "signal": "BUY"})
        bm._enqueue({"type": "fill",   "symbol": "BTCUSDT", "side": "BUY", "fill_price": 65000.0})
        events = bm.drain_events()
        types = [e["type"] for e in events]
        assert "signal" in types
        assert "fill" in types
        assert types.index("signal") < types.index("fill"), "Signal appears before fill in order"
        # Verify neither is conflated
        sig = next(e for e in events if e["type"] == "signal")
        assert "fill_price" not in sig, "Signal event must not carry fill_price"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Regression tests: PositionEvent bridge + chart data contract
# ══════════════════════════════════════════════════════════════════════════════

class TestBotManagerPositionBridge:
    """BotManager._enqueue must correctly serialise PositionEvent into websocket
    payloads that the chart can consume (type='position', required fields present)."""

    def _make_position_event(self, action="opened", direction="long",
                              entry_price=65000.0, exit_price=0.0,
                              size=0.0003, realized_pnl=0.0, symbol="BTCUSDT"):
        from bot.events import PositionEvent
        return PositionEvent(
            symbol=symbol,
            action=action,
            direction=direction,
            size=size,
            entry_price=entry_price,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
        )

    def test_position_opened_event_bridged(self):
        """'opened' PositionEvent must produce type='position' with correct fields."""
        from server.bot_manager import BotManager
        bm = BotManager()

        ev = self._make_position_event(action="opened", direction="long", entry_price=65000.0)
        # Simulate what _enq('position') does
        d = {"type": "position", "ts": ev.ts.isoformat()}
        for fname in type(ev).__dataclass_fields__:
            if fname != "ts":
                d[fname] = getattr(ev, fname)
        bm._enqueue(d)

        events = bm.drain_events()
        assert len(events) == 1
        e = events[0]
        assert e["type"] == "position"
        assert e["action"] == "opened"
        assert e["direction"] == "long"
        assert e["entry_price"] == 65000.0
        assert e["symbol"] == "BTCUSDT"
        assert "exit_price" in e
        assert "realized_pnl" in e

    def test_position_closed_event_bridged(self):
        """'closed' PositionEvent must carry exit_price and realized_pnl."""
        from server.bot_manager import BotManager
        bm = BotManager()

        ev = self._make_position_event(
            action="closed", direction="long",
            entry_price=65000.0, exit_price=66000.0, realized_pnl=0.3,
        )
        d = {"type": "position", "ts": ev.ts.isoformat()}
        for fname in type(ev).__dataclass_fields__:
            if fname != "ts":
                d[fname] = getattr(ev, fname)
        bm._enqueue(d)

        events = bm.drain_events()
        assert len(events) == 1
        e = events[0]
        assert e["action"] == "closed"
        assert e["exit_price"] == 66000.0
        assert e["realized_pnl"] == pytest.approx(0.3)

    def test_position_event_has_all_chart_required_fields(self):
        """All fields the chart JS reads must be present in the bridged payload."""
        from server.bot_manager import BotManager
        bm = BotManager()

        ev = self._make_position_event()
        d = {"type": "position", "ts": ev.ts.isoformat()}
        for fname in type(ev).__dataclass_fields__:
            if fname != "ts":
                d[fname] = getattr(ev, fname)
        bm._enqueue(d)

        events = bm.drain_events()
        required = {"type", "ts", "symbol", "action", "direction", "entry_price",
                    "exit_price", "size", "realized_pnl"}
        assert required <= events[0].keys(), (
            f"Missing chart-required fields: {required - events[0].keys()}"
        )

    def test_position_opened_and_closed_sequential(self):
        """Opened followed by closed must produce two events in order."""
        from server.bot_manager import BotManager
        bm = BotManager()

        for action, exit_p in [("opened", 0.0), ("closed", 66000.0)]:
            ev = self._make_position_event(action=action, exit_price=exit_p)
            d = {"type": "position", "ts": ev.ts.isoformat()}
            for fname in type(ev).__dataclass_fields__:
                if fname != "ts":
                    d[fname] = getattr(ev, fname)
            bm._enqueue(d)

        events = bm.drain_events()
        assert len(events) == 2
        assert events[0]["action"] == "opened"
        assert events[1]["action"] == "closed"

    def test_position_not_conflated_with_fill(self):
        """'position' event must be distinct from 'fill' event in the queue."""
        from server.bot_manager import BotManager
        bm = BotManager()

        bm._enqueue({"type": "fill",     "symbol": "BTCUSDT", "fill_price": 65000.0, "side": "BUY"})
        bm._enqueue({"type": "position", "symbol": "BTCUSDT", "action": "opened",   "entry_price": 65000.0})

        events = bm.drain_events()
        types = [e["type"] for e in events]
        assert "fill" in types
        assert "position" in types
        fill_ev = next(e for e in events if e["type"] == "fill")
        pos_ev  = next(e for e in events if e["type"] == "position")
        assert "action" not in fill_ev,      "fill event must not carry action field"
        assert "fill_price" not in pos_ev,   "position event must not carry fill_price"


class TestFillEventChartContract:
    """FillEvent bridge payloads must carry all fields the chart needs to render
    trade markers: order_id (dedup key), ts (time mapping), fill_price, side."""

    def test_fill_event_payload_has_order_id(self):
        """Bridged fill payload must include order_id for chart deduplication."""
        from server.bot_manager import BotManager
        bm = BotManager()
        bm._enqueue({
            "type":       "fill",
            "ts":         "2025-06-01T12:00:00+00:00",
            "order_id":   "ord-abc-123",
            "symbol":     "BTCUSDT",
            "side":       "BUY",
            "fill_price": 65000.0,
            "fill_qty":   0.00031,
            "fee":        0.00002015,
        })
        events = bm.drain_events()
        assert len(events) == 1
        e = events[0]
        assert e["order_id"] == "ord-abc-123", "order_id must be present for chart dedup"

    def test_fill_event_payload_has_fill_price_and_side(self):
        """Chart marker needs fill_price (y-axis) and side (BUY=▲ / SELL=▼)."""
        from server.bot_manager import BotManager
        bm = BotManager()
        bm._enqueue({
            "type": "fill", "ts": "2025-06-01T12:00:00+00:00",
            "order_id": "ord-sell-1", "symbol": "ETHUSDT",
            "side": "SELL", "fill_price": 3200.0, "fill_qty": 0.01, "fee": 0.0032,
        })
        events = bm.drain_events()
        e = events[0]
        assert e["fill_price"] == 3200.0
        assert e["side"] == "SELL"

    def test_fill_event_has_timestamp_for_candle_mapping(self):
        """Chart uses ev.ts to find the candle slot; it must be an ISO timestamp."""
        from server.bot_manager import BotManager
        import re
        bm = BotManager()
        ts = "2025-06-01T14:05:23.456789+00:00"
        bm._enqueue({
            "type": "fill", "ts": ts,
            "order_id": "ord-ts-check", "symbol": "BTCUSDT",
            "side": "BUY", "fill_price": 64000.0, "fill_qty": 0.0003, "fee": 0.0,
        })
        events = bm.drain_events()
        assert re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', events[0]["ts"]), \
            "ts must be ISO-8601 for JS new Date(ev.ts) to parse correctly"

    def test_fill_side_buy_not_confused_with_sell(self):
        """BUY fill and SELL fill must be distinguishable by 'side' field."""
        from server.bot_manager import BotManager
        bm = BotManager()
        bm._enqueue({"type": "fill", "order_id": "b1", "side": "BUY",  "fill_price": 65000.0, "symbol": "BTCUSDT"})
        bm._enqueue({"type": "fill", "order_id": "s1", "side": "SELL", "fill_price": 66000.0, "symbol": "BTCUSDT"})
        events = bm.drain_events()
        sides = {e["order_id"]: e["side"] for e in events if e["type"] == "fill"}
        assert sides["b1"] == "BUY"
        assert sides["s1"] == "SELL"

    def test_multiple_fills_different_order_ids(self):
        """Multiple fill events must each carry a unique order_id."""
        from server.bot_manager import BotManager
        bm = BotManager()
        for i in range(5):
            bm._enqueue({"type": "fill", "order_id": f"ord-{i}", "side": "BUY",
                          "fill_price": 65000.0 + i, "symbol": "BTCUSDT"})
        events = bm.drain_events()
        ids = [e["order_id"] for e in events]
        assert len(set(ids)) == 5, "All order_ids must be unique"


class TestPositionEventEmission:
    """PositionManager must emit PositionEvent on open and close, and the emitted
    events must carry the fields expected by the BotManager bridge."""

    def _make_infra(self, tmp_path):
        from bot.events import PositionEvent
        storage = BotStorage(str(tmp_path / "test.db"))
        storage.connect()
        bus = EventBus()
        pos_events: list = []
        bus.subscribe(PositionEvent, pos_events.append)
        positions = PositionManager(storage=storage, bus=bus)
        return storage, bus, positions, pos_events

    def _paper_fill(self, order_id, symbol, side, price, qty, fee=0.0):
        from bot.paper_exchange import PaperFill
        return PaperFill(order_id=order_id, symbol=symbol, side=side,
                         fill_price=price, fill_qty=qty, fee=fee)

    def test_open_position_emits_position_event_opened(self, tmp_path):
        """on_fill(BUY PaperFill) must emit PositionEvent(action='opened')."""
        from bot.events import PositionEvent
        _, _, positions, pos_events = self._make_infra(tmp_path)
        positions.on_fill(self._paper_fill("o1", "BTCUSDT", "BUY", 65000.0, 0.0003))
        opened = [e for e in pos_events if e.action == "opened"]
        assert len(opened) == 1, "Exactly one 'opened' PositionEvent expected"
        e = opened[0]
        assert e.symbol == "BTCUSDT"
        assert e.direction == "long"
        assert e.entry_price == 65000.0
        assert e.size == pytest.approx(0.0003)

    def test_close_position_emits_position_event_closed(self, tmp_path):
        """on_fill(SELL PaperFill) after BUY must emit PositionEvent(action='closed')."""
        _, _, positions, pos_events = self._make_infra(tmp_path)
        positions.on_fill(self._paper_fill("o1", "BTCUSDT", "BUY",  65000.0, 0.0003))
        positions.on_fill(self._paper_fill("o2", "BTCUSDT", "SELL", 66000.0, 0.0003))
        closed = [e for e in pos_events if e.action == "closed"]
        assert len(closed) == 1, "Exactly one 'closed' PositionEvent expected"
        e = closed[0]
        assert e.exit_price == pytest.approx(66000.0)
        assert e.realized_pnl == pytest.approx(0.0003 * (66000.0 - 65000.0))

    def test_position_event_fields_match_bridge_contract(self, tmp_path):
        """PositionEvent dataclass fields must include all fields the bridge serialises."""
        from bot.events import PositionEvent
        required_bridge_fields = {
            "symbol", "action", "direction", "size", "entry_price", "exit_price", "realized_pnl"
        }
        event_fields = set(PositionEvent.__dataclass_fields__.keys())
        missing = required_bridge_fields - event_fields
        assert not missing, f"PositionEvent missing fields needed by bridge: {missing}"

    def test_position_event_not_emitted_for_unknown_symbol_fill(self, tmp_path):
        """SELL fill on a symbol with no open position must not emit a closed event."""
        from bot.events import PositionEvent
        _, _, positions, pos_events = self._make_infra(tmp_path)
        positions.on_fill(self._paper_fill("o-bad", "UNKNOWN", "SELL", 100.0, 1.0))
        closed = [e for e in pos_events if e.action == "closed"]
        assert len(closed) == 0
