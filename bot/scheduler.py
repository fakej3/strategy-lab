"""Periodic task scheduler for the paper trading bot.

Runs heartbeat, monitoring snapshots, and daily reset on a fixed schedule.
Everything runs in a single background thread; tasks are cheap and fast.

Schedule
--------
  Every monitor_interval_s  → Monitor.tick()
  Every snapshot_interval_s → Portfolio.snapshot()
  At midnight UTC (once/day) → DailyResetEvent + report generation
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger("strategy_lab.bot.scheduler")


class Scheduler:
    """Background scheduler with second-resolution polling.

    Usage::

        sched = Scheduler()
        sched.every(60, monitor.tick, name="monitor")
        sched.daily_at_utc(0, daily_reset, name="daily_reset")
        sched.start()
        # ... later ...
        sched.stop()
    """

    def __init__(self) -> None:
        self._tasks: list[_Task] = []
        self._daily: list[_DailyTask] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def every(self, interval_s: float, fn: Callable, name: str = "") -> None:
        """Register *fn* to run every *interval_s* seconds."""
        self._tasks.append(_Task(interval_s=interval_s, fn=fn, name=name or fn.__name__))

    def daily_at_utc(self, hour_utc: int, fn: Callable, name: str = "") -> None:
        """Register *fn* to run once per day at *hour_utc* (0–23) UTC."""
        self._daily.append(_DailyTask(hour_utc=hour_utc, fn=fn, name=name or fn.__name__))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="bot-scheduler", daemon=True
        )
        self._thread.start()
        log.info("Scheduler started with %d tasks, %d daily tasks",
                 len(self._tasks), len(self._daily))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Scheduler stopped")

    # ── Private ───────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        # Prime all tasks so they don't fire immediately on start
        now = time.monotonic()
        for task in self._tasks:
            task.next_run = now + task.interval_s

        # Prime daily tasks
        for dt in self._daily:
            dt.last_fired_day = _today_utc()

        while not self._stop_event.is_set():
            now = time.monotonic()

            for task in self._tasks:
                if now >= task.next_run:
                    _run(task.fn, task.name)
                    task.next_run = now + task.interval_s

            today = _today_utc()
            current_hour = datetime.now(timezone.utc).hour
            for dt in self._daily:
                if current_hour == dt.hour_utc and today != dt.last_fired_day:
                    _run(dt.fn, dt.name)
                    dt.last_fired_day = today

            # Sleep until the next task is due (or at most 1 s so stop is checked)
            now = time.monotonic()
            if self._tasks:
                next_due = min(t.next_run for t in self._tasks)
                sleep_s = max(0.0, min(next_due - now, 1.0))
            else:
                sleep_s = 1.0
            self._stop_event.wait(timeout=sleep_s)


class _Task:
    def __init__(self, interval_s: float, fn: Callable, name: str) -> None:
        self.interval_s = interval_s
        self.fn         = fn
        self.name       = name
        self.next_run   = 0.0


class _DailyTask:
    def __init__(self, hour_utc: int, fn: Callable, name: str) -> None:
        self.hour_utc      = hour_utc
        self.fn            = fn
        self.name          = name
        self.last_fired_day = ""


def _run(fn: Callable, name: str) -> None:
    try:
        fn()
    except Exception:
        log.exception("Scheduled task %r raised an exception", name)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
