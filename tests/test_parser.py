"""Tests for pipeline.parser — TradingView CSV parsing."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pipeline.models import ParseError
from pipeline.parser import parse_tradingview_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sample_trades.csv"


# ── Helpers ────────────────────────────────────────────────────────────────────

def write_csv(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "trades.csv"
    f.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return f


# ── Happy-path tests ───────────────────────────────────────────────────────────

class TestParseFixture:
    def test_returns_correct_trade_count(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        assert len(trades) == 20

    def test_detects_percent_unit(self):
        _, unit = parse_tradingview_csv(FIXTURE)
        assert unit == "%"

    def test_first_trade_is_long(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        assert trades[0].direction == "Long"

    def test_first_trade_profit(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        assert trades[0].profit == pytest.approx(2.50)

    def test_third_trade_is_short_and_losing(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        t = trades[2]
        assert t.direction == "Short"
        assert t.profit == pytest.approx(-1.20)
        assert t.is_loser is True

    def test_trade_numbers_are_sequential(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        nums = [t.trade_number for t in trades]
        assert nums == list(range(1, 21))

    def test_entry_exit_times_are_parsed(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        t = trades[0]
        assert t.entry_time.year == 2024
        assert t.entry_time.month == 1
        assert t.entry_time.day == 2
        assert t.exit_time.day == 3

    def test_entry_exit_prices_nonzero(self):
        trades, _ = parse_tradingview_csv(FIXTURE)
        for t in trades:
            assert t.entry_price > 0
            assert t.exit_price > 0


class TestAbsoluteUnitDetection:
    def test_detects_dollar_unit(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown
            1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00,0.00
            1,Exit Long,,2024-01-03 09:30,105.00,1,500.00,500.00,500.00,0.00
        """)
        _, unit = parse_tradingview_csv(f)
        assert unit == "$"


class TestColumnVariants:
    def test_handles_alternate_header_names(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Signal,Date/Time,Price,Quantity,Profit,Cum. Profit,MFE,MAE
            1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00 %,0.00 %
            1,Exit Long,,2024-01-03 09:30,102.50,1,2.50 %,2.50 %,2.50 %,0.00 %
        """)
        trades, _ = parse_tradingview_csv(f)
        assert len(trades) == 1
        assert trades[0].profit == pytest.approx(2.50)

    def test_skips_blank_lines_in_data(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown
            1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00 %,0.00 %
            1,Exit Long,,2024-01-03 09:30,102.50,1,2.50 %,2.50 %,2.50 %,0.00 %

            2,Entry Long,Open,2024-01-04 09:30,102.50,1,,,0.00 %,0.00 %
            2,Exit Long,,2024-01-05 09:30,100.00,1,-2.44 %,0.06 %,0.00 %,2.44 %
        """)
        trades, _ = parse_tradingview_csv(f)
        assert len(trades) == 2

    def test_tolerates_bom(self, tmp_path):
        f = tmp_path / "bom.csv"
        content = (
            "Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown\n"
            "1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00 %,0.00 %\n"
            "1,Exit Long,,2024-01-03 09:30,102.50,1,2.50 %,2.50 %,2.50 %,0.00 %\n"
        )
        f.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        trades, _ = parse_tradingview_csv(f)
        assert len(trades) == 1


# ── Error-path tests ───────────────────────────────────────────────────────────

class TestParseErrors:
    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(ParseError, match="not found"):
            parse_tradingview_csv(tmp_path / "nonexistent.csv")

    def test_raises_on_empty_file(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        with pytest.raises(ParseError, match="empty"):
            parse_tradingview_csv(f)

    def test_raises_on_no_header(self, tmp_path):
        f = write_csv(tmp_path, """
            this,is,not,a,valid,csv
            with,no,recognisable,header,row,x
        """)
        with pytest.raises(ParseError, match="header"):
            parse_tradingview_csv(f)

    def test_raises_on_missing_required_column(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Date/Time,Price,Contracts
            1,Entry Long,2024-01-02 09:30,100.00,1
            1,Exit Long,2024-01-03 09:30,102.50,1
        """)
        with pytest.raises(ParseError, match="Missing required columns"):
            parse_tradingview_csv(f)

    def test_raises_when_no_complete_pairs(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown
            1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00 %,0.00 %
        """)
        with pytest.raises(ParseError, match="No complete"):
            parse_tradingview_csv(f)

    def test_skips_incomplete_trades_and_returns_valid_ones(self, tmp_path):
        f = write_csv(tmp_path, """
            Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown
            1,Entry Long,Open,2024-01-02 09:30,100.00,1,,,0.00 %,0.00 %
            1,Exit Long,,2024-01-03 09:30,102.50,1,2.50 %,2.50 %,2.50 %,0.00 %
            2,Entry Long,Open,2024-01-04 09:30,102.50,1,,,0.00 %,0.00 %
        """)
        # Trade 2 has no exit — should be skipped, trade 1 returned
        trades, _ = parse_tradingview_csv(f)
        assert len(trades) == 1
        assert trades[0].trade_number == 1
