"""Background scheduler that triggers research runs on a cron-like schedule."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class ResearchScheduler:
    """Run `python research.py` on a repeating schedule (default: daily at 02:00 UTC)."""

    def __init__(
        self,
        hour: int = 2,
        minute: int = 0,
        research_script: Path | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.hour   = hour
        self.minute = minute
        self.script = research_script or (Path(__file__).parents[1] / "research.py")
        self.args   = extra_args or []
        self._stop  = False
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT,  self._handle_signal)

    def _handle_signal(self, signum, frame) -> None:
        print(f"\n  Scheduler shutting down (signal {signum}) …", flush=True)
        self._stop = True

    def _seconds_until_next(self) -> float:
        now  = datetime.now(timezone.utc)
        next = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        if next <= now:
            # Already past today's window — target tomorrow
            from datetime import timedelta
            next += timedelta(days=1)
        return (next - now).total_seconds()

    def _run_once(self) -> None:
        cmd = [sys.executable, str(self.script)] + self.args
        print(f"  Running: {' '.join(cmd)}", flush=True)
        try:
            subprocess.run(cmd, check=False)
        except Exception as exc:
            print(f"  Research run failed: {exc}", flush=True)

    def run(self) -> None:
        print(
            f"  Scheduler started — next run at {self.hour:02d}:{self.minute:02d} UTC daily",
            flush=True,
        )
        while not self._stop:
            secs = self._seconds_until_next()
            print(
                f"  [{datetime.now(timezone.utc).isoformat(timespec='seconds')}]"
                f"  Next research run in {secs/3600:.1f} h",
                flush=True,
            )
            # Sleep in short chunks so SIGTERM is handled promptly
            slept = 0.0
            while slept < secs and not self._stop:
                chunk = min(60.0, secs - slept)
                time.sleep(chunk)
                slept += chunk
            if not self._stop:
                print(
                    f"\n  [{datetime.now(timezone.utc).isoformat(timespec='seconds')}]"
                    f"  Firing scheduled research run …",
                    flush=True,
                )
                self._run_once()
        print("  Scheduler stopped.", flush=True)
