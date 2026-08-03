"""Nightly research entry point.

Usage
-----
  python research.py                          # use defaults
  python research.py --symbols BTCUSDT ETHUSDT --interval 4h
  python research.py --start 2023-01-01 --no-wf --no-mc --fast
  python research.py --dashboard --port 8080  # launch dashboard only
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="EdgeLab nightly research automation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--symbols",   nargs="+", default=["BTCUSDT"],  metavar="SYM")
    p.add_argument("--intervals", nargs="+", default=["1h"],       metavar="IV")
    p.add_argument("--start",     type=_parse_date, default=date(2024, 1, 1),
                   metavar="YYYY-MM-DD")
    p.add_argument("--end",       type=_parse_date, default=date.today(),
                   metavar="YYYY-MM-DD")
    p.add_argument("--capital",   type=float, default=100_000.0)
    p.add_argument("--fee",       type=float, default=0.001,
                   help="Fee rate (e.g. 0.001 = 0.1%%)")
    p.add_argument("--slippage",  type=float, default=0.0005)
    p.add_argument("--workers",   type=int,   default=None,
                   help="CPU workers (default: all cores)")
    p.add_argument("--no-wf",     action="store_true",
                   help="Skip walk-forward testing")
    p.add_argument("--no-mc",     action="store_true",
                   help="Skip Monte Carlo simulation")
    p.add_argument("--mc-sims",   type=int, default=500)
    p.add_argument("--db",        default="research.db",  metavar="PATH")
    p.add_argument("--reports",   default="reports",      metavar="DIR")
    p.add_argument("--log",       default="logs/research.log", metavar="PATH")
    p.add_argument("--fast",      action="store_true",
                   help="In-process execution (no subprocess pool)")
    p.add_argument("--quiet",     action="store_true")
    # Dashboard-only mode
    p.add_argument("--dashboard", action="store_true",
                   help="Launch the web dashboard and exit (no research run)")
    p.add_argument("--port",      type=int, default=8000)
    p.add_argument("--host",      default="127.0.0.1")
    return p


def _run_dashboard(host: str, port: int) -> None:
    import uvicorn
    from reports.dashboard import app
    uvicorn.run(app, host=host, port=port)


def _run_research(args: argparse.Namespace) -> int:
    from automation.pipeline import PipelineConfig, ResearchPipeline

    cfg = PipelineConfig(
        symbols              = args.symbols,
        intervals            = args.intervals,
        start_date           = args.start,
        end_date             = args.end,
        starting_capital     = args.capital,
        fee_rate             = args.fee,
        slippage_pct         = args.slippage,
        n_workers            = args.workers,
        run_walk_forward     = not args.no_wf,
        run_monte_carlo      = not args.no_mc,
        mc_simulations       = args.mc_sims,
        db_path              = args.db,
        reports_dir          = args.reports,
        log_path             = args.log,
        verbose              = not args.quiet,
        fast_mode            = args.fast,
    )

    run = ResearchPipeline(cfg).execute()
    return 0 if run.n_errors == 0 else 1


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.dashboard:
        _run_dashboard(args.host, args.port)
        return 0

    return _run_research(args)


if __name__ == "__main__":
    sys.exit(main())
