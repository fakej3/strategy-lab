"""Regression snapshot management.

Saves known-good backtest outputs to JSON files.  Future runs must reproduce
identical results (within floating-point tolerance) for the stored snapshots.

Snapshots capture:
- All top-level PortfolioResult fields (ending_equity, max_drawdown_pct, etc.)
- Per-trade: entry_bar, exit_bar, entry_price, exit_price, net_pnl, exit_reason
- Equity curve at every bar (rounded to 10 decimal places for stability)

Snapshots are stored in verify/snapshots/<name>.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from portfolio.models import PortfolioResult

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
_ROUND = 8   # decimal places for float values in snapshots


def save_snapshot(name: str, result: PortfolioResult) -> Path:
    """Serialise a PortfolioResult to a snapshot file and return the path."""
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    data = _serialise(result)
    path.write_text(json.dumps(data, indent=2))
    return path


def load_snapshot(name: str) -> dict | None:
    """Load a snapshot by name; return None if it does not exist."""
    path = SNAPSHOT_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def compare_snapshot(name: str, result: PortfolioResult) -> list[str]:
    """Compare result against saved snapshot; return list of discrepancy messages."""
    saved = load_snapshot(name)
    if saved is None:
        return [f"No snapshot found for '{name}'"]

    current = _serialise(result)
    return _diff(saved, current, path="")


# ── Serialisation ──────────────────────────────────────────────────────────────

def _serialise(result: PortfolioResult) -> dict:
    trades = []
    for t in result.trades:
        trades.append({
            "trade_number" : t.trade_number,
            "entry_bar"    : t.entry_bar,
            "exit_bar"     : t.exit_bar,
            "entry_price"  : _r(t.entry_price),
            "exit_price"   : _r(t.exit_price),
            "gross_pnl"    : _r(t.gross_pnl),
            "net_pnl"      : _r(t.net_pnl),
            "entry_fee"    : _r(t.entry_fee),
            "exit_fee"     : _r(t.exit_fee),
            "holding_period": t.holding_period,
            "exit_reason"  : str(t.exit_reason),
        })
    return {
        "starting_capital" : _r(result.starting_capital),
        "ending_equity"    : _r(result.ending_equity),
        "peak_equity"      : _r(result.peak_equity),
        "net_profit"       : _r(result.net_profit),
        "total_return"     : _r(result.total_return),
        "max_drawdown_pct" : _r(result.max_drawdown_pct),
        "max_drawdown_abs" : _r(result.max_drawdown_abs),
        "exposure_pct"     : _r(result.exposure_pct),
        "n_trades"         : len(result.trades),
        "equity_curve"     : [_r(v) for v in result.equity_curve.tolist()],
        "trades"           : trades,
    }


def _r(v: float) -> float | None:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(float(v), _ROUND)


# ── Diff ───────────────────────────────────────────────────────────────────────

def _diff(saved: object, current: object, path: str) -> list[str]:
    diffs: list[str] = []

    if type(saved) != type(current):
        diffs.append(f"{path}: type mismatch {type(saved).__name__} vs {type(current).__name__}")
        return diffs

    if isinstance(saved, dict):
        for k in set(saved) | set(current):      # type: ignore[union-attr]
            sub = f"{path}.{k}" if path else k
            if k not in saved:                    # type: ignore[operator]
                diffs.append(f"{sub}: missing from snapshot")
            elif k not in current:                # type: ignore[operator]
                diffs.append(f"{sub}: missing from current result")
            else:
                diffs.extend(_diff(saved[k], current[k], sub))  # type: ignore[index]

    elif isinstance(saved, list):
        if len(saved) != len(current):           # type: ignore[arg-type]
            diffs.append(
                f"{path}: length {len(saved)} (snapshot) vs "
                f"{len(current)} (current)"      # type: ignore[arg-type]
            )
        else:
            for idx, (s, c) in enumerate(zip(saved, current)):  # type: ignore[call-overload]
                diffs.extend(_diff(s, c, f"{path}[{idx}]"))

    elif isinstance(saved, float) and isinstance(current, float):
        if not math.isclose(saved, current, rel_tol=1e-6, abs_tol=1e-9):
            diffs.append(f"{path}: {saved} (snapshot) != {current} (current)")

    elif saved != current:
        diffs.append(f"{path}: {saved!r} (snapshot) != {current!r} (current)")

    return diffs
