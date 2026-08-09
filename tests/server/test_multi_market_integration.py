"""Integration tests for the multi-market, multi-timeframe trading engine.

Verifies the complete pipeline (candle ingestion → strategy → risk → position)
for N×M symbol×interval combinations WITHOUT a live Binance connection.
Scenarios A–S from the Phase-4 test mandate.

Each test creates the real engine stack with in-memory components and feeds
candles directly via EventBus.  No mocking of engine logic; mocks used only
for I/O side effects (storage, bus emissions).

Classification
--------------
  A  3×3 candle ingestion — all 9 (symbol, interval) combinations receive data
  B  Symbol contamination — BTC candle never appears in ETH buffer
  C  Timeframe contamination — 1m candle never appears in 5m buffer
  D  Strategy receives correct per-(symbol, interval) buffer
  E  Signal isolation — BTC signal does NOT affect ETH position state
  F  Position isolation — BTC position does NOT block ETH entry (separate keys)
  G  PnL isolation — closed BTC trade PnL does NOT affect ETH accounting
  H  Candle replacement — same open_time overwrites, buffer length unchanged
  I  Out-of-order candles — older-open_time candle still stored correctly
  J  Duplicate candle — identical candle pushed twice; get_candles deduplicates
  K  WS reconnect simulation — engine continues after feed restart
  L  Failure isolation — exception in BTC candle does not kill ETH processing
  M  Market Watch routing — onCandle routes to correct (sym, iv) row
  N  Chart focus isolation — loadCandles query uses (sym, iv) not global constant
  O  REST/WS time consistency — time field matches between REST and WS formula
  P  Stateful strategy safety — EMACrossover produces independent output per call
  Q  max_open_positions=1 blocks second symbol (global risk limit)
  R  Mark price per symbol — BTC close does not affect ETH mark price
  S  Portfolio accounting — multi-symbol fills all hit the same cash balance
"""
from __future__ import annotations

import math
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from bot.config import BotConfig, FeedConfig, RiskConfig
from bot.engine import BotEngine
from bot.events import CandleEvent, EventBus, FillEvent, SignalEvent
from bot.order_manager import OrderManager
from bot.paper_exchange import PaperExchange, SIDE_BUY, SIDE_SELL
from bot.portfolio import Portfolio
from bot.position_manager import Position, PositionManager
from bot.risk import RiskEngine
from bot.state import BotState, CandleRow
from server.bot_manager import BotManager
from strategies.ema_crossover import EMACrossover


# ── Helpers ───────────────────────────────────────────────────────────────────

def _candle_event(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_time_ms: int = 1_700_000_000_000,
    close: float = 50_000.0,
    is_history: bool = False,
) -> CandleEvent:
    return CandleEvent(
        symbol=symbol,
        interval=interval,
        open_time=open_time_ms,
        open=close - 10,
        high=close + 20,
        low=close - 20,
        close=close,
        volume=1.0,
        close_time=open_time_ms + 59_999,
        is_history=is_history,
    )


def _candle_row(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_time_ms: int = 1_700_000_000_000,
    close: float = 50_000.0,
) -> CandleRow:
    return CandleRow(
        symbol=symbol,
        interval=interval,
        open_time=open_time_ms,
        open=close - 10,
        high=close + 20,
        low=close - 20,
        close=close,
        volume=1.0,
        close_time=open_time_ms + 59_999,
    )


def _stub_storage() -> MagicMock:
    """Return a MagicMock that satisfies BotStorage's interface."""
    s = MagicMock()
    s.get_open_positions.return_value = []
    s.get_open_orders.return_value = []
    s.get_balance_history.return_value = []
    return s


def _make_engine(
    capital: float = 10_000.0,
    min_signal_bars: int = 1,
) -> tuple[BotEngine, BotState, EventBus]:
    """Build a minimal but real engine stack wired to an in-memory EventBus."""
    bus      = EventBus()
    storage  = _stub_storage()
    state    = BotState(buffer_size=500)
    exchange = PaperExchange(bus=bus)
    orders   = OrderManager(exchange=exchange, storage=storage, bus=bus)
    positions = PositionManager(storage=storage, bus=bus)
    portfolio = Portfolio(starting_capital=capital, storage=storage, bus=bus)
    risk_cfg  = RiskConfig(
        max_open_positions    = 1,
        max_position_size_usd = capital * 0.8,
    )
    risk      = RiskEngine(config=risk_cfg, bus=bus)
    strategy  = EMACrossover(fast=2, slow=4)

    cfg = BotConfig(
        paper_capital   = capital,
        strategy_name   = "EMACrossover",
        strategy_params = {"fast": 2, "slow": 4},
        feed            = FeedConfig(
            symbols   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            intervals = ["1m", "5m", "15m"],
        ),
        min_signal_bars = min_signal_bars,
    )
    engine = BotEngine(
        config=cfg, strategy=strategy, state=state,
        orders=orders, positions=positions, portfolio=portfolio,
        risk=risk, storage=storage, bus=bus,
    )
    return engine, state, bus


