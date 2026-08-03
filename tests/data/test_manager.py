"""Tests for data.manager — ProviderManager fallback chain."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from data.manager import ProviderError, ProviderManager
from data.provider import MarketDataProvider


# ── fixtures ──────────────────────────────────────────────────────────────────

def _sample_df(n: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100.0},
        index=idx,
    )


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


class _SuccessProvider(MarketDataProvider):
    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.calls = 0

    def fetch_month(self, symbol, interval, year, month) -> pd.DataFrame:
        self.calls += 1
        return self._df


class _FailingProvider(MarketDataProvider):
    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("network error")
        self.calls = 0

    def fetch_month(self, symbol, interval, year, month) -> pd.DataFrame:
        self.calls += 1
        raise self._exc


class _EmptyProvider(MarketDataProvider):
    def __init__(self):
        self.calls = 0

    def fetch_month(self, symbol, interval, year, month) -> pd.DataFrame:
        self.calls += 1
        return _empty_df()


# ── construction ──────────────────────────────────────────────────────────────

def test_requires_at_least_one_provider():
    with pytest.raises(ValueError, match="at least one"):
        ProviderManager([])


def test_providers_property_returns_copy():
    p = _SuccessProvider(_sample_df())
    mgr = ProviderManager([p])
    lst = mgr.providers
    lst.clear()
    assert len(mgr.providers) == 1  # original unchanged


def test_provider_names():
    mgr = ProviderManager([_SuccessProvider(_sample_df()), _EmptyProvider()])
    names = mgr.provider_names()
    assert names == ["_SuccessProvider", "_EmptyProvider"]


# ── happy path ────────────────────────────────────────────────────────────────

def test_returns_data_from_first_provider():
    df = _sample_df(5)
    mgr = ProviderManager([_SuccessProvider(df), _FailingProvider()])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert len(result) == 5


def test_first_provider_not_called_unnecessarily():
    p1 = _SuccessProvider(_sample_df())
    p2 = _SuccessProvider(_sample_df(10))
    mgr = ProviderManager([p1, p2])
    mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert p1.calls == 1
    assert p2.calls == 0  # never reached


# ── fallback behaviour ────────────────────────────────────────────────────────

def test_falls_back_on_exception():
    df = _sample_df(3)
    p1 = _FailingProvider()
    p2 = _SuccessProvider(df)
    mgr = ProviderManager([p1, p2])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert len(result) == 3
    assert p1.calls == 1
    assert p2.calls == 1


def test_falls_back_on_empty_data():
    df = _sample_df(3)
    p1 = _EmptyProvider()
    p2 = _SuccessProvider(df)
    mgr = ProviderManager([p1, p2])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert len(result) == 3
    assert p1.calls == 1
    assert p2.calls == 1


def test_falls_back_through_multiple_failures():
    df = _sample_df(7)
    p1 = _FailingProvider()
    p2 = _FailingProvider()
    p3 = _SuccessProvider(df)
    mgr = ProviderManager([p1, p2, p3])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert len(result) == 7
    assert p1.calls == 1
    assert p2.calls == 1
    assert p3.calls == 1


# ── all-fail scenarios ────────────────────────────────────────────────────────

def test_all_exceptions_raises_provider_error():
    mgr = ProviderManager([_FailingProvider(), _FailingProvider()])
    with pytest.raises(ProviderError):
        mgr.fetch_month("BTCUSDT", "1h", 2024, 1)


def test_provider_error_message_names_each_provider():
    mgr = ProviderManager([
        _FailingProvider(RuntimeError("timeout")),
        _FailingProvider(RuntimeError("403 forbidden")),
    ])
    with pytest.raises(ProviderError, match="_FailingProvider"):
        mgr.fetch_month("BTCUSDT", "1h", 2024, 1)


def test_all_empty_returns_empty_not_error():
    mgr = ProviderManager([_EmptyProvider(), _EmptyProvider()])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert result.empty


def test_mix_of_exception_and_empty_returns_empty():
    """One fails with exception, one returns empty — result is empty (not error)."""
    mgr = ProviderManager([_FailingProvider(), _EmptyProvider()])
    result = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    assert result.empty


# ── implements MarketDataProvider ─────────────────────────────────────────────

def test_manager_is_a_provider():
    mgr = ProviderManager([_SuccessProvider(_sample_df())])
    assert isinstance(mgr, MarketDataProvider)


# ── rate limiting ─────────────────────────────────────────────────────────────

def test_rate_limit_delays_consecutive_calls():
    p = _SuccessProvider(_sample_df())
    rate = 0.05  # 50 ms
    mgr = ProviderManager([p], rate_limit_secs=rate)

    start = time.monotonic()
    mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    mgr.fetch_month("BTCUSDT", "1h", 2024, 2)
    elapsed = time.monotonic() - start

    assert elapsed >= rate * 0.8  # allow small timer jitter


def test_no_rate_limit_is_fast():
    p = _SuccessProvider(_sample_df())
    mgr = ProviderManager([p], rate_limit_secs=0.0)

    start = time.monotonic()
    for _ in range(5):
        mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # should be very fast without rate limiting


def test_rate_limit_is_per_provider():
    """Each provider has its own throttle clock — different providers don't block."""
    p1 = _FailingProvider()
    p2 = _SuccessProvider(_sample_df())
    rate = 0.1
    mgr = ProviderManager([p1, p2], rate_limit_secs=rate)

    start = time.monotonic()
    mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
    elapsed = time.monotonic() - start

    # p1 throttled, then p2 throttled separately — one call each should not double
    assert elapsed < rate * 2.5


# ── thread safety ─────────────────────────────────────────────────────────────

def test_concurrent_calls_are_safe():
    results = []
    errors  = []
    mgr = ProviderManager([_SuccessProvider(_sample_df())])

    def _call():
        try:
            df = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)
            results.append(len(df))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert all(r == 3 for r in results)
