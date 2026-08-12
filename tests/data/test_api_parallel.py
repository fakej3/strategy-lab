"""Tests for Phase 6 parallel downloads and progress callbacks."""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data.api import get_bars
from data.store import BarStore


def _make_bars(n: int = 24, start_ts: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start_ts, periods=n, freq="h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {"open": 40000.0, "high": 40100.0, "low": 39900.0,
         "close": 40050.0, "volume": 10.0},
        index=idx,
    )


def _make_provider(monthly_df: pd.DataFrame) -> MagicMock:
    provider = MagicMock()
    provider.fetch_month.return_value = monthly_df
    return provider


class TestParallelDownloads:
    """Parallel n_workers downloads same result as sequential n_workers=1."""

    def test_parallel_result_matches_sequential(self, tmp_path):
        df = _make_bars(24 * 31, "2024-01-01")   # full January

        provider = _make_provider(df)
        store    = BarStore(tmp_path)

        seq = get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
            provider=provider, store=BarStore(tmp_path / "seq"), n_workers=1,
        )
        par = get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
            provider=provider, store=BarStore(tmp_path / "par"), n_workers=4,
        )
        assert len(seq) == len(par)
        pd.testing.assert_frame_equal(seq, par)

    def test_multi_month_parallel_fetches_all(self, tmp_path):
        provider = MagicMock()
        provider.fetch_month.side_effect = lambda s, i, y, m: _make_bars(
            24, f"{y}-{m:02d}-01"
        )

        result = get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31),
            provider=provider,
            store=BarStore(tmp_path),
            n_workers=4,
        )
        assert not result.empty
        assert provider.fetch_month.call_count == 3   # Jan, Feb, Mar

    def test_progress_callback_called_once_per_month(self, tmp_path):
        provider = MagicMock()
        provider.fetch_month.side_effect = lambda s, i, y, m: _make_bars(24)

        calls = []

        def on_progress(label, done, total):
            calls.append((label, done, total))

        get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31),
            provider=provider,
            store=BarStore(tmp_path),
            n_workers=1,
            on_progress=on_progress,
        )

        assert len(calls) == 3
        # totals should all be 3
        assert all(total == 3 for _, _, total in calls)
        # done should be 1, 2, 3
        assert [done for _, done, _ in calls] == [1, 2, 3]

    def test_partial_fetch_failure_continues(self, tmp_path):
        """A failing month should not prevent other months from returning.

        get_bars() intentionally emits a RuntimeWarning (not an exception)
        when some months fail to fetch, so other months can still be returned.
        This test explicitly asserts that warning is emitted with the correct
        content, rather than letting it appear as an uncontrolled noisy warning.
        """
        call_count = 0

        def failing_provider(s, i, y, m):
            nonlocal call_count
            call_count += 1
            if m == 2:
                raise RuntimeError("simulated network error")
            return _make_bars(24, f"{y}-{m:02d}-01")

        provider = MagicMock()
        provider.fetch_month.side_effect = failing_provider

        with pytest.warns(RuntimeWarning, match="simulated network error"):
            result = get_bars(
                "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31),
                provider=provider,
                store=BarStore(tmp_path),
                n_workers=4,
            )
        # Jan and Mar should still be returned
        assert not result.empty
        assert call_count == 3

    def test_no_duplicate_rows_at_month_boundaries(self, tmp_path):
        """Concatenating adjacent months should not produce duplicates."""
        provider = MagicMock()
        provider.fetch_month.side_effect = lambda s, i, y, m: _make_bars(
            24 * 31, f"{y}-{m:02d}-01"
        )

        result = get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 2, 29),
            provider=provider,
            store=BarStore(tmp_path),
        )
        assert not result.index.duplicated().any()


class TestCacheWithParallel:
    """Parallel downloads respect the cache correctly."""

    def test_cached_months_not_refetched(self, tmp_path):
        """When all months are cached, provider.fetch_month is never called."""
        df = _make_bars(24, "2024-01-01")
        store = BarStore(tmp_path)
        store.write("BTCUSDT", "1h", 2024, 1, df)

        provider = MagicMock()

        get_bars(
            "BTCUSDT", "1h", date(2024, 1, 1), date(2024, 1, 31),
            provider=provider,
            store=store,
            n_workers=4,
        )
        provider.fetch_month.assert_not_called()
