"""Tests for research.report — ResearchReport and build_report."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig
from research.report import ResearchReport, build_report


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _bars(n: int = 50, price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({
        "open"  : price,
        "high"  : price + 1.0,
        "low"   : price - 1.0,
        "close" : price,
        "volume": 1_000.0,
    }, index=idx)


class _Hold(StrategyBase):
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(Signal.HOLD, index=bars.index, dtype=object)


def _make_result(bars=None):
    if bars is None:
        bars = _bars()
    cfg  = PortfolioConfig(starting_capital=10_000.0)
    ec   = EngineConfig(fee_rate=0.0, slippage_pct=0.0)
    return PortfolioEngine(cfg).run(bars, _Hold(), ec)


# ── build_report ──────────────────────────────────────────────────────────────

class TestBuildReport:
    def test_returns_research_report(self):
        result = _make_result()
        report = build_report(result, "TestStrategy", "AAPL")
        assert isinstance(report, ResearchReport)

    def test_strategy_name_stored(self):
        result = _make_result()
        report = build_report(result, "MyStrat", "BTC")
        assert report.strategy_name == "MyStrat"

    def test_symbol_stored(self):
        result = _make_result()
        report = build_report(result, "X", "ETHUSDT")
        assert report.symbol == "ETHUSDT"

    def test_bars_per_year_stored(self):
        result = _make_result()
        report = build_report(result, bars_per_year=8760)
        assert report.bars_per_year == 8760

    def test_start_end_dates_nonempty(self):
        result = _make_result()
        report = build_report(result)
        assert report.start_date != ""
        assert report.end_date   != ""

    def test_portfolio_has_required_keys(self):
        result = _make_result()
        report = build_report(result)
        required = {"starting_capital", "ending_equity", "total_return", "max_drawdown_pct"}
        assert required.issubset(set(report.portfolio.keys()))

    def test_trades_summary_has_required_keys(self):
        result = _make_result()
        report = build_report(result)
        required = {"total_trades", "winners", "losers"}
        assert required.issubset(set(report.trades_summary.keys()))


# ── to_json ───────────────────────────────────────────────────────────────────

class TestToJson:
    def test_returns_valid_json_string(self):
        result = _make_result()
        report = build_report(result)
        s = report.to_json()
        parsed = json.loads(s)
        assert isinstance(parsed, dict)

    def test_json_contains_strategy_name(self):
        result = _make_result()
        report = build_report(result, "Foo")
        parsed = json.loads(report.to_json())
        assert parsed["strategy_name"] == "Foo"

    def test_json_contains_metrics_key(self):
        result = _make_result()
        report = build_report(result)
        parsed = json.loads(report.to_json())
        assert "metrics" in parsed

    def test_json_contains_portfolio_key(self):
        result = _make_result()
        report = build_report(result)
        parsed = json.loads(report.to_json())
        assert "portfolio" in parsed

    def test_custom_indent(self):
        result = _make_result()
        report = build_report(result)
        s4 = report.to_json(indent=4)
        s2 = report.to_json(indent=2)
        assert len(s4) != len(s2)


# ── to_csv ────────────────────────────────────────────────────────────────────

class TestToCsv:
    def test_returns_string(self):
        result = _make_result()
        report = build_report(result)
        assert isinstance(report.to_csv(), str)

    def test_csv_has_header(self):
        result = _make_result()
        report = build_report(result)
        csv_text = report.to_csv()
        assert csv_text.startswith("key,value")

    def test_csv_contains_strategy_name(self):
        result = _make_result()
        report = build_report(result, "BarStrat")
        csv_text = report.to_csv()
        assert "BarStrat" in csv_text

    def test_csv_parseable_as_key_value(self):
        import csv, io
        result = _make_result()
        report = build_report(result)
        rows   = list(csv.reader(io.StringIO(report.to_csv())))
        # Header + data rows
        assert rows[0] == ["key", "value"]
        assert len(rows) > 1


# ── to_dict ───────────────────────────────────────────────────────────────────

class TestToDict:
    def test_all_top_level_keys_present(self):
        result = _make_result()
        report = build_report(result)
        d = report.to_dict()
        assert all(k in d for k in (
            "strategy_name", "symbol", "start_date", "end_date",
            "bars_per_year", "portfolio", "metrics", "trades_summary"
        ))
