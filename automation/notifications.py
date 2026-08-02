"""Research pipeline notifications — terminal + optional log file."""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_LEVEL_ICONS = {
    "info"    : "  ·",
    "ok"      : "  ✓",
    "warn"    : "  ⚠",
    "error"   : "  ✗",
    "step"    : " ──",
    "header"  : "══",
}

_W = 70


class Notifier:
    """Structured console output with optional file logging."""

    def __init__(
        self,
        verbose: bool       = True,
        log_path: Path | None = None,
    ) -> None:
        self.verbose  = verbose
        self._logger  = _setup_logger(log_path) if log_path else None

    def header(self, title: str) -> None:
        msg = f"\n{'═' * _W}\n  {title}\n{'═' * _W}"
        self._out(msg)

    def section(self, label: str) -> None:
        msg = f"\n  {'─' * (_W - 2)}\n  {label}"
        self._out(msg)

    def step(self, n: str, label: str) -> None:
        self._out(f"\n  STEP {n} · {label}")

    def ok(self, detail: str = "") -> None:
        self._out(f"  ✓  {detail}" if detail else "  ✓")

    def info(self, detail: str) -> None:
        self._out(f"  ·  {detail}")

    def warn(self, detail: str) -> None:
        self._out(f"  ⚠  {detail}")

    def error(self, detail: str) -> None:
        self._out(f"  ✗  {detail}", file=sys.stderr)

    def result(self, label: str, value: str) -> None:
        self._out(f"     {label:<30} {value}")

    def table_row(self, cells: list[str], widths: list[int]) -> None:
        row = "  " + "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))
        self._out(row)

    def _out(self, msg: str, file=sys.stdout) -> None:
        if self.verbose:
            print(msg, file=file, flush=True)
        if self._logger:
            self._logger.info(msg.strip())


def _setup_logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"edgelab.{path.stem}")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(str(path), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
        logger.addHandler(fh)
    return logger
