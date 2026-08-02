"""Comprehensive tests for engine.executor.BacktestExecutor."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from engine.executor import BacktestExecutor, _validate_bars, _validate_signals
from engine.models import BacktestTrade, EngineConfig, ExitReason
from engine.strategy import Signal, StrategyBase


# ── Test infrastructure ────────────────────────────────────────────────────────

def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Build a bars DataFrame from (open, high, low, close) tuples.

    Volume is fixed at 1.0; index is hourly UTC starting 2024-01-01.
    """
    idx = pd.date_range(
        "2024-01-01", periods=len(rows), freq="1h", tz="UTC", name="open_time"
    )
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [1.0] * len(rows)},
        index=idx,
    )


def _flat_bars(price: float, n: int) -> pd.DataFrame:
    """n identical bars at price; high = price+1, low = price-1."""
    return _bars([(price, price + 1.0, price - 1.0, price)] * n)


class _Signals(StrategyBase):
    """Test strategy: returns a preset signal for each bar index."""

    def __init__(self, signal_map: dict[int, Signal], default: Signal = Signal.HOLD):
        self._map = signal_map
        self._default = default

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(self._default, index=bars.index, dtype=object)
        for bar_idx, sig in self._map.items():
            if bar_idx < len(bars):
                s.iloc[bar_idx] = sig
        return s


# ── Shared config fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def free() -> EngineConfig:
    """Zero fees and slippage — isolates price logic."""
    return EngineConfig(fee_rate=0.0, slippage_pct=0.0)


@pytest.fixture
def ex(free) -> BacktestExecutor:
    return BacktestExecutor(free)


# ── Basic buy / exit ───────────────────────────────────────────────────────────

class TestBasicBuyExit:
    def test_buy_and_exit_produces_one_trade(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        trades = ex.run(bars, strategy)
        assert len(trades) == 1

    def test_buy_and_exit_is_long(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.direction == "Long"

    def test_exit_reason_is_signal(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.exit_reason == ExitReason.SIGNAL

    def test_sell_signal_also_closes_long(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.SELL})
        trades = ex.run(bars, strategy)
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.SIGNAL

    def test_hold_only_produces_no_trades(self, ex):
        bars = _flat_bars(100.0, 5)
        strategy = _Signals({})
        assert ex.run(bars, strategy) == []

    def test_buy_with_no_exit_closes_at_end_of_data(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY})
        t = ex.run(bars, strategy)[0]
        assert t.exit_reason == ExitReason.END_OF_DATA


# ── No-lookahead-bias: fills happen at next bar ────────────────────────────────

class TestNoLookaheadBias:
    def test_entry_at_next_bar_open_not_current_close(self, free):
        """BUY at bar 0 (close=100) must fill at bar 1 open (=200), not at 100."""
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),   # bar 0: BUY signal here
            (200.0, 201.0, 199.0, 200.0),   # bar 1: fill must be at open=200
            (200.0, 201.0, 199.0, 200.0),   # bar 2: EXIT
            (200.0, 201.0, 199.0, 200.0),
        ])
        ex = BacktestExecutor(free)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.entry_price == pytest.approx(200.0)

    def test_entry_time_is_next_bar_timestamp(self, free):
        """Entry timestamp must match bar 1, not bar 0."""
        bars = _flat_bars(100.0, 4)
        ex = BacktestExecutor(free)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.entry_time == bars.index[1]

    def test_exit_at_next_bar_open_not_current_close(self, free):
        """EXIT at bar 2 (close=100) fills at bar 3 open (=150)."""
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),   # bar 2: EXIT signal here
            (150.0, 151.0, 149.0, 150.0),   # bar 3: exit fills here
        ])
        ex = BacktestExecutor(free)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.exit_price == pytest.approx(150.0)

    def test_exit_time_is_next_bar_timestamp(self, free):
        bars = _flat_bars(100.0, 4)
        ex = BacktestExecutor(free)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.exit_time == bars.index[3]


# ── No duplicate positions ─────────────────────────────────────────────────────

