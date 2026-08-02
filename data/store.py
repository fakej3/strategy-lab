"""BarStore — Parquet-backed local cache for OHLCV bars."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_EMPTY_COLS = ["open", "high", "low", "close", "volume"]


class BarStore:
    """Reads and writes per-month Parquet files.

    Layout on disk::

        {data_dir}/{symbol}/{interval}/{YYYY}-{MM}.parquet

    Past months are written once and treated as immutable.  The caller
    (api.get_bars) decides which months need fetching; BarStore only
    handles persistence.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    # ── public ────────────────────────────────────────────────────────────────

    def exists(self, symbol: str, interval: str, year: int, month: int) -> bool:
        return self._path(symbol, interval, year, month).exists()

    def write(self, symbol: str, interval: str, year: int, month: int, df: pd.DataFrame) -> None:
        path = self._path(symbol, interval, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

    def read(self, symbol: str, interval: str, year: int, month: int) -> pd.DataFrame:
        df = pd.read_parquet(self._path(symbol, interval, year, month))
        # Ensure UTC timezone is preserved across round-trips
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    # ── private ───────────────────────────────────────────────────────────────

    def _path(self, symbol: str, interval: str, year: int, month: int) -> Path:
        return self.data_dir / symbol / interval / f"{year:04d}-{month:02d}.parquet"
