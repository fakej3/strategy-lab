"""Reproducible experiment specification and audit manifest.

An experiment is identified by its immutable inputs, not by a human-readable
name alone. The manifest deliberately records hashes rather than trusting
mutable filenames or implicit environment state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class ExperimentSpec:
    strategy_name: str
    strategy_version: str
    dataset_fingerprint: str
    code_commit: str
    parameters: dict[str, Any]
    execution_model: str
    fee_model: str
    slippage_model: str
    sizing_model: str
    random_seed: int | None = None
    train_period: str | None = None
    test_period: str | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def experiment_id(spec: ExperimentSpec) -> str:
    payload = canonical_json(asdict(spec)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_manifest(spec: ExperimentSpec, *, result: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = {
        "experiment_id": experiment_id(spec),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "spec": asdict(spec),
        "result": result or {},
    }
    return manifest
