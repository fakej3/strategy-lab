"""Tests for research.comparison — compare_strategies."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.strategy import Signal, StrategyBase
from research.comparison import ComparisonResult, compare_strategies


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _bars(n: int = 50, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({
        "open"  : price,
        "high"  : price + 1.0,
        "low"   : price - 1.0,
        "close" : price,
        "volume": 1_000.0,
    }, index=idx)


class _Hold(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


class _BuyFirst(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        s.iloc[0] = Signal.BUY
        return s


# ── Validation ────────────────────────────────────────────────────────────────

class TestCompareStrategiesValidation:
    def test_empty_strategies_raises(self):
        bars = _bars()
        with pytest.raises(ValueError, match="at least one"):
            compare_strategies(bars, {})


# ── Return type ───────────────────────────────────────────────────────────────

class TestCompareStrategiesReturn:
    def test_returns_comparison_result(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert isinstance(result, ComparisonResult)

    def test_single_strategy(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert len(result.ranking) == 1
        assert "Hold" in result.metrics
        assert "Hold" in result.results

    def test_two_strategies(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold(), "Buy": _BuyFirst()})
        assert len(result.ranking) == 2
        assert set(result.metrics.keys()) == {"Hold", "Buy"}


# ── Ranking structure ─────────────────────────────────────────────────────────

class TestRankingStructure:
    def test_strategy_name_column_present(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert "strategy_name" in result.ranking.columns

    def test_sharpe_ratio_column_present(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert "sharpe_ratio" in result.ranking.columns

    def test_cagr_column_present(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert "cagr" in result.ranking.columns

    def test_max_drawdown_column_present(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert "max_drawdown_pct" in result.ranking.columns

    def test_sort_by_calmar(self):
        bars   = _bars()
        result = compare_strategies(
            bars,
            {"Hold": _Hold(), "Buy": _BuyFirst()},
            sort_by="calmar_ratio",
        )
        calmar = result.ranking["calmar_ratio"].tolist()
        assert calmar == sorted(calmar, reverse=True)

    def test_all_expected_columns(self):
        bars     = _bars()
        result   = compare_strategies(bars, {"Hold": _Hold()})
        expected = {
            "strategy_name", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "cagr", "max_drawdown_pct", "win_rate", "profit_factor",
            "total_trades", "total_return",
        }
        assert expected.issubset(set(result.ranking.columns))


# ── Metrics dict ──────────────────────────────────────────────────────────────

class TestMetricsDict:
    def test_metrics_contains_institutional_metrics(self):
        from research.metrics import InstitutionalMetrics
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert isinstance(result.metrics["Hold"], InstitutionalMetrics)

    def test_results_contains_portfolio_result(self):
        from portfolio.models import PortfolioResult
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()})
        assert isinstance(result.results["Hold"], PortfolioResult)


# ── Invalid sort_by ───────────────────────────────────────────────────────────

class TestInvalidSortBy:
    def test_invalid_sort_by_raises_value_error(self):
        bars = _bars()
        with pytest.raises(ValueError, match="sort_by"):
            compare_strategies(bars, {"Hold": _Hold()}, sort_by="not_a_real_column")

    def test_valid_sort_by_does_not_raise(self):
        bars   = _bars()
        result = compare_strategies(bars, {"Hold": _Hold()}, sort_by="cagr")
        assert "cagr" in result.ranking.columns