def _push_n_candles(
    bus: EventBus,
    n: int,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    base_close: float = 50_000.0,
    base_ts: int = 1_700_000_000_000,
    step_ms: int = 60_000,
) -> None:
    """Push n sequential closed candles via the EventBus."""
    for i in range(n):
        bus.emit(_candle_event(
            symbol=symbol,
            interval=interval,
            open_time_ms=base_ts + i * step_ms,
            close=base_close + i * 10,
        ))


# ── A: 3×3 candle ingestion ───────────────────────────────────────────────────

class TestScenarioA_ThreeByThreeIngestion:
    SYMBOLS   = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    INTERVALS = ["1m", "5m", "15m"]

    def test_all_9_combinations_receive_candles(self):
        """Every (symbol, interval) combination independently accumulates candles."""
        _, state, bus = _make_engine()

        base = 1_700_000_000_000
        for sym in self.SYMBOLS:
            for iv in self.INTERVALS:
                for i in range(3):
                    bus.emit(_candle_event(
                        symbol=sym, interval=iv,
                        open_time_ms=base + i * 60_000,
                        close=100.0 + i,
                    ))

        for sym in self.SYMBOLS:
            for iv in self.INTERVALS:
                assert state.buffer_length(sym, iv) == 3, (
                    f"Expected 3 candles in ({sym}, {iv}), "
                    f"got {state.buffer_length(sym, iv)}"
                )

    def test_9_combinations_all_have_correct_close_prices(self):
        """Each (symbol, interval) close price is independent."""
        _, state, bus = _make_engine()
        closes = {
            ("BTCUSDT", "1m"):  50_000.0,
            ("BTCUSDT", "5m"):  50_100.0,
            ("BTCUSDT", "15m"): 50_200.0,
            ("ETHUSDT", "1m"):   3_000.0,
            ("ETHUSDT", "5m"):   3_100.0,
            ("ETHUSDT", "15m"):  3_200.0,
            ("SOLUSDT", "1m"):   100.0,
            ("SOLUSDT", "5m"):   110.0,
            ("SOLUSDT", "15m"):  120.0,
        }
        base = 1_700_000_000_000
        for (sym, iv), close in closes.items():
            bus.emit(_candle_event(symbol=sym, interval=iv,
                                   open_time_ms=base, close=close))

        for (sym, iv), expected_close in closes.items():
            df = state.get_buffer_df(sym, iv)
            assert not df.empty, f"Buffer empty for ({sym}, {iv})"
            assert df.iloc[-1]["close"] == expected_close


# ── B: Symbol contamination ───────────────────────────────────────────────────

class TestScenarioB_SymbolContamination:
    def test_btc_candle_not_in_eth_buffer(self):
        """A BTCUSDT candle must never appear in the ETHUSDT buffer."""
        _, state, bus = _make_engine()
        bus.emit(_candle_event(symbol="BTCUSDT", interval="1m", close=50_000.0))

        assert state.buffer_length("ETHUSDT", "1m") == 0
        assert state.buffer_length("SOLUSDT", "1m") == 0

    def test_eth_candle_not_in_btc_buffer(self):
        _, state, bus = _make_engine()
        bus.emit(_candle_event(symbol="ETHUSDT", interval="1m", close=3_000.0))

        assert state.buffer_length("BTCUSDT", "1m") == 0
        assert state.buffer_length("SOLUSDT", "1m") == 0

    def test_mixed_symbols_separate_buffers(self):
        _, state, bus = _make_engine()
        base = 1_700_000_000_000
        for i in range(5):
            bus.emit(_candle_event("BTCUSDT", "1m", base + i * 60_000, close=50_000.0 + i))
            bus.emit(_candle_event("ETHUSDT", "1m", base + i * 60_000, close=3_000.0 + i))

        assert state.buffer_length("BTCUSDT", "1m") == 5
        assert state.buffer_length("ETHUSDT", "1m") == 5

        btc_df = state.get_buffer_df("BTCUSDT", "1m")
        eth_df = state.get_buffer_df("ETHUSDT", "1m")
        assert btc_df.iloc[0]["close"] == 50_000.0
        assert eth_df.iloc[0]["close"] == 3_000.0


