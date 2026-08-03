"""YahooFinanceProvider — OHLCV data via Yahoo Finance chart API (no extra libraries).

Limitations vs Binance:
- Intraday intervals (1h and below) carry only ~60 days of history on Yahoo.
- Intervals not in _INTERVAL_MAP (e.g. 4h, 2h, 3d) return an empty DataFrame.
- Crypto symbols must follow Yahoo naming: BTCUSDT → BTC-USD.
- Data may differ slightly from exchange prices due to aggregation conventions.

Designed as a **fallback** provider: use Binance as primary and this when
Binance is unavailable or a month is missing.
"""
from __future__ import annotations

import calendar
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from ..provider import MarketDataProvider

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# Binance interval → Yahoo Finance interval (best fit)
_INTERVAL_MAP: dict[str, str] = {
    "1m" : "1m",
    "3m" : "5m",
    "5m" : "5m",
    "15m": "15m",
    "30m": "30m",
    "1h" : "60m",
    "2h" : "60m",
    "4h" : "60m",
    "6h" : "60m",
    "8h" : "60m",
    "12h": "60m",
    "1d" : "1d",
    "3d" : "1d",
    "1w" : "1wk",
    "1M" : "1mo",
}

# Quote-asset suffix → Yahoo suffix for common crypto pairs
_QUOTE_SUFFIX: dict[str, str] = {
    "USDT": "-USD",
    "USDC": "-USD",
    "BUSD": "-USD",
    "BTC" : "-BTC",
    "ETH" : "-ETH",
    "BNB" : "-BNB",
}

_OHLCV = ["open", "high", "low", "close", "volume"]
_MAX_RETRIES    = 3
_RETRY_BASE_SEC = 1.0


def _to_yahoo_ticker(symbol: str) -> str:
    """Convert a Binance-style symbol to a Yahoo Finance ticker.

    BTCUSDT → BTC-USD, ETHBTC → ETH-BTC, AAPL → AAPL (pass-through).
    """
    for suffix, replacement in _QUOTE_SUFFIX.items():
        if symbol.upper().endswith(suffix):
            base = symbol[: -len(suffix)]
            return (base + replacement).upper()
    return symbol.upper()


class YahooFinanceProvider(MarketDataProvider):
    """Fetches one calendar month of OHLCV bars from the Yahoo Finance chart API.

    Uses only the ``requests`` library — no ``yfinance`` dependency.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._s = session or requests.Session()
        self._s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })

    # ── MarketDataProvider interface ─────────────────────────────────────────

    def fetch_month(
        self, symbol: str, interval: str, year: int, month: int
    ) -> pd.DataFrame:
        """Fetch one calendar month of OHLCV bars.

        Returns empty DataFrame if the interval is unsupported, the ticker
        is unknown to Yahoo, or the period has no data.

        Raises:
            requests.RequestException: on non-recoverable HTTP/network errors.
        """
        yf_interval = _INTERVAL_MAP.get(interval)
        if yf_interval is None:
            return pd.DataFrame(columns=_OHLCV)

        ticker = _to_yahoo_ticker(symbol)
        start_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
        last_day  = calendar.monthrange(year, month)[1]
        end_ts    = int(datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

        raw = self._request(ticker, yf_interval, start_ts, end_ts)
        return self._parse(raw)

    # ── private ──────────────────────────────────────────────────────────────

    def _request(
        self, ticker: str, yf_interval: str, period1: int, period2: int
    ) -> dict:
        url = _CHART_URL.format(ticker=ticker)
        params = {
            "interval"      : yf_interval,
            "period1"       : period1,
            "period2"       : period2,
            "includePrePost": "false",
            "events"        : "div,splits",
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._s.get(url, params=params, timeout=30)
                if resp.status_code == 404:
                    return {}
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_SEC * (2 ** attempt))
            except requests.HTTPError as exc:
                if resp.status_code == 429:
                    last_exc = exc
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(_RETRY_BASE_SEC * (2 ** attempt) * 2)
                else:
                    raise
        raise requests.RequestException(
            f"YahooFinanceProvider: {_MAX_RETRIES} attempts failed for {ticker}: {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse(data: dict) -> pd.DataFrame:
        """Parse Yahoo chart JSON into a normalised OHLCV DataFrame."""
        try:
            chart = data.get("chart") if isinstance(data, dict) else None
            result_list = (chart.get("result") if isinstance(chart, dict) else None) or []
            if not result_list:
                return pd.DataFrame(columns=_OHLCV)

            chart = result_list[0]
            timestamps = chart.get("timestamp") or []
            if not timestamps:
                return pd.DataFrame(columns=_OHLCV)

            quote = (chart.get("indicators", {}).get("quote") or [{}])[0]

            df = pd.DataFrame(
                {
                    "open"  : quote.get("open",   [None] * len(timestamps)),
                    "high"  : quote.get("high",   [None] * len(timestamps)),
                    "low"   : quote.get("low",    [None] * len(timestamps)),
                    "close" : quote.get("close",  [None] * len(timestamps)),
                    "volume": quote.get("volume", [None] * len(timestamps)),
                }
            )
            df.index = pd.to_datetime(timestamps, unit="s", utc=True)
            df.index.name = "open_time"

            # Drop rows with any NaN in OHLCV (missing bars from Yahoo)
            df = df.dropna(subset=_OHLCV)
            for col in _OHLCV:
                df[col] = df[col].astype(float)

            df = df[~df.index.duplicated(keep="first")]
            df = df.sort_index()
            return df[_OHLCV]

        except (KeyError, IndexError, TypeError, ValueError):
            return pd.DataFrame(columns=_OHLCV)
