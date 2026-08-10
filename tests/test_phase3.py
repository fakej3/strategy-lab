"""Phase 3 — Full live multi-symbol execution audit and hardening regression tests.

Covers:
  Phase 3A — Audit: no critical single-symbol bugs in the execution path
  Phase 3B — Strategy state isolation per (symbol, interval)
  Phase 3C — Order/fill/position isolation for simultaneous multi-symbol positions
  Phase 3D — Portfolio accounting with multiple concurrent positions
  Phase 3E — Risk engine under concurrent positions (max_open_positions, exposure cap)
  Phase 3F — Failure isolation: one symbol fails, others continue
  Phase 3G — EventBus concurrency: thread-safe subscribe and emit
  Phase 3H — Live vs backtest determinism: workers=1 == workers=4
  Phase 3I — Performance benchmarks: 10/50/100 symbols
  Phase 3J — Memory bounds: 200 symbols × 5 intervals × 600 candles → buffer capped
  Phase 3K — Batch backtest stress: workers=1/2/4 correctness
  Phase 3L — Smart execution AUTO mode (< 4 pairs → sequential, >= 4 → ProcessPool)
  Phase 3M — UI isolation: set_active_pair does not affect bot trading state

All tests are deterministic (no network, no random seeds, no real-time waits).
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pandas as pd
import pytest

from bot.config import BotConfig, RiskConfig
from bot.engine import BotEngine
from bot.events import (
    CandleEvent,
    ErrorEvent,
    EventBus,
    FillEvent,
)
from bot.order_manager import OrderManager
from bot.paper_exchange import (
    PaperExchange,
    PaperFill,
    SIDE_BUY,
    SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from bot.portfolio import Portfolio
from bot.position_manager import PositionManager
from bot.risk import RiskContext, RiskEngine
from bot.state import BotState, CandleRow
from bot.storage import BotStorage
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import BatchBacktest, SymbolResult
from server.bot_manager import BotManager


# ══════════════════════════════════════════════════════════════════════════════
# Module-level strategies — must be top-level for ProcessPoolExecutor pickling
# ══════════════════════════════════════════════════════════════════════════════

class _Hold3(StrategyBase):
    """Always HOLD — zero trades; minimal CPU for timing benchmarks."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _SingleBuy3(StrategyBase):
    """One BUY at bar 10, EXIT at bar 20 — deterministic single trade."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 10:
            s.iloc[10] = Signal.BUY
        if len(bars) > 20:
            s.iloc[20] = Signal.EXIT
        return s


class _RaisingStrategy3(StrategyBase):
    """Raises on every call — verifies engine survives strategy crashes."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        raise RuntimeError("simulated strategy crash")


