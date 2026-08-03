"""Tests for server/websocket.py — WebSocket progress streaming."""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.auth import hash_password


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGELAB_SECRET_KEY", "test-secret-key-0123456789abcdef")
    monkeypatch.setenv("EDGELAB_USERNAME",   "testuser")
    monkeypatch.setenv("EDGELAB_PASSWORD_HASH", hash_password("testpass"))
    monkeypatch.setenv("EDGELAB_DB",      str(tmp_path / "test.db"))
    monkeypatch.setenv("EDGELAB_REPORTS", str(tmp_path / "reports"))
    monkeypatch.setenv("EDGELAB_LOG",     str(tmp_path / "test.log"))

    import server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_USERNAME",  "testuser")
    monkeypatch.setattr(auth_mod, "_PASS_HASH", hash_password("testpass"))
    monkeypatch.setattr(auth_mod, "USING_DEFAULT_CREDS", False)

    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inject_job(job_id: str, status: str = "running",
                q: queue.Queue | None = None) -> queue.Queue:
    from server.background import JobInfo, job_manager
    if q is None:
        q = queue.Queue()
    job_manager._jobs[job_id]   = JobInfo(job_id=job_id, status=status)
    job_manager._queues[job_id] = q
    job_manager._cancel[job_id] = threading.Event()
    return q


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWsJobProgress:
    def test_unknown_job_sends_error_and_closes(self, client):
        with client.websocket_connect("/ws/job/no-such-id") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not found" in msg["message"].lower()

    def test_already_done_job_sends_done_immediately(self, client):
        q = _inject_job("done-job", status="done")
        from server.background import job_manager
        job_manager._jobs["done-job"].n_passed = 5
        job_manager._jobs["done-job"].n_tested = 10
        job_manager._jobs["done-job"].elapsed_secs = 3.0

        with client.websocket_connect("/ws/job/done-job") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "done"
            assert msg["success"] is True
            assert msg["n_passed"] == 5

    def test_already_failed_job_sends_done_with_success_false(self, client):
        _inject_job("fail-job", status="failed")
        with client.websocket_connect("/ws/job/fail-job") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "done"
            assert msg["success"] is False

    def test_cancelled_job_sends_cancelled(self, client):
        _inject_job("cancel-job", status="cancelled")
        with client.websocket_connect("/ws/job/cancel-job") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "done"
            assert msg["cancelled"] is True

    def test_streams_events_from_queue(self, client):
        q = _inject_job("stream-job", status="running")
        q.put({"type": "step", "n": "1", "label": "Loading", "pct": 10})
        q.put({"type": "ok",   "message": "Done loading"})
        q.put({"type": "done", "success": True, "n_passed": 2, "n_tested": 5})

        messages = []
        with client.websocket_connect("/ws/job/stream-job") as ws:
            for _ in range(3):
                messages.append(ws.receive_json())

        types = [m["type"] for m in messages]
        assert types == ["step", "ok", "done"]
        assert messages[0]["pct"] == 10
        assert messages[2]["success"] is True

    def test_streams_section_event(self, client):
        q = _inject_job("section-job", status="running")
        q.put({"type": "section", "label": "BTCUSDT 1h"})
        q.put({"type": "done",    "success": True, "n_passed": 0, "n_tested": 0})

        messages = []
        with client.websocket_connect("/ws/job/section-job") as ws:
            for _ in range(2):
                messages.append(ws.receive_json())

        assert messages[0]["type"] == "section"
        assert messages[0]["label"] == "BTCUSDT 1h"

    def test_warn_and_error_events_passed_through(self, client):
        q = _inject_job("warn-job", status="running")
        q.put({"type": "warn",  "message": "Low bar count"})
        q.put({"type": "error", "message": "Pipeline aborted"})
        q.put({"type": "done",  "success": False, "n_passed": 0, "n_tested": 0})

        messages = []
        with client.websocket_connect("/ws/job/warn-job") as ws:
            for _ in range(3):
                messages.append(ws.receive_json())

        assert messages[0]["type"] == "warn"
        assert messages[1]["type"] == "error"
        assert messages[2]["type"] == "done"

    def test_connection_closes_after_done(self, client):
        q = _inject_job("close-job", status="running")
        q.put({"type": "done", "success": True, "n_passed": 1, "n_tested": 1})

        with client.websocket_connect("/ws/job/close-job") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "done"
            # After done the server closes the connection;
            # attempting another receive should raise or return nothing.
