"""BinanceProvider — fetches OHLCV data from Binance Vision and the REST API."""
from __future__ import annotations

import io
import zipfile
from calendar import monthrange
from datetime import datetime, timezone

import pandas as pd
import requests

from .provider import MarketDataProvider

_VISION_BASE = "https://data.binance.vision/data/spot/monthly/klines"
_API_BASE = "https://api.binance.com/api/v3/klines"
_API_LIMIT = 1000

_RAW_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]
_KEEP = ["open", "high", "low", "close", "volume"]


class BinanceProvider(MarketDataProvider):
    """Fetches from Binance Vision (bulk archive) with REST API fallback.

    Binance Vision hosts complete monthly files going back to 2017 at no cost.
    The REST API covers recent months not yet in the Vision archive.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._s = session or requests.Session()

    def fetch_month(self, symbol: str, interval: str, year: int, month: int) -> pd.DataFrame:
        df = self._try_vision(symbol, interval, year, month)
        if df is not None:
            return df
        return self._fetch_api(symbol, interval, year, month)

    # ── private ───────────────────────────────────────────────────────────────

    def _try_vision(
        self, symbol: str, interval: str, year: int, month: int
    ) -> pd.DataFrame | None:
        url = (
            f"{_VISION_BASE}/{symbol}/{interval}/"
            f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
        )
        resp = self._s.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            with zf.open(zf.namelist()[0]) as f:
                raw = pd.read_csv(f, header=None, names=_RAW_COLS)

        return self._normalize(raw)

    def _fetch_api(self, symbol: str, interval: str, year: int, month: int) -> pd.DataFrame:
        start_ms = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)
        last_day = monthrange(year, month)[1]
        # end_ms: exclusive upper bound — first millisecond of next month
        if month == 12:
            end_ms = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        else:
            end_ms = int(datetime(year, month + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

        rows: list[list] = []
        cursor = start_ms

        while cursor < end_ms:
            resp = self._s.get(
                _API_BASE,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms - 1,
                    "limit": _API_LIMIT,
                },
                timeout=30,
            )
            resp.raise_for_status()
            batch: list[list] = resp.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < _API_LIMIT:
                break
            cursor = batch[-1][0] + 1  # advance past the last bar's open_time

        if not rows:
            return pd.DataFrame(columns=_KEEP)

        raw = pd.DataFrame(rows, columns=_RAW_COLS)
        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.copy()
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("open_time")
        for col in _KEEP:
            df[col] = df[col].astype(float)
        return df[_KEEP]
