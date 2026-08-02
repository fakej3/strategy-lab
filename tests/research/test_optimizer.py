"""Tests for research.optimizer — GridSearchOptimizer and RandomSearchOptimizer."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.strategy import Signal, StrategyBase
from research.optimizer import (
    GridSearchOptimizer,
    OptimizationResult,
    ParameterSpace,
    RandomSearchOptimizer,
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _bars(n: int = 100, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({
        "open"  : price,
        "high"  : price + 1.0,
        "low"   : price - 1.0,
        "close" : price,
        "volume": 1_000.0,
    }, index=idx)


class _HoldStrategy(StrategyBase):
    def __init__(self, fast: int = 10, slow: int = 30):
        self.fast = fast
        self.slow = slow

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


# ── ParameterSpace ─────────────────────────────────────────────────────────────

class TestParameterSpace:
    def test_all_combinations_correct_count(self):
        space  = ParameterSpace({"fast": [5, 10], "slow": [20, 30, 50]})
        combos = space.all_combinations()
        assert len(combos) == 6

    def test_empty_space_returns_one_empty_dict(self):
        space  = ParameterSpace({})
        combos = space.all_combinations()
        assert combos == [{}]

    def test_single_param(self):
        space  = ParameterSpace({"fast": [5, 10, 20]})
        combos = space.all_combinations()
        assert len(combos) == 3
        assert all("fast" in c for c in combos)

    def test_random_sample_count(self):
        space   = ParameterSpace({"fast": [5, 10, 20, 50]})
        samples = space.random_sample(7, seed=42)
        assert len(samples) == 7

    def test_random_sample_reproducible(self):
        space = ParameterSpace({"fast": list(range(100))})
        s1 = space.random_sample(10, seed=0)
        s2 = space.random_sample(10, seed=0)
        assert s1 == s2

    def test_random_sample_different_seeds(self):
        space = ParameterSpace({"fast": list(range(100))})
        s1 = space.random_sample(10, seed=1)
        s2 = space.random_sample(10, seed=2)
        # Almost certainly different
        assert s1 != s2


# ── GridSearchOptimizer ────────────────────────────────────────────────────────

class TestGridSearchOptimizer:
    def test_returns_optimization_result(self):
        space  = ParameterSpace({"fast": [5], "slow": [20]})
        opt    = GridSearchOptimizer(space, _HoldStrategy)
        result = opt.run(_bars())
        assert isinstance(result, OptimizationResult)

    def test_n_evaluated_matches_combos(self):
        space  = ParameterSpace({"fast": [5, 10], "slow": [20, 30]})
        opt    = GridSearchOptimizer(space, _HoldStrategy)
        result = opt.run(_bars())
        assert result.n_evaluated == 4

    def test_all_results_has_correct_rows(self):
        space  = ParameterSpace({"fast": [5, 10], "slow": [20, 30]})
        opt    = GridSearchOptimizer(space, _HoldStrategy)
        result = opt.run(_bars())
        assert len(result.all_results) == 4

    def test_objective_stored(self):
        space  = ParameterSpace({"fast": [5]})
        opt    = GridSearchOptimizer(space, _HoldStrategy, objective="calmar_ratio")
        result = opt.run(_bars())
        assert result.objective == "calmar_ratio"

    def test_best_params_is_dict(self):
        space  = ParameterSpace({"fast": [5, 10]})
        opt    = GridSearchOptimizer(space, _HoldStrategy)
        result = opt.run(_bars())
        assert isinstance(result.best_params, dict)

    def test_all_results_sorted_descending(self):
        space  = ParameterSpace({"fast": [5, 10, 20]})
        opt    = GridSearchOptimizer(space, _HoldStrategy)
        result = opt.run(_bars())
        scores = result.all_results["score"].dropna().tolist()
        assert scores == sorted(scores, reverse=True)


# ── RandomSearchOptimizer ──────────────────────────────────────────────────────

class TestRandomSearchOptimizer:
    def test_n_iter_validation(self):
        space = ParameterSpace({"fast": [5]})
        with pytest.raises(ValueError, match="n_iter"):
            RandomSearchOptimizer(space, _HoldStrategy, n_iter=0)

    def test_returns_optimization_result(self):
        space  = ParameterSpace({"fast": [5, 10, 20]})
        opt    = RandomSearchOptimizer(space, _HoldStrategy, n_iter=3, seed=42)
        result = opt.run(_bars())
        assert isinstance(result, OptimizationResult)

    def test_n_evaluated_matches_n_iter(self):
        space  = ParameterSpace({"fast": [5, 10, 20]})
        opt    = RandomSearchOptimizer(space, _HoldStrategy, n_iter=5, seed=0)
        result = opt.run(_bars())
        assert result.n_evaluated == 5

    def test_reproducible_with_seed(self):
        space = ParameterSpace({"fast": list(range(50))})
        opt1  = RandomSearchOptimizer(space, _HoldStrategy, n_iter=5, seed=7)
        opt2  = RandomSearchOptimizer(space, _HoldStrategy, n_iter=5, seed=7)
        r1 = opt1.run(_bars())
        r2 = opt2.run(_bars())
        assert r1.best_params == r2.best_params


# ── Objective validation ───────────────────────────────────────────────────────

class TestObjectiveValidation:
    def test_invalid_objective_raises_value_error(self):
        space = ParameterSpace({"fast": [5]})
        opt   = GridSearchOptimizer(space, _HoldStrategy, objective="nonexistent_metric")
        with pytest.raises(ValueError, match="nonexistent_metric"):
            opt.run(_bars())

    def test_valid_objective_does_not_raise(self):
        space = ParameterSpace({"fast": [5]})
        opt   = GridSearchOptimizer(space, _HoldStrategy, objective="calmar_ratio")
        result = opt.run(_bars())
        assert result.objective == "calmar_ratio"

    def test_invalid_objective_random_raises(self):
        space = ParameterSpace({"fast": [5]})
        opt   = RandomSearchOptimizer(space, _HoldStrategy, n_iter=1, objective="bad_field")
        with pytest.raises(ValueError, match="bad_field"):
            opt.run(_bars())
