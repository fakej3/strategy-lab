"""Tests for server/background.py — dict_to_config, JobManager, QueueNotifier."""
from __future__ import annotations

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
