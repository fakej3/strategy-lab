"""
TradingView Strategy Tester CSV parser.

Supports the "List of Trades" CSV format exported from TradingView's
Strategy Tester panel. Handles both percentage-mode and absolute-value-mode
exports, and tolerates minor column-name variations across TV versions.

Expected CSV structure (one entry row + one exit row per trade):

    Trade #,Type,Signal,Date/Time,Price,Contracts,Profit,Cum. Profit,Run-up,Drawdown
    1,Entry Long,Open Long,2024-01-02 09:30,45000.00,0.01,,,0.00 %,0.00 %
    1,Exit Long,,2024-01-03 15:00,46125.00,0.01,2.50 %,2.50 %,2.50 %,0.00 %
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import ParseError, Trade

# ── Column name aliases ────────────────────────────────────────────────────────
_COLUMN_ALIASES: dict[str, list[str]] = {
    "trade_number": ["Trade #", "Trade#", "Trade"],
    "type":         ["Type"],
    "signal":       ["Signal"],
    "datetime":     ["Date/Time", "Date Time", "DateTime", "Date"],
    "price":        ["Price"],
    "contracts":    ["Contracts", "Quantity", "Qty", "Size"],
    "profit":       ["Profit"],
    "cum_profit":   ["Cum. Profit", "Cumulative Profit", "Cum Profit"],
    "run_up":       ["Run-up", "Run up", "Runup", "MFE"],
    "drawdown":     ["Drawdown", "MAE"],
}

_REQUIRED = ["trade_number", "type", "datetime", "price", "contracts", "profit"]

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%b %d, %Y %H:%M",
    "%B %d, %Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _clean_numeric(value: str) -> Optional[float]:
    """Strip %, commas, and whitespace; return float or None if blank/invalid."""
    if not value or not value.strip():
        return None
    cleaned = re.sub(r"[%,\s]", "", value.strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_unit(exit_rows: list[list[str]], profit_col: int) -> str:
    """Return '%' if any exit-row profit cell contains a '%' sign, else '$'."""
    for row in exit_rows:
        if profit_col < len(row) and "%" in row[profit_col]:
            return "%"
    return "$"


def _parse_datetime(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ParseError(
        f"Unrecognised date/time format: '{raw}'. "
        f"Expected formats like '2024-01-02 09:30' or 'Jan 02, 2024 09:30'."
    )


def _resolve_columns(header: list[str]) -> dict[str, int]:
    """Map canonical column keys to their 0-based indices in the header row."""
    stripped = {h.strip(): i for i, h in enumerate(header)}
    resolved: dict[str, int] = {}
    for key, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in stripped:
                resolved[key] = stripped[alias]
                break
    return resolved


def _safe_float(row: list[str], col: Optional[int]) -> float:
    if col is None or col >= len(row):
        return 0.0
    return _clean_numeric(row[col]) or 0.0


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_tradingview_csv(filepath: str | Path) -> tuple[list[Trade], str]:
    """
    Parse a TradingView Strategy Tester trade-list CSV.

    Returns:
        (trades, profit_unit) where trades is a list of completed Trade
        objects and profit_unit is either '%' or '$'.

    Raises:
        ParseError: if the file is missing, empty, malformed, or contains
                    no complete entry/exit pairs.
    """
    path = Path(filepath)
    if not path.exists():
        raise ParseError(f"File not found: {filepath}")
    if path.stat().st_size == 0:
        raise ParseError(f"File is empty: {filepath}")

    # Read all rows, tolerating BOM and UTF-8
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        raw_rows: list[list[str]] = [row for row in reader]

    # ── Locate the header row ──────────────────────────────────────────────
    header_idx: Optional[int] = None
    for i, row in enumerate(raw_rows):
        joined = ",".join(row).lower()
        if "trade" in joined and ("profit" in joined or "type" in joined):
            header_idx = i
            break

    if header_idx is None:
        raise ParseError(
            "Could not find a header row. "
            "Expected columns: Trade #, Type, Date/Time, Price, Contracts, Profit."
        )

    header = raw_rows[header_idx]
    data_rows = raw_rows[header_idx + 1 :]

    col = _resolve_columns(header)
    missing = [k for k in _REQUIRED if k not in col]
    if missing:
        raise ParseError(
            f"Missing required columns: {missing}. "
            f"Found headers: {[h.strip() for h in header]}"
        )

    # ── Detect profit unit ────────────────────────────────────────────────
    exit_rows = [
        r for r in data_rows
        if len(r) > col["type"] and "exit" in r[col["type"]].lower()
    ]
    profit_unit = _detect_unit(exit_rows, col["profit"])

    # ── Pair entry and exit rows by trade number ───────────────────────────
    trade_map: dict[int, dict[str, list[str]]] = {}
    for row in data_rows:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) <= max(col["trade_number"], col["type"]):
            continue
        raw_num = row[col["trade_number"]].strip()
        if not raw_num.isdigit():
            continue
        num = int(raw_num)
        row_type = row[col["type"]].strip().lower()
        bucket = trade_map.setdefault(num, {})
        if "entry" in row_type and "entry" not in bucket:
            bucket["entry"] = row
        elif "exit" in row_type:
            # Always take the last exit (handles re-entries gracefully)
            bucket["exit"] = row

    # ── Build Trade objects ────────────────────────────────────────────────
    trades: list[Trade] = []
    skipped = 0

    run_up_col  = col.get("run_up")
    dd_col      = col.get("drawdown")

    for num in sorted(trade_map.keys()):
        record = trade_map[num]
        if "entry" not in record or "exit" not in record:
            skipped += 1
            continue

        entry = record["entry"]
        exit_ = record["exit"]

        try:
            profit = _clean_numeric(exit_[col["profit"]])
            if profit is None:
                skipped += 1
                continue

            raw_type  = entry[col["type"]].strip()
            direction = "Long" if "long" in raw_type.lower() else "Short"

            trades.append(Trade(
                trade_number  = num,
                direction     = direction,
                entry_time    = _parse_datetime(entry[col["datetime"]]),
                exit_time     = _parse_datetime(exit_[col["datetime"]]),
                entry_price   = _safe_float(entry, col["price"]),
                exit_price    = _safe_float(exit_,  col["price"]),
                contracts     = _safe_float(entry, col["contracts"]),
                profit        = profit,
                run_up        = _safe_float(exit_, run_up_col),
                drawdown      = _safe_float(exit_, dd_col),
            ))
        except (ValueError, IndexError, ParseError):
            skipped += 1
            continue

    if not trades:
        detail = f" ({skipped} incomplete trade(s) skipped)" if skipped else ""
        raise ParseError(
            f"No complete entry/exit pairs found in {path.name}{detail}. "
            "Ensure the file is a TradingView Strategy Tester 'List of Trades' export."
        )

    return trades, profit_unit
