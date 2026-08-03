"""MarketData facade — wraps the data layer for external consumers."""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from shared.errors import DataError


class MarketData:
    """High-level interface for fetching and caching OHLCV bars.

    The Trading Bot (and any other external consumer) should use this class
    instead of importing from ``data`` directly.

    Example
    -------
    >>> md = MarketData()
    >>> bars = md.get_bars("BTCUSDT", "1h", date(2024, 1, 1), date(2024, 3, 31))
    """

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: date,
        end: date,
        provider=None,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars for *symbol* between *start* and *end*.

        Args:
            symbol:   Trading pair / ticker, e.g. "BTCUSDT".
            interval: Bar interval, e.g. "1h", "4h", "1d".
            start:    Inclusive start date.
            end:      Inclusive end date (defaults to today).
            provider: Optional custom MarketDataProvider or ProviderManager.

        Returns:
            DataFrame with DatetimeIndex and columns [open, high, low, close, volume].

        Raises:
            DataError: if the fetch fails or returns empty data.
        """
        try:
            from data.api import get_bars
            return get_bars(symbol, interval, start, end, provider=provider)
        except Exception as exc:
            raise DataError(f"Failed to fetch bars for {symbol}/{interval}: {exc}") from exc

    def audit(self, bars: pd.DataFrame):
        """Run the full data integrity audit on *bars*.

        Returns:
            DataIntegrityReport with an integrity_score in [0, 100].

        Raises:
            IntegrityError: on hard failures (duplicates, negative prices, etc.).
        """
        try:
            from research.integrity import audit_bars
            from shared.errors import IntegrityError as _IE
            report = audit_bars(bars)
            return report
        except ValueError as exc:
            from shared.errors import IntegrityError
            raise IntegrityError(str(exc)) from exc
        except Exception as exc:
            from shared.errors import DataError
            raise DataError(f"Integrity audit failed: {exc}") from exc
