from types import SimpleNamespace

import pandas as pd

from jobs.backtest_job import _verify_accounting


def _result(*, reported_profit=50.0, trade_pnl=50.0, ending=1050.0):
    return SimpleNamespace(
        starting_capital=1000.0,
        ending_equity=ending,
        net_profit=reported_profit,
        trades=[SimpleNamespace(net_pnl=trade_pnl)],
        equity_curve=pd.Series([1000.0, ending]),
    )


def test_accounting_verification_accepts_consistent_result():
    evidence = _verify_accounting(_result())
    assert evidence["passed"] is True
    assert all(evidence["checks"].values())


def test_accounting_verification_rejects_trade_pnl_mismatch():
    evidence = _verify_accounting(_result(trade_pnl=40.0))
    assert evidence["passed"] is False
    assert evidence["checks"]["trade_pnl_matches_profit"] is False


def test_accounting_verification_rejects_reported_profit_mismatch():
    evidence = _verify_accounting(_result(reported_profit=60.0))
    assert evidence["passed"] is False
    assert evidence["checks"]["reported_profit_matches_equity"] is False


def test_accounting_verification_rejects_equity_curve_mismatch():
    result = _result(ending=1050.0)
    result.equity_curve = pd.Series([1000.0, 1049.0])
    evidence = _verify_accounting(result)
    assert evidence["passed"] is False
    assert evidence["checks"]["ending_equity_matches_curve"] is False
