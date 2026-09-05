import pytest

from research.stage_status import (
    StageStatus,
    stage_failed,
    stage_passed,
    stage_skipped,
)


def test_pass_and_skip_are_cleanly_serializable():
    assert stage_passed("walk_forward").to_dict() == {
        "name": "walk_forward",
        "status": "PASS",
        "error_type": None,
        "message": None,
    }
    assert stage_skipped("monte_carlo").status is StageStatus.SKIPPED


def test_failed_stage_preserves_exception_details():
    result = stage_failed("stress", RuntimeError("boom"))
    assert result.status is StageStatus.FAILED
    assert result.error_type == "RuntimeError"
    assert result.message == "boom"


def test_failed_stage_requires_error_details():
    with pytest.raises(ValueError):
        from research.stage_status import StageResult
        StageResult("stress", StageStatus.FAILED)
