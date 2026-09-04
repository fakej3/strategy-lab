import json

from research.provenance import DiagnosticStage, DiagnosticStatus, is_publishable, serialize_stages


def _provenance(failed=None):
    names = ["data_integrity", "accounting", "robustness", "overfitting", "stress", "confidence", "walk_forward", "monte_carlo"]
    stages = [
        DiagnosticStage(name, DiagnosticStatus.FAILED, "RuntimeError", "diagnostic exploded") if name == failed
        else DiagnosticStage(name, DiagnosticStatus.PASS)
        for name in names
    ]
    return serialize_stages(stages)


def test_publishability_requires_explicit_evidence():
    assert is_publishable("PROMISING", _provenance()) is True
    assert is_publishable("PROMISING", None) is False
    assert is_publishable("PROMISING", _provenance("stress")) is False
    assert is_publishable("REJECT", _provenance()) is False


def test_failed_stage_preserves_exception_evidence():
    payload = json.loads(_provenance("monte_carlo"))
    stage = payload["stages"]["monte_carlo"]
    assert stage["status"] == "FAILED"
    assert stage["error_type"] == "RuntimeError"
    assert stage["message"] == "diagnostic exploded"


def test_fast_mode_can_explicitly_skip_optional_diagnostics():
    stages = [DiagnosticStage(name, DiagnosticStatus.PASS) for name in ("data_integrity", "accounting", "robustness", "overfitting", "stress", "confidence")]
    stages += [DiagnosticStage("walk_forward", DiagnosticStatus.SKIPPED), DiagnosticStage("monte_carlo", DiagnosticStatus.SKIPPED)]
    assert is_publishable("PROMISING", serialize_stages(stages)) is True


def test_missing_optional_stage_is_not_treated_as_skipped():
    stages = [DiagnosticStage(name, DiagnosticStatus.PASS) for name in ("data_integrity", "accounting", "robustness", "overfitting", "stress", "confidence")]
    assert is_publishable("PROMISING", serialize_stages(stages)) is False
