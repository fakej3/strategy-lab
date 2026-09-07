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
import math


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


def _finite_positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


def next_open(raw_open: float, slippage_rate: float) -> float:
    _finite_positive(raw_open, "open")
    if not math.isfinite(slippage_rate) or slippage_rate < 0 or slippage_rate >= 1:
        raise ValueError("slippage_rate must be finite and in [0, 1)")
    return raw_open * (1.0 + slippage_rate)


def protective_exit(*, raw_open: float, raw_high: float, raw_low: float, stop: float | None, target: float | None, slippage_rate: float) -> Fill | None:
    for value, name in ((raw_open, "open"), (raw_high, "high"), (raw_low, "low")):
        _finite_positive(value, name)
    if raw_low > raw_high or raw_open < raw_low or raw_open > raw_high:
        raise ValueError("invalid OHLC relationships")
    if not math.isfinite(slippage_rate) or slippage_rate < 0 or slippage_rate >= 1:
        raise ValueError("slippage_rate must be finite and in [0, 1)")
    if stop is not None:
        _finite_positive(stop, "stop")
    if target is not None:
        _finite_positive(target, "target")
    if stop is not None and target is not None and stop >= target:
        raise ValueError("stop must be below target for a long position")

    stop_hit = stop is not None and raw_low <= stop
    target_hit = target is not None and raw_high >= target
    if not stop_hit and not target_hit:
        return None
    if stop_hit:
        raw = min(stop, raw_open)
        return Fill(price=raw * (1.0 - slippage_rate), bar=-1, reason=ExitReason.STOP.value)
    raw = max(target, raw_open)
    return Fill(price=raw * (1.0 - slippage_rate), bar=-1, reason=ExitReason.TARGET.value)
