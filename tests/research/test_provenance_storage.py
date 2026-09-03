from research.provenance import DiagnosticStage, DiagnosticStatus, serialize_stages
from research_db.models import SessionRecord, StrategyResult
from research_db.storage import ResearchStorage


REQUIRED = ("data_integrity", "accounting", "robustness", "overfitting", "stress", "confidence")
OPTIONAL = ("walk_forward", "monte_carlo")


def _provenance(optional_status=DiagnosticStatus.PASS):
    stages = [DiagnosticStage(name, DiagnosticStatus.PASS) for name in REQUIRED]
    stages.extend(DiagnosticStage(name, optional_status) for name in OPTIONAL)
    return serialize_stages(stages)


def _result(session_id, provenance, *, sharpe=1.0):
    return StrategyResult(
        session_id=session_id,
        strategy_class="TestStrategy",
        strategy_name="test",
        params="{}",
        symbol="BTCUSDT",
        interval="1h",
        start_date="2025-01-01",
        end_date="2025-12-31",
        gate_decision="PROMISING",
        total_trades=20,
        sharpe_ratio=sharpe,
        diagnostic_provenance_json=provenance,
    )


def _save_session(storage):
    storage.save_session(
        SessionRecord(
            session_id="s1",
            started_at="2026-01-01T00:00:00+00:00",
            status="complete",
            symbols="BTCUSDT",
            intervals="1h",
            start_date="2025-01-01",
            end_date="2025-12-31",
        )
    )


def test_storage_round_trip_preserves_provenance_and_publishability(tmp_path):
    storage = ResearchStorage(tmp_path / "research.db")
    try:
        _save_session(storage)
        result_id = storage.save_strategy_result(_result("s1", _provenance()))

        loaded = storage.get_strategy_result_by_id(result_id)
        assert loaded is not None
        assert loaded.publishable is True
        assert loaded.diagnostic_provenance_json == _provenance()
    finally:
        storage.close()


def test_storage_hides_incomplete_results_from_publishable_reads(tmp_path):
    storage = ResearchStorage(tmp_path / "research.db")
    try:
        _save_session(storage)
        result_id = storage.save_strategy_result(_result("s1", None))

        assert storage.get_strategy_result_by_id(result_id) is None
        assert storage.get_best_by(metric="sharpe_ratio", min_trades=5) == []
    finally:
        storage.close()


def test_storage_allows_explicitly_skipped_optional_diagnostics(tmp_path):
    storage = ResearchStorage(tmp_path / "research.db")
    try:
        _save_session(storage)
        result_id = storage.save_strategy_result(_result("s1", _provenance(DiagnosticStatus.SKIPPED)))

        assert storage.get_strategy_result_by_id(result_id) is not None
        assert len(storage.get_best_by(metric="sharpe_ratio", min_trades=5)) == 1
    finally:
        storage.close()
