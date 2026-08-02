"""Verification Framework — financial safety system for strategy-lab.

Run all checks with:
    python verify.py

Or import individual modules:
    from verify._invariants import check_all
    from verify._reference  import run_reference
    from verify._regression import save_snapshot, compare_snapshot
"""
from verify._invariants import Violation, check_all
from verify._reference  import RefTrade, run_reference
from verify._reporter   import SectionResult, VerificationReport

__all__ = [
    "check_all",
    "Violation",
    "run_reference",
    "RefTrade",
    "SectionResult",
    "VerificationReport",
]
