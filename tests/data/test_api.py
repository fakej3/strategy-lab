"""Integration tests for data.api.get_bars — mocked provider, real filesystem."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from data.api import get_bars
from data.store import BarStore


# ── fixture helpers ───────────────────────────────────────────────────────────

def _provider_df(year: int, month: int, n_rows: int = 24) -> pd.DataFrame:
    """Simulate what a provider returns for one month: n hourly bars from month start."""
    start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    idx = pd.date_range(start, periods=n_rows, freq="1h", name="open_time")
    return pd.DataFrame(
        {
            "open":   [float(year * 1000 + month)] * n_rows,
            "high":   [float(year * 1000 + month + 1)] * n_rows,
            "low":    [float(year * 1000 + month - 1)] * n_rows,
            "close":  [float(year * 1000 + month)] * n_rows,
            "volume": [100.0] * n_rows,
        },
        index=idx,
    )


@pytest.fixture
def tmp_store(tmp_path) -> BarStore:
    return BarStore(tmp_path)


@pytest.fixture
def mock_provider() -> MagicMock:
    p = MagicMock()
    # 720 rows = 30 days × 24 hours; covers the full month for slicing tests
    p.fetch_month.side_effect = lambda s, i, y, m: _provider_df(y, m, n_rows=720)
    return p


# ── output shape ──────────────────────────────────────────────────────────────

class TestOutputShape:
    def test_correct_columns(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=mock_provider, store=tmp_store)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_index_is_utc_datetimeindex(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=mock_provider, store=tmp_store)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"

    def test_index_name_is_open_time(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=mock_provider, store=tmp_store)
        assert df.index.name == "open_time"

    def test_no_nans(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=mock_provider, store=tmp_store)
        assert not df.isnull().any().any()


# ── date range slicing ────────────────────────────────────────────────────────

class TestDateRangeSlicing:
    def test_bars_within_from_date(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 5), date(2024, 1, 31),
                      provider=mock_provider, store=tmp_store)
        assert df.index.min() >= pd.Timestamp("2024-01-05", tz="UTC")

    def test_bars_within_to_date(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 2),
                      provider=mock_provider, store=tmp_store)
        assert df.index.max() < pd.Timestamp("2024-01-03", tz="UTC")

    def test_single_day_range(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 1),
                      provider=mock_provider, store=tmp_store)
        # Only bars whose open_time falls on Jan 1
        assert len(df) == 24

    def test_multi_month_concatenated(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 2, 29),
                      provider=mock_provider, store=tmp_store)
        # Both months fetched and present in the result
        assert mock_provider.fetch_month.call_count == 2
        assert df.index.min() < pd.Timestamp("2024-02-01", tz="UTC")   # Jan data present
        assert df.index.max() >= pd.Timestamp("2024-02-01", tz="UTC")  # Feb data present

    def test_multi_month_sorted_by_time(self, mock_provider, tmp_store):
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 3, 31),
                      provider=mock_provider, store=tmp_store)
        assert df.index.is_monotonic_increasing


# ── cache behaviour ───────────────────────────────────────────────────────────

class TestCacheBehaviour:
    def test_past_month_fetched_only_once(self, mock_provider, tmp_store):
        kwargs = dict(provider=mock_provider, store=tmp_store)
        get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), **kwargs)
        get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), **kwargs)

        assert mock_provider.fetch_month.call_count == 1

    def test_second_call_returns_same_data(self, mock_provider, tmp_store):
        kwargs = dict(provider=mock_provider, store=tmp_store)
        df1 = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 1), **kwargs)
        df2 = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 1), **kwargs)
        # check_freq=False: Parquet round-trips drop the inferred freq from the index
        pd.testing.assert_frame_equal(df1, df2, check_freq=False)

    def test_current_month_always_refetched(self, mock_provider, tmp_store):
        from datetime import datetime
        today = datetime.utcnow().date()
        kwargs = dict(provider=mock_provider, store=tmp_store)
        get_bars("BTCUSDT", "1h", date(today.year, today.month, 1), today, **kwargs)
        get_bars("BTCUSDT", "1h", date(today.year, today.month, 1), today, **kwargs)

        assert mock_provider.fetch_month.call_count == 2

    def test_force_refresh_bypasses_cache(self, mock_provider, tmp_store):
        kwargs = dict(provider=mock_provider, store=tmp_store)
        get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), **kwargs)
        get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
                 force_refresh=True, **kwargs)

        assert mock_provider.fetch_month.call_count == 2

    def test_different_symbols_cached_independently(self, mock_provider, tmp_store):
        kwargs = dict(provider=mock_provider, store=tmp_store)
        get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), **kwargs)
        get_bars("ETHUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31), **kwargs)

        calls = [c[0] for c in mock_provider.fetch_month.call_args_list]
        symbols = [c[0] for c in calls]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols


# ── error handling ────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_raises_on_inverted_date_range(self, mock_provider, tmp_store):
        with pytest.raises(ValueError, match="from_date"):
            get_bars("BTCUSDT", "1h",
                     date(2024, 3, 1), date(2024, 1, 1),
                     provider=mock_provider, store=tmp_store)

    def test_empty_provider_returns_empty_df(self, tmp_store):
        empty_provider = MagicMock()
        empty_provider.fetch_month.return_value = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=empty_provider, store=tmp_store)
        assert df.empty

    def test_empty_df_has_correct_columns(self, tmp_store):
        empty_provider = MagicMock()
        empty_provider.fetch_month.return_value = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )
        df = get_bars("BTCUSDT", "1h",
                      date(2024, 1, 1), date(2024, 1, 31),
                      provider=empty_provider, store=tmp_store)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
