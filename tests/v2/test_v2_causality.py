"""Adversarial tests for indicator/feature look-ahead leakage."""

import pandas as pd
import pytest

from research.v2_causality import assert_prefix_causal, trailing_mean, trailing_return


def bars(n=12):
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"close": range(100, 100 + n)}, index=idx)


def test_standard_trailing_features_are_prefix_causal():
    data = bars()
    assert_prefix_causal(lambda x: trailing_mean(x["close"], 3), data)
    assert_prefix_causal(lambda x: trailing_return(x["close"], 1), data)


def test_future_dependent_feature_is_rejected():
    data = bars()

    def bad_feature(frame):
        # Deliberately illegal: the value at t depends on the final observation.
        return frame["close"] / frame["close"].iloc[-1]

    with pytest.raises(AssertionError, match="non-causal"):
        assert_prefix_causal(bad_feature, data, prefix_lengths=(5, 8))


def test_index_requirements_fail_closed():
    data = bars().iloc[::-1]
    with pytest.raises(ValueError, match="unique increasing"):
        assert_prefix_causal(lambda x: x["close"], data)
