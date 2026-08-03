"""Tests for data.providers.yahoo — YahooFinanceProvider (all network mocked)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from data.providers.yahoo import YahooFinanceProvider, _to_yahoo_ticker


# ── symbol conversion ─────────────────────────────────────────────────────────

class TestToYahooTicker:
    def test_usdt_pair(self):
        assert _to_yahoo_ticker("BTCUSDT") == "BTC-USD"

    def test_usdc_pair(self):
        assert _to_yahoo_ticker("ETHUSDC") == "ETH-USD"

    def test_btc_pair(self):
        assert _to_yahoo_ticker("ETHBTC") == "ETH-BTC"

    def test_eth_pair(self):
        assert _to_yahoo_ticker("ADAETH") == "ADA-ETH"

    def test_no_known_suffix_passes_through(self):
        assert _to_yahoo_ticker("AAPL") == "AAPL"

    def test_uppercase_normalisation(self):
        assert _to_yahoo_ticker("btcusdt") == "BTC-USD"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_chart_response(n_bars: int = 5, start_ts: int = 1704067200) -> dict:
    """Build a minimal Yahoo Finance v8 chart JSON response."""
    timestamps = [start_ts + i * 3600 for i in range(n_bars)]
    quote = {
        "open"  : [100.0 + i for i in range(n_bars)],
        "high"  : [101.0 + i for i in range(n_bars)],
        "low"   : [ 99.0 + i for i in range(n_bars)],
        "close" : [100.5 + i for i in range(n_bars)],
        "volume": [1000.0  * (i + 1) for i in range(n_bars)],
    }
    return {
        "chart": {
            "result": [
                {
                    "timestamp" : timestamps,
                    "indicators": {"quote": [quote]},
                }
            ],
            "error": None,
        }
    }


def _mock_session(json_data: dict | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value = resp
    return session


# ── happy path ────────────────────────────────────────────────────────────────

class TestFetchMonth:
    def test_returns_dataframe(self):
        session = _mock_session(_make_chart_response(10))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 10

    def test_correct_columns(self):
        session = _mock_session(_make_chart_response(3))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_utc_datetimeindex(self):
        session = _mock_session(_make_chart_response(3))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"
        assert df.index.name == "open_time"

    def test_float64_columns(self):
        session = _mock_session(_make_chart_response(3))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        for col in ["open", "high", "low", "close", "volume"]:
            assert df[col].dtype == "float64"

    def test_ohlcv_values_correct(self):
        session = _mock_session(_make_chart_response(1, start_ts=1704067200))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df["open"].iloc[0] == pytest.approx(100.0)
        assert df["high"].iloc[0] == pytest.approx(101.0)
        assert df["low"].iloc[0]  == pytest.approx(99.0)
        assert df["close"].iloc[0] == pytest.approx(100.5)
        assert df["volume"].iloc[0] == pytest.approx(1000.0)

    def test_sorted_ascending(self):
        session = _mock_session(_make_chart_response(5))
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df.index.is_monotonic_increasing

    def test_no_duplicate_timestamps(self):
        # Inject a duplicate timestamp in the response
        data = _make_chart_response(3)
        data["chart"]["result"][0]["timestamp"].append(
            data["chart"]["result"][0]["timestamp"][0]
        )
        for col in data["chart"]["result"][0]["indicators"]["quote"][0]:
            data["chart"]["result"][0]["indicators"]["quote"][0][col].append(
                data["chart"]["result"][0]["indicators"]["quote"][0][col][0]
            )
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert not df.index.duplicated().any()


# ── unsupported interval ──────────────────────────────────────────────────────

class TestUnsupportedInterval:
    def test_unknown_interval_returns_empty(self):
        session = _mock_session()
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "999d", 2024, 1)
        assert df.empty
        # Should NOT have hit the network for unsupported intervals
        session.get.assert_not_called()


# ── empty / missing data ──────────────────────────────────────────────────────

class TestEmptyResponses:
    def test_empty_result_list_returns_empty_df(self):
        data = {"chart": {"result": [], "error": None}}
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df.empty

    def test_none_result_returns_empty_df(self):
        data = {"chart": {"result": None, "error": "Not Found"}}
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df.empty

    def test_empty_timestamps_returns_empty_df(self):
        data = _make_chart_response(0)
        data["chart"]["result"][0]["timestamp"] = []
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df.empty

    def test_404_returns_empty_df(self):
        session = _mock_session(status=404)
        # 404 → returns empty (ticker not found)
        df = YahooFinanceProvider(session).fetch_month("UNKNWN", "1h", 2024, 1)
        assert df.empty

    def test_nan_rows_dropped(self):
        data = _make_chart_response(4)
        # Inject None into one row's OHLCV
        for col in ["open", "high", "low", "close", "volume"]:
            data["chart"]["result"][0]["indicators"]["quote"][0][col][1] = None
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert len(df) == 3  # one row dropped


# ── error handling ────────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_5xx_raises_after_retries(self):
        resp = MagicMock()
        resp.status_code = 503
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.RequestException):
            YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)

    def test_connection_error_raises_after_retries(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("connection refused")

        with pytest.raises(requests.RequestException):
            YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)

    def test_malformed_json_returns_empty(self):
        data = {"chart": "not_a_dict"}
        session = _mock_session(data)
        df = YahooFinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df.empty


# ── interval mapping ──────────────────────────────────────────────────────────

class TestIntervalMapping:
    @pytest.mark.parametrize("interval,expected_yf", [
        ("1h",  "60m"),
        ("1d",  "1d"),
        ("1m",  "1m"),
        ("30m", "30m"),
        ("1w",  "1wk"),
    ])
    def test_mapped_intervals_hit_network(self, interval, expected_yf):
        session = _mock_session(_make_chart_response(2))
        YahooFinanceProvider(session).fetch_month("BTCUSDT", interval, 2024, 1)
        call_params = session.get.call_args[1]["params"]
        assert call_params["interval"] == expected_yf