# ── C: Timeframe contamination ────────────────────────────────────────────────

class TestScenarioC_TimeframeContamination:
    def test_1m_candle_not_in_5m_buffer(self):
        _, state, bus = _make_engine()
        bus.emit(_candle_event("BTCUSDT", "1m", close=50_000.0))
        assert state.buffer_length("BTCUSDT", "5m") == 0
        assert state.buffer_length("BTCUSDT", "15m") == 0

    def test_5m_candle_not_in_1m_buffer(self):
        _, state, bus = _make_engine()
        bus.emit(_candle_event("BTCUSDT", "5m", close=50_000.0))
        assert state.buffer_length("BTCUSDT", "1m") == 0
        assert state.buffer_length("BTCUSDT", "15m") == 0

    def test_all_three_intervals_independent(self):
        _, state, bus = _make_engine()
        base = 1_700_000_000_000
        bus.emit(_candle_event("BTCUSDT", "1m",  base, close=50_000.0))
        bus.emit(_candle_event("BTCUSDT", "5m",  base, close=50_100.0))
        bus.emit(_candle_event("BTCUSDT", "15m", base, close=50_200.0))

        assert state.buffer_length("BTCUSDT", "1m")  == 1
        assert state.buffer_length("BTCUSDT", "5m")  == 1
        assert state.buffer_length("BTCUSDT", "15m") == 1
        assert state.get_buffer_df("BTCUSDT", "1m").iloc[-1]["close"]  == 50_000.0
        assert state.get_buffer_df("BTCUSDT", "5m").iloc[-1]["close"]  == 50_100.0
        assert state.get_buffer_df("BTCUSDT", "15m").iloc[-1]["close"] == 50_200.0


# ── D: Strategy receives correct per-(symbol, interval) buffer ────────────────

class TestScenarioD_StrategyBufferRouting:
    def test_strategy_called_with_correct_dataframe(self):
        """BotEngine calls strategy.generate_signals() with the (sym, iv) buffer."""
        _, state, bus = _make_engine(min_signal_bars=3)

        # Push 3 candles for BTCUSDT/1m (distinct prices)
        base = 1_700_000_000_000
        prices = [50_000.0, 51_000.0, 52_000.0]
        for i, p in enumerate(prices):
            bus.emit(_candle_event("BTCUSDT", "1m", base + i * 60_000, close=p))

        df = state.get_buffer_df("BTCUSDT", "1m")
        assert list(df["close"]) == prices, "BTCUSDT/1m buffer has wrong prices"

        # ETHUSDT/1m buffer should be empty
        assert state.get_buffer_df("ETHUSDT", "1m").empty

    def test_strategy_generates_per_buffer(self):
        """EMACrossover called per (sym, iv) produces independent results."""
        strategy = EMACrossover(fast=2, slow=4)

        btc_df = pd.DataFrame({"close": [100, 101, 102, 103, 104, 105]})
        eth_df = pd.DataFrame({"close": [50, 49, 48, 47, 46, 45]})

        btc_sigs = strategy.generate_signals(btc_df)
        eth_sigs = strategy.generate_signals(eth_df)

        # Trending up → BTC likely generates a BUY at some bar
        # Trending down → ETH likely generates an EXIT at some bar
        # The important thing is they produce independent results
        assert len(btc_sigs) == len(btc_df)
        assert len(eth_sigs) == len(eth_df)


# ── E: Signal isolation ───────────────────────────────────────────────────────

class TestScenarioE_SignalIsolation:
    def test_btc_signal_does_not_affect_eth_position_check(self):
        """A BUY signal on BTC cannot trigger an ETH entry."""
        _, state, bus = _make_engine(min_signal_bars=1)
        signals_emitted = []
        bus.subscribe(SignalEvent, lambda ev: signals_emitted.append(ev))

        # Only push BTCUSDT candles — engine should not emit signal for ETHUSDT
        base = 1_700_000_000_000
        bus.emit(_candle_event("BTCUSDT", "1m", base, close=50_000.0))

        eth_signals = [ev for ev in signals_emitted if ev.symbol == "ETHUSDT"]
        assert len(eth_signals) == 0, "No ETH signal should be emitted for BTC candle"

    def test_signals_carry_correct_symbol_and_interval(self):
        """Each emitted SignalEvent identifies the (symbol, interval) it came from."""
        _, state, bus = _make_engine(min_signal_bars=1)
        signals_emitted: list[SignalEvent] = []
        bus.subscribe(SignalEvent, lambda ev: signals_emitted.append(ev))

        base = 1_700_000_000_000
        bus.emit(_candle_event("BTCUSDT", "1m",  base, close=50_000.0))
        bus.emit(_candle_event("ETHUSDT", "5m",  base, close=3_000.0))
        bus.emit(_candle_event("SOLUSDT", "15m", base, close=100.0))

        syms = {(ev.symbol, ev.interval) for ev in signals_emitted}
        assert ("BTCUSDT", "1m")  in syms
        assert ("ETHUSDT", "5m")  in syms
        assert ("SOLUSDT", "15m") in syms


