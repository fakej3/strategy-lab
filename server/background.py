"""Background job execution — runs ResearchPipeline in daemon threads.

Design
------
* JobManager is a singleton used by the API layer.
* Each submitted job gets a uuid, a thread-safe Queue for progress events,
  and a cancellation Event.
* ResearchPipeline.notify is replaced with _QueueNotifier so all terminal
  output is also pushed as structured events to the per-job Queue.
* WebSocket handlers drain that Queue in their async loop.
* Completed jobs stay in memory for the session; results are also persisted
  to SQLite via the pipeline's own ResearchStorage.
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from automation.notifications import Notifier
from automation.pipeline import PipelineConfig, ResearchPipeline
from server.notify import notification_manager, JOB_DONE, JOB_FAILED, JOB_START


# ── Queue-aware Notifier ──────────────────────────────────────────────────────

_STEP_PCT: dict[str, int] = {
    "1": 10, "2": 18, "3": 18, "4": 60,
    "5": 72, "6": 84, "7": 90, "8": 97,
}


class _QueueNotifier(Notifier):
    """Notifier subclass that also pushes structured events to a queue."""

    def __init__(self, q: queue.Queue, verbose: bool = False,
                 log_path: Path | None = None) -> None:
        super().__init__(verbose=verbose, log_path=log_path)
        self._q = q

    def _push(self, msg: dict) -> None:
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            pass

    def step(self, n: str, label: str) -> None:
        super().step(n, label)
        pct = _STEP_PCT.get(str(n), 0)
        self._push({"type": "step", "n": n, "label": label, "pct": pct})

    def section(self, label: str) -> None:
        super().section(label)
        self._push({"type": "section", "label": label})

    def ok(self, detail: str = "") -> None:
        super().ok(detail)
        self._push({"type": "ok", "message": detail})

    def info(self, detail: str) -> None:
        super().info(detail)
        self._push({"type": "info", "message": detail})

    def warn(self, detail: str) -> None:
        super().warn(detail)
        self._push({"type": "warn", "message": detail})

    def error(self, detail: str) -> None:
        super().error(detail)
        self._push({"type": "error", "message": detail})


# ── Job record ────────────────────────────────────────────────────────────────

@dataclass
class JobInfo:
    job_id:       str
    status:       str  = "pending"   # pending|running|done|failed|cancelled
    config:       dict = field(default_factory=dict)
    session_id:   str  = ""
    started_at:   str  = ""
    finished_at:  str  = ""
    error:        str  = ""
    n_tested:     int  = 0
    n_passed:     int  = 0
    n_rejected:   int  = 0
    elapsed_secs: float = 0.0
    progress_pct: int  = 0
    current_stage:  str = ""
    current_detail: str = ""
    report_paths: dict = field(default_factory=dict)


# ── Job manager ───────────────────────────────────────────────────────────────

class JobManager:
    """Thread-safe in-memory job registry with background execution."""

    def __init__(self, db_path: str = "research.db") -> None:
        self._jobs:   dict[str, JobInfo]        = {}
        self._queues: dict[str, queue.Queue]    = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock    = threading.Lock()
        self._db_path = db_path

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, config_dict: dict) -> str:
        """Submit a research job. Returns job_id immediately."""
        job_id = str(uuid.uuid4())
        q: queue.Queue = queue.Queue(maxsize=50_000)
        cancel_ev      = threading.Event()

        info = JobInfo(job_id=job_id, status="pending", config=config_dict)
        with self._lock:
            self._jobs[job_id]   = info
            self._queues[job_id] = q
            self._cancel[job_id] = cancel_ev

        t = threading.Thread(
            target=self._run,
            args=(job_id, config_dict, q, cancel_ev),
            daemon=True,
            name=f"job-{job_id[:8]}",
        )
        t.start()
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. The thread may still be running briefly."""
        ev = self._cancel.get(job_id)
        if ev:
            ev.set()
        with self._lock:
            info = self._jobs.get(job_id)
            if info and info.status in ("pending", "running"):
                info.status = "cancelled"
                info.finished_at = datetime.now(timezone.utc).isoformat()
                q = self._queues.get(job_id)
                if q:
                    try:
                        q.put_nowait({"type": "done", "success": False,
                                      "cancelled": True})
                    except queue.Full:
                        pass
                return True
        return False

    def restart(self, job_id: str) -> str | None:
        """Clone job config and submit a new job. Returns new job_id."""
        with self._lock:
            info = self._jobs.get(job_id)
        if not info:
            return None
        return self.submit(info.config)

    def get_job(self, job_id: str) -> JobInfo | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobInfo]:
        with self._lock:
            return list(reversed(list(self._jobs.values())))

    def get_queue(self, job_id: str) -> queue.Queue | None:
        return self._queues.get(job_id)

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _run(
        self, job_id: str, config_dict: dict,
        q: queue.Queue, cancel: threading.Event,
    ) -> None:
        self._set_status(job_id, "running",
                         started_at=datetime.now(timezone.utc).isoformat())
        try:
            if cancel.is_set():
                self._finish(job_id, "cancelled", {})
                return

            cfg      = dict_to_config(config_dict)
            pipeline = ResearchPipeline(cfg)
            pipeline.notify = _QueueNotifier(
                q,
                verbose  = False,            # suppress terminal noise
                log_path = Path(cfg.log_path) if cfg.log_path else None,
            )

            notification_manager.notify(
                JOB_START, "Research Started",
                f"Job {job_id[:8]} started",
                job_id=job_id,
            )

            run = pipeline.execute()

            result = {
                "session_id":   run.session_id,
                "n_tested":     run.n_tested,
                "n_passed":     run.n_passed,
                "n_rejected":   run.n_rejected,
                "elapsed_secs": run.elapsed_secs,
                "report_paths": {k: str(v) for k, v in run.report_paths.items()},
            }

            # Data integrity blocked all symbol/interval pairs — this is a
            # failure, not a successful "zero-result" run.
            data_blocked = (
                run.n_tested == 0
                and getattr(run, "n_data_failures", 0) > 0
            )
            if data_blocked:
                err_msg = (
                    run.errors[-1] if run.errors
                    else "Data integrity failure blocked all symbol/interval pairs"
                )
                self._finish(job_id, "failed", result, error=err_msg)
                _put(q, {"type": "done", "success": False,
                         "error": err_msg, **result})
                notification_manager.notify(
                    JOB_FAILED,
                    "Research Failed",
                    f"Job {job_id[:8]} failed: data integrity failure — "
                    f"no strategies tested",
                    job_id=job_id,
                )
            else:
                self._finish(job_id, "done", result)
                _put(q, {"type": "done", "success": True, "pct": 100, **result})
                notification_manager.notify(
                    JOB_DONE,
                    "Research Complete",
                    f"Session {run.session_id[:8]} — "
                    f"{run.n_passed}/{run.n_tested} passed",
                    job_id=job_id,
                    session_id=run.session_id,
                )
        except Exception:
            err = traceback.format_exc()
            self._finish(job_id, "failed", {}, error=err)
            _put(q, {"type": "done", "success": False, "error": err[-600:]})
            notification_manager.notify(
                JOB_FAILED, "Research Failed",
                f"Job {job_id[:8]} failed: {err.splitlines()[-1]}",
                job_id=job_id,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _set_status(self, job_id: str, status: str, **fields: Any) -> None:
        with self._lock:
            info = self._jobs.get(job_id)
            if info:
                info.status = status
                for k, v in fields.items():
                    setattr(info, k, v)

    def _finish(self, job_id: str, status: str,
                result: dict, error: str = "") -> None:
        with self._lock:
            info = self._jobs.get(job_id)
            if info:
                info.status      = status
                info.finished_at = datetime.now(timezone.utc).isoformat()
                info.error       = error
                for k in ("session_id", "n_tested", "n_passed",
                          "n_rejected", "elapsed_secs", "report_paths"):
                    if k in result:
                        setattr(info, k, result[k])


def _put(q: queue.Queue, msg: dict) -> None:
    try:
        q.put_nowait(msg)
    except queue.Full:
        pass


# ── Config conversion ─────────────────────────────────────────────────────────

def dict_to_config(d: dict) -> PipelineConfig:
    """Convert a flat string dict (from form or JSON) to PipelineConfig."""
    cfg = PipelineConfig()

    # Market data
    raw_sym = d.get("symbols", "BTCUSDT")
    cfg.symbols = (
        [s.strip() for s in raw_sym.split(",") if s.strip()]
        if isinstance(raw_sym, str)
        else list(raw_sym)
    )
    raw_iv = d.get("intervals", "1h")
    cfg.intervals = (
        [i.strip() for i in raw_iv.split(",") if i.strip()]
        if isinstance(raw_iv, str)
        else list(raw_iv)
    )

    start = d.get("start_date", "2024-01-01")
    end   = d.get("end_date",   str(date.today()))
    cfg.start_date = date.fromisoformat(start) if isinstance(start, str) else start
    cfg.end_date   = date.fromisoformat(end)   if isinstance(end,   str) else end

    # Portfolio
    cfg.starting_capital = float(d.get("starting_capital", 100_000))
    cfg.fee_rate         = float(d.get("fee_rate",         0.001))
    cfg.slippage_pct     = float(d.get("slippage_pct",     0.0005))

    sl = d.get("stop_loss_pct",   "")
    tp = d.get("take_profit_pct", "")
    cfg.stop_loss_pct   = float(sl) if sl else None
    cfg.take_profit_pct = float(tp) if tp else None

    # Gate thresholds
    cfg.min_trades             = int(d.get("min_trades", 10))
    cfg.max_drawdown_threshold = float(d.get("max_drawdown_threshold", 0.35))

    # Execution
    cfg.n_workers = int(d.get("n_workers", max(1, os.cpu_count() or 1)))

    # Walk-forward
    cfg.run_walk_forward = _bool(d.get("run_walk_forward", True))
    cfg.wf_train_bars    = int(d.get("wf_train_bars", 1008))
    cfg.wf_test_bars     = int(d.get("wf_test_bars",  336))

    # Monte Carlo
    cfg.run_monte_carlo = _bool(d.get("run_monte_carlo", True))
    cfg.mc_simulations  = int(d.get("mc_simulations",  500))

    # Robustness
    cfg.run_robustness   = _bool(d.get("run_robustness",   True))
    cfg.robustness_steps = int(d.get("robustness_steps", 1))

    # Storage
    cfg.db_path      = d.get("db_path",      "research.db")
    cfg.reports_dir  = d.get("reports_dir",  "reports")
    cfg.log_path     = d.get("log_path",     "logs/research.log")

    # Behaviour
    cfg.verbose   = _bool(d.get("verbose",   False))
    cfg.fast_mode = _bool(d.get("fast_mode", False))

    return cfg


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


# ── Singleton ─────────────────────────────────────────────────────────────────

job_manager = JobManager()