class TestNoDuplicatePositions:
    def test_second_buy_while_long_is_ignored(self, ex):
        bars = _flat_bars(100.0, 6)
        strategy = _Signals({0: Signal.BUY, 2: Signal.BUY, 4: Signal.EXIT})
        trades = ex.run(bars, strategy)
        assert len(trades) == 1

    def test_buy_after_close_is_honoured(self, ex):
        bars = _flat_bars(100.0, 7)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT, 4: Signal.BUY})
        trades = ex.run(bars, strategy)
        assert len(trades) == 2

    def test_exit_while_flat_is_ignored(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.EXIT, 2: Signal.EXIT})
        assert ex.run(bars, strategy) == []


# ── Stop-loss ──────────────────────────────────────────────────────────────────

class TestStopLoss:
    def _config(self, sl_pct: float) -> EngineConfig:
        return EngineConfig(stop_loss_pct=sl_pct, fee_rate=0.0, slippage_pct=0.0)

    def test_sl_triggers_when_low_breaches(self):
        """Bar 2 has a low well below the 2% stop."""
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),   # bar 0: BUY
            (100.0, 101.0,  99.0, 100.0),   # bar 1: entry fill (open=100)
            (100.0, 101.0,  90.0, 100.0),   # bar 2: low=90 < SL≈98 → SL hit
            (100.0, 101.0,  99.0, 100.0),
        ])
        ex = BacktestExecutor(self._config(0.02))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_reason == ExitReason.STOP_LOSS

    def test_sl_exit_price_is_at_stop_level(self):
        # Entry at 100 (no slippage), SL = 100 * 0.98 = 98.
        # Bar 2 opens at 100, low = 90 → raw exit = min(98, 100) = 98.
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.0, 100.0),   # bar 1: fill at 100
            (100.0, 101.0,  90.0, 100.0),   # bar 2: SL=98 hit
        ])
        ex = BacktestExecutor(self._config(0.02))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_price == pytest.approx(98.0)

    def test_no_sl_trigger_when_low_above_stop(self):
        """Low stays above SL; position should remain open and close at end."""
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.5, 100.0),   # bar 1: fill; SL≈98
            (100.0, 101.0,  99.5, 100.0),   # bar 2: low=99.5 > SL=98 → no trigger
        ])
        ex = BacktestExecutor(self._config(0.02))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_reason == ExitReason.END_OF_DATA


# ── Take-profit ────────────────────────────────────────────────────────────────

class TestTakeProfit:
    def _config(self, tp_pct: float) -> EngineConfig:
        return EngineConfig(take_profit_pct=tp_pct, fee_rate=0.0, slippage_pct=0.0)

    def test_tp_triggers_when_high_exceeds_target(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),   # bar 1: fill at 100; TP=104
            (100.0, 110.0, 99.0, 100.0),   # bar 2: high=110 > TP=104 → TP hit
        ])
        ex = BacktestExecutor(self._config(0.04))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_reason == ExitReason.TAKE_PROFIT

    def test_tp_exit_price_is_at_target(self):
        # Entry=100, TP=104.  Bar 2 opens at 100, high=110.
        # raw = max(104, 100) = 104.
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 110.0, 99.0, 100.0),
        ])
        ex = BacktestExecutor(self._config(0.04))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_price == pytest.approx(104.0)

    def test_no_tp_trigger_when_high_below_target(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 103.0, 99.0, 100.0),   # bar 1: fill; TP=104
            (100.0, 103.5, 99.0, 100.0),   # bar 2: high=103.5 < TP=104
        ])
        ex = BacktestExecutor(self._config(0.04))
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_reason == ExitReason.END_OF_DATA


# ── SL beats TP when both fire on the same bar ────────────────────────────────

class TestSLBeatsTp:
    def test_sl_wins_over_tp_same_bar(self):
        # Entry at 100.  SL=98 (2%), TP=104 (4%).
        # Bar 2: high=110 (>TP), low=90 (<SL) → SL must win.
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 110.0,  90.0, 100.0),  # SL and TP both hit
        ])
        cfg = EngineConfig(stop_loss_pct=0.02, take_profit_pct=0.04,
                           fee_rate=0.0, slippage_pct=0.0)
        t = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_reason == ExitReason.STOP_LOSS
        assert t.exit_price == pytest.approx(98.0)


# ── Gap through stop ───────────────────────────────────────────────────────────

