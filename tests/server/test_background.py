"""Tests for server/background.py — dict_to_config, JobManager, QueueNotifier."""
from __future__ import annotations

import multiprocessing
import queue
import time
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from server.background import JobManager, dict_to_config, _QueueNotifier, _bool


# ── dict_to_config ────────────────────────────────────────────────────────────

class TestDictToConfig:
    def test_defaults(self):
        cfg = dict_to_config({})
        assert cfg.symbols == ["BTCUSDT"]
        assert cfg.intervals == ["1h"]
        assert cfg.starting_capital == 100_000.0
        assert cfg.run_walk_forward is True

    def test_symbols_comma_separated(self):
        cfg = dict_to_config({"symbols": "BTC, ETH, SOL"})
        assert cfg.symbols == ["BTC", "ETH", "SOL"]

    def test_symbols_list(self):
        cfg = dict_to_config({"symbols": ["BTC", "ETH"]})
        assert cfg.symbols == ["BTC", "ETH"]

    def test_intervals_comma_separated(self):
        cfg = dict_to_config({"intervals": "1h,4h"})
        assert cfg.intervals == ["1h", "4h"]

    def test_dates_parsed(self):
        cfg = dict_to_config({"start_date": "2023-01-01", "end_date": "2023-12-31"})
        assert cfg.start_date == date(2023, 1, 1)
        assert cfg.end_date   == date(2023, 12, 31)

    def test_numeric_fields(self):
        cfg = dict_to_config({
            "starting_capital": "50000",
            "fee_rate": "0.002",
            "min_trades": "20",
        })
        assert cfg.starting_capital == 50_000.0
        assert cfg.fee_rate == 0.002
        assert cfg.min_trades == 20

    def test_stop_loss_optional(self):
        cfg = dict_to_config({"stop_loss_pct": ""})
        assert cfg.stop_loss_pct is None

    def test_stop_loss_present(self):
        cfg = dict_to_config({"stop_loss_pct": "0.05"})
        assert cfg.stop_loss_pct == 0.05

    def test_bool_checkboxes(self):
        cfg = dict_to_config({"run_walk_forward": "on", "run_monte_carlo": False})
        assert cfg.run_walk_forward is True
        assert cfg.run_monte_carlo  is False

    def test_fast_mode(self):
        cfg = dict_to_config({"fast_mode": "on"})
        assert cfg.fast_mode is True


class TestBool:
    def test_true_strings(self):
        for v in ("1", "true", "True", "yes", "on", "ON"):
            assert _bool(v) is True

    def test_false_string(self):
        assert _bool("") is False
        assert _bool("0") is False
        assert _bool("false") is False

    def test_passthrough(self):
        assert _bool(True)  is True
        assert _bool(False) is False


# ── _QueueNotifier ────────────────────────────────────────────────────────────

class TestQueueNotifier:
    def _notifier(self):
        q = queue.Queue()
        n = _QueueNotifier(q, verbose=False)
        return n, q

    def test_step_pushes_event(self):
        n, q = self._notifier()
        n.step("4", "Running backtests")
        msg = q.get_nowait()
        assert msg["type"] == "step"
        assert msg["n"] == "4"
        assert msg["pct"] == 60

    def test_ok_pushes_event(self):
        n, q = self._notifier()
        n.ok("5,000 bars loaded")
        msg = q.get_nowait()
        assert msg["type"] == "ok"
        assert "5,000" in msg["message"]

    def test_info_event(self):
        n, q = self._notifier()
        n.info("20 combos")
        assert q.get_nowait()["type"] == "info"

    def test_warn_event(self):
        n, q = self._notifier()
        n.warn("Low bar count")
        assert q.get_nowait()["type"] == "warn"

    def test_error_event(self):
        n, q = self._notifier()
        n.error("Pipeline aborted")
        assert q.get_nowait()["type"] == "error"

    def test_section_event(self):
        n, q = self._notifier()
        n.section("BTCUSDT 1h")
        assert q.get_nowait()["type"] == "section"


# ── JobManager ────────────────────────────────────────────────────────────────

