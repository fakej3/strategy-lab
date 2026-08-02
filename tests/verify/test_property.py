"""Randomised property-based tests.

Runs 1000+ random deterministic scenarios (fixed seed = 42) and asserts that
ALL financial invariants hold for every one of them.

A single failure here indicates a systematic accounting bug, not a
coincidental edge case.  All scenarios are reproducible: run with the same
seed to get the same sequence.
"""
from __future__ import annotations

import pytest

from verify._property import run_property_tests


def test_property_all_invariants_1000_scenarios() -> None:
    """1000 random scenarios must all satisfy every financial invariant."""
    failures = run_property_tests(n=1000, seed=42)
    if failures:
        msgs = "\n".join(str(f) for f in failures[:10])
        extra = len(failures) - 10
        suffix = f"\n... and {extra} more failure(s)" if extra > 0 else ""
        pytest.fail(
            f"{len(failures)} / 1000 scenario(s) violated invariants:\n{msgs}{suffix}"
        )


def test_property_different_seed_200_scenarios() -> None:
    """Additional seed to catch non-deterministic failures."""
    failures = run_property_tests(n=200, seed=7)
    if failures:
        msgs = "\n".join(str(f) for f in failures[:5])
        pytest.fail(
            f"{len(failures)} / 200 scenario(s) violated invariants:\n{msgs}"
        )


def test_property_edge_seeds() -> None:
    """Small run with edge seeds to probe boundary conditions."""
    for seed in [0, 1, 13, 99, 999]:
        failures = run_property_tests(n=100, seed=seed)
        assert not failures, (
            f"seed={seed}: {len(failures)} failure(s): {failures[0]}"
        )
