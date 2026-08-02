"""Regression snapshot tests.

Saves known-good outputs for canonical scenarios and asserts that future runs
reproduce the same results.  Failures here mean a code change altered the
engine's numerical outputs — which may be intentional (fix) or accidental (bug).

Snapshot workflow:
  - First run: snapshots are CREATED automatically (no existing file).
  - Subsequent runs: current output is compared against saved snapshot.
  - To regenerate: delete the snapshot file and re-run; a new snapshot is saved.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from verify._regression import compare_snapshot, load_snapshot, save_snapshot
from verify._scenarios import (
    S01_WINNER_NO_COSTS,
    S03_FEES_ONLY,
    S04_SLIPPAGE_ONLY,
    S06_SL_GAP_DOWN,
    S12_TWO_TRADES_COMPOUNDING,
    GoldenScenario,
)


_REGRESSION_SCENARIOS = [
    S01_WINNER_NO_COSTS,
    S03_FEES_ONLY,
    S04_SLIPPAGE_ONLY,
    S06_SL_GAP_DOWN,
    S12_TWO_TRADES_COMPOUNDING,
]


class FixedStrategy(StrategyBase):
    def __init__(self, sigs: list[str]) -> None:
        self._sigs = sigs

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series([Signal(s) for s in self._sigs], index=bars.index)


def _run(s: GoldenScenario):
    bars = pd.DataFrame(s.bars, columns=["open", "high", "low", "close"])
    ec   = EngineConfig(
        position_size   = s.position_size,
        fee_rate        = s.fee_rate,
        slippage_pct    = s.slippage_pct,
        stop_loss_pct   = s.stop_loss_pct,
        take_profit_pct = s.take_profit_pct,
    )
    pc = PortfolioConfig(
        starting_capital = s.starting_capital,
        sizing_mode      = SizingMode.FIXED_UNITS,
        position_size    = s.position_size,
    )
    return PortfolioEngine(pc).run(bars, FixedStrategy(s.signals), ec)


@pytest.mark.parametrize("scenario", _REGRESSION_SCENARIOS, ids=lambda s: s.name)
def test_regression_snapshot(scenario: GoldenScenario) -> None:
    """Create snapshot on first run; assert identical output on subsequent runs."""
    result   = _run(scenario)
    snap_key = f"regression_{scenario.name}"

    if load_snapshot(snap_key) is None:
        # First run: save the snapshot and pass
        save_snapshot(snap_key, result)
        return  # snapshot created — nothing to compare yet

    diffs = compare_snapshot(snap_key, result)
    assert not diffs, (
        f"{scenario.name}: regression snapshot mismatch:\n"
        + "\n".join(f"  {d}" for d in diffs[:20])
    )
