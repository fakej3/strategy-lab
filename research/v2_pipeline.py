"""Gated V2 research pipeline.

The pipeline is intentionally orchestration-only: each stage receives explicit
inputs and returns explicit outputs. A run cannot be marked publishable unless
all mandatory gates pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass
class ValidationGate:
    name: str
    status: GateStatus = GateStatus.NOT_RUN
    detail: str = ""


@dataclass
class PipelineResult:
    output: Any = None
    gates: list[ValidationGate] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return bool(self.gates) and all(g.status == GateStatus.PASS for g in self.gates)


class ResearchPipeline:
    def __init__(self) -> None:
        self.gates: list[ValidationGate] = []

    def gate(self, name: str, check: Callable[[], Any]) -> Any:
        try:
            output = check()
        except Exception as exc:
            self.gates.append(ValidationGate(name, GateStatus.FAIL, str(exc)))
            raise
        self.gates.append(ValidationGate(name, GateStatus.PASS))
        return output

    def run(self, *, data: Any, validate: Callable[[Any], Any], research: Callable[[Any], Any], checks: list[tuple[str, Callable[[Any], Any]]]) -> PipelineResult:
        self.gates.clear()
        validated = self.gate("data_validation", lambda: validate(data))
        researched = research(validated)
        for name, check in checks:
            self.gate(name, lambda check=check: check(researched))
        return PipelineResult(output=researched, gates=list(self.gates))
