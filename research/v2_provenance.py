"""Deterministic provenance helpers for Strategy Labs V2."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_records(records: Any) -> str:
    """Fingerprint JSON-compatible research inputs canonically.

    Callers should fingerprint the normalized data actually consumed by the
    engine, not a mutable filename or URL. Timestamp/float normalization is a
    responsibility of the data layer before this function is called.
    """
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256_bytes(payload)


def environment_fingerprint(*, python_version: str, dependencies: dict[str, str]) -> str:
    payload = {"python_version": python_version, "dependencies": dependencies}
    return fingerprint_records(payload)
