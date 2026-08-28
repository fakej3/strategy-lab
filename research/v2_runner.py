"""Minimal deterministic V2 research runner.

This runner wires validated bars to a strategy callback while enforcing the
basic information boundary: a signal produced from bar i is passed to the
execution callback for bar i+1. It intentionally does not embed strategy,
fees, or portfolio math; those remain explicit dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any
import pandas as pd

from data.v2_contract import normalize_ohlcv


@dataclass(frozen=True)
class Signal:
    bar: int
    value: Any


@dataclass(frozen=True)
class RunResult:
    signals: tuple[Signal, ...]
    executions: tuple[Any, ...]


def run_signal_execution(
    bars: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame], Any],
    execute_fn: Callable[[int, Any, pd.Series], Any],
) -> RunResult:
    data = normalize_ohlcv(bars)
    signals: list[Signal] = []
    executions: list[Any] = []
    for i in range(len(data) - 1):
        history = data.iloc[: i + 1]
        signal = signal_fn(history)
        signals.append(Signal(i, signal))
        executions.append(execute_fn(i + 1, signal, data.iloc[i + 1]))
    return RunResult(tuple(signals), tuple(executions))
