"""Tests for data.reports — build_data_report and build_all_reports."""
from __future__ import annotations

import pandas as pd
import pytest

from data.reports import (
    DataQualityReport,
    MonthRecord,
    build_all_reports,
    build_data_report,
)
from data.store import BarStore


# ── fixtures ──────────────────────────────────────────────────────────────────

def _sample_df(n: int = 24) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100.0},
        index=idx,
    )


@pytest.fixture
def store(tmp_path) -> BarStore:
    return BarStore(tmp_path)


# ── MonthRecord ───────────────────────────────────────────────────────────────

def test_month_record_label():
    r = MonthRecord(year=2024, month=3, bar_count=720)
    assert r.label() == "2024-03"


def test_month_record_to_dict():
    r = MonthRecord(
        year=2024, month=1, bar_count=744,
        provider="BinanceProvider",
        download_time="2024-01-15T00:00:00+00:00",
        integrity_score=98.5,
        checksum="abc123",
    )
    d = r.to_dict()
    assert d["month"] == "2024-01"
    assert d["bar_count"] == 744
    assert d["provider"] == "BinanceProvider"
    assert d["integrity_score"] == 98.5


# ── build_data_report: empty cache ────────────────────────────────────────────

def test_empty_cache_returns_zero_report(store):
    report = build_data_report("BTCUSDT", "1h", store)
    assert isinstance(report, DataQualityReport)
    assert report.symbol == "BTCUSDT"
    assert report.interval == "1h"
    assert report.months_cached == 0
    assert report.total_bars == 0
    assert report.gap_months == []
    assert report.records == []
    assert report.avg_integrity_score is None


# ── build_data_report: with cached data ───────────────────────────────────────

def test_reports_correct_month_count(store):
    for month in [1, 2, 3]:
        store.write("BTCUSDT", "1h", 2024, month, _sample_df(24))
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.months_cached == 3


def test_reports_correct_total_bars(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df(10))
    store.write("BTCUSDT", "1h", 2024, 2, _sample_df(15))
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.total_bars == 25


def test_gap_detection_consecutive_months_no_gap(store):
    for month in [1, 2, 3]:
        store.write("BTCUSDT", "1h", 2024, month, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.gap_months == []


def test_gap_detection_finds_missing_month(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 3, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert (2024, 2) in report.gap_months


def test_gap_detection_across_year_boundary(store):
    store.write("BTCUSDT", "1h", 2023, 11, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 2, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert (2023, 12) in report.gap_months
    assert (2024, 1) in report.gap_months


def test_single_month_no_gaps(store):
    store.write("BTCUSDT", "1h", 2024, 6, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.gap_months == []


# ── metadata integration ──────────────────────────────────────────────────────

def test_months_with_meta_count(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 2, _sample_df())
    # Only write meta for month 1
    store.write_meta("BTCUSDT", "1h", 2024, 1, {"provider": "BinanceProvider"})
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.months_with_meta == 1


def test_avg_integrity_score_computed(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 2, _sample_df())
    store.write_meta("BTCUSDT", "1h", 2024, 1, {"integrity_score": 95.0, "provider": "BinanceProvider"})
    store.write_meta("BTCUSDT", "1h", 2024, 2, {"integrity_score": 85.0, "provider": "BinanceProvider"})
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.avg_integrity_score == pytest.approx(90.0)


def test_avg_integrity_score_none_when_no_meta(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.avg_integrity_score is None


def test_providers_used_collected(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 2, _sample_df())
    store.write_meta("BTCUSDT", "1h", 2024, 1, {"provider": "BinanceProvider"})
    store.write_meta("BTCUSDT", "1h", 2024, 2, {"provider": "YahooFinanceProvider"})
    report = build_data_report("BTCUSDT", "1h", store)
    assert "BinanceProvider" in report.providers_used
    assert "YahooFinanceProvider" in report.providers_used


def test_single_provider_not_duplicated(store):
    for m in [1, 2, 3]:
        store.write("BTCUSDT", "1h", 2024, m, _sample_df())
        store.write_meta("BTCUSDT", "1h", 2024, m, {"provider": "BinanceProvider"})
    report = build_data_report("BTCUSDT", "1h", store)
    assert report.providers_used == ["BinanceProvider"]


# ── to_dict / summary ─────────────────────────────────────────────────────────

def test_to_dict_keys(store):
    report = build_data_report("BTCUSDT", "1h", store)
    d = report.to_dict()
    for key in ("symbol", "interval", "months_cached", "total_bars",
                "gap_months", "records", "avg_integrity_score", "providers_used"):
        assert key in d


def test_summary_string_contains_symbol(store):
    report = build_data_report("BTCUSDT", "1h", store)
    assert "BTCUSDT" in report.summary()
    assert "1h" in report.summary()


def test_summary_reports_gaps(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1h", 2024, 3, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert "gap" in report.summary().lower()


def test_summary_no_gaps_stated(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    report = build_data_report("BTCUSDT", "1h", store)
    assert "no gap" in report.summary().lower()


# ── build_all_reports ─────────────────────────────────────────────────────────

def test_build_all_empty_cache(store):
    reports = build_all_reports(store)
    assert reports == []


def test_build_all_discovers_all_pairs(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    store.write("ETHUSDT", "4h", 2024, 1, _sample_df())
    store.write("BTCUSDT", "1d", 2024, 1, _sample_df())
    reports = build_all_reports(store)
    pairs = {(r.symbol, r.interval) for r in reports}
    assert ("BTCUSDT", "1h") in pairs
    assert ("ETHUSDT", "4h") in pairs
    assert ("BTCUSDT", "1d") in pairs


def test_build_all_returns_data_quality_reports(store):
    store.write("BTCUSDT", "1h", 2024, 1, _sample_df())
    reports = build_all_reports(store)
    assert all(isinstance(r, DataQualityReport) for r in reports)