class TestGapThroughStop:
    def test_gap_down_fills_at_bar_open(self):
        """Bar opens below the SL; fill must be at bar open, not stop level."""
        # Entry at 100, SL = 98.  Bar 2 opens at 90 (gap below SL).
        # raw_exit = min(98, 90) = 90 → fill = 90 (no slippage in this test).
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.0, 100.0),
            ( 90.0,  91.0,  89.0,  90.0),  # gap open below SL
        ])
        cfg = EngineConfig(stop_loss_pct=0.02, fee_rate=0.0, slippage_pct=0.0)
        t = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_price == pytest.approx(90.0)
        assert t.exit_reason == ExitReason.STOP_LOSS

    def test_gap_up_through_tp_fills_at_open(self):
        """Bar opens above TP; fill at bar open (a bonus vs. limit price)."""
        # Entry at 100, TP=104.  Bar 2 opens at 110 (gap above TP).
        # raw = max(104, 110) = 110.
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.0, 100.0),
            (110.0, 111.0, 109.0, 110.0),
        ])
        cfg = EngineConfig(take_profit_pct=0.04, fee_rate=0.0, slippage_pct=0.0)
        t = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_price == pytest.approx(110.0)
        assert t.exit_reason == ExitReason.TAKE_PROFIT


# ── Flat market ────────────────────────────────────────────────────────────────

class TestFlatMarket:
    def test_zero_gross_pnl_in_flat_market(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.gross_pnl == pytest.approx(0.0)

    def test_zero_net_pnl_in_flat_market_no_costs(self, ex):
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.net_pnl == pytest.approx(0.0)


# ── Fees ───────────────────────────────────────────────────────────────────────

class TestFees:
    def test_fees_reduce_net_pnl(self):
        """With 0.1% fee per side, a zero-move trade has negative net PnL."""
        cfg = EngineConfig(fee_rate=0.001, slippage_pct=0.0)
        bars = _flat_bars(100.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = BacktestExecutor(cfg).run(bars, strategy)[0]
        assert t.net_pnl < 0.0

    def test_entry_fee_equals_fill_times_size_times_rate(self):
        cfg = EngineConfig(position_size=2.0, fee_rate=0.001, slippage_pct=0.0)
        bars = _flat_bars(100.0, 3)
        strategy = _Signals({0: Signal.BUY})
        t = BacktestExecutor(cfg).run(bars, strategy)[0]
        # fill = 100, size = 2, rate = 0.001 → fee = 0.2
        assert t.entry_fee == pytest.approx(100.0 * 2.0 * 0.001)

    def test_net_pnl_equals_gross_minus_fees(self):
        cfg = EngineConfig(fee_rate=0.002, slippage_pct=0.0)
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (110.0, 111.0, 109.0, 110.0),
            (110.0, 111.0, 109.0, 110.0),
        ])
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = BacktestExecutor(cfg).run(bars, strategy)[0]
        assert t.net_pnl == pytest.approx(t.gross_pnl - t.entry_fee - t.exit_fee)


# ── Slippage ───────────────────────────────────────────────────────────────────

class TestSlippage:
    def test_entry_fill_is_above_raw_open(self):
        """Buyer pays more than the raw open price."""
        cfg = EngineConfig(fee_rate=0.0, slippage_pct=0.001)  # 0.1%
        bars = _flat_bars(1000.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = BacktestExecutor(cfg).run(bars, strategy)[0]
        assert t.entry_price == pytest.approx(1000.0 * 1.001)

    def test_exit_fill_is_below_raw_open(self):
        """Seller receives less than the raw open price."""
        cfg = EngineConfig(fee_rate=0.0, slippage_pct=0.001)
        bars = _flat_bars(1000.0, 4)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = BacktestExecutor(cfg).run(bars, strategy)[0]
        assert t.exit_price == pytest.approx(1000.0 * 0.999)

    def test_slippage_costs_are_positive(self):
        cfg = EngineConfig(fee_rate=0.0, slippage_pct=0.0005)
        bars = _flat_bars(100.0, 4)
        t = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY, 2: Signal.EXIT}))[0]
        assert t.entry_slippage > 0.0
        assert t.exit_slippage > 0.0

    def test_net_pnl_lower_with_slippage_than_without(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (110.0, 111.0, 109.0, 110.0),
            (110.0, 111.0, 109.0, 110.0),
        ])
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        no_slip = BacktestExecutor(EngineConfig(fee_rate=0.0, slippage_pct=0.0))
        with_slip = BacktestExecutor(EngineConfig(fee_rate=0.0, slippage_pct=0.001))
        t0 = no_slip.run(bars, strategy)[0]
        t1 = with_slip.run(bars, strategy)[0]
        assert t1.net_pnl < t0.net_pnl


