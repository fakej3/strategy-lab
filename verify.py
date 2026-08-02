#!/usr/bin/env python3
"""Verification Framework — single entry point.

Usage:
    python verify.py            # run all checks, print report
    python verify.py --fast     # skip property tests (quicker CI run)
    python verify.py --verbose  # show pytest output + report

Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the strategy-lab Verification Framework")
    parser.add_argument("--fast",    action="store_true", help="Skip property tests")
    parser.add_argument("--verbose", action="store_true", help="Show full pytest output")
    args = parser.parse_args()

    root     = Path(__file__).parent
    test_dir = root / "tests" / "verify"

    suites = [
        ("GOLDEN ACCOUNTING",    test_dir / "test_golden.py",       True),
        ("FINANCIAL INVARIANTS", test_dir / "test_invariants.py",   True),
        ("DIFFERENTIAL ENGINE",  test_dir / "test_differential.py", True),
        ("PROPERTY TESTS",       test_dir / "test_property.py",     not args.fast),
        ("REGRESSION SNAPSHOTS", test_dir / "test_regression.py",   True),
    ]

    W = 64
    print("=" * W)
    print("  STRATEGY-LAB VERIFICATION FRAMEWORK")
    print("=" * W)

    results = []
    total_start = time.time()

    for suite_name, suite_path, enabled in suites:
        if not enabled:
            print(f"\n  -  {suite_name}  (skipped — use without --fast)")
            results.append((suite_name, None, 0, 0))
            continue

        t0  = time.time()
        cmd = [
            sys.executable, "-m", "pytest",
            str(suite_path),
            "-q",
            "--tb=short",
            "--no-header",
        ]
        if args.verbose:
            cmd += ["-v"]

        proc = subprocess.run(
            cmd,
            capture_output=not args.verbose,
            text=True,
            cwd=str(root),
        )
        elapsed = time.time() - t0

        passed = proc.returncode == 0

        if args.verbose:
            # pytest already printed its output
            pass
        else:
            # parse pytest summary line (e.g. "5 passed, 2 failed in 0.12s")
            out = proc.stdout + proc.stderr
            summary = _last_summary(out)
            n_pass, n_fail = _parse_counts(summary)
            icon = "✓" if passed else "✗"
            print(f"\n  {icon}  {suite_name}")
            print(f"     {n_pass} passed, {n_fail} failed  ({elapsed:.1f}s)")
            if not passed and n_fail > 0:
                _print_failures(out)
            results.append((suite_name, passed, n_pass, n_fail))

    total_elapsed = time.time() - total_start
    total_pass  = sum(r[2] for r in results if r[1] is not None)
    total_fail  = sum(r[3] for r in results if r[1] is not None)
    all_ok      = all(r[1] for r in results if r[1] is not None)

    print("\n" + "=" * W)
    if all_ok:
        print(f"  RESULT : ALL {total_pass} TESTS PASSED")
    else:
        print(f"  RESULT : {total_fail} TESTS FAILED  ({total_pass} passed)")
    print(f"  Time   : {total_elapsed:.2f}s")
    print("=" * W)

    return 0 if all_ok else 1


def _last_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            return line
    return ""


def _parse_counts(summary: str) -> tuple[int, int]:
    import re
    passed = failed = 0
    m = re.search(r"(\d+)\s+passed", summary)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", summary)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+error", summary)
    if m:
        failed += int(m.group(1))
    return passed, failed


def _print_failures(output: str) -> None:
    """Print the first FAILED section from pytest output."""
    lines    = output.splitlines()
    in_fail  = False
    count    = 0
    max_show = 25
    for line in lines:
        if line.startswith("FAILED") or "FAILED" in line:
            in_fail = True
        if in_fail:
            print(f"     {line}")
            count += 1
            if count >= max_show:
                print("     ...")
                break


if __name__ == "__main__":
    sys.exit(main())
