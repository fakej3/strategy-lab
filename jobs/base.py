"""Abstract base job and result container."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobResult:
    success: bool
    data: dict[str, Any] | None
    error: str | None
    duration_secs: float


class BaseJob(ABC):
    """A unit of parallelisable research work.

    Subclasses implement ``execute()``.  Callers use ``run()`` which wraps
    ``execute()`` with timing and error capture.
    """

    @abstractmethod
    def execute(self) -> dict[str, Any]:
        """Do the actual work.  Return a plain serialisable dict."""

    def run(self) -> JobResult:
        t0 = time.perf_counter()
        try:
            data = self.execute()
            return JobResult(
                success       = True,
                data          = data,
                error         = None,
                duration_secs = time.perf_counter() - t0,
            )
        except Exception as exc:
            return JobResult(
                success       = False,
                data          = None,
                error         = f"{type(exc).__name__}: {exc}",
                duration_secs = time.perf_counter() - t0,
            )
