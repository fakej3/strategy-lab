"""Persisted provenance contract for multi-stage research diagnostics."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DiagnosticStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_RUN = "NOT_RUN"


REQUIRED_DIAGNOSTICS = ("data_integrity", "accounting", "robustness", "overfitting", "stress", "confidence")
OPTIONAL_DIAGNOSTICS = ("walk_forward", "monte_carlo")


@dataclass(frozen=True)
class DiagnosticStage:
    name: str
    status: DiagnosticStatus
    error_type: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("diagnostic stage name must not be empty")
        if self.status is DiagnosticStatus.FAILED and (not self.error_type or not self.message):
            raise ValueError("failed diagnostics require error_type and message")
        if self.status is not DiagnosticStatus.FAILED and (self.error_type is not None or self.message is not None):
            raise ValueError("error details are only valid for failed diagnostics")

    def to_dict(self) -> dict[str, str | None]:
        return {"status": self.status.value, "error_type": self.error_type, "message": self.message}


def failed_stage(name: str, exc: BaseException) -> DiagnosticStage:
    return DiagnosticStage(name, DiagnosticStatus.FAILED, type(exc).__name__, str(exc).strip() or repr(exc))


def serialize_stages(stages: list[DiagnosticStage]) -> str:
    return json.dumps({"version": 1, "stages": {s.name: s.to_dict() for s in stages}}, sort_keys=True, separators=(",", ":"))


def parse_stages(value: str | None) -> dict[str, dict[str, Any]]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    stages = payload.get("stages") if isinstance(payload, dict) else None
    return stages if isinstance(stages, dict) else {}


def is_publishable(gate_decision: str, provenance_json: str | None) -> bool:
    if str(gate_decision).upper() == "REJECT":
        return False
    stages = parse_stages(provenance_json)
    if any(stages.get(name, {}).get("status") != "PASS" for name in REQUIRED_DIAGNOSTICS):
        return False
    return all(stages.get(name, {}).get("status") in {"PASS", "SKIPPED"} for name in OPTIONAL_DIAGNOSTICS)
