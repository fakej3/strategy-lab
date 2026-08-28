"""Explicit, deterministic V2 execution semantics for long-only research.

Rules are deliberately conservative: signals observed on bar i are eligible
for execution at bar i+1 open. Stops/targets observed inside a bar are filled
at the modeled stop/target price, except when the bar opens beyond that level,
in which case the open is used. If both stop and target are touched in one bar,
the stop wins because intrabar ordering is unknown and this avoids optimistic
selection. This module models execution only; fees are applied by trade
accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    LONG = "long"


class ExitReason(str, Enum):
    SIGNAL = "signal"
    STOP = "stop"
    TARGET = "target"
    END = "end"


@dataclass(frozen=True)
class Fill:
    price: float
    bar: int
    reason: str


def next_open(raw_open: float, slippage_rate: float) -> float:
    if raw_open <= 0 or slippage_rate < 0:
        raise ValueError("invalid open or slippage")
    return raw_open * (1.0 + slippage_rate)


def protective_exit(*, raw_open: float, raw_high: float, raw_low: float, stop: float | None, target: float | None, slippage_rate: float) -> Fill | None:
    if min(raw_open, raw_high, raw_low) <= 0 or raw_low > raw_high or slippage_rate < 0:
        raise ValueError("invalid OHLC or slippage")
    stop_hit = stop is not None and raw_low <= stop
    target_hit = target is not None and raw_high >= target
    if not stop_hit and not target_hit:
        return None
    if stop_hit:
        raw = min(stop, raw_open)
        return Fill(price=raw * (1.0 - slippage_rate), bar=-1, reason=ExitReason.STOP.value)
    raw = max(target, raw_open)
    return Fill(price=raw * (1.0 - slippage_rate), bar=-1, reason=ExitReason.TARGET.value)
