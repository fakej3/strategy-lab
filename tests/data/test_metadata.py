"""Tests for BarStore metadata sidecar — write_meta, read_meta, list_months, etc."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data.store import BarStore


# ── fixtures ──────────────────────────────────────────────────────────────────

def _sample_df(n: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100.0},
        index=idx,
    )


@pytest.fixture
def store(tmp_path) -> BarStore:
    return BarStore(tmp_path)


# ── write_meta / read_meta round-trip ─────────────────────────────────────────

class TestMetaRoundTrip:
    def test_write_and_read_back(self, store):
        meta = {"provider": "BinanceProvider", "bar_count": 720}
        store.write_meta("BTCUSDT", "1h", 2024, 1, meta)
        result = store.read_meta("BTCUSDT", "1h", 2024, 1)
        assert result == meta

    def test_read_meta_returns_none_if_missing(self, store):
        result = store.read_meta("BTCUSDT", "1h", 2024, 1)
        assert result is None

    def test_all_meta_fields_preserved(self, store):
        meta = {
            "provider"       : "BinanceProvider",
            "download_time"  : "2024-01-15T10:00:00+00:00",
            "bar_count"      : 744,
            "first_bar"      : "2024-01-01T00:00:00+00:00",
            "last_bar"       : "2024-01-31T23:00:00+00:00",
            "integrity_score": 98.5,
            "checksum"       : "abc123def456",
        }
        store.write_meta("BTCUSDT", "1h", 2024, 1, meta)
        result = store.read_meta("BTCUSDT", "1h", 2024, 1)
        assert result == meta

    def test_meta_creates_directories(self, store, tmp_path):
        store.write_meta("ETHUSDT", "4h", 2024, 3, {"x": 1})
        expected = tmp_path / "ETHUSDT" / "4h" / "2024-03.meta.json"
        assert expected.exists()

    def test_meta_is_valid_json_on_disk(self, store, tmp_path):
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"a": 1})
        path = tmp_path / "BTCUSDT" / "1h" / "2024-01.meta.json"
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == {"a": 1}

    def test_overwrite_replaces_previous(self, store):
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"v": 1})
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"v": 2})
        assert store.read_meta("BTCUSDT", "1h", 2024, 1) == {"v": 2}

    def test_meta_scoped_by_symbol(self, store):
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"x": "btc"})
        assert store.read_meta("ETHUSDT", "1h", 2024, 1) is None

    def test_meta_scoped_by_month(self, store):
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"x": "jan"})
        assert store.read_meta("BTCUSDT", "1h", 2024, 2) is None


# ── list_months ───────────────────────────────────────────────────────────────

class TestListMonths:
    def test_empty_when_nothing_cached(self, store):
        assert store.list_months("BTCUSDT", "1h") == []

    def test_returns_cached_months(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        store.write("BTCUSDT", "1h", 2024, 3, _sample_df())
        months = store.list_months("BTCUSDT", "1h")
        assert months == [(2024, 1), (2024, 3)]

    def test_sorted_chronologically(self, store):
        for month in [6, 2, 4]:
            store.write("BTCUSDT", "1h", 2024, month, _sample_df())
        months = store.list_months("BTCUSDT", "1h")
        assert months == [(2024, 2), (2024, 4), (2024, 6)]

    def test_scoped_by_symbol(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.list_months("ETHUSDT", "1h") == []

    def test_scoped_by_interval(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        assert store.list_months("BTCUSDT", "4h") == []

    def test_ignores_non_parquet_files(self, store, tmp_path):
        base = tmp_path / "BTCUSDT" / "1h"
        base.mkdir(parents=True)
        (base / "notes.txt").write_text("ignored")
        (base / "2024-01.parquet").write_bytes(b"")  # may not be valid but extension matches
        months = store.list_months("BTCUSDT", "1h")
        assert (2024, 1) in months


# ── list_symbols / list_intervals ─────────────────────────────────────────────

class TestListDiscovery:
    def test_list_symbols_empty(self, store):
        assert store.list_symbols() == []

    def test_list_symbols_after_write(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        store.write("ETHUSDT", "1h", 2024, 1, _sample_df())
        symbols = store.list_symbols()
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols

    def test_list_intervals_empty(self, store):
        assert store.list_intervals("BTCUSDT") == []

    def test_list_intervals_after_write(self, store):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        store.write("BTCUSDT", "4h", 2024, 1, _sample_df())
        intervals = store.list_intervals("BTCUSDT")
        assert "1h" in intervals
        assert "4h" in intervals


# ── file layout ───────────────────────────────────────────────────────────────

class TestMetaPathLayout:
    def test_meta_alongside_parquet(self, store, tmp_path):
        store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
        store.write_meta("BTCUSDT", "1h", 2024, 1, {"k": "v"})
        parquet = tmp_path / "BTCUSDT" / "1h" / "2024-01.parquet"
        meta    = tmp_path / "BTCUSDT" / "1h" / "2024-01.meta.json"
        assert parquet.exists()
        assert meta.exists()

    def test_zero_padded_month_in_filename(self, store, tmp_path):
        store.write_meta("BTCUSDT", "1h", 2024, 3, {"k": "v"})
        assert (tmp_path / "BTCUSDT" / "1h" / "2024-03.meta.json").exists()
