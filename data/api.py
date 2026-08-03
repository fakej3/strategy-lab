"""Public API for the market data layer.

Usage::

    from data import get_bars
    from datetime import date

    df = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31))
"""
from __future__ import annotations

import os
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
    if fetch_months:
        workers = min(n_workers, len(fetch_months))
        if workers <= 1:
            for year, month in fetch_months:
                df = _fetch_and_cache(provider, store, symbol, interval, year, month)
                results[(year, month)] = df
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
                fetch_errors: list[str] = []
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
    """Fetch one month from provider, write to store, return the DataFrame."""
    df = provider.fetch_month(symbol, interval, year, month)
    if not df.empty:
        store.write(symbol, interval, year, month, df)
    return df


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
