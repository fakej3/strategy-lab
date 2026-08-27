"""Boundary and leakage tests for the V2 walk-forward protocol."""

import pandas as pd
import pytest

from research.v2_walk_forward import (
    V2WalkForwardConfig,
    WFOCapitalPolicy,
    build_plan,
    execute_oos_plan,
)


def bars(n=20):
    return pd.DataFrame({"close": range(1, n + 1)}, index=pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"))


def test_plan_has_no_train_test_overlap():
    plan = build_plan(20, V2WalkForwardConfig(train_bars=5, test_bars=3, step_bars=3))
    for fold in plan.folds:
        assert fold.train_end_exclusive == fold.test_start
        assert fold.train_start < fold.train_end_exclusive
        assert fold.test_start < fold.test_end_exclusive


def test_fit_never_receives_oos_rows():
    data = bars()
    plan = build_plan(len(data), V2WalkForwardConfig(train_bars=5, test_bars=3))
    seen = []

    def fit(train):
        seen.append(train.index[-1])
        return object()

    def evaluate(test, model, capital):
        return pd.Series([capital], index=[test.index[0]]), capital

    execute_oos_plan(data, plan, fit, evaluate, 1000)
    for fold, seen_last in zip(plan.folds, seen):
        assert seen_last == data.index[fold.train_end_exclusive - 1]
        assert seen_last < data.index[fold.test_start]


def test_carry_policy_compounds_between_folds():
    data = bars(11)
    plan = build_plan(11, V2WalkForwardConfig(train_bars=3, test_bars=2, capital_policy=WFOCapitalPolicy.CARRY))
    capitals = []

    def fit(train):
        return object()

    def evaluate(test, model, capital):
        capitals.append(capital)
        return pd.Series([capital, capital * 1.1], index=test.index), capital * 1.1

    execute_oos_plan(data, plan, fit, evaluate, 1000)
    assert capitals[0] == pytest.approx(1000)
    assert capitals[1] == pytest.approx(1100)


def test_reset_policy_does_not_compound():
    data = bars(11)
    plan = build_plan(11, V2WalkForwardConfig(train_bars=3, test_bars=2, capital_policy=WFOCapitalPolicy.RESET))
    capitals = []

    def fit(train):
        return object()

    def evaluate(test, model, capital):
        capitals.append(capital)
        return pd.Series([capital], index=[test.index[0]]), capital * 1.1

    execute_oos_plan(data, plan, fit, evaluate, 1000)
    assert capitals == [1000, 1000, 1000]