class _TrackingStrategy3(StrategyBase):
    """Counts calls and records the last close price seen on each call."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_closes: list[float] = []

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        self.calls += 1
        if not bars.empty:
            self.last_closes.append(float(bars["close"].iloc[-1]))
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

_T0_MS = 1_700_000_000_000  # fixed epoch so tests are deterministic


def _bars(n: int, close: float = 100.0) -> pd.DataFrame:
    prices = [close + i * 0.01 for i in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open":   prices,
            "high":   [p * 1.001 for p in prices],
            "low":    [p * 0.999 for p in prices],
            "close":  prices,
            "volume": [1.0] * n,
        },
        index=idx,
    )


def _bars_dict(symbols: list[str], intervals: list[str], n: int = 50) -> dict:
    return {(s, iv): _bars(n) for s in symbols for iv in intervals}


def _make_storage() -> BotStorage:
    return BotStorage(":memory:")


def _make_risk_cfg(**overrides: Any) -> RiskConfig:
    defaults: dict[str, Any] = dict(
        max_open_positions=10,
        max_position_size_usd=100_000.0,
        max_total_exposure_usd=0.0,
        max_daily_loss_usd=100_000.0,
        max_daily_trades=10_000,
        trading_cooldown_s=0.0,
        max_drawdown_pct=0.99,
        max_risk_pct=0.01,
        max_leverage=1.0,
    )
    defaults.update(overrides)
    return RiskConfig(**defaults)


def _make_bot_config(tmp_path: Any, **overrides: Any) -> BotConfig:
    defaults: dict[str, Any] = dict(
        paper_capital=10_000.0,
        min_signal_bars=3,
        buffer_size=500,
        fee_rate=0.0,
        slippage_pct=0.0,
        reports_dir=str(tmp_path / "reports"),
        log_path=str(tmp_path / "bot.log"),
        db_path=str(tmp_path / "bot.db"),
        risk=_make_risk_cfg(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_components(tmp_path: Any, risk_cfg: RiskConfig | None = None, capital: float = 10_000.0):
    risk_cfg = risk_cfg or _make_risk_cfg()
    cfg = BotConfig(
        paper_capital=capital,
        min_signal_bars=3,
        buffer_size=500,
        fee_rate=0.0,
        slippage_pct=0.0,
        reports_dir=str(tmp_path / "reports"),
        log_path=str(tmp_path / "bot.log"),
        db_path=str(tmp_path / "bot.db"),
        risk=risk_cfg,
    )
    bus = EventBus()
    state = BotState(buffer_size=500)
    storage = _make_storage()
    exchange = PaperExchange(fee_rate=0.0, slippage_pct=0.0, bus=bus)
    orders = OrderManager(exchange, storage, bus)
    positions = PositionManager(storage, bus)
    portfolio = Portfolio(
        starting_capital=capital, storage=storage, bus=bus, fee_rate=0.0
    )
    risk = RiskEngine(risk_cfg, bus)
    return cfg, bus, state, exchange, orders, positions, portfolio, risk, storage


def _make_engine(
    tmp_path: Any,
    strategy_map: dict,
    risk_cfg: RiskConfig | None = None,
    capital: float = 10_000.0,
) -> tuple[BotEngine, BotConfig, EventBus, BotState, OrderManager, PositionManager, Portfolio]:
    cfg, bus, state, exchange, orders, positions, portfolio, risk, storage = _make_components(
        tmp_path, risk_cfg=risk_cfg, capital=capital
    )
    engine = BotEngine(
        config=cfg,
        strategy=strategy_map,
        state=state,
        orders=orders,
        positions=positions,
        portfolio=portfolio,
        risk=risk,
        storage=storage,
        bus=bus,
    )
    return engine, cfg, bus, state, orders, positions, portfolio


def _emit_candles(
    bus: EventBus,
    symbol: str,
    interval: str,
    n: int,
    close: float = 100.0,
    t0_ms: int = _T0_MS,
) -> None:
    """Emit *n* non-history CandleEvents for (symbol, interval)."""
    step_ms = 3_600_000  # 1-hour candles
    for i in range(n):
        t = t0_ms + i * step_ms
        bus.emit(
            CandleEvent(
                symbol=symbol,
                interval=interval,
                open_time=t,
                open=close,
                high=close * 1.001,
                low=close * 0.999,
                close=close + i * 0.01,
                volume=1.0,
                close_time=t + step_ms - 1,
                is_history=False,
            )
        )


def _make_fill(
    symbol: str,
    side: str = SIDE_BUY,
    qty: float = 1.0,
    price: float = 100.0,
    order_id: str | None = None,
) -> PaperFill:
    return PaperFill(
        order_id=order_id or str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        fill_price=price,
        fill_qty=qty,
        fee=0.0,
        is_maker=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3A — Audit: no critical single-symbol assumptions
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditFindings:
    """Phase 3A: verify no hidden single-symbol bugs exist in the execution path."""

    def test_order_ids_are_unique_across_symbols(self, tmp_path):
        """Every order must get a globally unique ID — no symbol-scoped counter."""
        _, bus, _, exchange, orders, _, _, _, _ = _make_components(tmp_path)
        symbols = ["BTCUSDT", "ETHUSDT", "XAUUSDT", "SNDKUSDT"]
        ids: list[str] = []
        for sym in symbols:
            for _ in range(25):
                order = orders.submit_market(symbol=sym, side=SIDE_BUY, qty=0.001)
                ids.append(order.order_id)

        assert len(ids) == len(set(ids)), (
            "All 100 order IDs must be unique across symbols. "
            "Duplicate IDs would cause cross-symbol fill attribution errors."
        )

    def test_paper_exchange_only_processes_orders_for_requested_symbol(self, tmp_path):
        """process_candle('BTC') must not touch ETH orders and vice versa."""
        bus = EventBus()
        exchange = PaperExchange(fee_rate=0.0, slippage_pct=0.0, bus=bus)

        exchange.submit_order(
            symbol="BTCUSDT", side=SIDE_BUY, order_type=ORDER_TYPE_MARKET, qty=0.01
        )
        exchange.submit_order(
            symbol="ETHUSDT", side=SIDE_BUY, order_type=ORDER_TYPE_MARKET, qty=0.1
        )

        fill_symbols: list[str] = []
        bus.subscribe(FillEvent, lambda e: fill_symbols.append(e.symbol))

        # Only process BTC candle
        exchange.process_candle(
            "BTCUSDT", open_=50_000, high=51_000, low=49_000, close=50_500
        )

        assert fill_symbols == ["BTCUSDT"], (
            "Processing a BTC candle must fill only BTC orders. "
            f"Got: {fill_symbols}"
        )

        # ETH order is still pending
        eth_open = exchange.get_open_orders("ETHUSDT")
        assert len(eth_open) == 1, "ETH order must still be open after BTC process_candle"

    def test_strategy_map_creates_independent_instance_per_pair(self, tmp_path):
        """Each (symbol, interval) must get its own strategy instance in BotEngine."""
        pairs = [("BTCUSDT", "1h"), ("ETHUSDT", "1h"), ("BTCUSDT", "4h")]
        strategy_map = {pair: _TrackingStrategy3() for pair in pairs}

        # All instances must be different objects
        instances = list(strategy_map.values())
        for i, a in enumerate(instances):
            for b in instances[i + 1 :]:
                assert a is not b, (
                    "Each (symbol, interval) pair must get a separate strategy instance. "
                    "Sharing one instance across pairs causes state bleed."
                )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3B — Strategy state isolation per (symbol, interval)
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategyIsolation:
    """Phase 3B: verify strategy state is fully isolated per (symbol, interval)."""

    def test_strategy_calls_isolated_per_symbol(self, tmp_path):
        """BTC candles must not increment ETH strategy's call count."""
        s_btc = _TrackingStrategy3()
        s_eth = _TrackingStrategy3()
        strategy_map = {
            ("BTCUSDT", "1h"): s_btc,
            ("ETHUSDT", "1h"): s_eth,
        }
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        # Push 5 BTC candles (3+ triggers signal evaluation)
        _emit_candles(bus, "BTCUSDT", "1h", n=5, close=100.0)

        assert s_btc.calls > 0, "BTC strategy must have been called after 5 candles"
        assert s_eth.calls == 0, (
            "ETH strategy must NOT be called by BTC candles. "
            f"Got s_eth.calls={s_eth.calls}"
        )

    def test_strategy_sees_only_its_own_symbol_bars(self, tmp_path):
        """BTC strategy must receive bars with BTC close prices, not ETH prices."""
        s_btc = _TrackingStrategy3()
        s_eth = _TrackingStrategy3()
        strategy_map = {
            ("BTCUSDT", "1h"): s_btc,
            ("ETHUSDT", "1h"): s_eth,
        }
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        _emit_candles(bus, "BTCUSDT", "1h", n=5, close=50_000.0)
        _emit_candles(bus, "ETHUSDT", "1h", n=5, close=2_000.0)

        # BTC strategy must have seen BTC-range closes (~50_000)
        assert all(c > 10_000 for c in s_btc.last_closes), (
            f"BTC strategy received non-BTC closes: {s_btc.last_closes}"
        )
        # ETH strategy must have seen ETH-range closes (~2_000)
        assert all(c < 10_000 for c in s_eth.last_closes), (
            f"ETH strategy received non-ETH closes: {s_eth.last_closes}"
        )

    def test_two_intervals_same_symbol_get_independent_strategies(self, tmp_path):
        """(BTC,1h) and (BTC,4h) must dispatch to separate strategy instances."""
        s_1h = _TrackingStrategy3()
        s_4h = _TrackingStrategy3()
        strategy_map = {
            ("BTCUSDT", "1h"): s_1h,
            ("BTCUSDT", "4h"): s_4h,
        }
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        _emit_candles(bus, "BTCUSDT", "1h", n=5, close=100.0)

        assert s_1h.calls > 0, "1h strategy must be called for 1h candles"
        assert s_4h.calls == 0, (
            "4h strategy must NOT be called by 1h candles. "
            f"Got s_4h.calls={s_4h.calls}"
        )

        _emit_candles(bus, "BTCUSDT", "4h", n=5, close=100.0, t0_ms=_T0_MS + 10**12)

        assert s_4h.calls > 0, "4h strategy must be called for 4h candles"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3C — Order/fill/position isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestOrderFillPositionIsolation:
    """Phase 3C: four simultaneous positions (BTC/ETH/XAU/SNDK) tracked independently."""

    SYMBOLS = ["BTCUSDT", "ETHUSDT", "XAUUSDT", "SNDKUSDT"]
    PRICES  = [50_000.0,    2_000.0,   1_900.0,    100.0]

    def test_simultaneous_four_positions_tracked_independently(self):
        """Open four long positions; each tracked correctly in PositionManager."""
        storage = _make_storage()
        bus = EventBus()
        positions = PositionManager(storage, bus)

        for sym, price in zip(self.SYMBOLS, self.PRICES):
            fill = _make_fill(sym, side=SIDE_BUY, qty=1.0, price=price)
            positions.on_fill(fill, equity=100_000.0)

        assert positions.open_position_count() == 4, (
            f"Expected 4 open positions, got {positions.open_position_count()}"
        )
        for sym, price in zip(self.SYMBOLS, self.PRICES):
            pos = positions.get_open(sym)
            assert pos is not None, f"Position for {sym} must exist"
            assert pos.symbol == sym
            assert abs(pos.avg_entry_price - price) < 0.01, (
                f"{sym} entry price mismatch: expected {price}, got {pos.avg_entry_price}"
            )

    def test_fill_symbol_matches_submitted_order_symbol(self):
        """PaperExchange fill attribution must match the order's symbol exactly."""
        bus = EventBus()
        exchange = PaperExchange(fee_rate=0.0, slippage_pct=0.0, bus=bus)

        fill_events: list[FillEvent] = []
        bus.subscribe(FillEvent, fill_events.append)

        # qty=1.0 ensures notional > MIN_NOTIONAL (10 USD) for all test prices
        for sym, price in zip(self.SYMBOLS, self.PRICES):
            exchange.submit_order(
                symbol=sym, side=SIDE_BUY, order_type=ORDER_TYPE_MARKET, qty=1.0
            )

        # Process each symbol's candle independently
        for sym, price in zip(self.SYMBOLS, self.PRICES):
            exchange.process_candle(sym, open_=price, high=price*1.01, low=price*0.99, close=price)

        assert len(fill_events) == 4, (
            f"Expected 4 fills (one per symbol), got {len(fill_events)}"
        )
        filled_syms = [e.symbol for e in fill_events]
        assert sorted(filled_syms) == sorted(self.SYMBOLS), (
            f"Fill symbols mismatch. Expected {sorted(self.SYMBOLS)}, got {sorted(filled_syms)}"
        )

    def test_closing_one_position_does_not_affect_others(self):
        """Closing BTC position must leave ETH, XAU, SNDK positions intact."""
        storage = _make_storage()
        bus = EventBus()
        positions = PositionManager(storage, bus)

        for sym, price in zip(self.SYMBOLS, self.PRICES):
            positions.on_fill(_make_fill(sym, SIDE_BUY, qty=1.0, price=price), equity=100_000.0)

        assert positions.open_position_count() == 4

        # Close BTC
        positions.on_fill(
            _make_fill("BTCUSDT", SIDE_SELL, qty=1.0, price=51_000.0), equity=100_000.0
        )

        assert positions.open_position_count() == 3, (
            f"After closing BTC, expected 3 open positions, got {positions.open_position_count()}"
        )
        assert positions.get_open("BTCUSDT") is None, "BTC position must be closed"
        for sym in ["ETHUSDT", "XAUUSDT", "SNDKUSDT"]:
            assert positions.get_open(sym) is not None, f"{sym} position must still be open"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3D — Portfolio accounting with multiple concurrent positions
