"""V2 trade-ledger invariants.

These tests make accounting failures impossible to hide behind aggregate metrics.
"""

import pandas as pd
import pytest

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import Signal


class EntryThenExit:
    def generate_signals(self, bars):
        s = pd.Series(Signal.HOLD, index=bars.index, dtype=object)
        if len(s) >= 3:
            s.iloc[0] = Signal.BUY
            s.iloc[2] = Signal.EXIT
        return s


def bars():
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0, 110.0],
            "high": [100.0, 100.0, 110.0, 110.0],
            "low": [100.0, 100.0, 110.0, 110.0],
            "close": [100.0, 100.0, 110.0, 110.0],
            "volume": [1.0] * 4,
        },
        index=pd.date_range("2026-01-01", periods=4, freq="h"),
    )


def test_trade_ledger_cost_reconciliation():
    trade = BacktestExecutor(
        EngineConfig(position_size=2.0, fee_rate=0.01, slippage_pct=0.0)
    ).run(bars(), EntryThenExit())[0]

    assert trade.gross_pnl == pytest.approx(20.0)
    assert trade.entry_fee == pytest.approx(2.0)
    assert trade.exit_fee == pytest.approx(2.2)
    assert trade.net_pnl == pytest.approx(
        trade.gross_pnl - trade.entry_fee - trade.exit_fee
    )


def test_trade_ledger_price_size_pnl_reconciliation():
    trade = BacktestExecutor(
        EngineConfig(position_size=3.0, fee_rate=0.0, slippage_pct=0.0)
    ).run(bars(), EntryThenExit())[0]

    expected_gross = (trade.exit_price - trade.entry_price) * trade.size
    assert trade.gross_pnl == pytest.approx(expected_gross)
    assert trade.net_pnl == pytest.approx(expected_gross)


def test_trade_ledger_records_complete_execution_costs():
    trade = BacktestExecutor(
        EngineConfig(position_size=2.0, fee_rate=0.001, slippage_pct=0.005)
    ).run(bars(), EntryThenExit())[0]

    assert trade.entry_fee > 0
    assert trade.exit_fee > 0
    assert trade.entry_slippage > 0
    assert trade.exit_slippage > 0
    assert trade.entry_price != pytest.approx(100.0)
    assert trade.exit_price != pytest.approx(110.0)
    assert trade.net_pnl == pytest.approx(
        trade.gross_pnl - trade.entry_fee - trade.exit_fee
    )
