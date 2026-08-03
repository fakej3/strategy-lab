"""Fully automated research pipeline — orchestrates all 8 steps.

Pipeline steps
--------------
1. Update market data (smart incremental fetch via data.get_bars)
2. Discover strategy classes (inspect strategies/ package)
3. Generate parameter combinations (Cartesian product)
4. Run parallel backtests (multiprocessing)
5. Augment: walk-forward + Monte Carlo on survivors
6. Filter / reject (quality gate + custom thresholds)
7. Persist to SQLite (research_db)
8. Generate HTML / Markdown / JSON reports
"""
from __future__ import annotations

import importlib
import inspect
import io
import json
import math
import multiprocessing
import os
import pkgutil
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Type

import pandas as pd

import strategies as strategies_pkg
from automation.notifications import Notifier
from data.api import get_bars
from engine.strategy import StrategyBase
from jobs.backtest_job import BacktestJob, BacktestParams
from jobs.walkforward_job import WalkForwardJob, WalkForwardParams
from research_db.models import SessionRecord, StrategyResult
from research_db.storage import ResearchStorage
from research.validation import validate_bars_extended


# ── Default parameter spaces for known strategies ─────────────────────────────
# To add a new strategy: add it to strategies/ and add its param space here.

STRATEGY_PARAMETER_SPACES: dict[str, dict[str, list]] = {
    "EMACrossover": {
        "fast": [5, 10, 15, 20],
        "slow": [30, 40, 50, 100, 200],
    },
}


@dataclass
class PipelineConfig:
    """All settings controlling an automated research run."""

    # Market data
    symbols: list[str]   = field(default_factory=lambda: ["BTCUSDT"])
    intervals: list[str] = field(default_factory=lambda: ["1h"])
    start_date: date     = field(default_factory=lambda: date(2024, 1, 1))
    end_date: date       = field(default_factory=lambda: date.today())

    # Portfolio
    starting_capital: float       = 100_000.0
    fee_rate: float               = 0.001
    slippage_pct: float           = 0.0005
    stop_loss_pct: float | None   = None
    take_profit_pct: float | None = None

    # Rejection thresholds (beyond quality gate)
    min_trades: int            = 10
    max_drawdown_threshold: float = 0.35   # reject if > 35% DD

    # Execution
    n_workers: int = field(default_factory=lambda: max(1, (os.cpu_count() or 1)))

    # Walk-forward
    run_walk_forward: bool = True
    wf_train_bars: int     = 1008   # ~6 weeks of 1h bars
    wf_test_bars: int      = 336    # ~2 weeks

    # Monte Carlo
    run_monte_carlo: bool  = True
    mc_simulations: int    = 500

    # Storage
    db_path: str      = "research.db"
    reports_dir: str  = "reports"

    # Behaviour
    verbose: bool     = True
    log_path: str     = "logs/research.log"
    fast_mode: bool   = False   # skip WF + MC


@dataclass
class PipelineRun:
    """Complete output of one pipeline execution."""

    session_id: str
    config: PipelineConfig
    started_at: datetime
    finished_at: datetime | None = None
    n_tested: int                = 0
    n_passed: int                = 0
    n_rejected: int              = 0
    n_errors: int                = 0
    strategy_results: list[StrategyResult] = field(default_factory=list)
    report_paths: dict[str, Path]          = field(default_factory=dict)
    elapsed_secs: float                    = 0.0
    errors: list[str]                      = field(default_factory=list)


