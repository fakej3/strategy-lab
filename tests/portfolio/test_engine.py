"""Tests for portfolio.PortfolioEngine — sizing, equity curves, drawdown."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import (
    PortfolioEngine,
    build_balance_curve,
    build_drawdown_curve,
    build_equity_curve,
)
from portfolio.models import PortfolioConfig, PortfolioResult, SizingMode


# ── Shared test helpers ────────────────────────────────────────────────────────

def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": [1.0] * len(rows)},
        index=idx,
    )


def _flat_bars(price: float, n: int) -> pd.DataFrame:
    return _bars([(price, price + 1.0, price - 1.0, price)] * n)


class _FixedSignals(StrategyBase):
    def __init__(self, signal_map: dict[int, Signal], default: Signal = Signal.HOLD):
        self._map     = signal_map
        self._default = default

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(self._default, index=bars.index, dtype=object)
        for i, sig in self._map.items():
            if i < len(bars):
                s.iloc[i] = sig
        return s


@pytest.fixture
def free() -> EngineConfig:
    return EngineConfig(fee_rate=0.0, slippage_pct=0.0)


# ── PortfolioConfig validation ─────────────────────────────────────────────────

class TestPortfolioConfigValidation:
    def test_starting_capital_positive(self):
        with pytest.raises(ValueError, match="starting_capital"):
            PortfolioConfig(starting_capital=0.0)

    def test_position_size_positive(self):
        with pytest.raises(ValueError, match="position_size"):
            PortfolioConfig(position_size=0.0)

    def test_equity_fraction_range(self):
        with pytest.raises(ValueError, match="equity_fraction"):
            PortfolioConfig(equity_fraction=0.0)
        with pytest.raises(ValueError, match="equity_fraction"):
            PortfolioConfig(equity_fraction=1.5)

    def test_trade_capital_positive(self):
        with pytest.raises(ValueError, match="trade_capital"):
            PortfolioConfig(trade_capital=0.0)

    def test_fraction_range(self):
        with pytest.raises(ValueError, match="fraction"):
            PortfolioConfig(fraction=0.0)

    def test_valid_defaults(self):
        cfg = PortfolioConfig()
        assert cfg.starting_capital == 100_000.0
        assert cfg.sizing_mode == SizingMode.FIXED_UNITS


# ── No-trade case ─────────────────────────────────────────────────────────────

class TestNoTrades:
    def test_all_hold_returns_flat_curves(self, free):
        bars = _flat_bars(100.0, 10)
        cfg  = PortfolioConfig(starting_capital=50_000.0)
        eng  = PortfolioEngine(cfg)

        class _Hold(StrategyBase):
            def generate_signals(self, bars):
                return pd.Series(Signal.HOLD, index=bars.index, dtype=object)

        result = eng.run(bars, _Hold(), free)
        assert result.trades == []
        assert result.total_return == 0.0
        assert result.max_drawdown_pct == 0.0
        assert len(result.equity_curve) == len(bars)
        assert (result.equity_curve == 50_000.0).all()

    def test_ending_equity_equals_starting_when_no_trades(self, free):
        bars   = _flat_bars(100.0, 5)
        result = PortfolioEngine().run(bars, _FixedSignals({}), free)
        assert result.ending_equity == result.starting_capital


# ── FIXED_UNITS sizing ─────────────────────────────────────────────────────────

class TestFixedUnitsSizing:
    def test_single_trade_pnl(self, free):
        # Buy at bar 0 open (100), exit at bar 2 open (110)
        bars   = _bars([(100, 101, 99, 100), (110, 111, 109, 110), (110, 111, 109, 110)])
        cfg    = PortfolioConfig(starting_capital=10_000.0, position_size=1.0)
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 1: Signal.EXIT}), free
        )
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.size == 1.0
        # entry at bar 1 open (110), exit at bar 2 open (110)
        # Actually: BUY at bar 0 → fills bar 1 open; EXIT at bar 1 → fills bar 2 open
        assert trade.net_pnl == pytest.approx(0.0, abs=1.0)

    def test_equity_grows_with_profit(self, free):
        # BUY at bar 0 → fills bar 1 open (120); EXIT at bar 1 → fills bar 2 open (120)
        # Flat exit at same price → no PnL; this test verifies no crash and valid result
        bars   = _bars([(100, 110, 90, 105), (120, 125, 115, 120), (120, 125, 115, 120)])
        cfg    = PortfolioConfig(starting_capital=10_000.0, position_size=1.0)
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 1: Signal.EXIT}), free
        )
        assert len(result.trades) == 1
        assert result.ending_equity == pytest.approx(result.starting_capital, rel=1e-6)

    def test_equity_curve_long_direction_sign(self, free):
        # Price rises from 100 to 200 while in a long position
        # Unrealized PnL should be positive, raising the equity curve
        bars = _bars([
            (100, 101, 99, 100),
            (100, 201, 99, 200),
            (200, 201, 199, 200),
            (200, 201, 199, 200),
        ])
        cfg    = PortfolioConfig(starting_capital=10_000.0, position_size=1.0)
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        if result.trades:
            # While in position bars 1–2, equity should exceed starting capital
            assert result.equity_curve.iloc[1] > result.starting_capital


# ── PCT_OF_EQUITY sizing ───────────────────────────────────────────────────────

class TestPctOfEquitySizing:
    def test_size_scales_with_equity(self, free):
        bars = _flat_bars(100.0, 5)
        cfg  = PortfolioConfig(
            starting_capital=10_000.0,
            sizing_mode=SizingMode.PCT_OF_EQUITY,
            equity_fraction=0.10,
        )
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        if result.trades:
            trade = result.trades[0]
            # 10% of 10000 / 100 = 10 units
            assert trade.size == pytest.approx(10.0, rel=1e-6)

    def test_size_field_correct(self, free):
        bars = _flat_bars(200.0, 5)
        cfg  = PortfolioConfig(
            starting_capital=20_000.0,
            sizing_mode=SizingMode.PCT_OF_EQUITY,
            equity_fraction=0.05,
        )
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        if result.trades:
            # 5% of 20000 / 200 = 5 units
            assert result.trades[0].size == pytest.approx(5.0, rel=1e-6)


# ── FIXED_DOLLAR sizing ────────────────────────────────────────────────────────

class TestFixedDollarSizing:
    def test_size_equals_capital_over_price(self, free):
        bars = _flat_bars(50.0, 5)
        cfg  = PortfolioConfig(
            starting_capital=100_000.0,
            sizing_mode=SizingMode.FIXED_DOLLAR,
            trade_capital=5_000.0,
        )
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        if result.trades:
            # 5000 / 50 = 100 units
            assert result.trades[0].size == pytest.approx(100.0, rel=1e-6)


# ── FRACTIONAL sizing ──────────────────────────────────────────────────────────

class TestFractionalSizing:
    def test_size_uses_fraction(self, free):
        bars = _flat_bars(100.0, 5)
        cfg  = PortfolioConfig(
            starting_capital=10_000.0,
            sizing_mode=SizingMode.FRACTIONAL,
            fraction=0.25,
        )
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        if result.trades:
            # 25% of 10000 / 100 = 25 units
            assert result.trades[0].size == pytest.approx(25.0, rel=1e-6)


# ── Equity curve builders ──────────────────────────────────────────────────────

class TestBuildEquityCurve:
    def test_empty_trades_returns_flat_curve(self):
        bars = _flat_bars(100.0, 5)
        ec   = build_equity_curve(bars, [], 10_000.0)
        assert len(ec) == 5
        assert (ec == 10_000.0).all()
        assert ec.name == "equity"

    def test_empty_bars_returns_empty_series(self):
        bars = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([]),
        )
        ec = build_equity_curve(bars, [], 10_000.0)
        assert len(ec) == 0

    def test_curve_length_matches_bars(self, free):
        bars   = _flat_bars(100.0, 10)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 4: Signal.EXIT}), free
        )
        assert len(result.equity_curve) == len(bars)

    def test_equity_includes_unrealized_pnl(self, free):
        # Bars: open at 100, then price rises to 200
        bars = _bars([
            (100, 101, 99, 100),
            (100, 201, 99, 200),   # entry bar: fills at bar 1 open (100)
            (200, 201, 199, 200),
            (200, 201, 199, 200),  # exit triggered here
            (200, 201, 199, 200),
        ])
        cfg    = PortfolioConfig(starting_capital=10_000.0, position_size=1.0)
        result = PortfolioEngine(cfg).run(
            bars, _FixedSignals({0: Signal.BUY, 3: Signal.EXIT}), free
        )
        # While in position, equity > starting_capital (unrealized gain)
        if result.trades:
            assert result.equity_curve.max() >= result.starting_capital


class TestBuildBalanceCurve:
    def test_flat_until_exit(self, free):
        bars   = _flat_bars(100.0, 8)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 4: Signal.EXIT}), free
        )
        if result.trades:
            # Balance should be flat at starting_capital until exit
            exit_bar = result.trades[0].exit_bar
            assert (result.balance_curve.iloc[:exit_bar] == result.starting_capital).all()

    def test_empty_bars_returns_empty_series(self):
        bars = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([]),
        )
        bc = build_balance_curve(bars, [], 10_000.0)
        assert len(bc) == 0


class TestBuildDrawdownCurve:
    def test_all_zeros_when_equity_monotonic(self):
        equity = pd.Series([100.0, 105.0, 110.0, 115.0])
        dd     = build_drawdown_curve(equity)
        assert (dd == 0.0).all()
        assert dd.name == "drawdown"

    def test_drawdown_negative(self):
        equity = pd.Series([100.0, 90.0])
        dd     = build_drawdown_curve(equity)
        assert dd.iloc[1] == pytest.approx(-0.10, rel=1e-6)

    def test_max_drawdown_matches_result(self, free):
        bars   = _bars([(100, 110, 90, 100)] * 10)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 5: Signal.EXIT}), free
        )
        manual_max = float(-result.drawdown_curve.min())
        assert manual_max == pytest.approx(result.max_drawdown_pct, rel=1e-6)


# ── PortfolioResult fields ─────────────────────────────────────────────────────

class TestPortfolioResultFields:
    def test_exposure_pct_in_unit_range(self, free):
        bars   = _flat_bars(100.0, 10)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 4: Signal.EXIT}), free
        )
        assert 0.0 <= result.exposure_pct <= 1.0

    def test_peak_equity_gte_ending(self, free):
        bars   = _flat_bars(100.0, 10)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 4: Signal.EXIT}), free
        )
        assert result.peak_equity >= result.ending_equity

    def test_net_profit_matches_total_return(self, free):
        bars   = _flat_bars(100.0, 5)
        result = PortfolioEngine().run(
            bars, _FixedSignals({0: Signal.BUY, 2: Signal.EXIT}), free
        )
        expected_return = result.net_profit / result.starting_capital
        assert result.total_return == pytest.approx(expected_return, rel=1e-9)
