"""Tests for research.walk_forward — WalkForwardTester."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.strategy import Signal, StrategyBase
from portfolio.models import PortfolioConfig
from research.walk_forward import (
    WalkForwardConfig,
    WalkForwardMode,
    WalkForwardResult,
    WalkForwardTester,
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _bars(n: int, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({
        "open"  : price,
        "high"  : price + 1.0,
        "low"   : price - 1.0,
        "close" : price,
        "volume": 1_000.0,
    }, index=idx)


class _HoldStrategy(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


def _hold_factory(train_bars: pd.DataFrame) -> _HoldStrategy:
    return _HoldStrategy()


# ── WalkForwardConfig validation ───────────────────────────────────────────────

class TestWalkForwardConfigValidation:
    def test_train_bars_minimum(self):
        with pytest.raises(ValueError, match="train_bars"):
            WalkForwardConfig(train_bars=1)

    def test_test_bars_minimum(self):
        with pytest.raises(ValueError, match="test_bars"):
            WalkForwardConfig(test_bars=0)

    def test_step_bars_minimum(self):
        with pytest.raises(ValueError, match="step_bars"):
            WalkForwardConfig(step_bars=0)

    def test_valid_config_accepted(self):
        cfg = WalkForwardConfig(train_bars=100, test_bars=20, mode=WalkForwardMode.ROLLING)
        assert cfg.train_bars == 100


# ── Fold count ─────────────────────────────────────────────────────────────────

class TestFoldCount:
    def test_rolling_single_fold(self):
        bars    = _bars(150)
        cfg     = WalkForwardConfig(train_bars=100, test_bars=50)
        tester  = WalkForwardTester(cfg)
        result  = tester.run(bars, _hold_factory)
        assert len(result.folds) == 1

    def test_rolling_two_folds(self):
        bars    = _bars(200)
        cfg     = WalkForwardConfig(train_bars=100, test_bars=50)
        tester  = WalkForwardTester(cfg)
        result  = tester.run(bars, _hold_factory)
        assert len(result.folds) == 2

    def test_expanding_produces_folds(self):
        bars    = _bars(200)
        cfg     = WalkForwardConfig(train_bars=100, test_bars=50, mode=WalkForwardMode.EXPANDING)
        tester  = WalkForwardTester(cfg)
        result  = tester.run(bars, _hold_factory)
        assert len(result.folds) >= 1

    def test_too_short_raises(self):
        bars   = _bars(10)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        with pytest.raises(ValueError, match="at least"):
            tester.run(bars, _hold_factory)


# ── Combined equity ────────────────────────────────────────────────────────────

class TestCombinedEquity:
    def test_combined_equity_length(self):
        bars   = _bars(200)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        expected_len = sum(len(f.portfolio_result.equity_curve) for f in result.folds)
        assert len(result.combined_equity) == expected_len

    def test_combined_equity_name(self):
        bars   = _bars(150)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        assert result.combined_equity.name == "wf_equity"


# ── Fold indices ───────────────────────────────────────────────────────────────

class TestFoldIndices:
    def test_rolling_train_window_constant_size(self):
        bars   = _bars(300)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        for f in result.folds:
            assert f.train_end - f.train_start + 1 == 100

    def test_expanding_train_window_grows(self):
        bars   = _bars(300)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50, mode=WalkForwardMode.EXPANDING)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        if len(result.folds) > 1:
            first_train_size = result.folds[0].train_end - result.folds[0].train_start + 1
            last_train_size  = result.folds[-1].train_end - result.folds[-1].train_start + 1
            assert last_train_size > first_train_size


# ── No-trade strategy produces stable capital ─────────────────────────────────

class TestNoTradeStrategy:
    def test_total_return_zero_with_hold_strategy(self):
        bars   = _bars(200)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        assert result.total_return == pytest.approx(0.0, abs=1e-9)

    def test_result_is_walk_forward_result(self):
        bars   = _bars(200)
        cfg    = WalkForwardConfig(train_bars=100, test_bars=50)
        tester = WalkForwardTester(cfg)
        result = tester.run(bars, _hold_factory)
        assert isinstance(result, WalkForwardResult)
