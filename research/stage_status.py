"""Explicit status primitives for multi-stage research diagnostics.

A diagnostic stage may fail without invalidating the base backtest, but that
failure must remain visible. These types provide a small, serialisable
contract for pipeline/report layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StageStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class StageResult:
    name: str
    status: StageStatus
    error_type: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("stage name must not be empty")
        if self.status is StageStatus.FAILED:
            if not self.error_type or not self.message:
                raise ValueError("failed stages require error_type and message")
        elif self.error_type is not None or self.message is not None:
            raise ValueError("error details are only valid for failed stages")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "status": self.status.value,
            "error_type": self.error_type,
            "message": self.message,
        }


def stage_passed(name: str) -> StageResult:
    return StageResult(name=name, status=StageStatus.PASS)


def stage_skipped(name: str) -> StageResult:
    return StageResult(name=name, status=StageStatus.SKIPPED)


def stage_not_run(name: str) -> StageResult:
    return StageResult(name=name, status=StageStatus.NOT_RUN)


def stage_failed(name: str, exc: BaseException) -> StageResult:
    message = str(exc).strip() or repr(exc)
    return StageResult(
        name=name,
        status=StageStatus.FAILED,
        error_type=type(exc).__name__,
        message=message,
    )