# ── Trade metadata ─────────────────────────────────────────────────────────────

class TestTradeMetadata:
    def test_trade_number_starts_at_one(self, ex):
        bars = _flat_bars(100.0, 4)
        t = ex.run(bars, _Signals({0: Signal.BUY, 2: Signal.EXIT}))[0]
        assert t.trade_number == 1

    def test_trade_numbers_are_sequential(self, ex):
        bars = _flat_bars(100.0, 10)
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT, 4: Signal.BUY, 6: Signal.EXIT})
        trades = ex.run(bars, strategy)
        assert [t.trade_number for t in trades] == [1, 2]

    def test_holding_period_in_bars(self, ex):
        # BUY at bar 0 → fills at bar 1.  EXIT at bar 3 → fills at bar 4.
        # Held bars 1 through 4 = 3 bars.
        bars = _flat_bars(100.0, 6)
        strategy = _Signals({0: Signal.BUY, 3: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.holding_period == 3

    def test_holding_period_zero_when_sl_on_entry_bar(self):
        """Enter at bar 1 open; bar 1 immediately hits SL → hold 0 bars."""
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  50.0, 100.0),  # bar 1: low=50 well below SL
            (100.0, 101.0,  99.0, 100.0),
        ])
        cfg = EngineConfig(stop_loss_pct=0.02, fee_rate=0.0, slippage_pct=0.0)
        t = BacktestExecutor(cfg).run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.holding_period == 0

    def test_end_of_data_closes_on_last_bar_close(self, ex):
        bars = _bars([
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 101.0,  99.0, 100.0),
            (100.0, 121.0,  99.0, 120.0),  # close=120 within [99, 121]
        ])
        t = ex.run(bars, _Signals({0: Signal.BUY}))[0]
        assert t.exit_price == pytest.approx(120.0)
        assert t.exit_reason == ExitReason.END_OF_DATA

    def test_gross_pnl_formula(self, ex):
        # Entry=100, exit=110, size=1 → gross=10
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (110.0, 111.0, 109.0, 110.0),
            (110.0, 111.0, 109.0, 110.0),
        ])
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        t = ex.run(bars, strategy)[0]
        assert t.gross_pnl == pytest.approx((t.exit_price - t.entry_price) * t.size)


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_bars_returns_empty_list(self, ex):
        bars = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        assert ex.run(bars, _Signals({})) == []

    def test_single_bar_returns_empty_list(self, ex):
        # Only 1 bar: BUY signal at bar 0 but no bar 1 to fill into.
        bars = _flat_bars(100.0, 1)
        assert ex.run(bars, _Signals({0: Signal.BUY})) == []

    def test_two_bars_can_produce_one_end_of_data_trade(self, ex):
        bars = _flat_bars(100.0, 2)
        strategy = _Signals({0: Signal.BUY})
        trades = ex.run(bars, strategy)
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.END_OF_DATA

    def test_wrong_signal_length_raises(self, ex):
        bars = _flat_bars(100.0, 4)

        class _BadStrategy(StrategyBase):
            def generate_signals(self, bars):
                return pd.Series([Signal.HOLD] * 2)  # wrong length

        with pytest.raises(ValueError):
            ex.run(bars, _BadStrategy())

    def test_position_size_scales_pnl(self, free):
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (110.0, 111.0, 109.0, 110.0),
            (110.0, 111.0, 109.0, 110.0),
        ])
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})

        cfg1 = EngineConfig(position_size=1.0, fee_rate=0.0, slippage_pct=0.0)
        cfg2 = EngineConfig(position_size=5.0, fee_rate=0.0, slippage_pct=0.0)

        t1 = BacktestExecutor(cfg1).run(bars, strategy)[0]
        t2 = BacktestExecutor(cfg2).run(bars, strategy)[0]

        assert t2.gross_pnl == pytest.approx(t1.gross_pnl * 5.0)

    def test_multiple_round_trips(self, ex):
        bars = _flat_bars(100.0, 12)
        strategy = _Signals({
            0: Signal.BUY, 2: Signal.EXIT,
            4: Signal.BUY, 6: Signal.EXIT,
            8: Signal.BUY, 10: Signal.EXIT,
        })
        trades = ex.run(bars, strategy)
        assert len(trades) == 3
        assert [t.trade_number for t in trades] == [1, 2, 3]

    def test_profit_property_equals_net_pnl(self, ex):
        bars = _flat_bars(100.0, 4)
        t = ex.run(bars, _Signals({0: Signal.BUY, 2: Signal.EXIT}))[0]
        assert t.profit == t.net_pnl

    def test_is_winner_loser_properties(self, free):
        rising = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            (120.0, 121.0, 119.0, 120.0),
            (120.0, 121.0, 119.0, 120.0),
        ])
        falling = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0, 101.0, 99.0, 100.0),
            ( 80.0,  81.0,  79.0,  80.0),
            ( 80.0,  81.0,  79.0,  80.0),
        ])
        strategy = _Signals({0: Signal.BUY, 2: Signal.EXIT})
        winner = BacktestExecutor(free).run(rising, strategy)[0]
        loser = BacktestExecutor(free).run(falling, strategy)[0]
        assert winner.is_winner is True and winner.is_loser is False
        assert loser.is_loser is True and loser.is_winner is False


