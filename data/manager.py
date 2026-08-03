"""ProviderManager — ordered fallback chain over multiple MarketDataProvider instances.

Usage::

    from data.manager import ProviderManager
    from data.fetcher import BinanceProvider
    from data.providers import YahooFinanceProvider

    mgr = ProviderManager([BinanceProvider(), YahooFinanceProvider()])
    df = mgr.fetch_month("BTCUSDT", "1h", 2024, 1)

ProviderManager implements MarketDataProvider so it can be passed wherever
a provider is accepted (including as the ``provider=`` argument to ``get_bars``).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Sequence

import pandas as pd

from .provider import MarketDataProvider

_EMPTY_COLS = ["open", "high", "low", "close", "volume"]


class ProviderError(RuntimeError):
    """All providers in a ProviderManager failed for a given request."""


class ProviderManager(MarketDataProvider):
    """Try providers in order; fall back when one raises or returns empty data.

    A provider that **raises** is treated as a failure and the next provider
    is tried.  A provider that **returns empty** is treated as "no data for
    this period" (not a failure), but the manager still tries the next
    provider in case it has data.

    If every provider raises, :class:`ProviderError` is raised with a
    combined message that names each provider and its error.

    If every provider returns empty (or some raise and the rest return
    empty), an empty DataFrame is returned — the asset simply had no data
    during that period.

    Args:
        providers:       Ordered list of providers to try.  Must not be empty.
        rate_limit_secs: Minimum seconds to wait between consecutive calls to
                         the same provider.  Set to 0 (default) to disable.
    """

    def __init__(
        self,
        providers: Sequence[MarketDataProvider],
        *,
        rate_limit_secs: float = 0.0,
    ) -> None:
        if not providers:
            raise ValueError("ProviderManager requires at least one provider")
        self._providers  = list(providers)
        self._rate_limit = rate_limit_secs
        self._lock       = threading.Lock()
        self._last_call: dict[int, float] = {}

    # ── MarketDataProvider interface ─────────────────────────────────────────

    def fetch_month(
        self, symbol: str, interval: str, year: int, month: int
    ) -> pd.DataFrame:
        """Return bars from the first provider that succeeds.

        Returns:
            OHLCV DataFrame (may be empty if the period has no data anywhere).

        Raises:
            ProviderError: if every provider raised an exception.
        """
        errors: list[str]  = []
        had_exception      = False

        for provider in self._providers:
            self._throttle(provider)
            name = type(provider).__name__
            try:
                df = provider.fetch_month(symbol, interval, year, month)
            except Exception as exc:
                had_exception = True
                errors.append(f"{name}: {exc}")
                continue

            if not df.empty:
                return df

            errors.append(f"{name}: returned empty data")

        if had_exception and all(_is_exception_error(e) for e in errors):
            raise ProviderError(
                f"All providers failed for {symbol}/{interval} "
                f"{year}-{month:02d}: " + "; ".join(errors)
            )

        # All empty — not an error, asset had no data this period
        return pd.DataFrame(columns=_EMPTY_COLS)

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def providers(self) -> list[MarketDataProvider]:
        """Ordered list of providers (read-only copy)."""
        return list(self._providers)

    def provider_names(self) -> list[str]:
        """Names of each provider class in order."""
        return [type(p).__name__ for p in self._providers]

    # ── private ──────────────────────────────────────────────────────────────

    def _throttle(self, provider: MarketDataProvider) -> None:
        if self._rate_limit <= 0:
            return
        key  = id(provider)
        with self._lock:
            elapsed = time.monotonic() - self._last_call.get(key, 0.0)
            wait    = self._rate_limit - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_call[key] = time.monotonic()


def _is_exception_error(msg: str) -> bool:
    """Return True if the error message came from an exception (not empty data)."""
    return "returned empty data" not in msg