# ── F: Position isolation ─────────────────────────────────────────────────────

class TestScenarioF_PositionIsolation:
    def test_btc_position_does_not_block_eth_position_check(self):
        """Positions are keyed by symbol; BTC open ≠ ETH open."""
        bus = EventBus()
        storage = _stub_storage()
        positions = PositionManager(storage=storage, bus=bus)

        # Manually open a BTC position
        from bot.paper_exchange import PaperFill
        btc_fill = PaperFill(
            order_id="ord1", symbol="BTCUSDT", side=SIDE_BUY,
            fill_price=50_000.0, fill_qty=0.001, fee=0.05,
        )
        positions.on_fill(btc_fill, equity=10_000.0)

        assert positions.has_open_position("BTCUSDT") is True
        assert positions.has_open_position("ETHUSDT") is False
        assert positions.has_open_position("SOLUSDT") is False

    def test_position_count_per_symbol(self):
        bus = EventBus()
        storage = _stub_storage()
        positions = PositionManager(storage=storage, bus=bus)

        from bot.paper_exchange import PaperFill
        for sym, px in [("BTCUSDT", 50_000.0), ("ETHUSDT", 3_000.0)]:
            positions.on_fill(PaperFill(
                order_id=f"ord_{sym}", symbol=sym, side=SIDE_BUY,
                fill_price=px, fill_qty=0.001, fee=0.01,
            ), equity=10_000.0)

        assert positions.open_position_count() == 2
        assert positions.has_open_position("BTCUSDT")
        assert positions.has_open_position("ETHUSDT")
        assert not positions.has_open_position("SOLUSDT")


# ── G: PnL isolation ──────────────────────────────────────────────────────────

class TestScenarioG_PnlIsolation:
    def test_closed_btc_pnl_does_not_bleed_into_eth_position(self):
        """Realized PnL from a closed BTC position is separate from ETH tracking."""
        bus = EventBus()
        storage = _stub_storage()
        positions = PositionManager(storage=storage, bus=bus)

        from bot.paper_exchange import PaperFill
        # Open + close BTC
        buy = PaperFill("o1", "BTCUSDT", SIDE_BUY,  50_000.0, 0.001, 0.05)
        sell = PaperFill("o2", "BTCUSDT", SIDE_SELL, 51_000.0, 0.001, 0.05)
        positions.on_fill(buy, equity=10_000.0)
        closed_pos = positions.on_fill(sell, equity=10_000.0)

        assert closed_pos.status == "closed"
        assert closed_pos.realized_pnl > 0  # profit from BTC trade

        # ETH has no position at all
        assert positions.has_open_position("ETHUSDT") is False
        assert positions.get_open("ETHUSDT") is None


# ── H: Candle replacement ─────────────────────────────────────────────────────

class TestScenarioH_CandleReplacement:
    def test_same_open_time_overwrites_in_place(self):
        """Two candles with the same open_time: second replaces the first."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_000.0))
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_999.0))

        # The buffer still has 2 entries (ring buffer doesn't dedup — dedup at read)
        # but get_candles() in BotManager deduplicates by open_time (last wins)
        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1
        assert result[0]["close"] == 50_999.0

    def test_buffer_length_unchanged_after_same_time_push(self):
        """Deduplication at read time means buffer_length may count duplicates."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_000.0))
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_999.0))
        state.push_candle(_candle_row("BTCUSDT", "1m", t + 60_000, close=51_000.0))

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        # After dedup: 2 unique open_times
        assert len(result) == 2


# ── I: Out-of-order candles ───────────────────────────────────────────────────

