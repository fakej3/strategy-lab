"""Regression tests for clean shutdown of the Scheduler and bot components."""
from __future__ import annotations

import threading
import time

import pytest

from bot.scheduler import Scheduler
from bot.storage import BotStorage


class TestSchedulerShutdown:
    def test_stop_joins_thread_within_timeout(self):
        """stop() must join the background thread within its 5s timeout."""
        sched = Scheduler()
        sched.every(0.05, lambda: None, name="fast")
        sched.start()
        assert sched._thread is not None and sched._thread.is_alive()
        sched.stop()
        assert not sched._thread.is_alive()

    def test_stop_before_start_is_safe(self):
        """Calling stop before start must not raise."""
        sched = Scheduler()
        sched.stop()  # no thread to join — must be a no-op

    def test_double_stop_is_idempotent(self):
        sched = Scheduler()
        sched.every(1.0, lambda: None, name="noop")
        sched.start()
        sched.stop()
        sched.stop()  # second stop must not raise

    def test_double_start_is_idempotent(self):
        sched = Scheduler()
        sched.every(1.0, lambda: None, name="noop")
        sched.start()
        thread_id = id(sched._thread)
        sched.start()  # second start must be a no-op
        assert id(sched._thread) == thread_id
        sched.stop()

    def test_task_exception_does_not_kill_scheduler(self):
        """A task that raises must not terminate the scheduler thread."""
        sched = Scheduler()
        calls: list[int] = []

        def bad_task():
            calls.append(1)
            raise RuntimeError("boom")

        sched.every(0.02, bad_task, name="bad")
        sched.start()
        time.sleep(0.15)
        sched.stop()

        assert len(calls) > 0, "bad_task was never called"
        assert not sched._thread.is_alive()

    def test_periodic_task_fires_at_correct_rate(self):
        sched = Scheduler()
        calls: list[float] = []
        sched.every(0.05, lambda: calls.append(time.monotonic()), name="ticker")
        sched.start()
        time.sleep(0.35)
        sched.stop()
        # Should have fired roughly 5-7 times in 350ms at 50ms interval
        assert 4 <= len(calls) <= 9

    def test_stop_event_terminates_loop(self):
        """After stop(), the scheduler loop must exit and not accept new firings."""
        sched = Scheduler()
        counter: list[int] = []
        sched.every(0.01, lambda: counter.append(1), name="fast")
        sched.start()
        time.sleep(0.05)
        sched.stop()
        count_at_stop = len(counter)
        time.sleep(0.1)  # wait to see if more firings happen post-stop
        assert len(counter) == count_at_stop


class TestStorageCloseOnShutdown:
    def test_close_then_reopen_works(self, tmp_path):
        """BotStorage can be closed and reconnected cleanly."""
        s = BotStorage(tmp_path / "test.db")
        s.connect()
        s.save_heartbeat(uptime_s=1.0, active_symbols=1, candles_recv=10)
        s.close()
        assert s._conn is None

        s.connect()
        hb = s.get_last_heartbeat()
        assert hb is not None
        assert hb["uptime_s"] == pytest.approx(1.0)
        s.close()

    def test_context_manager_closes_on_exit(self, tmp_path):
        with BotStorage(tmp_path / "ctx.db") as s:
            s.save_balance_snapshot(equity=25.0, cash=25.0)
        assert s._conn is None

    def test_double_close_is_safe(self, tmp_path):
        s = BotStorage(tmp_path / "dc.db")
        s.connect()
        s.close()
        s.close()  # must not raise
