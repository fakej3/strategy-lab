"""Market data quality reports — scan the cache and summarise what's there.

Public API
----------
- ``MonthRecord``       — metadata for one cached month.
- ``DataQualityReport`` — aggregated report for one symbol/interval pair.
- ``build_data_report`` — scan cache, return :class:`DataQualityReport`.
- ``build_all_reports`` — scan every symbol/interval in the cache directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .store import BarStore


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MonthRecord:
    """Metadata for one cached month."""
    year            : int
    month           : int
    bar_count       : int
    provider        : str | None = None
    download_time   : str | None = None
    integrity_score : float | None = None
    checksum        : str | None = None

    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def to_dict(self) -> dict:
        return {
            "month"          : self.label(),
            "bar_count"      : self.bar_count,
            "provider"       : self.provider,
            "download_time"  : self.download_time,
            "integrity_score": self.integrity_score,
            "checksum"       : self.checksum,
        }


@dataclass
class DataQualityReport:
    """Aggregated cache quality report for one symbol/interval.

    Attributes
    ----------
    symbol, interval : Identifying the dataset.
    months_cached    : Number of months with a Parquet file on disk.
    months_with_meta : Number of those months that also have a metadata sidecar.
    gap_months       : Calendar months that fall between first and last cached
                       month but have no Parquet file.
    records          : Per-month detail.
    total_bars       : Sum of bar counts across all cached months.
    avg_integrity_score : Mean of available integrity scores, or None.
    providers_used   : Distinct provider names that served data.
    """
    symbol              : str
    interval            : str
    months_cached       : int
    months_with_meta    : int
    gap_months          : list[tuple[int, int]]
    records             : list[MonthRecord]
    total_bars          : int
    avg_integrity_score : float | None
    providers_used      : list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol"              : self.symbol,
            "interval"            : self.interval,
            "months_cached"       : self.months_cached,
            "months_with_meta"    : self.months_with_meta,
            "gap_months"          : [f"{y}-{m:02d}" for y, m in self.gap_months],
            "total_bars"          : self.total_bars,
            "avg_integrity_score" : self.avg_integrity_score,
            "providers_used"      : self.providers_used,
            "records"             : [r.to_dict() for r in self.records],
        }

    def summary(self) -> str:
        gaps = f"{len(self.gap_months)} gap(s)" if self.gap_months else "no gaps"
        score = (
            f"{self.avg_integrity_score:.0f}/100"
            if self.avg_integrity_score is not None else "n/a"
        )
        providers = ", ".join(self.providers_used) if self.providers_used else "unknown"
        return (
            f"{self.symbol}/{self.interval}: "
            f"{self.months_cached} months, {self.total_bars} bars, "
            f"{gaps}, avg integrity {score}, "
            f"providers: {providers}"
        )


# ── Main functions ─────────────────────────────────────────────────────────────

def build_data_report(
    symbol: str,
    interval: str,
    store: BarStore,
) -> DataQualityReport:
    """Scan the cache and build a :class:`DataQualityReport` for one pair.

    Args:
        symbol:   Trading pair, e.g. ``"BTCUSDT"``.
        interval: Bar interval, e.g. ``"1h"``.
        store:    :class:`~data.store.BarStore` instance to inspect.

    Returns:
        :class:`DataQualityReport` — even if no data is cached (zero months).
    """
    months = store.list_months(symbol, interval)
    records: list[MonthRecord] = []
    total_bars = 0

    for year, month in months:
        try:
            df = store.read(symbol, interval, year, month)
            bar_count = len(df)
        except Exception:
            bar_count = 0

        meta = store.read_meta(symbol, interval, year, month) or {}
        total_bars += bar_count
        records.append(MonthRecord(
            year            = year,
            month           = month,
            bar_count       = bar_count,
            provider        = meta.get("provider"),
            download_time   = meta.get("download_time"),
            integrity_score = meta.get("integrity_score"),
            checksum        = meta.get("checksum"),
        ))

    gap_months = _find_gaps(months)

    scores = [r.integrity_score for r in records if r.integrity_score is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    providers_used = sorted({
        r.provider for r in records if r.provider is not None
    })

    return DataQualityReport(
        symbol              = symbol,
        interval            = interval,
        months_cached       = len(months),
        months_with_meta    = sum(1 for r in records if r.provider is not None),
        gap_months          = gap_months,
        records             = records,
        total_bars          = total_bars,
        avg_integrity_score = avg_score,
        providers_used      = providers_used,
    )


def build_all_reports(store: BarStore) -> list[DataQualityReport]:
    """Build a :class:`DataQualityReport` for every symbol/interval in the cache.

    Returns an empty list if the cache directory doesn't exist or is empty.
    """
    reports: list[DataQualityReport] = []
    for symbol in store.list_symbols():
        for interval in store.list_intervals(symbol):
            reports.append(build_data_report(symbol, interval, store))
    return reports


# ── private ────────────────────────────────────────────────────────────────────

def _find_gaps(months: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return calendar months that are missing between first and last entry."""
    if len(months) < 2:
        return []
    gaps: list[tuple[int, int]] = []
    y, m = months[0]
    for year, month in months[1:]:
        ny, nm = _next_month(y, m)
        while (ny, nm) < (year, month):
            gaps.append((ny, nm))
            ny, nm = _next_month(ny, nm)
        y, m = year, month
    return gaps


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)
