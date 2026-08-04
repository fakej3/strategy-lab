"""Regression tests for paper trading bot integration with the research server.

Tests cover:
  - /bot page renders without error
  - POST /bot/start and /bot/stop form routes
  - GET /api/bot/status JSON shape
  - POST /api/bot/start and /api/bot/stop JSON API
  - Low-capital (20-25 USDT) config validation passes
  - No min=1000 restriction on research starting_capital field
  - Only one bot instance may run at a time
"""
from __future__ import annotations

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


@pytest.fixture()
def authed_client(client):
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass", "next": "/"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return client


# ── Idle-state status fixture ─────────────────────────────────────────────────

_STOPPED_STATUS = {
    "running": False,
    "started_at": None,
    "stopped_at": None,
    "error": "",
    "symbols": [],
    "interval": "—",
    "strategy": "",
    "capital": 0.0,
    "cash": 0.0,
    "equity": 0.0,
    "unrealized_pnl": 0.0,
    "realized_pnl": 0.0,
    "drawdown": 0.0,
    "open_positions": [],
    "recent_trades": [],
    "log_tail": [],
}

_RUNNING_STATUS = {
    **_STOPPED_STATUS,
    "running": True,
    "started_at": "2025-01-01T00:00:00+00:00",
    "symbols": ["BTCUSDT"],
    "interval": "1h",
    "strategy": "EMACrossover",
    "capital": 25.0,
    "cash": 24.8,
    "equity": 25.0,
}


# ── Bot page ──────────────────────────────────────────────────────────────────

