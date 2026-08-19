"""Public API for the market data layer.

Usage::

    from data import get_bars
    from datetime import date

    df = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31))

    # With provider fallback chain:
    from data.manager import ProviderManager
    from data.providers import YahooFinanceProvider
    mgr = ProviderManager([BinanceProvider(), YahooFinanceProvider()])
    df = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31), provider=mgr)
"""
from __future__ import annotations

import hashlib
import os
import struct
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from .fetcher import BinanceProvider
from .provider import MarketDataProvider
from .store import BarStore

_DEFAULT_DATA_DIR = Path(os.environ.get("EDGELAB_DATA_DIR", "market_data"))

_EMPTY_COLS = ["open", "high", "low", "close", "volume"]


class DataFetchError(RuntimeError):
    """Raised when required historical months could not be downloaded.

    Distinct from data integrity errors (corrupt/gappy data that was
    successfully downloaded).  The message names the failed months and
    suggests remediation steps.
    """


def get_bars(
    symbol: str,
    interval: str,
    from_date: date,
    to_date: date,
    *,
    provider: MarketDataProvider | None = None,
    store: BarStore | None = None,
    force_refresh: bool = False,
    n_workers: int = 4,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> pd.DataFrame:
    """Return OHLCV bars for a symbol/interval over the requested date range.

    Cache policy:
    - Completed past months: fetched once, served from local Parquet thereafter.
    - Current month: always re-fetched (data grows throughout the month).
    - ``force_refresh=True``: re-fetch all months regardless of cache state.

    Args:
        symbol: Trading pair, e.g. ``"BTCUSDT"``.
        interval: Bar interval, e.g. ``"1h"``, ``"4h"``, ``"1d"``.
        from_date: First day of range, inclusive.
        to_date: Last day of range, inclusive.
        provider: Override the default ``BinanceProvider``.
        store: Override the default ``BarStore`` (uses ``EDGELAB_DATA_DIR``).
        force_refresh: Re-fetch even months that are already cached.
        n_workers: Thread-pool size for parallel month downloads (default 4).
            Set to 1 to fetch sequentially.
        on_progress: Optional callback ``(label, done, total) -> None`` called
            after each month is resolved (fetched or read from cache).

    Returns:
        DataFrame with UTC DatetimeIndex (``name="open_time"``) and float64
        columns: ``open``, ``high``, ``low``, ``close``, ``volume``.
        Empty DataFrame if no data exists for the range.

    Raises:
        ValueError: if ``from_date`` is after ``to_date``.
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} is after to_date {to_date}")

    if provider is None:
        provider = BinanceProvider()
    if store is None:
        store = BarStore(_DEFAULT_DATA_DIR)

    months = list(_iter_months(from_date, to_date))
    total  = len(months)

    # Decide per-month: fetch from network or read from cache
    fetch_months = []
    cache_months = []
    for year, month in months:
        if force_refresh or _is_current_month(year, month) or not store.exists(symbol, interval, year, month):
            fetch_months.append((year, month))
        else:
            cache_months.append((year, month))

    # Results dict: (year, month) -> DataFrame
    results: dict[tuple[int, int], pd.DataFrame] = {}
    done = 0

    # Read cached months (fast, no network)
    for year, month in cache_months:
        results[(year, month)] = store.read(symbol, interval, year, month)
        done += 1
        if on_progress:
            on_progress(f"{year}-{month:02d}", done, total)

    # Fetch network months in parallel
    fetch_errors: list[str] = []  # accumulated across both serial and parallel paths
    if fetch_months:
        workers = min(n_workers, len(fetch_months))
        if workers <= 1:
            for year, month in fetch_months:
                try:
                    df = _fetch_and_cache(provider, store, symbol, interval, year, month)
                    results[(year, month)] = df
                except Exception as exc:
                    results[(year, month)] = pd.DataFrame(columns=_EMPTY_COLS)
                    fetch_errors.append(f"{year}-{month:02d}: {exc}")
                done += 1
                if on_progress:
                    on_progress(f"{year}-{month:02d}", done, total)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_ym = {
                    pool.submit(
                        _fetch_and_cache, provider, store, symbol, interval, y, m
                    ): (y, m)
                    for y, m in fetch_months
                }
                for future in as_completed(future_to_ym):
                    ym = future_to_ym[future]
                    try:
                        results[ym] = future.result()
                    except Exception as exc:
                        results[ym] = pd.DataFrame(columns=_EMPTY_COLS)
                        fetch_errors.append(f"{ym[0]}-{ym[1]:02d}: {exc}")
                    done += 1
                    if on_progress:
                        on_progress(f"{ym[0]}-{ym[1]:02d}", done, total)

    # Raise on past-month download failures BEFORE integrity checks so the
    # caller sees a clear "download failed" error rather than a misleading
    # "data integrity fail" caused by the resulting gaps.
    if fetch_errors:
        today = datetime.now(timezone.utc).date()
        # Distinguish past months (should be in archive) from current month
        past_failures = [
            e for e in fetch_errors
            if not e.startswith(f"{today.year}-{today.month:02d}:")
        ]
        if past_failures:
            n = len(past_failures)
            cached_months = sorted(
                ym for ym in months
                if ym not in {
                    _ym_from_error(e) for e in past_failures
                } and not results.get(ym, pd.DataFrame()).empty
            )
            cache_range = (
                f" Available cached data: {cached_months[0][0]}-{cached_months[0][1]:02d}"
                f" to {cached_months[-1][0]}-{cached_months[-1][1]:02d}."
                if cached_months else " No cached data available."
            )
            raise DataFetchError(
                f"Failed to download {n} month(s) of {symbol}/{interval} data "
                f"from Binance (network error or blocked access). "
                f"Failed months: {', '.join(e.split(':')[0] for e in past_failures[:5])}"
                + (" ..." if n > 5 else "") + "."
                + cache_range
                + " To fix: resolve network access to data.binance.vision/api.binance.com,"
                + " or narrow your start_date to use only locally cached data."
                + f" First failure: {past_failures[0]}"
            )
        # Only current-month failures: issue a warning but don't block
        if fetch_errors:
            import warnings as _warn
            _warn.warn(
                f"Data fetch failures for {symbol}/{interval}: "
                + "; ".join(fetch_errors),
                RuntimeWarning,
                stacklevel=3,
            )

    # Assemble frames in chronological order
    frames = [results[ym] for ym in months if not results.get(ym, pd.DataFrame()).empty]

    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)

    result = pd.concat(frames).sort_index()
    # Drop any duplicates that survived month-boundary concatenation
    result = result[~result.index.duplicated(keep="first")]

    # Trim to the exact requested date range
    start = pd.Timestamp(from_date, tz="UTC")
    end   = pd.Timestamp(to_date, tz="UTC") + pd.offsets.Day(1)
    return result[(result.index >= start) & (result.index < end)]


# ── helpers ───────────────────────────────────────────────────────────────────

def _fetch_and_cache(
    provider: MarketDataProvider,
    store: BarStore,
    symbol: str,
    interval: str,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Fetch one month from provider, validate, write to store, record metadata."""
    df = provider.fetch_month(symbol, interval, year, month)
    if df.empty:
        return df

    # Validate before caching — hard failures propagate, soft issues are logged
    integrity_score: float | None = None
    try:
        from research.integrity import audit_bars as _audit
        report = _audit(df, symbol=symbol, interval=interval)
        integrity_score = report.integrity_score
        if not report.passed:
            warnings.warn(
                f"Data quality warning for {symbol}/{interval} "
                f"{year}-{month:02d} "
                f"(score={integrity_score:.0f}/100): "
                + "; ".join(report.warnings),
                RuntimeWarning,
                stacklevel=4,
            )
    except ValueError as exc:
        # Hard integrity failure — refuse to cache corrupt data
        raise ValueError(
            f"Data integrity hard failure for {symbol}/{interval} "
            f"{year}-{month:02d}: {exc}"
        ) from exc
    except ImportError:
        pass  # research package not available in minimal environments

    store.write(symbol, interval, year, month, df)

    # Write metadata sidecar (best-effort — don't fail the whole fetch on this)
    try:
        store.write_meta(symbol, interval, year, month, _build_meta(df, provider, integrity_score))
    except Exception:
        pass

    return df


def _build_meta(
    df: pd.DataFrame,
    provider: MarketDataProvider,
    integrity_score: float | None,
) -> dict:
    """Build a metadata dict for the downloaded month."""
    provider_name = type(provider).__name__
    checksum = _df_checksum(df)
    return {
        "provider"       : provider_name,
        "download_time"  : datetime.now(timezone.utc).isoformat(),
        "bar_count"      : len(df),
        "first_bar"      : df.index[0].isoformat() if not df.empty else None,
        "last_bar"       : df.index[-1].isoformat() if not df.empty else None,
        "integrity_score": integrity_score,
        "checksum"       : checksum,
    }


def _df_checksum(df: pd.DataFrame) -> str:
    """Fast, deterministic MD5 checksum over row-count + close prices."""
    h = hashlib.md5()
    h.update(struct.pack(">q", len(df)))
    if not df.empty and "close" in df.columns:
        h.update(df["close"].values.astype("float64").tobytes())
    return h.hexdigest()[:16]


def _iter_months(from_date: date, to_date: date):
    """Yield (year, month) tuples covering from_date through to_date."""
    year, month = from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        yield year, month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def _is_current_month(year: int, month: int) -> bool:
    today = datetime.now(timezone.utc).date()
    return year == today.year and month == today.month


def _ym_from_error(error_str: str) -> tuple[int, int] | None:
    """Parse (year, month) from an error string like '2025-03: ...'."""
    try:
        prefix = error_str.split(":")[0].strip()
        y, m = prefix.split("-")
        return int(y), int(m)
    except (ValueError, IndexError):
        return None