# ── EngineConfig validation ────────────────────────────────────────────────────

class TestEngineConfigValidation:
    def test_zero_position_size_raises(self):
        with pytest.raises(ValueError, match="position_size"):
            EngineConfig(position_size=0.0)

    def test_negative_position_size_raises(self):
        with pytest.raises(ValueError, match="position_size"):
            EngineConfig(position_size=-1.0)

    def test_negative_fee_rate_raises(self):
        with pytest.raises(ValueError, match="fee_rate"):
            EngineConfig(fee_rate=-0.001)

    def test_negative_slippage_raises(self):
        with pytest.raises(ValueError, match="slippage_pct"):
            EngineConfig(slippage_pct=-0.0005)

    def test_stop_loss_zero_raises(self):
        with pytest.raises(ValueError, match="stop_loss_pct"):
            EngineConfig(stop_loss_pct=0.0)

    def test_stop_loss_one_raises(self):
        with pytest.raises(ValueError, match="stop_loss_pct"):
            EngineConfig(stop_loss_pct=1.0)

    def test_stop_loss_greater_than_one_raises(self):
        with pytest.raises(ValueError, match="stop_loss_pct"):
            EngineConfig(stop_loss_pct=1.5)

    def test_take_profit_zero_raises(self):
        with pytest.raises(ValueError, match="take_profit_pct"):
            EngineConfig(take_profit_pct=0.0)

    def test_take_profit_negative_raises(self):
        with pytest.raises(ValueError, match="take_profit_pct"):
            EngineConfig(take_profit_pct=-0.01)

    def test_valid_config_does_not_raise(self):
        cfg = EngineConfig(
            position_size=2.0,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            fee_rate=0.001,
            slippage_pct=0.0005,
        )
        assert cfg.position_size == 2.0

    def test_zero_fee_and_slippage_are_valid(self):
        cfg = EngineConfig(fee_rate=0.0, slippage_pct=0.0)
        assert cfg.fee_rate == 0.0
        assert cfg.slippage_pct == 0.0

    def test_stop_loss_none_and_tp_none_are_valid(self):
        cfg = EngineConfig(stop_loss_pct=None, take_profit_pct=None)
        assert cfg.stop_loss_pct is None
        assert cfg.take_profit_pct is None


# ── Bar validation ─────────────────────────────────────────────────────────────

