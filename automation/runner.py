"""Parallel backtest runner using multiprocessing.

Design
------
- Bars are serialized to Parquet bytes ONCE in the main process.
- A pool initializer deserializes them into each worker's local memory.
- Each worker receives only lightweight job configuration (a plain dict).
- Errors in individual workers are caught; the pipeline continues.
"""
from __future__ import annotations

import io
import multiprocessing
import threading
import traceback
from typing import Any

import pandas as pd

from automation.notifications import Notifier

# ── Module-level globals set per worker process via _pool_init ────────────────
_WORKER_BARS: pd.DataFrame | None = None


def _pool_init(bars_parquet: bytes) -> None:
    """Called once per spawned worker process."""
    global _WORKER_BARS
    _WORKER_BARS = pd.read_parquet(io.BytesIO(bars_parquet))


def _worker_fn(job_dict: dict[str, Any]) -> dict[str, Any]:
    """Execute a single backtest job inside a worker process.

    Must be at module level so multiprocessing can pickle the reference.
    """
    import importlib
    import json

    from jobs.backtest_job import BacktestJob, BacktestParams

    global _WORKER_BARS

    try:
        module = importlib.import_module(job_dict["strategy_module"])
        cls    = getattr(module, job_dict["strategy_class"])
        params = json.loads(job_dict["params_json"]) if isinstance(job_dict["params_json"], str) else job_dict["params_json"]

        bp = BacktestParams(
            bars             = _WORKER_BARS,
            strategy_class   = cls,
            params           = params,
            symbol           = job_dict["symbol"],
            interval         = job_dict["interval"],
            start_date       = job_dict["start_date"],
            end_date         = job_dict["end_date"],
            starting_capital = job_dict["starting_capital"],
            fee_rate         = job_dict["fee_rate"],
            slippage_pct     = job_dict["slippage_pct"],
            stop_loss_pct    = job_dict.get("stop_loss_pct"),
            take_profit_pct  = job_dict.get("take_profit_pct"),
        )

        result = BacktestJob(bp).run()
        if result.success:
            return {"ok": True, "data": result.data, "duration": result.duration_secs,
                    "job_dict": job_dict}
        else:
            return {"ok": False, "error": result.error, "job_dict": job_dict}

    except Exception:
        return {"ok": False, "error": traceback.format_exc(), "job_dict": job_dict}


class ParallelRunner:
    """Run a list of job dicts in parallel using multiprocessing.Pool."""

    def __init__(self, n_workers: int | None = None, verbose: bool = True) -> None:
        self.n_workers = n_workers or max(1, (multiprocessing.cpu_count() or 1))
        self.notify    = Notifier(verbose=verbose)

    def run(
        self,
        bars: pd.DataFrame,
        job_dicts: list[dict[str, Any]],
        cancel_event: "threading.Event | None" = None,
    ) -> list[dict[str, Any]]:
        """Run all jobs, return list of result dicts (same order as input).

        Failed jobs produce ``{"ok": False, "error": "...", "job_dict": ...}``.
        When cancel_event is set while jobs are running, the pool is terminated
        and an empty list is returned — workers already executing a backtest may
        complete their current iteration before the OS delivers SIGTERM, but no
        new work starts and the caller receives no partial results.
        """
        if not job_dicts:
            return []

        # Serialize bars once; each worker deserializes once
        buf = io.BytesIO()
        bars.to_parquet(buf)
        bars_bytes = buf.getvalue()

        n = len(job_dicts)
        workers = min(self.n_workers, n)
        self.notify.info(f"Spawning {workers} worker(s) for {n} job(s) …")

        ctx = multiprocessing.get_context("spawn")
        cancelled = False
        with ctx.Pool(
            processes   = workers,
            initializer = _pool_init,
            initargs    = (bars_bytes,),
        ) as pool:
            async_result = pool.map_async(_worker_fn, job_dicts)
            while True:
                try:
                    results = async_result.get(timeout=0.25)
                    break
                except multiprocessing.TimeoutError:
                    if cancel_event and cancel_event.is_set():
                        pool.terminate()
                        cancelled = True
                        break

        if cancelled:
            self.notify.info("Cancelled — parallel backtests terminated.")
            return []

        ok    = sum(1 for r in results if r.get("ok"))
        fail  = n - ok
        self.notify.info(f"Done: {ok} succeeded, {fail} failed")
        return results