class TestBotPage:
    def test_bot_page_requires_auth(self, client):
        resp = client.get("/bot", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)

    def test_bot_page_renders_when_stopped(self, authed_client):
        with patch("server.app.bot_manager") as mock_bm, \
             patch("server.bot_manager.bot_manager") as _:
            mock_bm.get_status.return_value = _STOPPED_STATUS
            resp = authed_client.get("/bot")
        assert resp.status_code == 200
        assert b"Paper Bot" in resp.content
        assert b"Start Bot" in resp.content

    def test_bot_page_shows_running_state(self, authed_client):
        with patch("server.app.bot_manager") as mock_bm, \
             patch("server.bot_manager.bot_manager") as _:
            mock_bm.get_status.return_value = _RUNNING_STATUS
            resp = authed_client.get("/bot")
        assert resp.status_code == 200
        assert b"Stop Bot" in resp.content or b"Running" in resp.content

    def test_bot_page_has_no_min_1000_capital(self, authed_client):
        """The start form must allow any positive capital, not enforce ≥1000."""
        with patch("server.app.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _STOPPED_STATUS
            resp = authed_client.get("/bot")
        assert resp.status_code == 200
        assert b'min="1000"' not in resp.content


# ── Research page capital restriction ─────────────────────────────────────────

class TestResearchCapitalRestriction:
    def test_research_page_no_min_1000(self, authed_client):
        """The research form starting_capital input must NOT have min=1000."""
        resp = authed_client.get("/research")
        assert resp.status_code == 200
        assert b'min="1000"' not in resp.content

    def test_research_page_accepts_low_capital_label(self, authed_client):
        """The research form starting_capital input should be present."""
        resp = authed_client.get("/research")
        assert resp.status_code == 200
        assert b"starting_capital" in resp.content


# ── API status endpoint ───────────────────────────────────────────────────────

class TestBotStatusAPI:
    def test_status_unauthenticated(self, client):
        resp = client.get("/api/bot/status", follow_redirects=False)
        assert resp.status_code in (302, 303, 307, 401)

    def test_status_returns_json_shape(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _STOPPED_STATUS
            resp = authed_client.get("/api/bot/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "symbols" in data
        assert "equity" in data
        assert "cash" in data
        assert "open_positions" in data
        assert "recent_trades" in data
        assert "log_tail" in data

    def test_status_running_true(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _RUNNING_STATUS
            resp = authed_client.get("/api/bot/status")
        assert resp.status_code == 200
        assert resp.json()["running"] is True


# ── API start/stop endpoints ──────────────────────────────────────────────────

class TestBotStartStopAPI:
    def test_start_requires_auth(self, client):
        resp = client.post(
            "/api/bot/start",
            json={"capital": 25.0},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 307, 401)

    def test_start_success(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.start.return_value = (True, "")
            resp = authed_client.post(
                "/api/bot/start",
                json={
                    "capital": 25.0,
                    "symbols": ["BTCUSDT"],
                    "interval": "1h",
                    "strategy": "EMACrossover",
                },
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 200
        assert resp.json()["started"] is True

    def test_start_already_running_returns_409(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.start.return_value = (False, "Bot is already running")
            resp = authed_client.post(
                "/api/bot/start",
                json={"capital": 25.0, "symbols": ["BTCUSDT"],
                      "interval": "1h", "strategy": "EMACrossover"},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 409

    def test_start_invalid_capital_returns_422(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            resp = authed_client.post(
                "/api/bot/start",
                json={"capital": 0, "symbols": ["BTCUSDT"],
                      "interval": "1h", "strategy": "EMACrossover"},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 422

    def test_stop_success(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.stop.return_value = (True, "")
            resp = authed_client.post("/api/bot/stop")
        assert resp.status_code == 200
        assert resp.json()["stopped"] is True

    def test_stop_not_running_returns_409(self, authed_client):
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.stop.return_value = (False, "Bot is not running")
            resp = authed_client.post("/api/bot/stop")
        assert resp.status_code == 409

    def test_start_with_low_capital_20_usdt(self, authed_client):
        """20 USDT capital must be accepted — no minimum above 1."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.start.return_value = (True, "")
            resp = authed_client.post(
                "/api/bot/start",
                json={"capital": 20.0, "symbols": ["BTCUSDT"],
                      "interval": "1h", "strategy": "EMACrossover"},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 200

    def test_start_with_low_capital_25_usdt(self, authed_client):
        """25 USDT capital must be accepted."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.start.return_value = (True, "")
            resp = authed_client.post(
                "/api/bot/start",
                json={"capital": 25.0, "symbols": ["BTCUSDT"],
                      "interval": "1h", "strategy": "EMACrossover"},
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 200


# ── Form routes ───────────────────────────────────────────────────────────────

class TestBotFormRoutes:
    def test_form_start_redirects_to_bot_page(self, authed_client):
        with patch("server.app.bot_manager") as mock_bm:
            mock_bm.start.return_value = (True, "")
            resp = authed_client.post(
                "/bot/start",
                data={
                    "capital": "25",
                    "symbols": "BTCUSDT",
                    "interval": "1h",
                    "strategy": "EMACrossover",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert resp.headers["location"].endswith("/bot")

    def test_form_stop_redirects_to_bot_page(self, authed_client):
        with patch("server.app.bot_manager") as mock_bm:
            mock_bm.stop.return_value = (True, "")
            resp = authed_client.post("/bot/stop", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].endswith("/bot")


# ── BotManager unit tests (no server) ────────────────────────────────────────

class TestBotManagerLowCapital:
    """Verify BotConfig validates cleanly at low capital amounts."""

    def test_20_usdt_config_is_valid(self):
        from bot.config import BotConfig, FeedConfig, RiskConfig
        cfg = BotConfig(
            paper_capital=20.0,
            risk=RiskConfig(
                max_position_size_usd=16.0,
                max_daily_loss_usd=1.0,
            ),
        )
        assert cfg.paper_capital == 20.0

    def test_25_usdt_config_is_valid(self):
        from bot.config import BotConfig
        cfg = BotConfig(paper_capital=25.0)
        assert cfg.paper_capital == 25.0

    def test_zero_capital_raises(self):
        from bot.config import BotConfig
        import pytest
        with pytest.raises(ValueError):
            BotConfig(paper_capital=0.0)

    def test_negative_capital_raises(self):
        from bot.config import BotConfig
        with pytest.raises(ValueError):
            BotConfig(paper_capital=-5.0)

    def test_bot_manager_start_with_20_usdt_builds_config(self):
        """BotManager.start() with 20 USDT must accept the config (mock thread)."""
        from server.bot_manager import BotManager
        bm = BotManager()
        with patch.object(bm, "_thread", None), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock(start=MagicMock())
            ok, err = bm.start(
                capital=20.0,
                symbols=["BTCUSDT"],
                interval="1h",
                strategy="EMACrossover",
            )
        assert ok is True, f"Expected success, got error: {err}"
        assert err == ""

    def test_bot_manager_start_with_25_usdt_builds_config(self):
        from server.bot_manager import BotManager
        bm = BotManager()
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock(start=MagicMock())
            ok, err = bm.start(
                capital=25.0,
                symbols=["BTCUSDT"],
                interval="1h",
                strategy="EMACrossover",
            )
        assert ok is True, f"Expected success, got error: {err}"

    def test_bot_manager_double_start_returns_error(self):
        """Second start() call must return (False, error_message)."""
        from server.bot_manager import BotManager
        bm = BotManager()
        with patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock(start=MagicMock(), is_alive=MagicMock(return_value=True))
            bm.start(capital=25.0, symbols=["BTCUSDT"], interval="1h", strategy="EMACrossover")
            ok, err = bm.start(capital=25.0, symbols=["BTCUSDT"], interval="1h", strategy="EMACrossover")
        assert ok is False
        assert err != ""

    def test_bot_manager_stop_when_not_running(self):
        """stop() when bot is not running returns (False, message)."""
        from server.bot_manager import BotManager
        bm = BotManager()
        ok, err = bm.stop()
        assert ok is False
        assert err != ""

    def test_bot_manager_status_when_idle(self):
        """get_status() always returns a well-shaped dict."""
        from server.bot_manager import BotManager
        bm = BotManager()
        s = bm.get_status()
        assert isinstance(s, dict)
        assert "running" in s
        assert s["running"] is False
        assert "open_positions" in s
        assert "recent_trades" in s
        assert "log_tail" in s