class TestJobManager:
    def _mock_pipeline(self, run_obj):
        """Return a context manager that patches ResearchPipeline."""
        mock_cls = MagicMock()
        mock_inst = MagicMock()
        mock_inst.execute.return_value = run_obj
        mock_cls.return_value = mock_inst
        return patch("server.background.ResearchPipeline", mock_cls)

    def _make_run(self):
        run = MagicMock()
        run.session_id  = "sess-123"
        run.n_tested    = 10
        run.n_passed    = 3
        run.n_rejected  = 7
        run.elapsed_secs = 5.5
        run.report_paths = {}
        return run

    def test_submit_returns_job_id(self):
        mgr = JobManager()
        with self._mock_pipeline(self._make_run()):
            job_id = mgr.submit({"symbols": "BTCUSDT", "fast_mode": "on"})
        assert len(job_id) == 36    # uuid format

    def test_job_appears_in_list(self):
        mgr = JobManager()
        with self._mock_pipeline(self._make_run()):
            job_id = mgr.submit({"fast_mode": "on"})
        assert any(j.job_id == job_id for j in mgr.list_jobs())

    def test_job_completes(self):
        mgr = JobManager()
        with self._mock_pipeline(self._make_run()):
            job_id = mgr.submit({"fast_mode": "on"})
            # Wait for thread to finish
            for _ in range(50):
                info = mgr.get_job(job_id)
                if info and info.status in ("done", "failed"):
                    break
                time.sleep(0.1)
        info = mgr.get_job(job_id)
        assert info is not None
        assert info.status == "done"
        assert info.n_passed == 3

    def test_cancel_pending(self):
        mgr = JobManager()
        # Inject a job manually without thread
        from server.background import JobInfo
        mgr._jobs["fake-id"] = JobInfo(job_id="fake-id", status="running")
        import queue as q_mod
        mgr._queues["fake-id"] = q_mod.Queue()
        import threading
        mgr._cancel["fake-id"] = threading.Event()
        result = mgr.cancel("fake-id")
        assert result is True
        assert mgr._jobs["fake-id"].status == "cancelled"

    def test_cancel_nonexistent(self):
        mgr = JobManager()
        assert mgr.cancel("does-not-exist") is False

    def test_get_queue(self):
        mgr = JobManager()
        with self._mock_pipeline(self._make_run()):
            job_id = mgr.submit({"fast_mode": "on"})
        q = mgr.get_queue(job_id)
        assert q is not None

    def test_restart_creates_new_job(self):
        mgr = JobManager()
        run = self._make_run()
        with self._mock_pipeline(run):
            job_id  = mgr.submit({"fast_mode": "on"})
            # Wait for completion
            for _ in range(50):
                info = mgr.get_job(job_id)
                if info and info.status in ("done", "failed"):
                    break
                time.sleep(0.1)
            new_id = mgr.restart(job_id)
        assert new_id != job_id
        assert new_id is not None


