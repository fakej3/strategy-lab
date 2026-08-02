"""Public API for the market data layer.

Usage::

    from data import get_bars
    from datetime import date

    df = get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31))
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

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

    frames: list[pd.DataFrame] = []

    for year, month in _iter_months(from_date, to_date):
        need_fetch = (
            force_refresh
            or _is_current_month(year, month)
            or not store.exists(symbol, interval, year, month)
        )

        if need_fetch:
            df = provider.fetch_month(symbol, interval, year, month)
            if not df.empty:
                store.write(symbol, interval, year, month, df)
        else:
            df = store.read(symbol, interval, year, month)

        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=_EMPTY_COLS)

    result = pd.concat(frames).sort_index()

    # Trim to the exact requested date range
    start = pd.Timestamp(from_date, tz="UTC")
    end = pd.Timestamp(to_date, tz="UTC") + pd.offsets.Day(1)
    return result[(result.index >= start) & (result.index < end)]


# ── helpers ───────────────────────────────────────────────────────────────────

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
