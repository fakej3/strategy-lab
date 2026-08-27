"""Golden tests for the V2 research dataset contract."""

import pandas as pd
import pytest

from data.v2_contract import DatasetSpec, validate_research_dataset


def make_data():
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [10.0, 11.0, 12.0],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )


def test_valid_dataset_passes():
    validate_research_dataset(make_data(), DatasetSpec(require_positive_volume=True))


def test_duplicate_timestamps_fail_closed():
    data = make_data()
    data.index = [data.index[0], data.index[0], data.index[2]]
    with pytest.raises(ValueError, match="duplicate"):
        validate_research_dataset(data)


def test_out_of_order_timestamps_fail_closed():
    data = make_data().iloc[[0, 2, 1]]
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_research_dataset(data)


def test_missing_hour_fails_when_contiguity_is_declared():
    data = make_data().iloc[[0, 2]].copy()
    with pytest.raises(ValueError, match="not contiguous"):
        validate_research_dataset(
            data, DatasetSpec(require_contiguous=True, expected_frequency="1h")
        )


def test_impossible_ohlc_fails():
    data = make_data()
    data.loc[data.index[1], "high"] = 90
    with pytest.raises(ValueError, match="impossible OHLC"):
        validate_research_dataset(data)


def test_non_positive_price_fails():
    data = make_data()
    data.loc[data.index[1], "close"] = 0
    with pytest.raises(ValueError, match="non-positive"):
        validate_research_dataset(data)


def test_negative_volume_fails():
    data = make_data()
    data.loc[data.index[1], "volume"] = -1
    with pytest.raises(ValueError, match="volume"):
        validate_research_dataset(data)


def test_positive_volume_requirement_fails_when_volume_missing():
    data = make_data().drop(columns="volume")
    with pytest.raises(ValueError, match="volume"):
        validate_research_dataset(data, DatasetSpec(require_positive_volume=True))
