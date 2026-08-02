"""Tests for data.store — Parquet persistence layer."""
from __future__ import annotations

import pandas as pd
import pytest

from data.store import BarStore


# ── fixture helpers ───────────────────────────────────────────────────────────

def _sample_df(n: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {
            "open":   [1.0 * i for i in range(1, n + 1)],
            "high":   [1.1 * i for i in range(1, n + 1)],
            "low":    [0.9 * i for i in range(1, n + 1)],
            "close":  [1.05 * i for i in range(1, n + 1)],
            "volume": [100.0 * i for i in range(1, n + 1)],
        },
        index=idx,
    )


@pytest.fixture
def store(tmp_path) -> BarStore:
    return BarStore(tmp_path)


# ── existence checks ──────────────────────────────────────────────────────────

class TestExists:
    def test_false_before_write(self, store):
        assert store.exists("BTCUSDT", "1h", 2024, 1) is False

    def test_true_after_write(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.exists("BTCUSDT", "1h", 2024, 1) is True

    def test_scoped_by_symbol(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.exists("ETHUSDT", "1h", 2024, 1) is False

    def test_scoped_by_interval(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.exists("BTCUSDT", "4h", 2024, 1) is False

    def test_scoped_by_month(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.exists("BTCUSDT", "1h", 2024, 2) is False


# ── round-trip ────────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_values_preserved(self, store):
        original = _sample_df()
        store.write("BTCUSDT", "1h", 2024, 1, original)
        result = store.read("BTCUSDT", "1h", 2024, 1)
        pd.testing.assert_frame_equal(result, original, check_freq=False)

    def test_index_name_preserved(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        result = store.read("BTCUSDT", "1h", 2024, 1)
        assert result.index.name == "open_time"

    def test_utc_timezone_preserved(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        result = store.read("BTCUSDT", "1h", 2024, 1)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_float_dtypes_preserved(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        result = store.read("BTCUSDT", "1h", 2024, 1)
        for col in ["open", "high", "low", "close", "volume"]:
            assert result[col].dtype == float

    def test_write_overwrites_previous(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df(3))
        new_df = _sample_df(5)
        store.write("BTCUSDT", "1h", 2024, 1, new_df)
        result = store.read("BTCUSDT", "1h", 2024, 1)
        assert len(result) == 5


# ── file layout ───────────────────────────────────────────────────────────────

class TestPathLayout:
    def test_correct_directory_structure(self, store, tmp_path):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        expected = tmp_path / "BTCUSDT" / "1h" / "2024-01.parquet"
        assert expected.exists()

    def test_creates_nested_directories(self, store, tmp_path):
        store.write("ETHUSDT", "4h", 2023, 12, _sample_df())
        expected = tmp_path / "ETHUSDT" / "4h" / "2023-12.parquet"
        assert expected.exists()

    def test_zero_padded_month(self, store, tmp_path):
        store.write("BTCUSDT", "1h", 2024, 3, _sample_df())
        expected = tmp_path / "BTCUSDT" / "1h" / "2024-03.parquet"
        assert expected.exists()
