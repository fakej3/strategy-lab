"""Tests for research.curves — return and rolling metric builders."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.curves import build_daily_returns, build_monthly_returns, build_rolling_metric


def _equity(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="1D")
    return pd.Series(values, index=idx, name="equity")


# ── build_daily_returns ────────────────────────────────────────────────────────

class TestBuildDailyReturns:
    def test_simple_returns_correct(self):
        eq  = _equity([100.0, 110.0, 99.0])
        ret = build_daily_returns(eq)
        assert len(ret) == 2
        assert ret.iloc[0] == pytest.approx(0.10, rel=1e-9)
        assert ret.iloc[1] == pytest.approx(-0.10, rel=1e-6)

    def test_first_bar_dropped(self):
        eq  = _equity([100.0, 105.0])
        ret = build_daily_returns(eq)
        assert len(ret) == 1

    def test_flat_curve_returns_zero(self):
        eq  = _equity([100.0] * 10)
        ret = build_daily_returns(eq)
        assert (ret == 0.0).all()

    def test_name_is_returns(self):
        eq = _equity([100.0, 110.0])
        assert build_daily_returns(eq).name == "returns"


# ── build_monthly_returns ─────────────────────────────────────────────────────

class TestBuildMonthlyReturns:
    def test_two_months_one_return(self):
        # January and February
        idx = pd.date_range("2024-01-01", periods=60, freq="1D")
        eq  = pd.Series(100.0 + np.arange(60) * 0.5, index=idx, name="equity")
        mr  = build_monthly_returns(eq)
        assert len(mr) >= 1

    def test_name_is_monthly_returns(self):
        idx = pd.date_range("2024-01-01", periods=40, freq="1D")
        eq  = pd.Series(100.0 + np.arange(40), index=idx, name="equity")
        assert build_monthly_returns(eq).name == "monthly_returns"

    def test_single_month_returns_empty(self):
        # Only 10 days in January → only one month-end → pct_change drops it → empty
        idx = pd.date_range("2024-01-01", periods=10, freq="1D")
        eq  = pd.Series(100.0 + np.arange(10), index=idx, name="equity")
        mr  = build_monthly_returns(eq)
        assert len(mr) == 0


# ── build_rolling_metric ──────────────────────────────────────────────────────

class TestBuildRollingMetric:
    def _sharpe(self, returns: pd.Series) -> float:
        std = returns.std()
        return float(returns.mean() / std * math.sqrt(252)) if std > 0 else 0.0

    def test_raises_on_window_lt_2(self):
        eq = _equity([100.0] * 20)
        with pytest.raises(ValueError, match="window"):
            build_rolling_metric(eq, lambda r: 0.0, window=1)

    def test_output_length_matches_equity(self):
        eq  = _equity([100.0 + i for i in range(50)])
        res = build_rolling_metric(eq, self._sharpe, window=10)
        assert len(res) == len(eq)

    def test_leading_nans_before_full_window(self):
        eq  = _equity([100.0 + i for i in range(20)])
        res = build_rolling_metric(eq, self._sharpe, window=10)
        assert res.iloc[:9].isna().all()   # first window-1 bars are NaN
        assert not res.iloc[9:].isna().all()

    def test_name_is_rolling_metric(self):
        eq  = _equity([100.0 + i for i in range(10)])
        res = build_rolling_metric(eq, lambda r: 0.0, window=2)
        assert res.name == "rolling_metric"

    def test_min_periods_override(self):
        eq  = _equity([100.0 + i for i in range(20)])
        res = build_rolling_metric(eq, self._sharpe, window=10, min_periods=3)
        # With min_periods=3, bars 0-1 are still NaN (fewer than 3 points)
        assert res.iloc[:2].isna().all()
        assert not res.iloc[3:].isna().all()
