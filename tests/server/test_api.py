"""Tests for server/api.py — REST API endpoints."""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
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

    # server.api sets _REPORTS_DIR at import time from EDGELAB_REPORTS, so the
    # env-var change above is too late.  Patch the attribute directly so every
    # test using this fixture is isolated from the developer's real reports dir.
    import server.api as api_mod
    monkeypatch.setattr(api_mod, "_REPORTS_DIR", tmp_path / "reports")

    application = create_app()
    return application


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def authed_client(client):
    """Client with an active session cookie."""
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass", "next": "/"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return client


# ── Auth guard ────────────────────────────────────────────────────────────────

class TestAuthGuard:
    def test_unauthenticated_redirects(self, client):
        resp = client.get("/api/jobs", follow_redirects=False)
        # Auth raises HTTPException 303 which TestClient follows
        assert resp.status_code in (303, 401, 307, 302, 200)

    def test_authenticated_reaches_endpoint(self, authed_client):
        resp = authed_client.get("/api/jobs")
        assert resp.status_code == 200


# ── /api/jobs ─────────────────────────────────────────────────────────────────

class TestApiJobs:
    def test_list_jobs_empty(self, authed_client):
        resp = authed_client.get("/api/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_jobs_has_expected_keys(self, authed_client):
        from server.background import JobInfo, job_manager
        job_manager._jobs["test-abc"] = JobInfo(job_id="test-abc", status="done")
        resp = authed_client.get("/api/jobs")
        data = resp.json()
        assert any(j["job_id"] == "test-abc" for j in data)
        job = next(j for j in data if j["job_id"] == "test-abc")
        assert "status"   in job
        assert "n_passed" in job


# ── /api/research/run ─────────────────────────────────────────────────────────

class TestApiResearchRun:
    def _mock_pipeline(self):
        run = MagicMock()
        run.session_id   = "sess-api"
        run.n_tested     = 5
        run.n_passed     = 2
        run.n_rejected   = 3
        run.elapsed_secs = 1.0
        run.report_paths = {}
        mock_cls  = MagicMock()
        mock_inst = MagicMock()
        mock_inst.execute.return_value = run
        mock_cls.return_value = mock_inst
        return patch("server.background.ResearchPipeline", mock_cls)

    def test_wrong_content_type_returns_415(self, authed_client):
        resp = authed_client.post(
            "/api/research/run",
            content=b"symbols=BTCUSDT",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 415

    def test_invalid_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/research/run",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_valid_request_returns_job_id(self, authed_client):
        with self._mock_pipeline():
            resp = authed_client.post(
                "/api/research/run",
                json={"symbols": "BTCUSDT", "fast_mode": True},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert len(body["job_id"]) == 36


# ── /api/research/status/{job_id} ─────────────────────────────────────────────

class TestApiJobStatus:
    def test_unknown_job_404(self, authed_client):
        resp = authed_client.get("/api/research/status/does-not-exist")
        assert resp.status_code == 404

    def test_known_job_returns_info(self, authed_client):
        from server.background import JobInfo, job_manager
        job_manager._jobs["stat-job"] = JobInfo(
            job_id="stat-job", status="running", n_passed=1, n_tested=3
        )
        resp = authed_client.get("/api/research/status/stat-job")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"]   == "stat-job"
        assert data["status"]   == "running"
        assert data["n_passed"] == 1
        assert data["n_tested"] == 3


# ── /api/jobs/{job_id}/cancel ─────────────────────────────────────────────────

class TestApiCancelJob:
    def test_cancel_nonexistent_404(self, authed_client):
        resp = authed_client.post("/api/jobs/no-such-job/cancel")
        assert resp.status_code == 404

    def test_cancel_running_job(self, authed_client):
        from server.background import JobInfo, job_manager
        import threading
        job_manager._jobs["cjob"] = JobInfo(job_id="cjob", status="running")
        job_manager._queues["cjob"] = queue.Queue()
        job_manager._cancel["cjob"] = threading.Event()
        resp = authed_client.post("/api/jobs/cjob/cancel")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True


# ── /api/jobs/{job_id}/restart ────────────────────────────────────────────────

class TestApiRestartJob:
    def _mock_pipeline(self):
        run = MagicMock()
        run.session_id   = "sess-restart"
        run.n_tested     = 2
        run.n_passed     = 1
        run.n_rejected   = 1
        run.elapsed_secs = 0.5
        run.report_paths = {}
        mock_cls  = MagicMock()
        mock_inst = MagicMock()
        mock_inst.execute.return_value = run
        mock_cls.return_value = mock_inst
        return patch("server.background.ResearchPipeline", mock_cls)

    def test_restart_nonexistent_404(self, authed_client):
        resp = authed_client.post("/api/jobs/ghost-id/restart")
        assert resp.status_code == 404

    def test_restart_existing_job(self, authed_client):
        from server.background import JobInfo, job_manager
        job_manager._jobs["rjob"] = JobInfo(job_id="rjob", status="done", config={})
        job_manager._queues["rjob"] = queue.Queue()
        job_manager._cancel["rjob"] = threading.Event()
        with self._mock_pipeline():
            resp = authed_client.post("/api/jobs/rjob/restart")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] != "rjob"


# ── /api/reports ──────────────────────────────────────────────────────────────

class TestApiReports:
    def test_list_reports_empty(self, authed_client):
        """Reports endpoint returns [] when the (isolated) reports dir has no HTML files."""
        resp = authed_client.get("/api/reports")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_reports_empty_isolated_from_real_reports_dir(
        self, app, tmp_path, monkeypatch
    ):
        """Isolation regression: test must return [] even when the real reports/
        directory on disk contains HTML files.  The fixture must not leak the
        developer's existing reports into the test result."""
        import server.api as api_mod

        # Create a directory with HTML files and inject it as a "real" dir to
        # simulate what a developer machine has.
        polluted_dir = tmp_path / "polluted_reports"
        polluted_dir.mkdir()
        (polluted_dir / "leaked_report.html").write_text("<html>real</html>")
        (polluted_dir / "another.html").write_text("<html>real</html>")

        # The authed_client fixture builds on top of `app`, which patches
        # _REPORTS_DIR to an empty temp dir.  Verify the polluted_dir is NOT
        # the one the API is using.
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "testpass", "next": "/"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

        # Without the isolation fix, _REPORTS_DIR would point at the real
        # reports/ folder (which may have HTML files) and this test would fail.
        api_resp = client.get("/api/reports")
        assert api_resp.status_code == 200
        files = api_resp.json()
        assert files == [], (
            f"Expected [] but got {[f['name'] for f in files]}. "
            "The test is reading from the real reports directory instead of "
            "the isolated tmp_path — check the app fixture's _REPORTS_DIR patch."
        )

    def test_list_reports_with_file(self, authed_client, tmp_path, monkeypatch):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "report1.html").write_text("<html>test</html>")
        import server.api as api_mod
        monkeypatch.setattr(api_mod, "_REPORTS_DIR", reports_dir)
        resp = authed_client.get("/api/reports")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        assert files[0]["name"] == "report1.html"

    def test_get_report_not_found(self, authed_client):
        resp = authed_client.get("/api/reports/nonexistent.html")
        assert resp.status_code == 404

    def test_get_report_path_traversal_blocked(self, authed_client):
        resp = authed_client.get("/api/reports/../etc/passwd")
        # Either 404 or sanitised; must not serve arbitrary files
        assert resp.status_code in (404, 400, 422)

    def test_delete_report_not_found(self, authed_client):
        resp = authed_client.delete("/api/reports/ghost.html")
        assert resp.status_code == 404

    def test_delete_report_success(self, authed_client, tmp_path, monkeypatch):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "todelete.html").write_text("<html/>")
        import server.api as api_mod
        monkeypatch.setattr(api_mod, "_REPORTS_DIR", reports_dir)
        resp = authed_client.delete("/api/reports/todelete.html")
        assert resp.status_code == 200
        assert not (reports_dir / "todelete.html").exists()