class TestCancellationPropagation:
    """Cancellation event must be wired into ResearchPipeline so the pipeline
    actually stops rather than continuing to exhaustion."""

    def test_cancel_event_set_on_pipeline(self):
        """When a job is cancelled, the cancel_event on the pipeline is set."""
        import threading

        received_event: list = []

        class CapturingPipeline:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cancel_event = None
                self.notify = None

            def execute(self):
                received_event.append(self.cancel_event)
                if self.cancel_event:
                    self.cancel_event.set()  # simulate pipeline checking it
                run = MagicMock()
                run.session_id = "sess-cap"
                run.n_tested = 0
                run.n_passed = 0
                run.n_rejected = 0
                run.elapsed_secs = 0.1
                run.report_paths = {}
                return run

        mgr = JobManager()
        with patch("server.background.ResearchPipeline", CapturingPipeline):
            job_id = mgr.submit({"fast_mode": "on"})
            for _ in range(50):
                info = mgr.get_job(job_id)
                if info and info.status in ("done", "failed", "cancelled"):
                    break
                time.sleep(0.1)

        assert len(received_event) >= 1
        assert received_event[0] is not None, (
            "cancel_event was not wired into pipeline — pipeline.cancel_event must be set"
        )
        assert isinstance(received_event[0], threading.Event), (
            "pipeline.cancel_event must be a threading.Event"
        )

    def test_cancel_event_is_a_real_threading_event(self):
        """The cancel_event wired into the pipeline must be a real threading.Event
        that becomes set when the job is cancelled."""
        import threading

        cancel_event_observed: list = []
        done_barrier = threading.Barrier(2, timeout=5)

        class InspectingPipeline:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cancel_event = None
                self.notify = None

            def execute(self):
                # Capture the event reference; it should be a real threading.Event
                cancel_event_observed.append(self.cancel_event)
                # Signal the test thread that we have captured it
                done_barrier.wait()
                # Now block until the event is actually set (or timeout)
                if self.cancel_event:
                    self.cancel_event.wait(timeout=3.0)
                run = MagicMock()
                run.session_id = "sess-insp"
                run.n_tested = 0
                run.n_passed = 0
                run.n_rejected = 0
                run.elapsed_secs = 0.1
                run.report_paths = {}
                return run

        mgr = JobManager()
        with patch("server.background.ResearchPipeline", InspectingPipeline):
            job_id = mgr.submit({"fast_mode": "on"})
            done_barrier.wait()  # pipeline has captured cancel_event

            # At this point we know the pipeline has the event reference
            assert cancel_event_observed, "Pipeline.execute() was never called"
            ev = cancel_event_observed[0]
            assert ev is not None, "cancel_event was None — wiring is broken"
            assert isinstance(ev, threading.Event), (
                f"cancel_event must be threading.Event, got {type(ev)}"
            )
            assert not ev.is_set(), "cancel_event is already set before cancel()"

            # Now cancel: the event must become set
            mgr.cancel(job_id)
            assert ev.is_set(), (
                "cancel_event was not set after mgr.cancel() — "
                "cancellation does not propagate to the pipeline"
            )


class TestCancellationStatusRace:
    """_finish() must not overwrite 'cancelled' status set by cancel()."""

    def _make_blocking_pipeline(self, pipeline_started, allow_return,
                                return_n_passed=3):
        """Pipeline that signals when started, then blocks until told to return."""
        class BlockingPipeline:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cancel_event = None
                self.notify = None

            def execute(self):
                pipeline_started.set()
                allow_return.wait(timeout=5.0)
                run = MagicMock()
                run.session_id    = "sess-race"
                run.n_tested      = 10
                run.n_passed      = return_n_passed
                run.n_rejected    = 10 - return_n_passed
                run.elapsed_secs  = 0.5
                run.report_paths  = {}
                run.n_data_failures = 0
                return run
        return BlockingPipeline

    def test_finish_does_not_overwrite_cancelled_with_done(self):
        """cancel() sets 'cancelled'; pipeline returning after that must not flip to 'done'."""
        import threading

        pipeline_started = threading.Event()
        allow_return     = threading.Event()
        PipelineCls      = self._make_blocking_pipeline(pipeline_started, allow_return,
                                                        return_n_passed=3)

        mgr = JobManager()
        with patch("server.background.ResearchPipeline", PipelineCls):
            job_id = mgr.submit({"fast_mode": "on"})
            assert pipeline_started.wait(timeout=5.0), "Pipeline never started"

            # Cancel while pipeline is still blocked in execute()
            assert mgr.cancel(job_id) is True
            assert mgr.get_job(job_id).status == "cancelled"

            # Let pipeline's execute() return (simulates step 4 finishing after cancel)
            allow_return.set()
            # Give background thread time to call _finish()
            time.sleep(0.4)

        info = mgr.get_job(job_id)
        assert info is not None
        assert info.status == "cancelled", (
            f"Expected 'cancelled', got '{info.status}' — "
            "_finish('done') must not overwrite cancellation"
        )
        # Partial results from the completed pipeline must not be exposed
        assert info.n_passed == 0, (
            "Cancelled job must not populate n_passed from pipeline results"
        )

    def test_finish_does_not_overwrite_cancelled_with_failed(self):
        """cancel(); pipeline raises → final status stays 'cancelled', not 'failed'."""
        import threading

        pipeline_started = threading.Event()
        allow_raise      = threading.Event()

        class RaisingPipeline:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cancel_event = None
                self.notify = None

            def execute(self):
                pipeline_started.set()
                allow_raise.wait(timeout=5.0)
                raise RuntimeError("Pipeline crashed after cancel was requested")

        mgr = JobManager()
        with patch("server.background.ResearchPipeline", RaisingPipeline):
            job_id = mgr.submit({"fast_mode": "on"})
            assert pipeline_started.wait(timeout=5.0), "Pipeline never started"

            assert mgr.cancel(job_id) is True
            assert mgr.get_job(job_id).status == "cancelled"

            allow_raise.set()
            time.sleep(0.4)

        info = mgr.get_job(job_id)
        assert info is not None
        assert info.status == "cancelled", (
            f"Expected 'cancelled', got '{info.status}' — "
            "_finish('failed') must not overwrite cancellation"
        )


