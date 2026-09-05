"""Adversarial V2 tests: intentionally try to make the backtester lie.

These tests are contract-level tripwires. They should fail loudly rather than
silently accepting economically impossible or non-causal research inputs.
"""

import pandas as pd
import pytest

from data.v2_contract import DatasetSpec, validate_research_dataset
from engine.strategy import CausalStrategyBase, Signal


class FuturePriceProbe(CausalStrategyBase):
    def __init__(self):
        self.seen_lengths = []
        self.max_seen_index = []

    def generate_signal(self, bars):
        self.seen_lengths.append(len(bars))
        self.max_seen_index.append(bars.index[-1])
        return Signal.HOLD


def make_bars(n=5):
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": range(100, 100 + n),
            "high": range(101, 101 + n),
            "low": range(99, 99 + n),
            "close": range(100, 100 + n),
            "volume": [10.0] * n,
        },
        index=idx,
    )


def test_causal_strategy_never_receives_future_rows():
    bars = make_bars()
    strategy = FuturePriceProbe()
    # Contract test at the strategy boundary: every supplied view must end at
    # the current bar, never after it.
    for i in range(len(bars)):
        view = bars.iloc[: i + 1]
        strategy.generate_signal(view)
        assert strategy.seen_lengths[-1] == i + 1
        assert strategy.max_seen_index[-1] == bars.index[i]


def test_nan_and_infinity_fail_closed():
    for value in [float("nan"), float("inf"), float("-inf")]:
        data = make_bars()
        data.iloc[2, data.columns.get_loc("close")] = value
        with pytest.raises(ValueError, match="non-finite"):
            validate_research_dataset(data)


def test_duplicate_rows_fail_closed():
    data = make_bars()
    data = pd.concat([data.iloc[:2], data.iloc[1:2], data.iloc[2:]])
    with pytest.raises(ValueError, match="duplicate"):
        validate_research_dataset(data)


def test_declared_hourly_series_cannot_hide_a_gap():
    data = make_bars().drop(make_bars().index[2])
    with pytest.raises(ValueError, match="not contiguous"):
        validate_research_dataset(
            data,
            DatasetSpec(require_contiguous=True, expected_frequency="1h"),
        )


def test_ohlc_relationships_fail_closed():
    data = make_bars()
    data.loc[data.index[2], "low"] = 200
    with pytest.raises(ValueError, match="impossible OHLC"):
        validate_research_dataset(data)
