"""Unit tests for research/robustness.py — score ranges, sensitivity direction."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.robustness import (
    _generate_neighbor_combos,
    _compute_sensitivity,
    analyze_robustness,
)


def _make_bars(n: int = 600) -> pd.DataFrame:
    np.random.seed(7)
    idx    = pd.date_range("2022-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    prices = 40000 + np.cumsum(np.random.randn(n) * 10 + 0.5)
    prices = np.maximum(prices, 1.0)
    return pd.DataFrame({
        "open":   prices,
        "high":   prices + 5,
        "low":    prices - 5,
        "close":  prices,
        "volume": np.random.uniform(100, 1000, n),
    }, index=idx)


class TestGenerateNeighborCombos:
    def test_single_param_generates_two_neighbors(self):
        focal = {"fast": 10}
        space = {"fast": [5, 10, 15, 20]}
        combos = _generate_neighbor_combos(focal, space)
        assert len(combos) == 2
        vals = [c["fast"] for c in combos]
        assert 5 in vals
        assert 15 in vals

    def test_focal_at_start_generates_one_neighbor(self):
        focal = {"fast": 5}
        space = {"fast": [5, 10, 15, 20]}
        combos = _generate_neighbor_combos(focal, space)
        assert len(combos) == 1
        assert combos[0]["fast"] == 10

    def test_focal_at_end_generates_one_neighbor(self):
        focal = {"fast": 20}
        space = {"fast": [5, 10, 15, 20]}
        combos = _generate_neighbor_combos(focal, space)
        assert len(combos) == 1
        assert combos[0]["fast"] == 15

    def test_two_params_generates_up_to_four_neighbors(self):
        focal = {"fast": 10, "slow": 50}
        space = {"fast": [5, 10, 15], "slow": [30, 50, 100]}
        combos = _generate_neighbor_combos(focal, space)
        # fast: 5, 15 → 2; slow: 30, 100 → 2; total = 4
        assert len(combos) == 4
        # All should preserve the other param
        for c in combos:
            changed = [k for k in focal if c[k] != focal[k]]
            assert len(changed) == 1

    def test_focal_value_not_in_space_is_skipped(self):
        focal = {"fast": 99}
        space = {"fast": [5, 10, 15]}
        combos = _generate_neighbor_combos(focal, space)
        assert combos == []

    def test_no_duplicates(self):
        focal  = {"fast": 10, "slow": 50}
        space  = {"fast": [5, 10, 15], "slow": [30, 50, 100]}
        combos = _generate_neighbor_combos(focal, space)
        keys   = [tuple(sorted(c.items())) for c in combos]
        assert len(keys) == len(set(keys))


class TestComputeSensitivity:
    def test_sensitivity_increases_with_large_delta_sharpe(self):
        focal_params = {"fast": 10, "slow": 50}
        focal_sharpe = 1.0
        space        = {"fast": [5, 10, 15], "slow": [30, 50, 100]}
        neighbors = [
            {"params": {"fast": 5,  "slow": 50}, "net_profit": 100, "sharpe": 0.0},
            {"params": {"fast": 15, "slow": 50}, "net_profit": 100, "sharpe": 2.0},
        ]
        sensitivity = _compute_sensitivity(focal_params, focal_sharpe, space, neighbors)
        # fast: |0-1|/|5-10| + |2-1|/|15-10| / 2 = 1/5 + 1/5 / 2 = 0.2
        assert sensitivity.get("fast") == pytest.approx(0.2, abs=1e-5)

    def test_no_relevant_neighbors_returns_none(self):
        focal_params = {"fast": 10}
        space        = {"fast": [5, 10, 15]}
        # No neighbors that changed "fast"
        neighbors = [{"params": {"fast": 10}, "sharpe": 1.0, "net_profit": 0}]
        sensitivity = _compute_sensitivity(focal_params, 1.0, space, neighbors)
        assert sensitivity.get("fast") is None


class TestAnalyzeRobustness:
    """Integration tests — run real backtests on synthetic bars."""

    def test_robustness_score_in_0_100(self):
        from strategies.ema_crossover import EMACrossover
        bars    = _make_bars(600)
        space   = {"fast": [5, 10, 15, 20], "slow": [30, 40, 50]}
        focal   = {"fast": 10, "slow": 40}
        result  = analyze_robustness(
            bars, EMACrossover, focal, space,
            bars_per_year=8760,
        )
        assert result["robustness_score"] is not None
        assert 0.0 <= result["robustness_score"] <= 100.0

    def test_stability_score_in_0_100(self):
        from strategies.ema_crossover import EMACrossover
        bars   = _make_bars(600)
        space  = {"fast": [5, 10, 15, 20], "slow": [30, 40, 50]}
        focal  = {"fast": 10, "slow": 40}
        result = analyze_robustness(bars, EMACrossover, focal, space)
        assert result["stability_score"] is not None
        assert 0.0 <= result["stability_score"] <= 100.0

    def test_empty_param_space_returns_empty(self):
        from strategies.ema_crossover import EMACrossover
        bars   = _make_bars(200)
        result = analyze_robustness(bars, EMACrossover, {"fast": 5}, {})
        assert result["robustness_score"] is None

    def test_neighbor_results_have_required_keys(self):
        from strategies.ema_crossover import EMACrossover
        bars   = _make_bars(600)
        space  = {"fast": [5, 10, 15], "slow": [30, 50]}
        focal  = {"fast": 10, "slow": 30}
        result = analyze_robustness(bars, EMACrossover, focal, space)
        for nr in result["neighbor_results"]:
            assert "params" in nr
            assert "net_profit" in nr
            assert "sharpe" in nr

    def test_focal_at_edge_of_space(self):
        from strategies.ema_crossover import EMACrossover
        # focal is at the edge → fewer neighbors
        bars   = _make_bars(600)
        space  = {"fast": [5, 10, 15], "slow": [30, 40, 50]}
        focal  = {"fast": 5, "slow": 30}
        result = analyze_robustness(bars, EMACrossover, focal, space)
        # Should still complete without error, may have fewer neighbors
        assert result["n_neighbors"] >= 0
