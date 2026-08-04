"""System monitoring for the paper trading bot.

Reads memory and CPU usage from /proc/self (Linux) to avoid the psutil
dependency.  Snapshots are persisted to BotStorage and exposed via the
EventBus as HeartbeatEvents.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from .events import EventBus, HeartbeatEvent
from .state import BotState
from .storage import BotStorage

log = logging.getLogger("strategy_lab.bot.monitor")


class Monitor:
    """Collects and persists system and bot runtime metrics.

    Usage::

        mon = Monitor(state, storage, bus)
        mon.tick()    # call on each monitoring interval (e.g. every 60s)
    """

    def __init__(
        self,
        state: BotState,
        storage: BotStorage,
        bus: EventBus,
    ) -> None:
        self.state   = state
        self.storage = storage
        self.bus     = bus

    def tick(self) -> dict[str, Any]:
        """Collect metrics, persist, and emit heartbeat.  Returns snapshot dict."""
        counters = self.state.counters()
        mem_mb   = _read_memory_mb()
        cpu_pct  = _read_cpu_pct()

        snap = {
            "uptime_s":       counters["uptime_s"],
            "candles_total":  counters["candles_total"],
            "reconnects":     counters["reconnects"],
            "missed_candles": counters["missed_candles"],
            "memory_mb":      mem_mb,
            "cpu_pct":        cpu_pct,
            "avg_latency_ms": counters.get("avg_latency_ms"),
        }

        try:
            self.storage.save_runtime_snapshot(snap)
        except Exception:
            log.exception("Failed to persist runtime snapshot")

        try:
            self.storage.save_heartbeat(
                uptime_s=counters["uptime_s"],
                active_symbols=self.state.active_symbols(),
                candles_recv=counters["candles_total"],
            )
        except Exception:
            log.exception("Failed to persist heartbeat")

        try:
            self.bus.emit(HeartbeatEvent(
                uptime_s=counters["uptime_s"],
                candles_received=counters["candles_total"],
                active_symbols=self.state.active_symbols(),
            ))
        except Exception:
            log.exception("Failed to emit heartbeat event")

        log.debug(
            "Monitor tick: uptime=%.0fs candles=%d mem=%.1fMB cpu=%.1f%%",
            counters["uptime_s"], counters["candles_total"],
            mem_mb or 0.0, cpu_pct or 0.0,
        )
        return snap


# ── Linux /proc readers ────────────────────────────────────────────────────────

# These parse /proc/self/status and /proc/self/stat so psutil isn't required.

_CPU_PREV: dict[str, float] = {}   # stores prev (utime+stime, wall_time)


def _read_memory_mb() -> float | None:
    """Read resident set size from /proc/self/status (Linux only)."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024.0
    except Exception:
        pass
    return None


def _read_cpu_pct() -> float | None:
    """Estimate CPU % since last call using /proc/self/stat (Linux only)."""
    try:
        with open("/proc/self/stat") as fh:
            parts = fh.read().split()
        # Fields 14 and 15 are utime and stime in clock ticks
        utime  = int(parts[13])
        stime  = int(parts[14])
        ticks  = os.sysconf("SC_CLK_TCK")
        cpu_s  = (utime + stime) / ticks
        wall_s = time.monotonic()

        prev = _CPU_PREV.get("data")
        _CPU_PREV["data"] = (cpu_s, wall_s)

        if prev is not None:
            prev_cpu, prev_wall = prev
            elapsed_cpu  = cpu_s  - prev_cpu
            elapsed_wall = wall_s - prev_wall
            if elapsed_wall > 0:
                return 100.0 * elapsed_cpu / elapsed_wall
    except Exception:
        pass
    return None