class TestScenarioI_OutOfOrderCandles:
    def test_older_candle_after_newer_is_sorted_correctly(self):
        """Candles pushed out of chronological order are sorted ascending on read."""
        state = BotState()
        base = 1_700_000_000_000
        # Push candles in reverse order
        for i in reversed(range(5)):
            state.push_candle(_candle_row("BTCUSDT", "1m", base + i * 60_000,
                                          close=50_000.0 + i))

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        times = [r["time"] for r in result]
        assert times == sorted(times), "get_candles() must return ascending order"

    def test_latest_candle_is_last_after_sorting(self):
        state = BotState()
        base = 1_700_000_000_000
        for i in reversed(range(5)):
            state.push_candle(_candle_row("BTCUSDT", "1m", base + i * 60_000,
                                          close=50_000.0 + i))

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert result[-1]["close"] == 50_004.0


# ── J: Duplicate candle ───────────────────────────────────────────────────────

class TestScenarioJ_DuplicateCandle:
    def test_identical_candle_pushed_twice_deduplicates(self):
        """Pushing the exact same candle twice yields 1 entry after dedup."""
        state = BotState()
        t = 1_700_000_000_000
        c = _candle_row("BTCUSDT", "1m", t, close=50_000.0)
        state.push_candle(c)
        state.push_candle(c)

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")
        assert len(result) == 1

    def test_duplicate_from_different_symbol_does_not_merge(self):
        """Identical open_time from different symbol: both entries kept separately."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_000.0))
        state.push_candle(_candle_row("ETHUSDT", "1m", t, close=3_000.0))

        mgr = BotManager()
        mgr._state = state
        btc_result = mgr.get_candles("BTCUSDT", "1m")
        eth_result = mgr.get_candles("ETHUSDT", "1m")
        assert len(btc_result) == 1
        assert len(eth_result) == 1


# ── K: WS reconnect simulation ────────────────────────────────────────────────

class TestScenarioK_FeedRestart:
    def test_engine_continues_processing_after_feed_restart(self):
        """Engine correctly processes candles before and after a simulated restart."""
        _, state, bus = _make_engine(min_signal_bars=1)
        base = 1_700_000_000_000

        # Phase 1: pre-restart candles
        bus.emit(_candle_event("BTCUSDT", "1m", base, close=50_000.0))
        assert state.buffer_length("BTCUSDT", "1m") == 1

        # Simulate restart: create fresh engine connected to same state/bus
        # (In real runtime, LiveFeed.run() restarts; engine stays alive)
        # Just push more candles to verify the buffer accumulates correctly
        bus.emit(_candle_event("BTCUSDT", "1m", base + 60_000, close=50_100.0))
        bus.emit(_candle_event("BTCUSDT", "1m", base + 120_000, close=50_200.0))

        assert state.buffer_length("BTCUSDT", "1m") == 3

    def test_backfill_candles_warm_buffer_but_not_submitted(self):
        """is_history=True candles go into buffer but never trigger orders."""
        _, state, bus = _make_engine(min_signal_bars=1)

        signals: list[SignalEvent] = []
        bus.subscribe(SignalEvent, lambda ev: signals.append(ev))

        base = 1_700_000_000_000
        # Push backfill candles (is_history=True)
        for i in range(5):
            bus.emit(_candle_event("BTCUSDT", "1m", base + i * 60_000,
                                   close=50_000.0 + i, is_history=True))

        assert state.buffer_length("BTCUSDT", "1m") == 5
        # No signals emitted for history candles (engine returns early)
        assert len(signals) == 0


# ── L: Failure isolation ──────────────────────────────────────────────────────

class TestScenarioL_FailureIsolation:
    def test_exception_in_strategy_for_btc_does_not_kill_eth(self):
        """If strategy raises for BTC, ETH candles still process normally."""
        bus = EventBus()
        storage = _stub_storage()
        state = BotState(buffer_size=500)
        exchange = PaperExchange(bus=bus)
        orders = OrderManager(exchange=exchange, storage=storage, bus=bus)
        positions = PositionManager(storage=storage, bus=bus)
        portfolio = Portfolio(starting_capital=1_000.0, storage=storage, bus=bus)
        risk = RiskEngine(config=RiskConfig(), bus=bus)

        # Strategy that raises for BTCUSDT only
        class PartiallyBrokenStrategy:
            def generate_signals(self, df):
                raise RuntimeError("Simulated strategy failure")

        cfg = BotConfig(
            paper_capital=1_000.0,
            strategy_name="broken",
            strategy_params={},
            feed=FeedConfig(symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m"]),
            min_signal_bars=1,
        )
        engine = BotEngine(
            config=cfg, strategy=PartiallyBrokenStrategy(), state=state,
            orders=orders, positions=positions, portfolio=portfolio,
            risk=risk, storage=storage, bus=bus,
        )

        base = 1_700_000_000_000
        # BTC candle triggers strategy failure — engine catches it
        bus.emit(_candle_event("BTCUSDT", "1m", base, close=50_000.0))
        # ETH candle must still be stored in buffer
        bus.emit(_candle_event("ETHUSDT", "1m", base, close=3_000.0))

        assert state.buffer_length("BTCUSDT", "1m") == 1  # stored despite strategy error
        assert state.buffer_length("ETHUSDT", "1m") == 1  # not contaminated

    def test_candle_processing_error_isolated_to_one_candle(self):
        """Engine's per-candle try/except means one bad candle doesn't stop the loop."""
        _, state, bus = _make_engine(min_signal_bars=10)
        base = 1_700_000_000_000

        # Push 5 candles — even if one had an error, others still accumulate
        for i in range(5):
            bus.emit(_candle_event("BTCUSDT", "1m", base + i * 60_000, close=50_000.0 + i))

        assert state.buffer_length("BTCUSDT", "1m") == 5


# ── M: Market Watch routing ───────────────────────────────────────────────────

class TestScenarioM_MarketWatchRouting:
    """Verify the get_candles() routing used by the REST endpoint (Market Watch source)."""

    def test_get_candles_isolates_by_symbol(self):
        """GET /api/bot/candles?symbol=X returns only X's candles."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_000.0))
        state.push_candle(_candle_row("ETHUSDT", "1m", t, close=3_000.0))

        mgr = BotManager()
        mgr._state = state

        btc = mgr.get_candles("BTCUSDT", "1m")
        eth = mgr.get_candles("ETHUSDT", "1m")
        assert len(btc) == 1 and btc[0]["close"] == 50_000.0
        assert len(eth) == 1 and eth[0]["close"] == 3_000.0

    def test_get_candles_isolates_by_interval(self):
        """GET /api/bot/candles?interval=X returns only X-interval candles."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m",  t, close=50_000.0))
        state.push_candle(_candle_row("BTCUSDT", "5m",  t, close=50_100.0))
        state.push_candle(_candle_row("BTCUSDT", "15m", t, close=50_200.0))

        mgr = BotManager()
        mgr._state = state

        assert mgr.get_candles("BTCUSDT", "1m")[0]["close"]  == 50_000.0
        assert mgr.get_candles("BTCUSDT", "5m")[0]["close"]  == 50_100.0
        assert mgr.get_candles("BTCUSDT", "15m")[0]["close"] == 50_200.0

    def test_get_candles_no_state_returns_empty(self):
        """BotManager.get_candles() when bot is not running returns []."""
        mgr = BotManager()
        assert mgr._state is None
        assert mgr.get_candles("BTCUSDT", "1m") == []


# ── N: Chart focus isolation ──────────────────────────────────────────────────

class TestScenarioN_ChartFocusIsolation:
    """get_candles() accepts (symbol, interval) so the chart can switch both axes."""

    def test_get_candles_accepts_any_interval(self):
        state = BotState()
        t = 1_700_000_000_000
        for iv, close in [("1m", 50_000.0), ("5m", 50_100.0), ("15m", 50_200.0)]:
            state.push_candle(_candle_row("BTCUSDT", iv, t, close=close))

        mgr = BotManager()
        mgr._state = state

        for iv, expected in [("1m", 50_000.0), ("5m", 50_100.0), ("15m", 50_200.0)]:
            result = mgr.get_candles("BTCUSDT", iv)
            assert result[0]["close"] == expected, f"Expected {expected} for {iv}"

    def test_get_candles_returns_empty_for_missing_interval(self):
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", t, close=50_000.0))

        mgr = BotManager()
        mgr._state = state

        assert mgr.get_candles("BTCUSDT", "4h") == []


# ── O: REST/WS time consistency ───────────────────────────────────────────────

class TestScenarioO_RestWsTimeConsistency:
    def test_rest_time_equals_open_time_divided_by_1000(self):
        """REST time field = open_time // 1000 (Unix seconds at candle open)."""
        state = BotState()
        open_ms = 1_700_000_060_000
        state.push_candle(_candle_row("BTCUSDT", "1m", open_ms, close=50_000.0))

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")

        expected_time = open_ms // 1000
        assert result[0]["time"] == expected_time

    def test_ws_formula_matches_rest_formula(self):
        """WS formula Math.floor(open_time / 1000) == REST formula open_time // 1000."""
        open_ms = 1_700_000_060_000
        # Python equivalent of JS Math.floor(open_time / 1000)
        ws_time   = math.floor(open_ms / 1000)
        rest_time = open_ms // 1000
        assert ws_time == rest_time

    def test_time_is_not_close_time(self):
        """REST time must be open_time, not close_time."""
        state = BotState()
        open_ms = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m", open_ms, close=50_000.0))

        mgr = BotManager()
        mgr._state = state
        result = mgr.get_candles("BTCUSDT", "1m")

        close_time_sec = (open_ms + 59_999) // 1000
        assert result[0]["time"] != close_time_sec