class TestBarValidation:
    """Tests for _validate_bars; also exercises it via BacktestExecutor.run()."""

    def _good_bars(self) -> pd.DataFrame:
        return _flat_bars(100.0, 3)

    def test_missing_column_raises(self):
        bars = self._good_bars().drop(columns=["close"])
        with pytest.raises(ValueError, match="missing required column"):
            _validate_bars(bars)

    def test_nan_in_ohlc_raises(self):
        bars = self._good_bars().copy()
        bars.iloc[1, bars.columns.get_loc("close")] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            _validate_bars(bars)

    def test_inf_in_ohlc_raises(self):
        bars = self._good_bars().copy()
        bars.iloc[0, bars.columns.get_loc("high")] = float("inf")
        with pytest.raises(ValueError, match="infinite"):
            _validate_bars(bars)

    def test_high_less_than_low_raises(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 100.0),
            (100.0,  98.0, 99.0, 100.0),   # high < low
            (100.0, 101.0, 99.0, 100.0),
        ])
        with pytest.raises(ValueError, match="high < low"):
            _validate_bars(bars)

    def test_open_below_low_raises(self):
        bars = _bars([
            ( 95.0, 101.0, 99.0, 100.0),   # open=95 < low=99
        ])
        with pytest.raises(ValueError, match="open is outside"):
            _validate_bars(bars)

    def test_open_above_high_raises(self):
        bars = _bars([
            (105.0, 101.0, 99.0, 100.0),   # open=105 > high=101
        ])
        with pytest.raises(ValueError, match="open is outside"):
            _validate_bars(bars)

    def test_close_below_low_raises(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 98.0),   # close=98 < low=99
        ])
        with pytest.raises(ValueError, match="close is outside"):
            _validate_bars(bars)

    def test_close_above_high_raises(self):
        bars = _bars([
            (100.0, 101.0, 99.0, 102.0),   # close=102 > high=101
        ])
        with pytest.raises(ValueError, match="close is outside"):
            _validate_bars(bars)

    def test_valid_bars_do_not_raise(self):
        _validate_bars(self._good_bars())   # must not raise

    def test_invalid_bars_raise_via_executor(self):
        bars = self._good_bars().copy()
        bars.iloc[0, bars.columns.get_loc("high")] = float("nan")
        ex = BacktestExecutor(EngineConfig(fee_rate=0.0, slippage_pct=0.0))
        with pytest.raises(ValueError, match="NaN"):
            ex.run(bars, _Signals({}))


# ── Signal validation ──────────────────────────────────────────────────────────

class TestSignalValidation:
    """Tests for _validate_signals; also exercises it via BacktestExecutor.run()."""

    def _idx(self, n: int = 4) -> pd.DatetimeIndex:
        return pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")

    def test_lowercase_buy_raises(self):
        signals = pd.Series(["buy", "hold", "hold", "hold"], index=self._idx())
        with pytest.raises(ValueError, match="invalid signal"):
            _validate_signals(signals, 4)

    def test_none_value_raises(self):
        signals = pd.Series([None, Signal.HOLD, Signal.HOLD, Signal.HOLD],
                            index=self._idx(), dtype=object)
        with pytest.raises(ValueError, match="invalid signal"):
            _validate_signals(signals, 4)

    def test_unknown_string_raises(self):
        signals = pd.Series(["LONG", "HOLD", "HOLD", "HOLD"], index=self._idx())
        with pytest.raises(ValueError, match="invalid signal"):
            _validate_signals(signals, 4)

    def test_wrong_length_raises(self):
        signals = pd.Series([Signal.HOLD, Signal.HOLD], index=self._idx(2))
        with pytest.raises(ValueError, match="4 bars"):
            _validate_signals(signals, 4)

    def test_signal_enum_members_are_valid(self):
        signals = pd.Series(
            [Signal.BUY, Signal.HOLD, Signal.EXIT, Signal.SELL], index=self._idx()
        )
        _validate_signals(signals, 4)   # must not raise

    def test_uppercase_string_equivalents_are_valid(self):
        signals = pd.Series(["BUY", "HOLD", "EXIT", "SELL"], index=self._idx())
        _validate_signals(signals, 4)   # must not raise

    def test_invalid_signal_raises_via_executor(self):
        bars = _flat_bars(100.0, 4)

        class _BadSignals(StrategyBase):
            def generate_signals(self, b: pd.DataFrame) -> pd.Series:
                return pd.Series(["buy", "hold", "hold", "hold"], index=b.index)

        ex = BacktestExecutor(EngineConfig(fee_rate=0.0, slippage_pct=0.0))
        with pytest.raises(ValueError, match="invalid signal"):
            ex.run(bars, _BadSignals())