class ResearchPipeline:
    """Autonomous research pipeline.

    Usage
    -----
    >>> cfg = PipelineConfig(symbols=["BTCUSDT"], intervals=["1h"])
    >>> run = ResearchPipeline(cfg).execute()
    >>> print(f"{run.n_passed} strategies passed quality gate")
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.cfg     = config or PipelineConfig()
        self.notify  = Notifier(
            verbose  = self.cfg.verbose,
            log_path = Path(self.cfg.log_path),
        )
        self.storage = ResearchStorage(self.cfg.db_path)

    def execute(self) -> PipelineRun:
        cfg        = self.cfg
        session_id = _new_session_id()
        started_at = datetime.now(timezone.utc)
        run        = PipelineRun(
            session_id = session_id,
            config     = cfg,
            started_at = started_at,
        )

        session = SessionRecord(
            session_id = session_id,
            started_at = started_at.isoformat(),
            status     = "running",
            symbols    = json.dumps(cfg.symbols),
            intervals  = json.dumps(cfg.intervals),
            start_date = str(cfg.start_date),
            end_date   = str(cfg.end_date),
        )
        self.storage.save_session(session)

        self.notify.header(
            f"EDGELAB AUTOMATED RESEARCH  ·  session {session_id[:8]}"
        )
        t0 = time.perf_counter()

        try:
            self._run_all(run)
        except Exception:
            run.errors.append(traceback.format_exc())
            self.notify.error("Pipeline aborted: " + traceback.format_exc()[-200:])
            self.storage.update_session(session_id, status="failed")
        else:
            run.elapsed_secs = time.perf_counter() - t0
            run.finished_at  = datetime.now(timezone.utc)
            self.storage.update_session(
                session_id,
                status           = "complete",
                finished_at      = run.finished_at.isoformat(),
                n_strategies_run = run.n_tested,
                n_passed         = run.n_passed,
                n_rejected       = run.n_rejected,
                n_errors         = run.n_errors,
                elapsed_secs     = run.elapsed_secs,
            )
            self._print_summary(run)

        return run

    # ── Step orchestration ────────────────────────────────────────────────────

    def _run_all(self, run: PipelineRun) -> None:
        cfg = self.cfg
        t0  = time.perf_counter()

        for symbol in cfg.symbols:
            for interval in cfg.intervals:
                self.notify.section(f"Symbol: {symbol}  Interval: {interval}")

                # STEP 1 — fetch data
                t_step = time.perf_counter()
                bars   = self._step1_fetch(symbol, interval)
                self.storage.log_event(
                    "step1_fetch", "duration_secs",
                    session_id  = run.session_id,
                    value_float = time.perf_counter() - t_step,
                    value_text  = f"{symbol}/{interval}",
                )
                if bars is None or bars.empty:
                    continue

                self.storage.log_event(
                    "step1_fetch", "bars_count",
                    session_id  = run.session_id,
                    value_float = float(len(bars)),
                    value_text  = f"{symbol}/{interval}",
                )

                # STEP 2 & 3 — discover strategies + generate combos
                combos = self._step2_3_combos()
                if not combos:
                    self.notify.warn("No strategies discovered — nothing to run.")
                    continue

                total_combos = sum(len(c["combos"]) for c in combos)
                self.notify.info(
                    f"Discovered {len(combos)} strategy class(es), "
                    f"{total_combos} parameter combination(s)"
                )
                self.storage.log_event(
                    "step2_3_discovery", "combos_count",
                    session_id  = run.session_id,
                    value_float = float(total_combos),
                )

                # STEP 4 — parallel backtests
                t_step      = time.perf_counter()
                raw_results = self._step4_run_parallel(bars, combos, symbol, interval)
                self.storage.log_event(
                    "step4_backtests", "duration_secs",
                    session_id  = run.session_id,
                    value_float = time.perf_counter() - t_step,
                    value_text  = f"{symbol}/{interval}",
                )
                run.n_tested += len(raw_results)

                # STEP 5 — walk-forward + Monte Carlo
                # STEP 6 — filter
                # STEP 7 — persist
                for raw in raw_results:
                    if not raw.get("ok"):
                        run.n_errors += 1
                        run.errors.append(raw.get("error", "unknown"))
                        self.notify.warn(
                            f"  Job failed: {raw.get('error', '')[:120]}"
                        )
                        continue

                    data       = raw["data"]
                    bt_result  = self._step5_augment(bars, data, combos)
                    sr         = self._step6_filter_and_build(
                        bt_result, symbol, interval, run.session_id
                    )

                    if sr is not None:
                        run.strategy_results.append(sr)
                        self.storage.save_strategy_result(sr)
                        if sr.gate_decision != "REJECT":
                            run.n_passed += 1
                        else:
                            run.n_rejected += 1
                    else:
                        run.n_rejected += 1

                # STEP 8 — generate reports
                # Set elapsed before passing to reports so timing is accurate
                run.elapsed_secs = time.perf_counter() - t0
                self.notify.step("8", "Generating reports")
                try:
                    report_paths = self._step8_reports(run, symbol, interval)
                    run.report_paths.update(report_paths)
                    self.notify.ok(f"{len(report_paths)} report(s) saved")
                except Exception:
                    self.notify.warn("Report generation failed: "
                                     + traceback.format_exc()[-120:])

    # ── Step 1: fetch market data ─────────────────────────────────────────────

    def _step1_fetch(self, symbol: str, interval: str) -> pd.DataFrame | None:
        self.notify.step("1", f"Updating market data  {symbol} {interval}")
        try:
            bars = get_bars(
                symbol    = symbol,
                interval  = interval,
                from_date = self.cfg.start_date,
                to_date   = self.cfg.end_date,
            )
        except Exception as exc:
            self.notify.error(str(exc))
            return None

        if bars.empty:
            self.notify.warn("No data returned — skipping this symbol/interval.")
            return None

        try:
            warnings = validate_bars_extended(bars)
        except ValueError as exc:
            self.notify.error(f"Data validation failed: {exc}")
            return None

        if warnings:
            for w in warnings:
                self.notify.warn(f"Data: {w}")

        self.notify.ok(
            f"{len(bars):,} bars  "
            f"({bars.index[0].strftime('%Y-%m-%d')} → "
            f"{bars.index[-1].strftime('%Y-%m-%d')})"
        )
        return bars

    # ── Step 2 & 3: strategy discovery + parameter combos ────────────────────

    def _step2_3_combos(self) -> list[dict]:
        self.notify.step("2/3", "Discovering strategies + generating combos")
        discovered = _discover_strategies()
        combos     = []
        for cls in discovered:
            space = STRATEGY_PARAMETER_SPACES.get(cls.__name__, {})
            if space:
                all_c = _cartesian(space)
            else:
                # Default: try instantiating with no args
                try:
                    cls()
                    all_c = [{}]
                except Exception:
                    self.notify.warn(
                        f"  {cls.__name__}: no param space, cannot instantiate — skipping"
                    )
                    continue

            # Filter invalid combos (e.g. EMACrossover fast >= slow)
            valid = []
            for c in all_c:
                try:
                    cls(**c)
                    valid.append(c)
                except Exception:
                    pass

            if valid:
                combos.append({
                    "cls"    : cls,
                    "module" : cls.__module__,
                    "combos" : valid,
                })
                self.notify.info(
                    f"  {cls.__name__}: {len(valid)} valid combo(s)"
                )
        return combos

    # ── Step 4: parallel backtests ────────────────────────────────────────────

    def _step4_run_parallel(
        self,
        bars: pd.DataFrame,
        combos: list[dict],
        symbol: str,
        interval: str,
    ) -> list[dict]:
        self.notify.step("4", "Running parallel backtests")

        job_dicts = []
        for entry in combos:
            cls = entry["cls"]
            for params in entry["combos"]:
                job_dicts.append({
                    "strategy_module": cls.__module__,
                    "strategy_class" : cls.__name__,
                    "params_json"    : json.dumps(params),
                    "symbol"         : symbol,
                    "interval"       : interval,
                    "start_date"     : self.cfg.start_date,
                    "end_date"       : self.cfg.end_date,
                    "starting_capital": self.cfg.starting_capital,
                    "fee_rate"       : self.cfg.fee_rate,
                    "slippage_pct"   : self.cfg.slippage_pct,
                    "stop_loss_pct"  : self.cfg.stop_loss_pct,
                    "take_profit_pct": self.cfg.take_profit_pct,
                })

        n = len(job_dicts)
        self.notify.info(f"Submitting {n} job(s) to {self.cfg.n_workers} worker(s) …")

        # Use in-process sequential execution to avoid spawn overhead on small runs,
        # parallel for larger batches.
        if n == 1 or self.cfg.n_workers == 1 or n < 4:
            results = [_run_job_inprocess(j, bars) for j in job_dicts]
        else:
            from automation.runner import ParallelRunner
            runner  = ParallelRunner(
                n_workers = self.cfg.n_workers,
                verbose   = self.cfg.verbose,
            )
            results = runner.run(bars, job_dicts)

        ok = sum(1 for r in results if r.get("ok"))
        self.notify.ok(f"{ok}/{n} backtests succeeded")
        return results

    # ── Step 5: walk-forward + Monte Carlo augmentation ───────────────────────

    def _step5_augment(
        self,
        bars: pd.DataFrame,
        data: dict,
        combos: list[dict],
    ) -> dict:
        """Add walk-forward return and MC stats to a backtest result dict."""
        cfg = self.cfg

        if cfg.fast_mode or (not cfg.run_walk_forward and not cfg.run_monte_carlo):
            return data

        # Find strategy class
        cls = None
        for entry in combos:
            if entry["cls"].__name__ == data.get("strategy_class"):
                cls = entry["cls"]
                break

        if cls is None:
            return data

        params = json.loads(data["params"]) if isinstance(data["params"], str) else data["params"]

        # Walk-forward
        if cfg.run_walk_forward and not cfg.fast_mode:
            try:
                wfp = WalkForwardParams(
                    bars             = bars,
                    strategy_class   = cls,
                    params           = params,
                    starting_capital = cfg.starting_capital,
                    fee_rate         = cfg.fee_rate,
                    slippage_pct     = cfg.slippage_pct,
                    stop_loss_pct    = cfg.stop_loss_pct,
                    take_profit_pct  = cfg.take_profit_pct,
                    train_bars       = cfg.wf_train_bars,
                    test_bars        = cfg.wf_test_bars,
                )
                wf_result = WalkForwardJob(wfp).run()
                if wf_result.success and wf_result.data:
                    data["walk_forward_return"] = wf_result.data.get("walk_forward_return")
            except Exception:
                pass  # walk-forward failure never stops the pipeline

        # Monte Carlo — use trade_pnls from the backtest result (no second run needed).
        # BacktestJob now includes trade_pnls in its return dict, so we avoid
        # re-running the entire backtest just to obtain trade PnL values.
        if cfg.run_monte_carlo and not cfg.fast_mode:
            try:
                trade_pnls = data.get("trade_pnls", [])
                if trade_pnls:
                    from jobs.montecarlo_job import MonteCarloJob, MonteCarloParams
                    mc_job = MonteCarloJob(MonteCarloParams(
                        pnl_sequence     = trade_pnls,
                        starting_capital = cfg.starting_capital,
                        n_simulations    = cfg.mc_simulations,
                    ))
                    mc_result = mc_job.run()
                    if mc_result.success and mc_result.data:
                        mc = mc_result.data
                        data["mc_median_return"] = mc.get("median_return")
                        data["mc_pct5_return"]   = mc.get("pct5_return")
                        data["mc_pct95_return"]  = mc.get("pct95_return")
                        data["mc_prob_positive"] = mc.get("prob_positive")
            except Exception:
                pass

        return data

    # ── Step 6: filter + build StrategyResult ─────────────────────────────────

    def _step6_filter_and_build(
        self,
        data: dict,
        symbol: str,
        interval: str,
        session_id: str,
    ) -> StrategyResult | None:
        cfg = self.cfg
        decision = data.get("gate_decision", "REJECT")

        # Hard rejection criteria beyond quality gate
        if data.get("total_trades", 0) < cfg.min_trades and decision != "REJECT":
            decision = "REJECT"
        if data.get("max_drawdown_pct", 0.0) > cfg.max_drawdown_threshold:
            decision = "REJECT"

        return StrategyResult(
            session_id          = session_id,
            strategy_class      = data.get("strategy_class", ""),
            strategy_name       = data.get("strategy_name", ""),
            params              = data.get("params", "{}"),
            symbol              = symbol,
            interval            = interval,
            start_date          = str(cfg.start_date),
            end_date            = str(cfg.end_date),
            gate_decision       = decision,
            gate_score          = data.get("gate_score"),
            total_trades        = data.get("total_trades", 0),
            net_profit          = data.get("net_profit", 0.0),
            total_return        = data.get("total_return", 0.0),
            max_drawdown_pct    = data.get("max_drawdown_pct", 0.0),
            sharpe_ratio        = data.get("sharpe_ratio", 0.0),
            sortino_ratio       = data.get("sortino_ratio", 0.0),
            calmar_ratio        = data.get("calmar_ratio", 0.0),
            cagr                = data.get("cagr", 0.0),
            win_rate            = data.get("win_rate", 0.0),
            profit_factor       = data.get("profit_factor", 0.0),
            avg_trade_pnl       = data.get("avg_trade_pnl", 0.0),
            walk_forward_return = data.get("walk_forward_return"),
            mc_median_return    = data.get("mc_median_return"),
            mc_pct5_return      = data.get("mc_pct5_return"),
            mc_pct95_return     = data.get("mc_pct95_return"),
            mc_prob_positive    = data.get("mc_prob_positive"),
            equity_curve_json   = data.get("equity_curve_json"),
            created_at          = datetime.now(timezone.utc).isoformat(),
        )

    # ── Step 8: generate reports ──────────────────────────────────────────────

    def _step8_reports(
        self,
        run: PipelineRun,
        symbol: str,
        interval: str,
    ) -> dict[str, Path]:
        from reports.html import generate_html_report

        reports_dir = Path(self.cfg.reports_dir)
        reports_dir.mkdir(exist_ok=True)

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = f"{symbol}_{interval}_{run.session_id[:8]}_{ts}"
        paths: dict[str, Path] = {}

        # HTML report
        try:
            html_path = reports_dir / f"{slug}.html"
            html      = generate_html_report(
                session_id     = run.session_id,
                symbol         = symbol,
                interval       = interval,
                start_date     = str(self.cfg.start_date),
                end_date       = str(self.cfg.end_date),
                results        = run.strategy_results,
                n_tested       = run.n_tested,
                elapsed_secs   = run.elapsed_secs,
            )
            html_path.write_text(html, encoding="utf-8")
            paths["html"] = html_path
        except Exception:
            self.notify.warn("HTML report failed: " + traceback.format_exc()[-100:])

        # JSON summary
        try:
            json_path = reports_dir / f"{slug}.json"
            _write_json_summary(json_path, run, symbol, interval)
            paths["json"] = json_path
        except Exception:
            pass

        # Markdown summary
        try:
            md_path = reports_dir / f"{slug}.md"
            _write_md_summary(md_path, run, symbol, interval)
            paths["md"] = md_path
        except Exception:
            pass

        return paths

    # ── Terminal summary ──────────────────────────────────────────────────────

    def _print_summary(self, run: PipelineRun) -> None:
        n = self.notify
        n.section("RESULTS")
        n.result("Session",          run.session_id[:16])
        n.result("Elapsed",          f"{run.elapsed_secs:.1f}s")
        n.result("Strategies tested",str(run.n_tested))
        n.result("Passed gate",      str(run.n_passed))
        n.result("Rejected",         str(run.n_rejected))
        n.result("Errors",           str(run.n_errors))

        if run.strategy_results:
            best = max(run.strategy_results, key=lambda r: r.sharpe_ratio or 0)
            n.result("Best Sharpe",
                      f"{best.sharpe_ratio:.3f}  "
                      f"({best.strategy_name}  {json.loads(best.params)})")

        for kind, path in run.report_paths.items():
            n.result(f"Report [{kind.upper()}]", str(path))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _discover_strategies() -> list[Type[StrategyBase]]:
    """Find all StrategyBase subclasses in the strategies/ package."""
    found = []
    for _info in pkgutil.iter_modules(strategies_pkg.__path__):
        module = importlib.import_module(f"strategies.{_info.name}")
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, StrategyBase)
                and obj is not StrategyBase
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return found


def _cartesian(space: dict[str, list]) -> list[dict]:
    import itertools
    keys   = list(space.keys())
    values = [space[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _run_job_inprocess(job_dict: dict, bars: pd.DataFrame) -> dict:
    """Run a backtest in the current process (no subprocess overhead)."""
    import importlib
    from jobs.backtest_job import BacktestJob, BacktestParams

    try:
        module = importlib.import_module(job_dict["strategy_module"])
        cls    = getattr(module, job_dict["strategy_class"])
        params = (
            json.loads(job_dict["params_json"])
            if isinstance(job_dict["params_json"], str)
            else job_dict["params_json"]
        )

        bp = BacktestParams(
            bars             = bars,
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
        return {"ok": False, "error": result.error, "job_dict": job_dict}

    except Exception:
        return {"ok": False, "error": traceback.format_exc(), "job_dict": job_dict}


def _write_json_summary(path: Path, run: PipelineRun, symbol: str, interval: str) -> None:
    def safe(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    doc = {
        "session_id"  : run.session_id,
        "symbol"      : symbol,
        "interval"    : interval,
        "started_at"  : run.started_at.isoformat(),
        "finished_at" : run.finished_at.isoformat() if run.finished_at else None,
        "elapsed_secs": run.elapsed_secs,
        "n_tested"    : run.n_tested,
        "n_passed"    : run.n_passed,
        "n_rejected"  : run.n_rejected,
        "n_errors"    : run.n_errors,
        "strategies"  : [
            {
                "strategy_class" : r.strategy_class,
                "params"         : json.loads(r.params),
                "gate_decision"  : r.gate_decision,
                "gate_score"     : safe(r.gate_score),
                "total_trades"   : r.total_trades,
                "net_profit"     : safe(r.net_profit),
                "total_return"   : safe(r.total_return),
                "max_drawdown_pct": safe(r.max_drawdown_pct),
                "sharpe_ratio"   : safe(r.sharpe_ratio),
                "calmar_ratio"   : safe(r.calmar_ratio),
                "cagr"           : safe(r.cagr),
            }
            for r in run.strategy_results
        ],
    }
    path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")


def _write_md_summary(path: Path, run: PipelineRun, symbol: str, interval: str) -> None:
    passed  = [r for r in run.strategy_results if r.gate_decision != "REJECT"]
    lines   = [
        f"# EdgeLab Research Report",
        f"",
        f"**Session:** `{run.session_id[:16]}`  ",
        f"**Symbol:** {symbol}  **Interval:** {interval}  ",
        f"**Period:** {run.config.start_date} → {run.config.end_date}  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## Summary",
        f"",
        f"| | Count |",
        f"|---|---|",
        f"| Strategies tested | {run.n_tested} |",
        f"| Passed quality gate | {run.n_passed} |",
        f"| Rejected | {run.n_rejected} |",
        f"| Errors | {run.n_errors} |",
        f"| Elapsed | {run.elapsed_secs:.1f}s |",
        f"",
        f"## Strategy Rankings",
        f"",
        f"| Rank | Strategy | Params | Decision | Sharpe | CAGR | Max DD | Trades |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    ranked = sorted(passed, key=lambda r: r.sharpe_ratio or 0, reverse=True)
    for i, r in enumerate(ranked[:20], 1):
        params = json.loads(r.params) if r.params else {}
        lines.append(
            f"| {i} | {r.strategy_class} | {params} | {r.gate_decision} "
            f"| {(r.sharpe_ratio or 0):.3f} | {(r.cagr or 0):.2%} "
            f"| {(r.max_drawdown_pct or 0):.2%} | {r.total_trades} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
