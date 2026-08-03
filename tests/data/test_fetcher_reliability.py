"""Tests for Phase 6 data fetcher reliability improvements."""
from __future__ import annotations

import io
import time
import zipfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from data.fetcher import BinanceProvider, _KEEP, _RAW_COLS


def _make_session(responses: list) -> MagicMock:
    """Return a mock session that returns responses in sequence."""
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _make_ok_response(status: int = 200, json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _make_error_response(status: int = 500) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return resp


def _make_vision_zip(n_rows: int = 3) -> bytes:
    """Build a minimal valid Binance Vision zip with n_rows candles."""
    rows = []
    for i in range(n_rows):
        ts_ms = (1_700_000_000 + i * 3600) * 1000
        rows.append(
            f"{ts_ms},40000.0,40100.0,39900.0,40050.0,10.0,"
            f"{ts_ms + 3_599_999},400000.0,500,5.0,200000.0,0"
        )
    csv_bytes = ("\n".join(rows) + "\n").encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BTCUSDT-1h-2023-11.csv", csv_bytes.decode())
    return buf.getvalue()


class TestRetryLogic:
    """Verify exponential-backoff retry on transient failures."""

    def test_vision_retries_on_5xx_then_succeeds(self):
        """Two 500 errors then a 200 — should succeed after retries."""
        zip_bytes = _make_vision_zip()
        ok = MagicMock()
        ok.status_code = 200
        ok.raise_for_status = MagicMock()
        ok.content = zip_bytes

        err1 = _make_error_response(500)
        err2 = _make_error_response(500)

        session = _make_session([err1, err2, ok])

        with patch("data.fetcher.time.sleep"):   # don't actually sleep
            p = BinanceProvider(session=session)
            df = p._try_vision("BTCUSDT", "1h", 2023, 11)

        assert df is not None
        assert not df.empty
        assert list(df.columns) == _KEEP
        assert session.get.call_count == 3

    def test_vision_gives_up_after_max_retries(self):
        """All attempts fail — should raise RequestException."""
        errors = [_make_error_response(500) for _ in range(4)]
        session = _make_session(errors)

        with patch("data.fetcher.time.sleep"):
            p = BinanceProvider(session=session)
            with pytest.raises(requests.RequestException):
                p._try_vision("BTCUSDT", "1h", 2023, 11)

    def test_vision_404_does_not_retry(self):
        """404 is not a transient error — return None immediately without retry."""
        not_found = _make_ok_response(404)
        session = _make_session([not_found])

        p = BinanceProvider(session=session)
        result = p._try_vision("BTCUSDT", "1h", 2099, 1)

        assert result is None
        assert session.get.call_count == 1   # no retries

    def test_api_retries_on_timeout(self):
        """ConnectionError then success — retry works for REST API too."""
        ok_batch = [[1_700_000_000_000 + i * 3_600_000, "40000", "40100", "39900",
                     "40050", "10", 0, "0", 0, "0", "0", "0"] for i in range(5)]
        ok_resp = _make_ok_response(200)
        ok_resp.json.return_value = ok_batch

        session = MagicMock()
        session.get.side_effect = [requests.ConnectionError("timeout"), ok_resp]

        with patch("data.fetcher.time.sleep"):
            p = BinanceProvider(session=session)
            df = p._fetch_api("BTCUSDT", "1h", 2023, 11)

        assert not df.empty
        assert session.get.call_count == 2


class TestCursorSafety:
    """Verify the API cursor never loops infinitely."""

    def test_stale_cursor_breaks_loop(self):
        """If the API returns the same batch twice, the loop must terminate."""
        # Batch with 1000 rows but a cursor that wouldn't advance past end_ms
        # Simulate by returning a batch where last[0] == cursor - 1
        start_ms = int(__import__("datetime").datetime(2023, 11, 1,
                        tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
        # Return a batch where last open_time is before start_ms — cursor would regress
        bad_batch = [[start_ms - 1, "40000", "40100", "39900", "40050", "10",
                      0, "0", 0, "0", "0", "0"] for _ in range(1000)]
        ok_resp = _make_ok_response(200)
        ok_resp.json.return_value = bad_batch

        session = _make_session([ok_resp])

        p = BinanceProvider(session=session)
        # Should not loop forever — the stale-cursor guard breaks it
        df = p._fetch_api("BTCUSDT", "1h", 2023, 11)
        # Called exactly once (cursor guard triggers immediately)
        assert session.get.call_count == 1


class TestDuplicateRemoval:
    """Verify _normalize() deduplicates rows with identical open_time."""

    def test_normalize_drops_duplicate_timestamps(self):
        import pandas as pd

        ts = 1_700_000_000_000
        rows = [
            [ts, "40000", "40100", "39900", "40050", "10",
             ts + 3_599_999, "400000", "500", "5", "200000", "0"],
            [ts, "40000", "40100", "39900", "40050", "10",   # duplicate
             ts + 3_599_999, "400000", "500", "5", "200000", "0"],
        ]
        raw = pd.DataFrame(rows, columns=_RAW_COLS)
        df = BinanceProvider._normalize(raw)
        assert len(df) == 1
        assert not df.index.duplicated().any()