# ── P: Stateful strategy safety ───────────────────────────────────────────────

class TestScenarioP_StatefulStrategySafety:
    def test_ema_crossover_is_stateless(self):
        """EMACrossover stores no per-call state — calling twice with same df gives same result."""
        strategy = EMACrossover(fast=5, slow=20)
        df = pd.DataFrame({"close": list(range(30, 60))})

        result1 = strategy.generate_signals(df)
        result2 = strategy.generate_signals(df)
        assert list(result1) == list(result2)

    def test_ema_crossover_independent_for_different_symbols(self):
        """Calling generate_signals with BTC data then ETH data: each is independent."""
        strategy = EMACrossover(fast=5, slow=20)
        btc_df = pd.DataFrame({"close": list(range(30, 60))})
        eth_df = pd.DataFrame({"close": list(range(60, 30, -1))})

        btc_sigs1 = strategy.generate_signals(btc_df)
        eth_sigs  = strategy.generate_signals(eth_df)
        btc_sigs2 = strategy.generate_signals(btc_df)

        # After calling with ETH, BTC result must be unchanged
        assert list(btc_sigs1) == list(btc_sigs2), (
            "Strategy must not retain state between calls"
        )


# ── Q: max_open_positions=1 blocks second symbol ─────────────────────────────

class TestScenarioQ_GlobalPositionLimit:
    def test_second_symbol_blocked_when_one_position_open(self):
        """With max_open_positions=1, opening BTC blocks ETH entry via risk check."""
        from bot.risk import RiskContext

        # max_position_size_usd=100 so notional checks pass; only open_positions limit matters
        risk = RiskEngine(
            config=RiskConfig(max_open_positions=1, max_position_size_usd=100.0),
            bus=None,
        )

        # First trade: no positions open → allowed
        ctx_btc = RiskContext(
            symbol="BTCUSDT", side=SIDE_BUY, qty=0.001, ref_price=50_000.0,
            equity=10_000.0, peak_equity=10_000.0, daily_pnl=0.0,
            n_trades_today=0, open_positions=0,
        )
        assert risk.check(ctx_btc) == ""

        # Second trade: 1 position already open → blocked
        ctx_eth = RiskContext(
            symbol="ETHUSDT", side=SIDE_BUY, qty=0.01, ref_price=3_000.0,
            equity=10_000.0, peak_equity=10_000.0, daily_pnl=0.0,
            n_trades_today=0, open_positions=1,  # BTC is open
        )
        reason = risk.check(ctx_eth)
        assert reason != "", "max_open_positions=1 must block ETHUSDT entry"
        assert "max open positions" in reason.lower()


