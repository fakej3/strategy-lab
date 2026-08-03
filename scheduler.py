"""Daily research scheduler daemon.

Usage
-----
  python scheduler.py                        # run at 02:00 UTC every day
  python scheduler.py --hour 3 --minute 30  # run at 03:30 UTC
  python scheduler.py --now                  # fire immediately, then schedule
  python scheduler.py --dashboard            # also launch the web dashboard
  python scheduler.py --dashboard --port 8080 --host 0.0.0.0
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="EdgeLab nightly scheduler daemon",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--hour",       type=int, default=2,
                   help="UTC hour to fire research run (0-23)")
    p.add_argument("--minute",     type=int, default=0,
                   help="UTC minute to fire research run (0-59)")
    p.add_argument("--now",        action="store_true",
                   help="Fire one research run immediately before entering schedule loop")
    p.add_argument("--dashboard",  action="store_true",
                   help="Launch dashboard in background thread")
    p.add_argument("--host",       default="127.0.0.1")
    p.add_argument("--port",       type=int, default=8000)
    # Pass-through flags forwarded to research.py
    p.add_argument("--symbols",    nargs="+", default=None)
    p.add_argument("--intervals",  nargs="+", default=None)
    p.add_argument("--no-wf",      action="store_true")
    p.add_argument("--no-mc",      action="store_true")
    p.add_argument("--fast",       action="store_true")
    p.add_argument("--quiet",      action="store_true")
    return p


def _start_dashboard(host: str, port: int) -> None:
    import uvicorn
    from reports.dashboard import app
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    # Build extra args to forward to research.py
    extra: list[str] = []
    if args.symbols:
        extra += ["--symbols"] + args.symbols
    if args.intervals:
        extra += ["--intervals"] + args.intervals
    if args.no_wf:
        extra.append("--no-wf")
    if args.no_mc:
        extra.append("--no-mc")
    if args.fast:
        extra.append("--fast")
    if args.quiet:
        extra.append("--quiet")

    if args.dashboard:
        t = threading.Thread(
            target=_start_dashboard,
            args=(args.host, args.port),
            daemon=True,
        )
        t.start()
        print(f"  Dashboard listening on http://{args.host}:{args.port}", flush=True)

    from automation.scheduler import ResearchScheduler

    sched = ResearchScheduler(
        hour       = args.hour,
        minute     = args.minute,
        extra_args = extra,
    )

    if args.now:
        print("  --now: firing immediate research run …", flush=True)
        sched._run_once()

    sched.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
