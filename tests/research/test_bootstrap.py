"""Unit tests for research/bootstrap.py — deterministic seed, hand-verified bounds."""
from __future__ import annotations

import pytest

from research.bootstrap import bootstrap_confidence_intervals, _max_drawdown_from_pnls


class TestBootstrapCI:
    def test_empty_pnls_returns_null_ci(self):
        result = bootstrap_confidence_intervals([], n_simulations=100)
        assert result["n_trades"] == 0
        assert result["total_return"]["pct_50"] is None

    def test_two_pnls_returns_null_ci(self):
        result = bootstrap_confidence_intervals([10.0, -5.0], n_simulations=100)
        assert result["total_return"]["pct_50"] is None

    def test_deterministic_seed(self):
        pnls = [10.0, -5.0, 8.0, -2.0, 15.0, -3.0, 7.0]
        r1   = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=200)
        r2   = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=200)
        assert r1["total_return"]["pct_50"] == r2["total_return"]["pct_50"]
        assert r1["win_rate"]["pct_5"]      == r2["win_rate"]["pct_5"]

    def test_different_seeds_differ(self):
        pnls = [10.0, -5.0, 8.0, -2.0, 15.0, -3.0, 7.0]
        r1   = bootstrap_confidence_intervals(pnls, seed=0,  n_simulations=200)
        r2   = bootstrap_confidence_intervals(pnls, seed=99, n_simulations=200)
        # High probability of differing — not a certainty, but with 200 sims it's very likely
        assert r1["total_return"]["pct_50"] != r2["total_return"]["pct_50"]

    def test_ordering_pct5_le_pct50_le_pct95(self):
        pnls = [float(i - 5) for i in range(20)]
        result = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=500)
        for metric in ("total_return", "trade_sharpe", "win_rate",
                       "profit_factor", "expectancy", "max_drawdown"):
            ci = result[metric]
            if ci["pct_5"] is not None:
                assert ci["pct_5"] <= ci["pct_50"] <= ci["pct_95"], metric

    def test_win_rate_bounds_in_0_1(self):
        pnls   = [10.0, -5.0, 8.0, -2.0, 15.0, -3.0, 7.0, 4.0, -1.0, 6.0]
        result = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=500)
        for pct in ("pct_5", "pct_50", "pct_95"):
            v = result["win_rate"][pct]
            if v is not None:
                assert 0.0 <= v <= 1.0

    def test_max_drawdown_non_negative(self):
        pnls   = [10.0, -5.0, 8.0, -2.0, 15.0]
        result = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=500)
        for pct in ("pct_5", "pct_50", "pct_95"):
            v = result["max_drawdown"][pct]
            if v is not None:
                assert v >= 0.0

    def test_known_all_positive_pnls_return_positive_total_return(self):
        pnls   = [10.0, 20.0, 30.0, 15.0, 25.0]
        result = bootstrap_confidence_intervals(
            pnls, starting_capital=100_000.0, seed=42, n_simulations=200
        )
        # All trades profitable → all bootstrap samples should have positive total return
        assert result["total_return"]["pct_5"] > 0.0

    def test_n_simulations_recorded(self):
        pnls   = [1.0, -1.0, 2.0, -2.0, 3.0]
        result = bootstrap_confidence_intervals(pnls, n_simulations=77, seed=0)
        assert result["n_simulations"] == 77
        assert result["n_trades"] == 5

    def test_all_metric_keys_present(self):
        pnls   = [1.0, -1.0, 2.0, -2.0, 3.0]
        result = bootstrap_confidence_intervals(pnls, seed=42, n_simulations=100)
        for m in ("total_return", "trade_sharpe", "win_rate",
                  "profit_factor", "expectancy", "max_drawdown"):
            assert m in result
            ci = result[m]
            for pct in ("pct_5", "pct_50", "pct_95"):
                assert pct in ci


class TestMaxDrawdownFromPnls:
    def test_all_positive_no_drawdown(self):
        import numpy as np
        pnls = np.array([10.0, 20.0, 30.0])
        dd   = _max_drawdown_from_pnls(pnls)
        assert dd == pytest.approx(0.0)

    def test_single_loss(self):
        import numpy as np
        # equity: 0 → 10 → 0 → 20
        pnls = np.array([10.0, -10.0, 20.0])
        dd   = _max_drawdown_from_pnls(pnls)
        assert dd == pytest.approx(10.0)

    def test_no_pnls_empty_result(self):
        import numpy as np
        pnls = np.array([], dtype=float)
        dd   = _max_drawdown_from_pnls(pnls)
        assert dd == pytest.approx(0.0)
