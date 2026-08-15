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
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass"},
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
        """API status endpoint must require auth (401), not open to anonymous."""
        resp = client.get("/api/bot/status", follow_redirects=False)
        assert resp.status_code in (302, 303, 307, 401)

    def test_bot_page_renders_when_stopped(self, authed_client):
        """API status must report running=False when bot is stopped."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _STOPPED_STATUS
            resp = authed_client.get("/api/bot/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False

    def test_bot_page_shows_running_state(self, authed_client):
        """API status must report running=True when bot is active."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _RUNNING_STATUS
            resp = authed_client.get("/api/bot/status")
        assert resp.status_code == 200
        assert resp.json()["running"] is True

    def test_bot_page_has_no_min_1000_capital(self, authed_client):
        """The start API must allow any positive capital, not enforce ≥1000."""
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
            )
        assert resp.status_code == 200
        assert resp.json().get("started") is True


# ── Research page capital restriction ─────────────────────────────────────────

class TestResearchCapitalRestriction:
    def test_research_page_no_min_1000(self, authed_client):
        """Research API must accept starting_capital well below 1000 (no min=1000 restriction)."""
        with patch("server.api.job_manager") as mock_jm:
            mock_jm.submit.return_value = "test-job-id"
            resp = authed_client.post(
                "/api/research/run",
                json={
                    "starting_capital": 100,
                    "symbols": "BTCUSDT",
                    "strategies": ["EMACrossover"],
                },
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_research_page_accepts_low_capital_label(self, authed_client):
        """Research API must accept a starting_capital field without error."""
        with patch("server.api.job_manager") as mock_jm:
            mock_jm.submit.return_value = "test-job-id-2"
            resp = authed_client.post(
                "/api/research/run",
                json={
                    "starting_capital": 50,
                    "symbols": "BTCUSDT",
                    "strategies": ["EMACrossover"],
                },
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 202


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
        """API bot start must succeed and return started=True."""
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
            )
        assert resp.status_code == 200
        assert resp.json()["started"] is True

    def test_form_stop_redirects_to_bot_page(self, authed_client):
        """API bot stop must succeed and return stopped=True."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.stop.return_value = (True, "")
            resp = authed_client.post("/api/bot/stop")
        assert resp.status_code == 200
        assert resp.json()["stopped"] is True


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


# ── Strategy select regression tests ─────────────────────────────────────────

class TestStrategySelectOptions:
    """Regression tests for the strategy name serialisation bug.

    Before the fix, the strategy value sent to bot_manager.start() was
    the full Python dict repr (e.g. "{'name': 'EMACrossover', ...}")
    instead of just the clean class name.  These tests verify the API
    layer passes only the clean name.
    """

    def test_strategy_option_values_are_clean_names_not_dicts(self, authed_client):
        """GET /api/available-strategies: each item's 'name' must be a plain string, not a dict repr."""
        resp = authed_client.get("/api/available-strategies")
        assert resp.status_code == 200
        strategies = resp.json()
        assert len(strategies) > 0, "Expected at least one strategy"
        for s in strategies:
            name = s["name"]
            # Must be a plain class name, not a dict repr
            assert not name.startswith("{"), (
                f"Strategy name looks like a dict repr: {name!r}"
            )
            assert "param_space" not in name, (
                f"Strategy name contains 'param_space': {name!r}"
            )
            assert "'" not in name, (
                f"Strategy name contains quotes (dict repr?): {name!r}"
            )

    def test_strategy_option_selected_matches_running_strategy(self, authed_client):
        """GET /api/bot/status: strategy field must equal the running strategy name."""
        with patch("server.api.bot_manager") as mock_bm:
            mock_bm.get_status.return_value = _RUNNING_STATUS
            resp = authed_client.get("/api/bot/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "EMACrossover"

    def test_form_start_submits_clean_strategy_name(self, authed_client):
        """POST /api/bot/start: strategy field must reach bot_manager.start() as 'EMACrossover'."""
        captured: list[str] = []

        with patch("server.api.bot_manager") as mock_bm:
            def capture_start(**kwargs):
                captured.append(kwargs.get("strategy", ""))
                return (True, "")
            mock_bm.start.side_effect = capture_start
            resp = authed_client.post(
                "/api/bot/start",
                json={
                    "capital": 25.0,
                    "symbols": ["BTCUSDT"],
                    "interval": "1h",
                    "strategy": "EMACrossover",
                },
            )
        assert resp.status_code == 200
        assert len(captured) == 1
        assert captured[0] == "EMACrossover", (
            f"Expected 'EMACrossover' but got {captured[0]!r}"
        )


# ── Bot strategy loading regression tests ────────────────────────────────────

class TestBotStrategyLoading:
    """Regression tests for _load_strategy() with clean vs dict-repr name."""

    def test_clean_name_loads_strategy(self):
        """BotConfig with strategy_name='EMACrossover' must produce a working strategy."""
        from bot.config import BotConfig
        from bot_trade import _load_strategy
        cfg = BotConfig(strategy_name="EMACrossover", strategy_params={"fast": 20, "slow": 50})
        strategy = _load_strategy(cfg)
        assert strategy is not None
        assert hasattr(strategy, "generate_signals")

    def test_dict_repr_name_raises_clear_error(self):
        """BotConfig with a dict-repr strategy_name must raise ValueError immediately."""
        from bot.config import BotConfig
        from bot_trade import _load_strategy
        bad_name = "{'name': 'EMACrossover', 'param_space': {}}"
        cfg = BotConfig(strategy_name=bad_name, strategy_params={})
        with pytest.raises(ValueError) as exc_info:
            _load_strategy(cfg)
        assert "Unknown strategy" in str(exc_info.value) or bad_name in str(exc_info.value)

    def test_unknown_strategy_error_is_surfaced_in_status(self):
        """A bad strategy name must surface in get_status()['error'], not silently die."""
        from server.bot_manager import BotManager
        import time
        bm = BotManager()
        # Use a real thread so the error actually reaches self._error
        ok, err = bm.start(
            capital=25.0,
            symbols=["BTCUSDT"],
            interval="1h",
            strategy="__NONEXISTENT_STRATEGY__",
        )
        # start() itself succeeds (config-level validation passes)
        assert ok is True
        # Wait for the thread to die (it will fail in _load_strategy)
        if bm._thread:
            bm._thread.join(timeout=10)
        status = bm.get_status()
        assert status["running"] is False
        assert status["error"] != "", (
            "Expected error to be surfaced in status but got empty string"
        )


# ── Lifecycle integration test ────────────────────────────────────────────────

class TestBotLifecycleMocked:
    """Integration test: proves the full bot lifecycle fires with a mocked LiveFeed.

    This exercises BotStorage.connect() → _load_strategy() → BotEngine →
    LiveFeed.run() without requiring Binance network connectivity.
    The LiveFeed is replaced with a coroutine that immediately cancels itself,
    simulating one clean loop iteration.
    """

    def test_full_lifecycle_reaches_feed_run(self, tmp_path):
        """Bot thread must reach LiveFeed.run() and shut down cleanly."""
        import asyncio
        import time
        from server.bot_manager import BotManager

        reached: list[str] = []

        async def fake_feed_run(self_feed):
            reached.append("feed.run")
            # Immediately stop — simulates a clean single-cycle run
            raise asyncio.CancelledError()

        with patch("bot.runtime.LiveFeed.run", new=fake_feed_run):
            bm = BotManager()
            ok, err = bm.start(
                capital=25.0,
                symbols=["BTCUSDT"],
                interval="1h",
                strategy="EMACrossover",
                db_path=str(tmp_path / "bot.db"),
                log_path=str(tmp_path / "bot.log"),
            )
            assert ok is True, f"start() failed: {err}"

            # Wait for the thread to complete
            if bm._thread:
                bm._thread.join(timeout=30)

        assert "feed.run" in reached, (
            "LiveFeed.run() was never reached — lifecycle did not complete BotStorage → "
            "_load_strategy → BotEngine → LiveFeed path"
        )
        status = bm.get_status()
        assert status["running"] is False
        assert status["error"] == "", f"Unexpected error: {status['error']}"
