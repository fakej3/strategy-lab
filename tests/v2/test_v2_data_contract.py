import pandas as pd
import pytest
from data.v2_contract import DatasetSpec, normalize_research_dataset, validate_research_dataset

def valid():
    return pd.DataFrame({"open":[100,101],"high":[102,103],"low":[99,100],"close":[101,102],"volume":[10,12]}, index=pd.date_range("2026-01-01", periods=2, freq="h", tz="Asia/Kolkata"))

def test_valid_data_normalizes_to_utc_without_mutating_input():
    df = valid(); original = df.index.copy(); out = normalize_research_dataset(df)
    assert str(out.index.tz) == "UTC"
    assert df.index.equals(original)
    assert out["close"].dtype.kind == "f"

def test_bad_ohlc_is_rejected():
    df = valid(); df.loc[df.index[0], "high"] = 98
    with pytest.raises(ValueError): validate_research_dataset(df)

def test_naive_timestamps_are_rejected_by_default():
    df = valid(); df.index = df.index.tz_localize(None)
    with pytest.raises(ValueError): validate_research_dataset(df)

def test_duplicate_and_unsorted_timestamps_are_rejected():
    df = valid(); df.index = [df.index[1], df.index[0]]
    with pytest.raises(ValueError): validate_research_dataset(df)
    df = valid(); df.index = [df.index[0], df.index[0]]
    with pytest.raises(ValueError): validate_research_dataset(df)

def test_contiguity_is_explicit():
    df = valid(); df.index = [df.index[0], df.index[0] + pd.Timedelta(hours=2)]
    with pytest.raises(ValueError): validate_research_dataset(df, DatasetSpec(require_contiguous=True, expected_frequency="1h"))
