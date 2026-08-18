"""Deterministic GBM fixture provider — for tests and demo mode ONLY.

NEVER used in production. Generates synthetic OHLCV bars from Geometric
Brownian Motion without touching the market_data/ directory.

To use in tests:
    from data.fixture import FixtureProvider
    provider = FixtureProvider()
    df = provider.fetch_month("BTCUSDT", "1h", 2024, 1)
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .provider import MarketDataProvider

_INTERVAL_BARS_PER_HOUR: dict[str, int] = {
    "1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2,
    "1h": 1,  "2h": 1,  "4h": 1,  "6h": 1,  "8h": 1, "12h": 1, "1d": 1,
}

_INTERVAL_PANDAS_FREQ: dict[str, str] = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h",   "2h": "2h",   "4h": "4h",   "6h": "6h",    "8h": "8h",
    "12h": "12h", "1d": "1D",
}


class FixtureProvider(MarketDataProvider):
    """Generates deterministic synthetic OHLCV bars from GBM.

    Seeds are fixed so tests are reproducible across runs.
    No data is written to disk; no network calls are made.

    NOT for production use.
    """

    def __init__(
        self,
        seed: int = 42,
        s0: float = 46_000.0,
        sigma_per_hour: float = 0.006,
        mu_per_hour: float = 0.0001,
        base_year: int = 2024,
    ) -> None:
        self.seed           = seed
        self.s0             = s0
        self.sigma_per_hour = sigma_per_hour
        self.mu_per_hour    = mu_per_hour
        self.base_year      = base_year

    def fetch_month(
        self, symbol: str, interval: str, year: int, month: int
    ) -> pd.DataFrame:
        """Return one month of deterministic GBM bars."""
        bars_per_hour = _INTERVAL_BARS_PER_HOUR.get(interval, 1)
        freq          = _INTERVAL_PANDAS_FREQ.get(interval, "1h")

        # Count total bars from base_year Jan 1 up to the start of this month
        hours_before = self._hours_from_base(year, month)
        _, days_in_month = calendar.monthrange(year, month)
        hours_in_month   = days_in_month * 24

        total_hours = hours_before + hours_in_month
        n_total     = total_hours * bars_per_hour

        if n_total <= 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # Single seeded RNG for reproducibility across month boundaries
        rng = np.random.default_rng(self.seed)

        # Scale per-bar statistics from hourly parameters
        mu    = self.mu_per_hour    / bars_per_hour
        sigma = self.sigma_per_hour / (bars_per_hour ** 0.5)

        ret   = rng.normal(mu, sigma, n_total)

        # close[i] = s0 * prod(1 + ret[0..i]); vectorised cumprod
        close  = self.s0 * np.cumprod(1.0 + ret)
        # open[i] = close[i-1]; open[0] = s0
        open_     = np.empty(n_total)
        open_[0]  = self.s0
        open_[1:] = close[:-1]

        # High/low anchored on max/min(open, close) → OHLC geometry always valid
        hi_base = np.maximum(open_, close)
        lo_base = np.minimum(open_, close)
        noise_h = rng.uniform(0.001, 0.012, n_total)
        noise_l = rng.uniform(0.001, 0.012, n_total)
        high   = hi_base * (1.0 + noise_h)
        low    = lo_base * (1.0 - noise_l)
        volume = rng.uniform(10_000.0, 500_000.0, n_total)

        # Slice to this month only
        start_idx = hours_before * bars_per_hour
        end_idx   = start_idx + hours_in_month * bars_per_hour

        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        idx = pd.date_range(
            start=start_dt,
            periods=end_idx - start_idx,
            freq=freq,
            name="open_time",
        )

        return pd.DataFrame(
            {
                "open":   open_[start_idx:end_idx].astype("float64"),
                "high":   high[start_idx:end_idx].astype("float64"),
                "low":    low[start_idx:end_idx].astype("float64"),
                "close":  close[start_idx:end_idx].astype("float64"),
                "volume": volume[start_idx:end_idx].astype("float64"),
            },
            index=idx,
        )

    def _hours_from_base(self, year: int, month: int) -> int:
        """Hours elapsed from base_year-01-01 00:00 UTC to year-month-01 00:00 UTC."""
        from datetime import date as _date
        base   = _date(self.base_year, 1, 1)
        target = _date(year, month, 1)
        return max(0, (target - base).days * 24)
