"""Regression tests for Monte Carlo input validation."""
from __future__ import annotations

import pytest

from jobs.montecarlo_job import MonteCarloJob, MonteCarloParams


def test_zero_simulations_is_rejected() -> None:
    with pytest.raises(ValueError, match="n_simulations"):
        MonteCarloJob(MonteCarloParams([1.0, -1.0], n_simulations=0)).run()


def test_non_positive_starting_capital_is_rejected() -> None:
    with pytest.raises(ValueError, match="starting_capital"):
        MonteCarloJob(MonteCarloParams([1.0, -1.0], starting_capital=0)).run()


def test_non_finite_trade_pnl_is_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        MonteCarloJob(MonteCarloParams([1.0, float("nan")])).run()


def test_short_trade_sequence_returns_explicit_empty_distribution() -> None:
    result = MonteCarloJob(
        MonteCarloParams([10.0], n_simulations=10)
    ).run()
    assert result.success
    assert result.data["n_trades"] == 1
    assert result.data["all_returns"] == []