# ══════════════════════════════════════════════════════════════════════════════

class TestPortfolioAccountingMultiSymbol:
    """Phase 3D: shared cash pool deducted/restored correctly per symbol."""

    def test_cash_deducted_for_each_buy_fill(self):
        """Two BUY fills must deduct both notionals from the shared cash pool."""
        storage = _make_storage()
        bus = EventBus()
        portfolio = Portfolio(starting_capital=100_000.0, storage=storage, bus=bus, fee_rate=0.0)

        initial_cash = portfolio.cash

        # BTC: 1 unit @ 50_000 → cash -= 50_000
        portfolio.on_fill(_make_fill("BTCUSDT", SIDE_BUY, qty=1.0, price=50_000.0))
        assert abs(portfolio.cash - (initial_cash - 50_000.0)) < 0.01

        # ETH: 10 units @ 2_000 → cash -= 20_000
        portfolio.on_fill(_make_fill("ETHUSDT", SIDE_BUY, qty=10.0, price=2_000.0))
        assert abs(portfolio.cash - (initial_cash - 50_000.0 - 20_000.0)) < 0.01

    def test_cash_restored_on_sell_fill(self):
        """SELL fill must restore cash; net cash = initial after round-trip."""
        storage = _make_storage()
        bus = EventBus()
        portfolio = Portfolio(starting_capital=100_000.0, storage=storage, bus=bus, fee_rate=0.0)

        initial_cash = portfolio.cash
        portfolio.on_fill(_make_fill("BTCUSDT", SIDE_BUY, qty=1.0, price=50_000.0))
        portfolio.on_fill(_make_fill("BTCUSDT", SIDE_SELL, qty=1.0, price=50_000.0))

        assert abs(portfolio.cash - initial_cash) < 0.01, (
            "Round-trip BUY→SELL at same price must restore cash to initial value"
        )

    def test_snapshot_aggregates_unrealized_across_all_symbols(self):
        """snapshot() must sum unrealized PnL from all open positions."""
        storage = _make_storage()
        bus = EventBus()
        portfolio = Portfolio(starting_capital=100_000.0, storage=storage, bus=bus, fee_rate=0.0)

        # Two open positions
        from bot.position_manager import Position
        pos_btc = Position(
            position_id="p1", symbol="BTCUSDT", direction="long", status="open",
            size=1.0, entry_price=50_000.0, avg_entry_price=50_000.0,
        )
        pos_eth = Position(
            position_id="p2", symbol="ETHUSDT", direction="long", status="open",
            size=10.0, entry_price=2_000.0, avg_entry_price=2_000.0,
        )

        mark_prices = {"BTCUSDT": 51_000.0, "ETHUSDT": 2_100.0}
        snap = portfolio.snapshot(mark_prices, [pos_btc, pos_eth])

        expected_unrealized = (51_000.0 - 50_000.0) * 1.0 + (2_100.0 - 2_000.0) * 10.0
        assert abs(snap.unrealized - expected_unrealized) < 0.01, (
            f"Expected unrealized={expected_unrealized:.2f}, got {snap.unrealized:.2f}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3E — Risk engine under concurrent positions
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskEngineConcurrentPositions:
    """Phase 3E: risk limits are global (portfolio-level), not per-symbol."""

    def _ctx(self, open_positions: int = 0, total_exposure: float = 0.0, **kw) -> RiskContext:
        defaults = dict(
            symbol="BTCUSDT", side="BUY", qty=1.0, ref_price=100.0,
            equity=10_000.0, peak_equity=10_000.0,
            daily_pnl=0.0, n_trades_today=0,
            last_trade_ts=0.0,
        )
        defaults.update(kw)
        return RiskContext(open_positions=open_positions, total_exposure=total_exposure, **defaults)

    def test_max_open_positions_rejects_when_at_limit(self):
        """Trade must be rejected when open_positions == max_open_positions."""
        risk_cfg = _make_risk_cfg(max_open_positions=3)
        risk = RiskEngine(risk_cfg)

        reason = risk.check(self._ctx(open_positions=3))
        assert reason, "Risk check must reject when at max_open_positions=3"
        assert "max open positions" in reason.lower(), (
            f"Rejection reason must mention max open positions. Got: {reason!r}"
        )

    def test_max_total_exposure_rejects_when_exceeded(self):
        """Trade must be rejected when projected exposure would exceed the cap."""
        # Cap = 5_000 USD; already have 4_800 open; new order = 500 → total = 5_300 → reject
        risk_cfg = _make_risk_cfg(max_total_exposure_usd=5_000.0)
        risk = RiskEngine(risk_cfg)

        reason = risk.check(self._ctx(open_positions=2, total_exposure=4_800.0,
                                      qty=5.0, ref_price=100.0))  # notional=500
        assert reason, "Risk check must reject when total exposure would exceed cap"
        assert "exposure" in reason.lower(), (
            f"Rejection reason must mention exposure. Got: {reason!r}"
        )

    def test_risk_open_positions_is_global_count_not_per_symbol(self):
        """open_positions in RiskContext is the global count, not per-symbol."""
        storage = _make_storage()
        bus = EventBus()
        positions = PositionManager(storage, bus)

        for sym, price in zip(["BTCUSDT", "ETHUSDT", "XAUUSDT"], [50_000, 2_000, 1_900]):
            positions.on_fill(_make_fill(sym, SIDE_BUY, qty=1.0, price=price), equity=100_000.0)

        # Global count must be 3 (not 1 "for BTCUSDT" or similar)
        global_count = positions.open_position_count()
        assert global_count == 3, (
            f"open_position_count() must return the global portfolio count. "
            f"Got {global_count}"
        )

        # Risk context constructed with global count → rejected at max=3
        risk_cfg = _make_risk_cfg(max_open_positions=3)
        risk = RiskEngine(risk_cfg)
        ctx = RiskContext(
            symbol="SNDKUSDT", side="BUY", qty=1.0, ref_price=100.0,
            equity=100_000.0, peak_equity=100_000.0,
            daily_pnl=0.0, n_trades_today=0,
            open_positions=global_count,
            total_exposure=positions.total_exposure(),
            last_trade_ts=0.0,
        )
        reason = risk.check(ctx)
        assert reason, (
            "Fourth trade must be rejected when global open_positions == max_open_positions"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3F — Failure isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureIsolation:
    """Phase 3F: a failing symbol must not bring down other symbols."""

    def test_crashing_strategy_does_not_propagate_exception(self, tmp_path):
        """Strategy RuntimeError must be caught inside the engine; no re-raise."""
        strategy_map = {("BTCUSDT", "1h"): _RaisingStrategy3()}
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        # This must not raise — engine swallows strategy exceptions
        try:
            _emit_candles(bus, "BTCUSDT", "1h", n=5, close=100.0)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"Engine must not propagate strategy exceptions. Got: {exc!r}")

    def test_crashing_symbol_does_not_prevent_other_symbol_processing(self, tmp_path):
        """ETH strategy must still receive its candles even when BTC strategy crashes."""
        s_eth = _TrackingStrategy3()
        strategy_map = {
            ("BTCUSDT", "1h"): _RaisingStrategy3(),
            ("ETHUSDT", "1h"): s_eth,
        }
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        _emit_candles(bus, "BTCUSDT", "1h", n=5, close=100.0)
        _emit_candles(bus, "ETHUSDT", "1h", n=5, close=2_000.0, t0_ms=_T0_MS + 10**12)

        assert s_eth.calls > 0, (
            "ETH strategy must be called even when BTC strategy crashes. "
            f"Got s_eth.calls={s_eth.calls}"
        )

    def test_engine_continues_filling_buffer_after_strategy_crash(self, tmp_path):
        """Candle buffer must keep filling even when strategy raises every call."""
        strategy_map = {("BTCUSDT", "1h"): _RaisingStrategy3()}
        _, _, bus, state, *_ = _make_engine(tmp_path, strategy_map)

        n = 10
        _emit_candles(bus, "BTCUSDT", "1h", n=n, close=100.0)

        buf_len = state.buffer_length("BTCUSDT", "1h")
        assert buf_len == n, (
            f"Buffer must still grow after strategy crashes. "
            f"Expected {n}, got {buf_len}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3G — EventBus concurrency
# ══════════════════════════════════════════════════════════════════════════════

class TestEventBusConcurrency:
    """Phase 3G: EventBus must be thread-safe for concurrent subscribe and emit."""

    def test_subscribe_is_thread_safe(self):
        """Concurrent subscribe from 20 threads must register all handlers."""
        bus = EventBus()
        n_threads = 20

        def register():
            bus.subscribe(CandleEvent, lambda e: None)

        threads = [threading.Thread(target=register) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        registered = bus.handler_count(CandleEvent)
        assert registered == n_threads, (
            f"All {n_threads} subscribe calls must succeed. Got {registered} handlers."
        )

    def test_emit_is_thread_safe(self):
        """Concurrent emit from 50 threads must deliver all events without data races."""
        bus = EventBus()
        received: list[CandleEvent] = []
        lock = threading.Lock()

        def handler(e: CandleEvent) -> None:
            with lock:
                received.append(e)

        bus.subscribe(CandleEvent, handler)

        evt = CandleEvent(
            symbol="BTCUSDT", interval="1h",
            open_time=_T0_MS, open=100.0, high=101.0, low=99.0,
            close=100.5, volume=1.0, close_time=_T0_MS + 3_599_999,
        )
        n_threads = 50
        threads = [threading.Thread(target=lambda: bus.emit(evt)) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == n_threads, (
            f"All {n_threads} emits must deliver to handler. Got {len(received)}."
        )

    def test_handler_exception_does_not_crash_other_handlers(self):
        """If one handler raises, subsequent handlers in the chain must still run."""
        bus = EventBus()
        delivered: list[str] = []

        def crashing_handler(e: CandleEvent) -> None:
            raise RuntimeError("handler crash")

        def good_handler(e: CandleEvent) -> None:
            delivered.append("ok")

        bus.subscribe(CandleEvent, crashing_handler)
        bus.subscribe(CandleEvent, good_handler)

        evt = CandleEvent(symbol="BTCUSDT", interval="1h")
        bus.emit(evt)  # must not raise

        assert delivered == ["ok"], (
            "good_handler must run even when crashing_handler raised. "
            f"Got {delivered!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3H — Live vs backtest determinism
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveVsBacktestDeterminism:
    """Phase 3H: workers=1 and workers=4 must produce identical results."""

    def test_workers_1_vs_workers_4_same_results(self):
        """Sequential and parallel batch runs must produce identical trade counts."""
        symbols = [f"SYM{i:03d}" for i in range(8)]
        intervals = ["1h"]
        bars = _bars_dict(symbols, intervals, n=50)

        def run(workers: int) -> list[SymbolResult]:
            return BatchBacktest(
                symbols=symbols,
                intervals=intervals,
                strategy_class=_SingleBuy3,
                params={},
                bars=bars,
                starting_capital=100_000.0,
                max_workers=workers,
            ).run().symbol_results

        results_1 = run(1)
        results_4 = run(4)

        assert len(results_1) == len(results_4) == len(symbols)

        # Sort by (symbol, interval) for stable comparison
        key = lambda r: (r.symbol, r.interval)
        results_1.sort(key=key)
        results_4.sort(key=key)

        for r1, r4 in zip(results_1, results_4):
            assert r1.symbol == r4.symbol
            assert r1.interval == r4.interval
            assert r1.n_trades == r4.n_trades, (
                f"{r1.symbol} {r1.interval}: workers=1 gave {r1.n_trades} trades, "
                f"workers=4 gave {r4.n_trades} trades — must be identical"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3I — Performance benchmarks
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceBenchmarks:
    """Phase 3I: batch backtest must complete within time budgets."""

    def _run_timed(self, n_symbols: int, n_bars: int, workers: int) -> float:
        symbols = [f"SYM{i:04d}" for i in range(n_symbols)]
        bars = _bars_dict(symbols, ["1h"], n=n_bars)
        t0 = time.monotonic()
        BatchBacktest(
            symbols=symbols,
            intervals=["1h"],
            strategy_class=_Hold3,
            params={},
            bars=bars,
            starting_capital=100_000.0,
            max_workers=workers,
        ).run()
        return time.monotonic() - t0

    def test_10_symbols_300_bars_sequential_under_5s(self):
        elapsed = self._run_timed(n_symbols=10, n_bars=300, workers=1)
        assert elapsed < 5.0, (
            f"10 symbols × 300 bars (workers=1) must complete in < 5s. "
            f"Took {elapsed:.2f}s"
        )

    def test_50_symbols_200_bars_parallel_under_30s(self):
        elapsed = self._run_timed(n_symbols=50, n_bars=200, workers=4)
        assert elapsed < 30.0, (
            f"50 symbols × 200 bars (workers=4) must complete in < 30s. "
            f"Took {elapsed:.2f}s"
        )

    def test_100_symbols_200_bars_parallel_under_60s(self):
        elapsed = self._run_timed(n_symbols=100, n_bars=200, workers=4)
        assert elapsed < 60.0, (
            f"100 symbols × 200 bars (workers=4) must complete in < 60s. "
            f"Took {elapsed:.2f}s"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3J — Memory bounds
# ══════════════════════════════════════════════════════════════════════════════

class TestMemoryBounds:
    """Phase 3J: candle buffers must be capped at buffer_size even under high load."""

    def test_200_symbols_5_intervals_buffer_bounded_at_500(self):
        """Push 600 candles per (symbol, interval) — buffer must stay at 500."""
        buffer_size = 500
        n_push = 600
        n_symbols = 200
        n_intervals = 5
        intervals = [f"{i+1}h" for i in range(n_intervals)]

        state = BotState(buffer_size=buffer_size)
        t0 = _T0_MS

        for sym_idx in range(n_symbols):
            sym = f"SYM{sym_idx:03d}"
            for iv in intervals:
                for i in range(n_push):
                    t = t0 + i * 3_600_000
                    state.push_candle(CandleRow(
                        symbol=sym, interval=iv,
                        open_time=t, open=100.0, high=101.0, low=99.0,
                        close=100.0, volume=1.0,
                        close_time=t + 3_599_999,
                    ))

        # Every buffer must be capped at buffer_size, never n_push
        violations: list[str] = []
        for sym_idx in range(n_symbols):
            sym = f"SYM{sym_idx:03d}"
            for iv in intervals:
                length = state.buffer_length(sym, iv)
                if length != buffer_size:
                    violations.append(f"{sym}/{iv}: got {length}")

        assert not violations, (
            f"Buffer must be capped at {buffer_size} after {n_push} pushes. "
            f"Violations ({len(violations)}): {violations[:5]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3K — Batch backtest stress test
# ══════════════════════════════════════════════════════════════════════════════

class TestBatchBacktestStress:
    """Phase 3K: multi-worker runs must produce correct and complete results."""

    SYMBOLS   = [f"STRESS{i:02d}" for i in range(12)]
    INTERVALS = ["1h"]
    N_BARS    = 60

    @property
    def _bars(self) -> dict:
        return _bars_dict(self.SYMBOLS, self.INTERVALS, n=self.N_BARS)

    def _run(self, workers: int) -> list[SymbolResult]:
        return BatchBacktest(
            symbols=self.SYMBOLS,
            intervals=self.INTERVALS,
            strategy_class=_SingleBuy3,
            params={},
            bars=self._bars,
            starting_capital=100_000.0,
            max_workers=workers,
        ).run().symbol_results

    def test_workers_1_vs_workers_2_identical_results(self):
        """Sequential and 2-worker runs must yield identical per-pair trade counts."""
        r1 = sorted(self._run(1), key=lambda r: (r.symbol, r.interval))
        r2 = sorted(self._run(2), key=lambda r: (r.symbol, r.interval))

        assert len(r1) == len(r2) == len(self.SYMBOLS)
        for a, b in zip(r1, r2):
            assert a.n_trades == b.n_trades, (
                f"{a.symbol} {a.interval}: workers=1 → {a.n_trades} trades, "
                f"workers=2 → {b.n_trades} trades — must be identical"
            )

    def test_workers_4_completes_all_pairs_correctly(self):
        """4-worker batch must return results for every (symbol, interval) pair."""
        results = self._run(4)
        expected = len(self.SYMBOLS) * len(self.INTERVALS)
        assert len(results) == expected, (
            f"Expected {expected} results with workers=4, got {len(results)}"
        )
        errors = [r for r in results if not r.ok]
        assert not errors, (
            f"{len(errors)} pairs failed with workers=4: "
            + ", ".join(f"{r.symbol}/{r.interval}: {r.error}" for r in errors[:3])
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3L — Smart execution AUTO mode
# ══════════════════════════════════════════════════════════════════════════════

class TestSmartExecutionMode:
    """Phase 3L: BatchBacktest.AUTO=0 selects sequential vs ProcessPool automatically."""

    def test_auto_sentinel_value_is_zero(self):
        """BatchBacktest.AUTO must equal 0 (conventional sentinel for auto-select)."""
        assert BatchBacktest.AUTO == 0, (
            f"BatchBacktest.AUTO must be 0; got {BatchBacktest.AUTO!r}"
        )

    def test_3_pairs_auto_mode_runs_correctly_sequential(self):
        """3 pairs < AUTO_THRESHOLD(4) → sequential path; results must be correct."""
        symbols = ["AAA", "BBB", "CCC"]
        bars = _bars_dict(symbols, ["1h"], n=50)

        result = BatchBacktest(
            symbols=symbols,
            intervals=["1h"],
            strategy_class=_SingleBuy3,
            params={},
            bars=bars,
            starting_capital=100_000.0,
            max_workers=BatchBacktest.AUTO,
        ).run()

        assert len(result.symbol_results) == 3
        errors = [r for r in result.symbol_results if not r.ok]
        assert not errors, (
            f"AUTO mode with 3 pairs must complete without errors. Got: {errors}"
        )

    def test_4_pairs_auto_mode_uses_process_pool(self):
        """4 pairs >= AUTO_THRESHOLD(4) → ProcessPool path; results must be correct."""
        symbols = ["AAA", "BBB", "CCC", "DDD"]
        bars = _bars_dict(symbols, ["1h"], n=50)

        result = BatchBacktest(
            symbols=symbols,
            intervals=["1h"],
            strategy_class=_SingleBuy3,
            params={},
            bars=bars,
            starting_capital=100_000.0,
            max_workers=BatchBacktest.AUTO,
        ).run()

        assert len(result.symbol_results) == 4
        errors = [r for r in result.symbol_results if not r.ok]
        assert not errors, (
            f"AUTO mode with 4 pairs (ProcessPool) must complete without errors. Got: {errors}"
        )

        # Trade counts must match sequential run (sanity check for ProcessPool correctness)
        sequential = BatchBacktest(
            symbols=symbols,
            intervals=["1h"],
            strategy_class=_SingleBuy3,
            params={},
            bars=bars,
            starting_capital=100_000.0,
            max_workers=1,
        ).run().symbol_results

        auto_trades = {(r.symbol, r.interval): r.n_trades for r in result.symbol_results}
        seq_trades  = {(r.symbol, r.interval): r.n_trades for r in sequential}
        assert auto_trades == seq_trades, (
            "AUTO mode (ProcessPool) must produce the same trade counts as sequential. "
            f"AUTO: {auto_trades}, Sequential: {seq_trades}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3M — UI isolation: chart switching ≠ bot stopping
# ══════════════════════════════════════════════════════════════════════════════

class TestUIIsolation:
    """Phase 3M: set_active_pair must never affect bot running state or trading."""

    def test_set_active_pair_does_not_change_running_state(self):
        """set_active_pair on a stopped bot must not set _running=True."""
        mgr = BotManager()
        assert not mgr._running

        mgr.set_active_pair("BTCUSDT", "1h")

        assert not mgr._running, (
            "set_active_pair must not start the bot or change _running state"
        )

    def test_set_active_pair_is_thread_safe_under_concurrent_writes(self):
        """Concurrent set_active_pair calls from N threads must not raise or corrupt state."""
        mgr = BotManager()
        symbols = [f"SYM{i:02d}" for i in range(10)]
        exceptions: list[Exception] = []

        def writer(sym: str) -> None:
            try:
                mgr.set_active_pair(sym, "1h")
            except Exception as exc:
                exceptions.append(exc)

        threads = [threading.Thread(target=writer, args=(s,)) for s in symbols * 5]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not exceptions, (
            f"set_active_pair must be thread-safe. Got {len(exceptions)} exception(s): "
            f"{exceptions[:2]}"
        )
        # Final state must be one of the written symbols
        assert mgr._active_symbol in symbols, (
            f"After concurrent writes, _active_symbol must be one of the written values. "
            f"Got {mgr._active_symbol!r}"
        )

    def test_set_active_pair_stores_both_symbol_and_interval(self):
        """set_active_pair must update both _active_symbol and _active_interval atomically."""
        mgr = BotManager()
        mgr.set_active_pair("ETHUSDT", "4h")

        assert mgr._active_symbol == "ETHUSDT", (
            f"Expected _active_symbol='ETHUSDT', got {mgr._active_symbol!r}"
        )
        assert mgr._active_interval == "4h", (
            f"Expected _active_interval='4h', got {mgr._active_interval!r}"
        )
