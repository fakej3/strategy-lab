"""Verification report generator.

Collects PASS/FAIL results from each section and formats a human-readable
summary report.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SectionResult:
    name   : str
    passed : int          = 0
    failed : int          = 0
    errors : list[str]    = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if self.failed == 0 else "FAIL"

    def record(self, passed: bool, message: str = "") -> None:
        if passed:
            self.passed += 1
        else:
            self.failed += 1
            if message:
                self.errors.append(message)


@dataclass
class VerificationReport:
    start_time: float = field(default_factory=time.time)
    sections  : list[SectionResult] = field(default_factory=list)

    def add(self, section: SectionResult) -> None:
        self.sections.append(section)

    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.sections)

    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.sections)

    @property
    def all_passed(self) -> bool:
        return self.total_failed == 0

    def render(self) -> str:
        elapsed = time.time() - self.start_time
        W = 62
        lines: list[str] = []
        lines.append("=" * W)
        lines.append("  VERIFICATION REPORT")
        lines.append("=" * W)

        for s in self.sections:
            icon   = "✓" if s.failed == 0 else "✗"
            total  = s.passed + s.failed
            lines.append(f"\n  {icon}  {s.name}")
            lines.append(f"     {s.passed}/{total} tests passed")
            max_show = 8
            for err in s.errors[:max_show]:
                lines.append(f"     FAIL: {err}")
            if len(s.errors) > max_show:
                lines.append(f"     ... and {len(s.errors) - max_show} more failure(s)")

        lines.append("\n" + "=" * W)
        total_tests = self.total_passed + self.total_failed
        if self.all_passed:
            lines.append(f"  RESULT : ALL {total_tests} TESTS PASSED")
        else:
            lines.append(f"  RESULT : {self.total_failed} / {total_tests} TESTS FAILED")
        lines.append(f"  Time   : {elapsed:.2f}s")
        lines.append("=" * W)
        return "\n".join(lines)