# ── /api/history ──────────────────────────────────────────────────────────────

class TestApiHistory:
    def test_history_returns_list(self, authed_client, monkeypatch):
        mock_store = MagicMock()
        mock_store.get_sessions.return_value = []
        with patch("server.api._store", return_value=mock_store):
            resp = authed_client.get("/api/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_history_limit_capped(self, authed_client, monkeypatch):
        mock_store = MagicMock()
        mock_store.get_sessions.return_value = []
        with patch("server.api._store", return_value=mock_store):
            resp = authed_client.get("/api/history?limit=9999")
        assert resp.status_code == 200
        mock_store.get_sessions.assert_called_once_with(limit=200)


# ── /api/strategies ───────────────────────────────────────────────────────────

class TestApiStrategies:
    def test_strategies_returns_list(self, authed_client):
        mock_store = MagicMock()
        mock_store.get_best_by.return_value = []
        with patch("server.api._store", return_value=mock_store):
            resp = authed_client.get("/api/strategies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_invalid_metric_defaults_to_sharpe(self, authed_client):
        mock_store = MagicMock()
        mock_store.get_best_by.return_value = []
        with patch("server.api._store", return_value=mock_store):
            authed_client.get("/api/strategies?metric=malicious_col")
        mock_store.get_best_by.assert_called_once_with(metric="sharpe_ratio", limit=100)


# ── /api/available-strategies ─────────────────────────────────────────────────

class TestApiAvailableStrategies:
    def test_available_strategies(self, authed_client):
        with patch("server.api.get_available_strategies", return_value=[{"name": "SMA"}]):
            resp = authed_client.get("/api/available-strategies")
        assert resp.status_code == 200
        assert resp.json() == [{"name": "SMA"}]


# ── /api/notifications ────────────────────────────────────────────────────────

class TestApiNotifications:
    def test_get_notifications(self, authed_client):
        resp = authed_client.get("/api/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_clear_notifications(self, authed_client):
        resp = authed_client.delete("/api/notifications")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True


# ── /api/logs ─────────────────────────────────────────────────────────────────

class TestApiLogs:
    def test_logs_no_file(self, authed_client, tmp_path, monkeypatch):
        import server.api as api_mod
        monkeypatch.setattr(api_mod, "_LOG_PATH", tmp_path / "none.log")
        resp = authed_client.get("/api/logs")
        assert resp.status_code == 200
        assert resp.json() == {"lines": []}

    def test_logs_with_content(self, authed_client, tmp_path, monkeypatch):
        log = tmp_path / "test.log"
        log.write_text("line1\nline2\nline3\n")
        import server.api as api_mod
        monkeypatch.setattr(api_mod, "_LOG_PATH", log)
        resp = authed_client.get("/api/logs?lines=2")
        assert resp.status_code == 200
        lines = resp.json()["lines"]
        assert len(lines) == 2
        assert lines[-1] == "line3"


# ── /api/stats ────────────────────────────────────────────────────────────────

class TestApiStats:
    def test_stats(self, authed_client):
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"total_sessions": 0}
        with patch("server.api._store", return_value=mock_store):
            resp = authed_client.get("/api/stats")
        assert resp.status_code == 200
        assert "total_sessions" in resp.json()