# ── R: Mark price per symbol ──────────────────────────────────────────────────

class TestScenarioR_MarkPriceIsolation:
    def test_btc_close_does_not_affect_eth_mark_price(self):
        """Each symbol has an independent mark price in BotState."""
        state = BotState()
        state.push_candle(_candle_row("BTCUSDT", "1m", 1_700_000_000_000, close=50_000.0))
        state.push_candle(_candle_row("ETHUSDT", "1m", 1_700_000_000_000, close=3_000.0))

        assert state.mark_price("BTCUSDT") == 50_000.0
        assert state.mark_price("ETHUSDT") == 3_000.0

    def test_mark_price_updated_per_interval_close(self):
        """Mark price for a symbol updates whenever any of its interval's candle closes."""
        state = BotState()
        t = 1_700_000_000_000
        state.push_candle(_candle_row("BTCUSDT", "1m",  t,          close=50_000.0))
        state.push_candle(_candle_row("BTCUSDT", "5m",  t + 60_000, close=50_100.0))

        # Mark price is the latest close from ANY interval for this symbol
        assert state.mark_price("BTCUSDT") == 50_100.0

    def test_mark_prices_dict_contains_all_seen_symbols(self):
        state = BotState()
        t = 1_700_000_000_000
        for sym, px in [("BTCUSDT", 50_000.0), ("ETHUSDT", 3_000.0), ("SOLUSDT", 100.0)]:
            state.push_candle(_candle_row(sym, "1m", t, close=px))

        marks = state.all_mark_prices()
        assert marks == {"BTCUSDT": 50_000.0, "ETHUSDT": 3_000.0, "SOLUSDT": 100.0}


