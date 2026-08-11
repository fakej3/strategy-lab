"""BarStore — Parquet-backed local cache for OHLCV bars.

Each month's bars are stored as a Parquet file.  An optional JSON sidecar
stores download metadata (provider name, timestamp, checksum, bar count).

Layout on disk::

    {data_dir}/{symbol}/{interval}/{YYYY}-{MM}.parquet
    {data_dir}/{symbol}/{interval}/{YYYY}-{MM}.meta.json  ← optional
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_EMPTY_COLS = ["open", "high", "low", "close", "volume"]


class BarStore:
    """Reads and writes per-month Parquet files with optional metadata sidecars.

    Past months are written once and treated as immutable.  The caller
    (api.get_bars) decides which months need fetching; BarStore only
    handles persistence.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    # ── OHLCV persistence ─────────────────────────────────────────────────────

    def exists(self, symbol: str, interval: str, year: int, month: int) -> bool:
        return self._path(symbol, interval, year, month).exists()

    def write(self, symbol: str, interval: str, year: int, month: int, df: pd.DataFrame) -> None:
        """Write bars to a Parquet file atomically (temp file → rename).

        A crash during write leaves the previous file intact; readers always
        see either the old valid file or the newly completed file, never a
        partial write.
        """
        path = self._path(symbol, interval, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        try:
            df.to_parquet(tmp)
            tmp.replace(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def read(self, symbol: str, interval: str, year: int, month: int) -> pd.DataFrame:
        df = pd.read_parquet(self._path(symbol, interval, year, month))
        # Ensure UTC timezone is preserved across round-trips
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    # ── Metadata sidecar ──────────────────────────────────────────────────────

    def write_meta(
        self,
        symbol: str,
        interval: str,
        year: int,
        month: int,
        meta: dict,
    ) -> None:
        """Write a JSON metadata sidecar alongside the Parquet file.

        Common fields: ``provider``, ``download_time``, ``bar_count``,
        ``first_bar``, ``last_bar``, ``integrity_score``, ``checksum``.
        """
        path = self._meta_path(symbol, interval, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)

    def read_meta(
        self,
        symbol: str,
        interval: str,
        year: int,
        month: int,
    ) -> dict | None:
        """Read the JSON metadata sidecar, or return None if it doesn't exist."""
        path = self._meta_path(symbol, interval, year, month)
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    # ── Discovery ─────────────────────────────────────────────────────────────

    def list_months(self, symbol: str, interval: str) -> list[tuple[int, int]]:
        """Return sorted (year, month) tuples for all cached months."""
        base = self.data_dir / symbol / interval
        if not base.exists():
            return []
        months: list[tuple[int, int]] = []
        for p in base.glob("*.parquet"):
            parts = p.stem.split("-")
            if len(parts) == 2:
                try:
                    months.append((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
        return sorted(months)

    def list_symbols(self) -> list[str]:
        """Return all symbol directories present in the data directory."""
        if not self.data_dir.exists():
            return []
        return sorted(
            d.name for d in self.data_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def list_intervals(self, symbol: str) -> list[str]:
        """Return all interval directories cached for a symbol."""
        base = self.data_dir / symbol
        if not base.exists():
            return []
        return sorted(
            d.name for d in base.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _path(self, symbol: str, interval: str, year: int, month: int) -> Path:
        return self.data_dir / symbol / interval / f"{year:04d}-{month:02d}.parquet"

    def _meta_path(self, symbol: str, interval: str, year: int, month: int) -> Path:
        return self.data_dir / symbol / interval / f"{year:04d}-{month:02d}.meta.json"
