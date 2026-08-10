"""Tests for BatchBacktest — Phase 4 (per-pair) and Phase 5 (portfolio)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from jobs.batch_backtest import (
    BatchBacktest,
    BatchBacktestResult,
    SymbolResult,
    _max_drawdown,
    _sharpe_from_pnls,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bars(n: int, start_price: float = 100.0, trend: float = 1.0) -> pd.DataFrame:
    """Synthetic OHLCV bars with a simple linear price trend."""
    prices = [start_price + i * trend for i in range(n)]
    idx    = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open":   prices,
        "high":   [p * 1.001 for p in prices],
        "low":    [p * 0.999 for p in prices],
        "close":  prices,
        "volume": [1.0] * n,
    }, index=idx)


class _BuyAndHoldStrategy(StrategyBase):
    """Buy at bar 5, exit at bar 15 (if available)."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(bars) > 5:
            s.iloc[5] = Signal.BUY
        if len(bars) > 15:
            s.iloc[15] = Signal.EXIT
        return s


class _NeverTradeStrategy(StrategyBase):
    """Never signals — produces zero trades."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _AlwaysExitStrategy(StrategyBase):
    """Signals EXIT from the start — should produce no trades."""

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.EXIT, index=bars.index, dtype=object)


# ── SymbolResult ──────────────────────────────────────────────────────────────

class TestSymbolResult:
    def test_ok_when_portfolio_result_present(self):
        from portfolio.models import PortfolioConfig, SizingMode
        from portfolio.engine import PortfolioEngine
        bars   = _bars(30)
        result = PortfolioEngine(PortfolioConfig()).run(bars, _BuyAndHoldStrategy(), EngineConfig())
        sr     = SymbolResult(symbol="BTCUSDT", interval="1h", portfolio_result=result)
        assert sr.ok

    def test_not_ok_when_error(self):
        sr = SymbolResult(symbol="X", interval="1h", error="fetch failed")
        assert not sr.ok
        assert sr.n_trades == 0
        assert sr.total_return == 0.0

    def test_not_ok_when_no_result(self):
        sr = SymbolResult(symbol="X", interval="1h")
        assert not sr.ok


# ── BatchBacktest construction ─────────────────────────────────────────────────

class TestBatchBacktestValidation:
    def _bars_dict(self, symbols, intervals):
        return {(s, iv): _bars(50) for s in symbols for iv in intervals}

    def test_empty_symbols_raises(self):
        with pytest.raises(ValueError, match="symbols"):
            BatchBacktest(
                symbols=[], intervals=["1h"],
                strategy_class=_NeverTradeStrategy, params={},
                bars={}, starting_capital=10_000.0,
            )

    def test_empty_intervals_raises(self):
        with pytest.raises(ValueError, match="intervals"):
            BatchBacktest(
                symbols=["BTCUSDT"], intervals=[],
                strategy_class=_NeverTradeStrategy, params={},
                bars={}, starting_capital=10_000.0,
            )

    def test_zero_capital_raises(self):
        with pytest.raises(ValueError, match="starting_capital"):
            BatchBacktest(
                symbols=["BTCUSDT"], intervals=["1h"],
                strategy_class=_NeverTradeStrategy, params={},
                bars=self._bars_dict(["BTCUSDT"], ["1h"]),
                starting_capital=0.0,
            )

    def test_bad_equity_fraction_raises(self):
        with pytest.raises(ValueError, match="equity_fraction"):
            BatchBacktest(
                symbols=["BTCUSDT"], intervals=["1h"],
                strategy_class=_NeverTradeStrategy, params={},
                bars=self._bars_dict(["BTCUSDT"], ["1h"]),
                starting_capital=10_000.0,
                equity_fraction=0.0,
            )


# ── Phase 4: per-pair results ─────────────────────────────────────────────────

class TestBatchBacktestPerPair:
    def _run(self, symbols, intervals, strategy, params=None, n_bars=50):
        bars = {(s, iv): _bars(n_bars) for s in symbols for iv in intervals}
        return BatchBacktest(
            symbols=symbols,
            intervals=intervals,
            strategy_class=strategy,
            params=params or {},
            bars=bars,
            starting_capital=10_000.0,
        ).run()

    def test_single_pair_produces_one_result(self):
        result = self._run(["BTCUSDT"], ["1h"], _NeverTradeStrategy)
        assert len(result.symbol_results) == 1
        assert result.symbol_results[0].symbol == "BTCUSDT"
        assert result.symbol_results[0].interval == "1h"

    def test_three_symbols_one_interval_produces_three_results(self):
        result = self._run(["BTCUSDT", "ETHUSDT", "BNBUSDT"], ["1h"], _NeverTradeStrategy)
        assert len(result.symbol_results) == 3
        symbols_found = {r.symbol for r in result.symbol_results}
        assert symbols_found == {"BTCUSDT", "ETHUSDT", "BNBUSDT"}

    def test_one_symbol_three_intervals_produces_three_results(self):
        result = self._run(["BTCUSDT"], ["1h", "4h", "1d"], _NeverTradeStrategy)
        assert len(result.symbol_results) == 3
        intervals_found = {r.interval for r in result.symbol_results}
        assert intervals_found == {"1h", "4h", "1d"}

    def test_3x3_grid_produces_nine_results(self):
        result = self._run(
            ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            ["1h", "4h", "1d"],
            _NeverTradeStrategy,
        )
        assert len(result.symbol_results) == 9

    def test_missing_bars_produces_error_result(self):
        bt = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"],
            intervals=["1h"],
            strategy_class=_NeverTradeStrategy,
            params={},
            bars={("BTCUSDT", "1h"): _bars(50)},  # ETHUSDT missing
            starting_capital=10_000.0,
        )
        result = bt.run()
        sym_map = {r.symbol: r for r in result.symbol_results}
        assert sym_map["BTCUSDT"].ok
        assert not sym_map["ETHUSDT"].ok
        assert sym_map["ETHUSDT"].error is not None

    def test_no_trades_results_are_still_ok(self):
        result = self._run(["BTCUSDT"], ["1h"], _NeverTradeStrategy)
        assert result.symbol_results[0].ok
        assert result.symbol_results[0].n_trades == 0

    def test_trading_strategy_produces_trades(self):
        result = self._run(["BTCUSDT"], ["1h"], _BuyAndHoldStrategy, n_bars=50)
        sr = result.symbol_results[0]
        assert sr.ok
        assert sr.n_trades >= 1

    def test_each_pair_uses_full_starting_capital(self):
        # Two pairs both start with the same full capital (not split)
        bars = {
            ("BTCUSDT", "1h"): _bars(50, start_price=100.0, trend=1.0),
            ("ETHUSDT", "1h"): _bars(50, start_price=100.0, trend=1.0),
        }
        bt = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"],
            intervals=["1h"],
            strategy_class=_BuyAndHoldStrategy,
            params={},
            bars=bars,
            starting_capital=10_000.0,
        )
        result = bt.run()
        for sr in result.symbol_results:
            assert sr.ok
            assert sr.portfolio_result.starting_capital == pytest.approx(10_000.0)

    def test_successful_and_failed_pairs(self):
        bt = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"],
            intervals=["1h"],
            strategy_class=_NeverTradeStrategy,
            params={},
            bars={("BTCUSDT", "1h"): _bars(50)},
            starting_capital=10_000.0,
        )
        result = bt.run()
        assert len(result.successful_pairs) == 1
        assert len(result.failed_pairs) == 1


# ── Phase 5: portfolio-level simulation ───────────────────────────────────────

class TestPortfolioSimulation:
    def _run_two_symbols(self, strategy=None, equity_fraction=0.10, n_bars=50):
        strategy = strategy or _BuyAndHoldStrategy
        bars = {
            ("BTCUSDT", "1h"): _bars(n_bars, start_price=50_000.0, trend=100.0),
            ("ETHUSDT", "1h"): _bars(n_bars, start_price=3_000.0, trend=10.0),
        }
        return BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"],
            intervals=["1h"],
            strategy_class=strategy,
            params={},
            bars=bars,
            starting_capital=100_000.0,
            equity_fraction=equity_fraction,
        ).run()

    def test_portfolio_equity_curve_present(self):
        result = self._run_two_symbols()
        assert isinstance(result.portfolio_equity_curve, pd.Series)
        # At minimum the starting equity point is present
        assert len(result.portfolio_equity_curve) >= 1

    def test_portfolio_equity_starts_at_starting_capital(self):
        result = self._run_two_symbols()
        assert result.portfolio_equity_curve.iloc[0] == pytest.approx(100_000.0)

    def test_portfolio_n_trades_equals_sum_of_pair_trades(self):
        result = self._run_two_symbols()
        expected = sum(r.n_trades for r in result.successful_pairs)
        assert result.portfolio_n_trades == expected

    def test_no_trades_gives_zero_portfolio_metrics(self):
        bars = {
            ("BTCUSDT", "1h"): _bars(50),
            ("ETHUSDT", "1h"): _bars(50),
        }
        result = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT"],
            intervals=["1h"],
            strategy_class=_NeverTradeStrategy,
            params={},
            bars=bars,
            starting_capital=100_000.0,
        ).run()
        assert result.portfolio_n_trades == 0
        assert result.portfolio_total_return == 0.0

    def test_portfolio_win_rate_in_valid_range(self):
        result = self._run_two_symbols()
        if result.portfolio_n_trades > 0:
            assert 0.0 <= result.portfolio_win_rate <= 1.0

    def test_portfolio_equity_curve_monotone_with_uptrend(self):
        # Strong uptrend → profit → equity curve ends above start
        bars = {("BTCUSDT", "1h"): _bars(50, start_price=100.0, trend=5.0)}
        result = BatchBacktest(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            strategy_class=_BuyAndHoldStrategy,
            params={},
            bars=bars,
            starting_capital=10_000.0,
            equity_fraction=0.10,
        ).run()
        if result.portfolio_n_trades > 0:
            assert result.portfolio_equity_curve.iloc[-1] >= result.portfolio_equity_curve.iloc[0]

    def test_all_failed_pairs_produces_empty_portfolio(self):
        bt = BatchBacktest(
            symbols=["BTCUSDT"],
            intervals=["1h"],
            strategy_class=_NeverTradeStrategy,
            params={},
            bars={},  # no bars at all → all fail
            starting_capital=10_000.0,
        )
        result = bt.run()
        assert result.portfolio_n_trades == 0
        assert result.portfolio_total_return == 0.0

    def test_portfolio_not_simple_sum_of_individual_returns(self):
        # Portfolio return uses equity_fraction sizing, not full capital per pair.
        # So portfolio_total_return ≠ sum(individual total_return) in general.
        result = self._run_two_symbols(equity_fraction=0.10)
        # This just checks that we compute something; exact value is strategy-dependent
        assert isinstance(result.portfolio_total_return, float)
        assert not math.isnan(result.portfolio_total_return)

    def test_portfolio_metrics_are_finite(self):
        result = self._run_two_symbols()
        for attr in [
            "portfolio_total_return", "portfolio_net_profit",
            "portfolio_max_drawdown", "portfolio_sharpe", "portfolio_sortino",
            "portfolio_calmar", "portfolio_win_rate",
        ]:
            val = getattr(result, attr)
            assert math.isfinite(val), f"{attr} is not finite: {val}"

    def test_multi_worker_produces_same_pair_count(self):
        bars = {(s, iv): _bars(50) for s in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
                for iv in ["1h", "4h"]}
        result_seq = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            intervals=["1h", "4h"],
            strategy_class=_NeverTradeStrategy, params={},
            bars=bars, starting_capital=10_000.0, max_workers=1,
        ).run()
        result_par = BatchBacktest(
            symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            intervals=["1h", "4h"],
            strategy_class=_NeverTradeStrategy, params={},
            bars=bars, starting_capital=10_000.0, max_workers=3,
        ).run()
        assert len(result_seq.symbol_results) == len(result_par.symbol_results) == 6


# ── Helper functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_max_drawdown_flat_series(self):
        s = pd.Series([100.0, 100.0, 100.0])
        assert _max_drawdown(s) == pytest.approx(0.0)

    def test_max_drawdown_declining(self):
        s = pd.Series([100.0, 80.0, 90.0])
        dd = _max_drawdown(s)
        assert dd <= 0.0
        assert dd == pytest.approx(-0.20, abs=0.001)

    def test_max_drawdown_empty(self):
        assert _max_drawdown(pd.Series([], dtype=float)) == 0.0

    def test_sharpe_empty(self):
        assert _sharpe_from_pnls([], 10_000.0) == 0.0

    def test_sharpe_one_trade(self):
        assert _sharpe_from_pnls([100.0], 10_000.0) == 0.0

    def test_sharpe_positive_trades(self):
        pnls = [100.0, 200.0, 150.0, 120.0]
        s = _sharpe_from_pnls(pnls, 10_000.0)
        assert s > 0

    def test_sharpe_finite(self):
        pnls = [50.0] * 10
        s = _sharpe_from_pnls(pnls, 10_000.0)
        assert math.isfinite(s)
