"""Tests for data.fetcher.BinanceProvider — network layer (mocked)."""
from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data.fetcher import BinanceProvider


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_kline_row(open_time_ms: int, o=1.0, h=1.1, lo=0.9, c=1.05, v=100.0) -> list:
    return [open_time_ms, str(o), str(h), str(lo), str(c), str(v),
            open_time_ms + 3_599_999, "0", "0", "0", "0", "0"]


def _make_vision_zip(rows: list[list], filename: str = "BTCUSDT-1h-2024-01.csv") -> bytes:
    csv_body = "\n".join(",".join(str(v) for v in row) for row in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, csv_body)
    return buf.getvalue()


def _mock_session(status: int, content: bytes | None = None, json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if content is not None:
        resp.content = content
    if json_data is not None:
        resp.json.return_value = json_data
    session = MagicMock()
    session.get.return_value = resp
    return session


# ── Vision path ───────────────────────────────────────────────────────────────

class TestVisionPath:
    def test_returns_dataframe_on_200(self):
        rows = [_make_kline_row(1_704_067_200_000 + i * 3_600_000) for i in range(5)]
        session = _mock_session(200, content=_make_vision_zip(rows))
        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert len(df) == 5

    def test_correct_columns(self):
        rows = [_make_kline_row(1_704_067_200_000)]
        session = _mock_session(200, content=_make_vision_zip(rows))
        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_index_is_utc_datetimeindex(self):
        rows = [_make_kline_row(1_704_067_200_000)]
        session = _mock_session(200, content=_make_vision_zip(rows))
        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"
        assert df.index.name == "open_time"

    def test_numeric_columns_are_float64(self):
        rows = [_make_kline_row(1_704_067_200_000)]
        session = _mock_session(200, content=_make_vision_zip(rows))
        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        for col in ["open", "high", "low", "close", "volume"]:
            assert df[col].dtype == "float64"

    def test_correct_ohlcv_values(self):
        rows = [_make_kline_row(1_704_067_200_000, o=42000.0, h=42500.0, lo=41800.0, c=42300.0, v=250.5)]
        session = _mock_session(200, content=_make_vision_zip(rows))
        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert df["open"].iloc[0] == pytest.approx(42000.0)
        assert df["high"].iloc[0] == pytest.approx(42500.0)
        assert df["low"].iloc[0]  == pytest.approx(41800.0)
        assert df["close"].iloc[0] == pytest.approx(42300.0)
        assert df["volume"].iloc[0] == pytest.approx(250.5)


# ── REST API fallback ─────────────────────────────────────────────────────────

class TestAPIFallback:
    def test_falls_back_to_api_on_404(self):
        rows = [_make_kline_row(1_704_067_200_000)]
        vision_resp = MagicMock()
        vision_resp.status_code = 404

        api_resp = MagicMock()
        api_resp.status_code = 200
        api_resp.json.return_value = rows

        session = MagicMock()
        session.get.side_effect = [vision_resp, api_resp]

        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2024, 1)
        assert len(df) == 1

    def test_api_pagination_stops_when_batch_smaller_than_limit(self):
        # Use 1-minute bars: January 2024 has 44,640 bars, so 1000 rows stay
        # well within the month (cursor doesn't pass end_ms after batch1).
        first_open = 1_704_067_200_000  # Jan 1, 2024 00:00:00 UTC
        interval_ms = 60_000            # 1 minute
        batch1 = [_make_kline_row(first_open + i * interval_ms) for i in range(1000)]
        batch2 = [_make_kline_row(first_open + 1000 * interval_ms + i * interval_ms) for i in range(50)]

        vision_resp = MagicMock()
        vision_resp.status_code = 404

        api_resp1 = MagicMock()
        api_resp1.status_code = 200
        api_resp1.json.return_value = batch1

        api_resp2 = MagicMock()
        api_resp2.status_code = 200
        api_resp2.json.return_value = batch2

        session = MagicMock()
        session.get.side_effect = [vision_resp, api_resp1, api_resp2]

        df = BinanceProvider(session).fetch_month("BTCUSDT", "1m", 2024, 1)
        assert len(df) == 1050

    def test_empty_api_response_returns_empty_df(self):
        vision_resp = MagicMock()
        vision_resp.status_code = 404

        api_resp = MagicMock()
        api_resp.status_code = 200
        api_resp.json.return_value = []

        session = MagicMock()
        session.get.side_effect = [vision_resp, api_resp]

        df = BinanceProvider(session).fetch_month("BTCUSDT", "1h", 2099, 1)
        assert df.empty

    def test_vision_url_is_correct(self):
        vision_resp = MagicMock()
        vision_resp.status_code = 404

        api_resp = MagicMock()
        api_resp.status_code = 200
        api_resp.json.return_value = []

        session = MagicMock()
        session.get.side_effect = [vision_resp, api_resp]

        BinanceProvider(session).fetch_month("ETHUSDT", "4h", 2023, 6)

        vision_url = session.get.call_args_list[0][0][0]
        assert "ETHUSDT" in vision_url
        assert "4h" in vision_url
        assert "2023-06" in vision_url
