"""V2 data-quality gates.

Invalid market data must fail closed instead of producing plausible-looking
backtest results.
"""

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase


class HoldStrategy(StrategyBase):
    def generate_signals(self, bars):
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


def make_bars(index=None):
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
        },
        index=index or pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )


def run(data):
    return BacktestExecutor(EngineConfig(fee_rate=0, slippage_pct=0)).run(data, HoldStrategy())


def test_duplicate_timestamps_are_rejected():
    data = make_bars(pd.DatetimeIndex([
        "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", "2026-01-01T01:00:00Z"
    ]))
    with pytest.raises(ValueError, match="duplicate timestamps"):
        run(data)


def test_non_monotonic_timestamps_are_rejected():
    data = make_bars(pd.DatetimeIndex([
        "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z", "2026-01-01T01:00:00Z"
    ]))
    with pytest.raises(ValueError, match="monotonically increasing"):
        run(data)


def test_non_numeric_ohlc_is_rejected():
    data = make_bars()
    data.loc[data.index[1], "close"] = "not-a-price"
    with pytest.raises(ValueError, match="numeric"):
        run(data)


def test_impossible_candle_is_rejected():
    data = make_bars()
    data.loc[data.index[1], "high"] = 98.0
    with pytest.raises(ValueError, match="high < low"):
        run(data)


def test_nan_ohlc_is_rejected():
    data = make_bars()
    data.loc[data.index[1], "open"] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        run(data)
