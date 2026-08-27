"""Independent trade-economics calculations for V2 reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TradeEconomics:
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    net_pnl: float


def calculate_trade_economics(
    *,
    direction: str,
    entry_price: float,
    exit_price: float,
    size: float,
    fee_rate: float,
) -> TradeEconomics:
    """Calculate one completed trade from its executed prices and size.

    Slippage must already be reflected in the executed entry/exit prices.
    Therefore this function never charges slippage a second time.
    """
    direction = direction.lower()
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    vals = (entry_price, exit_price, size, fee_rate)
    if not all(math.isfinite(float(x)) for x in vals):
        raise ValueError("trade economics inputs must be finite")
    if entry_price <= 0 or exit_price <= 0 or size <= 0 or fee_rate < 0:
        raise ValueError("prices and size must be positive; fee_rate must be non-negative")

    sign = -1.0 if direction == "short" else 1.0
    gross = (exit_price - entry_price) * size * sign
    entry_fee = entry_price * size * fee_rate
    exit_fee = exit_price * size * fee_rate
    return TradeEconomics(gross, entry_fee, exit_fee, gross - entry_fee - exit_fee)
