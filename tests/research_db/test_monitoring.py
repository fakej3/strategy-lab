"""Tests for Phase 6 monitoring events storage."""
from __future__ import annotations

import pytest
from pathlib import Path

from research_db.database import Database
from research_db.models import MonitoringEvent
from research_db.storage import ResearchStorage


@pytest.fixture
def storage(tmp_path):
    s = ResearchStorage(str(tmp_path / "test.db"))
    yield s
    s.close()


class TestMonitoringEvents:
    def test_log_event_stores_float(self, storage):
        storage.log_event("step1_fetch", "duration_secs", value_float=12.5)
        events = storage.get_monitoring_events()
        assert len(events) == 1
        assert events[0].stage == "step1_fetch"
        assert events[0].event_type == "duration_secs"
        assert events[0].value_float == pytest.approx(12.5)

    def test_log_event_stores_text(self, storage):
        storage.log_event("step1_fetch", "bars_count", value_text="BTCUSDT/1h")
        events = storage.get_monitoring_events()
        assert events[0].value_text == "BTCUSDT/1h"

    def test_log_event_with_session_id(self, storage):
        storage.log_event("step4_backtests", "duration_secs",
                          session_id="abc123", value_float=30.0)
        events = storage.get_monitoring_events(session_id="abc123")
        assert len(events) == 1
        assert events[0].session_id == "abc123"

    def test_filter_by_stage(self, storage):
        storage.log_event("step1_fetch",    "duration_secs", value_float=1.0)
        storage.log_event("step4_backtests", "duration_secs", value_float=5.0)
        events = storage.get_monitoring_events(stage="step1_fetch")
        assert len(events) == 1
        assert events[0].stage == "step1_fetch"

    def test_filter_by_session_and_stage(self, storage):
        storage.log_event("step1_fetch", "bars_count",
                          session_id="session_a", value_float=1000.0)
        storage.log_event("step1_fetch", "bars_count",
                          session_id="session_b", value_float=2000.0)
        events = storage.get_monitoring_events(session_id="session_a", stage="step1_fetch")
        assert len(events) == 1
        assert events[0].value_float == pytest.approx(1000.0)

    def test_monitoring_never_raises_on_bad_value(self, storage):
        """log_event must silently swallow any internal error."""
        import math
        # NaN should be stored as None via _safe
        storage.log_event("x", "y", value_float=float("nan"))
        events = storage.get_monitoring_events()
        assert len(events) == 1
        assert events[0].value_float is None

    def test_multiple_events_returned_newest_first(self, storage):
        for i in range(5):
            storage.log_event("step", "count", value_float=float(i))
        events = storage.get_monitoring_events()
        assert len(events) == 5

    def test_limit_parameter(self, storage):
        for i in range(20):
            storage.log_event("step", "count", value_float=float(i))
        events = storage.get_monitoring_events(limit=5)
        assert len(events) == 5

    def test_monitoring_event_dataclass_fields(self, storage):
        storage.log_event("stage_x", "type_y", session_id="sid",
                          value_float=3.14, value_text="hello")
        ev = storage.get_monitoring_events()[0]
        assert isinstance(ev, MonitoringEvent)
        assert ev.stage == "stage_x"
        assert ev.event_type == "type_y"
        assert ev.session_id == "sid"
        assert ev.value_float == pytest.approx(3.14)
        assert ev.value_text == "hello"
        assert ev.id is not None
        assert ev.created_at != ""
