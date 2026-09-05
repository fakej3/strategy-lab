"""Independent golden tests for the conservative V2 metric core."""

import math
import pandas as pd
import pytest

from research.v2_metrics import calculate_v2_metrics


def equity():
    return pd.Series(
        [100.0, 110.0, 105.0, 120.0],
        index=pd.to_datetime([
            "2020-01-01 00:00:00",
            "2020-07-02 00:00:00",
            "2021-01-01 00:00:00",
            "2021-07-02 00:00:00",
        ], utc=True),
    )


def test_total_return_and_elapsed_time_cagr():
    m = calculate_v2_metrics(equity())
    assert m.total_return == pytest.approx(0.20)
    elapsed_years = (
        pd.Timestamp("2021-07-02", tz="UTC") - pd.Timestamp("2020-01-01", tz="UTC")
    ).total_seconds() / (365.2425 * 86400)
    expected_cagr = (120.0 / 100.0) ** (1.0 / elapsed_years) - 1.0
    assert m.cagr == pytest.approx(expected_cagr)


def test_sharpe_requires_explicit_annualization():
    m = calculate_v2_metrics(equity())
    assert math.isnan(m.sharpe)
    m2 = calculate_v2_metrics(equity(), annualization=2)
    assert math.isfinite(m2.sharpe)


def test_drawdown_is_peak_to_trough():
    m = calculate_v2_metrics(equity())
    assert m.max_drawdown == pytest.approx(1.0 - 105.0 / 110.0)


def test_invalid_equity_fails_closed():
    bad = equity().copy()
    bad.iloc[1] = 0
    with pytest.raises(ValueError):
        calculate_v2_metrics(bad)
