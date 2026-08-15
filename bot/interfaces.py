"""Abstract interfaces for the Trading Bot.

These abstract base classes define the contracts that Trading Bot components
must implement.  They are intentionally minimal — the goal is to establish
the API surface, not to implement it.

All concrete implementations will live here or in sub-packages of bot/.
All of them must import from lab/ or shared/ ONLY.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExecutionEngine(ABC):
    """Sends orders to the exchange and tracks fill state."""

    @abstractmethod
    def submit_order(self, symbol: str, side: str, size: float, **kwargs) -> str:
        """Submit an order; return an order ID."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order; return True if successful."""

    @abstractmethod
    def get_order(self, order_id: str) -> dict[str, Any]:
        """Return the current state of an order."""


class OrderManager(ABC):
    """Manages the lifecycle of orders: creation, tracking, reconciliation."""

    @abstractmethod
    def place(self, symbol: str, side: str, size: float, **kwargs) -> str:
        """Place and track an order."""

    @abstractmethod
    def open_orders(self) -> list[dict[str, Any]]:
        """Return a list of all currently open orders."""


class PositionManager(ABC):
    """Tracks open positions and their current P&L."""

    @abstractmethod
    def positions(self) -> list[dict[str, Any]]:
        """Return a list of all currently open positions."""

    @abstractmethod
    def close(self, symbol: str) -> None:
        """Close the open position for *symbol*."""


class ExchangeAdapter(ABC):
    """Interface for order submission, matching, and lifecycle management.

    ``PaperExchange`` implements this interface.  A future Binance Testnet or
    live adapter would also implement it, allowing ``OrderManager`` to switch
    backends without any engine changes.
    """

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        order_id: str | None = None,
        current_position_size: float = 0.0,
    ) -> Any:
        """Validate and accept (or reject) a new order. Returns the order record."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""

    @abstractmethod
    def cancel_all(self, symbol: str | None = None) -> int:
        """Cancel all open orders for *symbol* (or all if None). Returns count."""

    @abstractmethod
    def process_candle(
        self,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        candle_ts: str | None = None,
    ) -> list:
        """Match all open orders against a closed candle. Returns list of fills."""

    @abstractmethod
    def get_open_orders(self, symbol: str | None = None) -> list:
        """Return currently open orders, optionally filtered by symbol."""

    @abstractmethod
    def get_order(self, order_id: str) -> Any:
        """Return a single order record by ID, or None if not found."""

    @abstractmethod
    def get_all_orders(self, symbol: str | None = None, limit: int = 200) -> list:
        """Return all orders (open + terminal), newest first."""

    @abstractmethod
    def restore_order(self, order: Any) -> None:
        """Re-register a previously-accepted open order (used on restart recovery)."""

    def get_min_notional(self, symbol: str) -> float:
        """Return the minimum order notional (quote currency) for *symbol*.

        Returns 0.0 by default — subclasses override to enforce per-symbol limits.
        PaperExchange delegates to its SymbolRules table.
        """
        return 0.0


class MarketDataInterface(ABC):
    """Normalises exchange-specific REST/WebSocket market data APIs."""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> list:
        """Fetch recent OHLCV candles from the exchange."""

    @abstractmethod
    def fetch_balance(self) -> dict[str, float]:
        """Return available balances keyed by asset."""


class PaperTrading(MarketDataInterface):
    """Paper trading market-data adapter placeholder."""

    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> list:
        raise NotImplementedError("PaperTrading is a placeholder — not yet implemented.")

    def fetch_balance(self) -> dict[str, float]:
        raise NotImplementedError("PaperTrading is a placeholder — not yet implemented.")


class LiveTrading(MarketDataInterface):
    """Live trading market-data adapter placeholder."""

    def fetch_ohlcv(self, symbol: str, interval: str, limit: int) -> list:
        raise NotImplementedError("LiveTrading is a placeholder — not yet implemented.")

    def fetch_balance(self) -> dict[str, float]:
        raise NotImplementedError("LiveTrading is a placeholder — not yet implemented.")


class RiskEngine(ABC):
    """Evaluates proposed trades against risk limits before submission."""

    @abstractmethod
    def check(self, symbol: str, side: str, size: float, price: float) -> bool:
        """Return True if the trade passes all risk checks."""


class NotificationEngine(ABC):
    """Sends alerts and status updates to external channels."""

    @abstractmethod
    def send(self, message: str, level: str = "info") -> None:
        """Send *message* to the configured notification channel."""


class StrategyRuntime(ABC):
    """Runs a live strategy in a bar-by-bar event loop."""

    @abstractmethod
    def start(self) -> None:
        """Start the event loop."""

    @abstractmethod
    def stop(self) -> None:
        """Gracefully stop the event loop."""


class Monitoring(ABC):
    """Exposes metrics and health-check endpoints for the bot."""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return a health-check dict."""

    @abstractmethod
    def metrics(self) -> dict[str, Any]:
        """Return current operational metrics."""
