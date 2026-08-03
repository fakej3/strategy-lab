"""Unit tests for research/distribution.py — hand-verified calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.distribution import analyze_distribution, _compute_dd_durations


def _eq(values) -> pd.Series:
    idx = pd.date_range("2022-01-01", periods=len(values), freq="1h", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


class TestAnalyzeDistribution:
    def test_empty_pnls_returns_empty_result(self):
        result = analyze_distribution([], _eq([100_000.0]))
        assert result["pct_50"] is None
        assert result["max_consec_wins"] == 0
        assert result["max_consec_losses"] == 0

    def test_percentiles_known_values(self):
        # pnls = [-3, -1, 0, 2, 4, 6, 8, 10, 12, 14]
        pnls   = [-3.0, -1.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]
        result = analyze_distribution(pnls, _eq([100_000.0]))
        expected_p50 = np.percentile(pnls, 50)
        assert result["pct_50"] == pytest.approx(float(expected_p50), abs=1e-4)
        assert result["pct_5"]  == pytest.approx(float(np.percentile(pnls, 5)), abs=1e-4)
        assert result["pct_95"] == pytest.approx(float(np.percentile(pnls, 95)), abs=1e-4)

    def test_var_5pct_equals_5th_percentile(self):
        pnls   = list(range(-50, 51))  # -50..50 inclusive
        result = analyze_distribution(pnls, _eq([100_000.0]))
        expected = float(np.percentile(pnls, 5))
        assert result["var_5pct"] == pytest.approx(expected, abs=1e-3)

    def test_cvar_is_mean_below_var(self):
        pnls = list(range(-50, 51))
        result = analyze_distribution(pnls, _eq([100_000.0]))
        arr    = np.array(pnls, dtype=float)
        var    = float(np.percentile(arr, 5))
        below  = arr[arr <= var]
        expected_cvar = float(below.mean())
        assert result["cvar_5pct"] == pytest.approx(expected_cvar, abs=1e-3)

    def test_consecutive_wins_hand_calculated(self):
        # +,+,+,-,+,-,-,+  → max wins = 3, max losses = 2
        pnls   = [1.0, 2.0, 3.0, -1.0, 4.0, -2.0, -3.0, 5.0]
        result = analyze_distribution(pnls, _eq([100_000.0]))
        assert result["max_consec_wins"]   == 3
        assert result["max_consec_losses"] == 2

    def test_all_winners(self):
        pnls   = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = analyze_distribution(pnls, _eq([100_000.0]))
        assert result["max_consec_wins"]   == 5
        assert result["max_consec_losses"] == 0

    def test_histogram_bins_and_counts(self):
        pnls   = [float(i) for i in range(1, 21)]
        result = analyze_distribution(pnls, _eq([100_000.0]), n_bins=5)
        hist   = result["histogram"]
        assert len(hist["counts"]) == 5
        assert len(hist["bins"])   == 6  # n_bins+1 edges
        assert sum(hist["counts"]) == len(pnls)

    def test_all_keys_present(self):
        pnls   = [1.0, -1.0, 2.0]
        result = analyze_distribution(pnls, _eq([100_000.0]))
        for k in ("pct_5", "pct_25", "pct_50", "pct_75", "pct_95",
                  "var_5pct", "cvar_5pct",
                  "max_consec_wins", "max_consec_losses",
                  "histogram", "dd_durations"):
            assert k in result


class TestComputeDdDurations:
    def test_no_drawdown_returns_zero(self):
        # Monotonically rising equity → no drawdown
        eq     = _eq([100.0, 101.0, 102.0, 103.0, 104.0])
        result = _compute_dd_durations(eq)
        assert result["n_periods"] == 0
        assert result["max_bars"]  == 0

    def test_single_drawdown(self):
        # Peak at 102, then drops to 100, recovers above 102
        # Drawdown starts at bar 2 (102→101), ends at bar 3 (102 exceeded)
        eq     = _eq([100.0, 101.0, 102.0, 101.0, 100.0, 103.0])
        result = _compute_dd_durations(eq)
        assert result["n_periods"] >= 1
        assert result["max_bars"]  >= 1

    def test_never_recovers(self):
        # Drawdown from bar 1 onwards, never recovers
        eq     = _eq([100.0, 90.0, 80.0, 70.0])
        result = _compute_dd_durations(eq)
        assert result["n_periods"] == 1
        assert result["max_bars"]  == 3   # bars 1,2,3

    def test_short_equity_curve(self):
        eq     = _eq([100.0])
        result = _compute_dd_durations(eq)
        assert result["n_periods"] == 0
