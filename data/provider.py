"""MarketDataProvider — exchange-agnostic interface for fetching OHLCV bars."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class MarketDataProvider(ABC):
    """Implement this to add a new exchange or data source.

    The rest of the system depends only on this interface, never on a
    concrete provider, so switching sources requires no changes outside
    the data package.
    """

    @abstractmethod
    def fetch_month(
        self, symbol: str, interval: str, year: int, month: int
    ) -> pd.DataFrame:
        """Fetch one calendar month of OHLCV bars.

        Returns:
            DataFrame with DatetimeIndex (UTC, name="open_time") and float64
            columns: open, high, low, close, volume.  Returns an empty
            DataFrame if the month has no data (asset didn't exist yet,
            future month, etc.).

        Raises:
            requests.HTTPError: on non-recoverable network failures.
        """