class TestStep4Cancellation:
    """Cancellation while step 4 is running: pool terminates, job stays cancelled."""

    def test_cancel_during_step4_job_stays_cancelled(self):
        """Cancel while execute() is blocked (simulating step 4) → status stays 'cancelled'."""
        import threading

        step4_started = threading.Event()
        allow_return  = threading.Event()

        class Step4Pipeline:
            """Simulates a pipeline blocked in the parallel backtest phase."""
            def __init__(self, cfg):
                self.cfg = cfg
                self.cancel_event = None
                self.notify = None

            def execute(self):
                step4_started.set()
                # Block until test releases — represents pool.map_async() polling
                allow_return.wait(timeout=5.0)
                run = MagicMock()
                run.session_id     = "sess-s4"
                run.n_tested       = 8
                run.n_passed       = 4
                run.n_rejected     = 4
                run.elapsed_secs   = 2.0
                run.report_paths   = {}
                run.n_data_failures = 0
                return run

        mgr = JobManager()
        with patch("server.background.ResearchPipeline", Step4Pipeline):
            job_id = mgr.submit({"fast_mode": "on"})
            assert step4_started.wait(timeout=5.0), "Pipeline never reached step 4"

            mgr.cancel(job_id)
            assert mgr.get_job(job_id).status == "cancelled"

            # Step 4 "finishes" — pool.map returns results after termination delay
            allow_return.set()
            time.sleep(0.4)

        info = mgr.get_job(job_id)
        assert info is not None
        assert info.status == "cancelled", (
            f"Expected 'cancelled', got '{info.status}' — "
            "step 4 completing after cancel must not change job status to 'done'"
        )
        assert info.n_passed == 0, (
            "Cancelled job must not show step-4 results as n_passed"
        )

    def test_parallel_runner_cancel_event_terminates_pool(self):
        """ParallelRunner.run() returns [] and terminates pool when cancel_event fires."""
        import threading
        from automation.runner import ParallelRunner
        import pandas as pd

        cancel = threading.Event()
        runner = ParallelRunner(n_workers=2, verbose=False)

        mock_pool    = MagicMock()
        mock_async   = MagicMock()
        call_count   = [0]

        def fake_get(timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                cancel.set()           # simulate cancel arriving during first poll
                raise multiprocessing.TimeoutError()
            # Should not reach here
            return [{"ok": True}]

        mock_async.get    = fake_get
        mock_pool.map_async.return_value = mock_async
        mock_pool.__enter__ = lambda s: s
        mock_pool.__exit__  = MagicMock(return_value=False)

        import multiprocessing as mp
        mock_ctx = MagicMock()
        mock_ctx.Pool.return_value = mock_pool

        job_dicts = [{"strategy_class": f"X{i}"} for i in range(5)]

        with patch("automation.runner.multiprocessing.get_context",
                   return_value=mock_ctx):
            results = runner.run(pd.DataFrame({"c": [1.0]}), job_dicts,
                                 cancel_event=cancel)

        assert results == [], (
            f"Expected empty list when cancelled, got {results}"
        )
        assert mock_pool.terminate.called, (
            "pool.terminate() must be called when cancel_event fires"
        )