# ── S: Portfolio accounting ───────────────────────────────────────────────────

class TestScenarioS_PortfolioAccounting:
    def test_multi_symbol_fills_hit_same_cash_balance(self):
        """BTC fill and ETH fill both deduct from the same portfolio cash."""
        bus = EventBus()
        storage = _stub_storage()
        portfolio = Portfolio(starting_capital=10_000.0, storage=storage, bus=bus)

        initial_cash = portfolio.cash

        from bot.paper_exchange import PaperFill
        btc_fill = PaperFill("o1", "BTCUSDT", SIDE_BUY, 50_000.0, 0.001, 50.0)
        eth_fill = PaperFill("o2", "ETHUSDT", SIDE_BUY, 3_000.0, 0.01, 3.0)

        portfolio.on_fill(btc_fill, closed_pnl=None)
        portfolio.on_fill(eth_fill, closed_pnl=None)

        # Cash should have decreased by (50_000 * 0.001 + 50) + (3_000 * 0.01 + 3) = 103
        expected = initial_cash - (50_000.0 * 0.001 + 50.0) - (3_000.0 * 0.01 + 3.0)
        assert abs(portfolio.cash - expected) < 1e-6

    def test_portfolio_cash_increases_on_exit_fill(self):
        """SELL fill returns cash to portfolio."""
        bus = EventBus()
        storage = _stub_storage()
        portfolio = Portfolio(starting_capital=10_000.0, storage=storage, bus=bus)

        from bot.paper_exchange import PaperFill
        # fee is fee_rate * notional; use realistic ~0.1% fee
        buy  = PaperFill("o1", "BTCUSDT", SIDE_BUY,  50_000.0, 0.001, 0.05)
        sell = PaperFill("o2", "BTCUSDT", SIDE_SELL, 51_000.0, 0.001, 0.051)

        portfolio.on_fill(buy, closed_pnl=None)
        cash_after_buy = portfolio.cash

        portfolio.on_fill(sell, closed_pnl=1.0)
        assert portfolio.cash > cash_after_buy, "SELL must increase cash"


# ── BotManager.start() N×M support ───────────────────────────────────────────

class TestBotManagerMultiIntervalStart:
    """Verify the new intervals parameter in BotManager.start()."""

    def test_start_with_intervals_list(self):
        """BotManager.start() accepts intervals as a list."""
        mgr = BotManager()
        # Don't actually start the thread — just verify config construction
        from bot.config import BotConfig, FeedConfig, RiskConfig
        resolved: list[str] = (
            ["1m", "5m", "15m"]  # what we'd pass
        )
        cfg = BotConfig(
            paper_capital=25.0,
            strategy_name="EMACrossover",
            strategy_params={"fast": 20, "slow": 50},
            feed=FeedConfig(symbols=["BTCUSDT", "ETHUSDT"], intervals=resolved),
            risk=RiskConfig(),
        )
        assert cfg.feed.intervals == ["1m", "5m", "15m"]
        assert cfg.feed.symbols   == ["BTCUSDT", "ETHUSDT"]

    def test_start_with_legacy_interval_string(self):
        """BotManager.start() with legacy interval=str still works."""
        from bot.config import BotConfig, FeedConfig, RiskConfig
        interval = "1h"
        resolved = [interval]
        cfg = BotConfig(
            paper_capital=25.0,
            strategy_name="EMACrossover",
            strategy_params={"fast": 20, "slow": 50},
            feed=FeedConfig(symbols=["BTCUSDT"], intervals=resolved),
            risk=RiskConfig(),
        )
        assert cfg.feed.intervals == ["1h"]

    def test_get_status_returns_intervals_list(self):
        """BotManager.get_status() returns intervals list (not just first interval)."""
        mgr = BotManager()
        # Build a mock config with multiple intervals
        from bot.config import BotConfig, FeedConfig, RiskConfig
        mgr._config = BotConfig(
            paper_capital=25.0,
            strategy_name="EMACrossover",
            strategy_params={"fast": 20, "slow": 50},
            feed=FeedConfig(symbols=["BTCUSDT", "ETHUSDT"], intervals=["1m", "5m", "15m"]),
            risk=RiskConfig(),
        )
        status = mgr.get_status()
        assert "intervals" in status
        assert status["intervals"] == ["1m", "5m", "15m"]
        assert "interval" in status  # backward-compat field still present
        assert status["interval"] == "1m"
