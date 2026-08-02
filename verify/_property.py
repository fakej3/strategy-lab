"""Randomized property-based testing.

Generates thousands of random but structurally valid scenarios and verifies
that ALL financial invariants hold for every one of them.  Failures indicate
a systematic bug, not a single bad input.

Design constraints:
- Deterministic: fixed seed → same sequence every run.
- No production code in the random generation logic.
- Every bar satisfies the OHLCV geometry constraints (executor rejects bad bars).
- Signals are valid Signal enum values.
"""
from __future__ import annotations

import random

import pandas as pd

from engine.executor import BacktestExecutor
from engine.models import EngineConfig
from engine.strategy import Signal, StrategyBase
from portfolio.engine import PortfolioEngine
from portfolio.models import PortfolioConfig, SizingMode
from verify._invariants import Violation, check_all


class PropertyFailure:
    def __init__(self, scenario_idx: int, description: str, violations: list[Violation]):
        self.scenario_idx = scenario_idx
        self.description  = description
        self.violations   = violations

    def __str__(self) -> str:
        lines = [f"Scenario {self.scenario_idx}: {self.description}"]
        for v in self.violations:
            lines.append(f"  [{v.invariant}] {v.message}")
        return "\n".join(lines)


def run_property_tests(n: int = 1000, seed: int = 42) -> list[PropertyFailure]:
    """Run n random scenarios; return failures (empty list = all passed)."""
    rng = random.Random(seed)
    failures: list[PropertyFailure] = []

    for i in range(n):
        bars_df, sigs, engine_cfg, port_cfg = _random_scenario(rng, i)
        desc = (
            f"n_bars={len(bars_df)}, size={engine_cfg.position_size:.2f}, "
            f"fee={engine_cfg.fee_rate}, slip={engine_cfg.slippage_pct}, "
            f"sl={engine_cfg.stop_loss_pct}, tp={engine_cfg.take_profit_pct}"
        )
        try:
            strategy = _FixedSignalStrategy(sigs)
            result   = PortfolioEngine(port_cfg).run(bars_df, strategy, engine_cfg)
            viols    = check_all(result)
            if viols:
                failures.append(PropertyFailure(i, desc, viols))
        except Exception as exc:
            failures.append(PropertyFailure(
                i, desc,
                [Violation("EXCEPTION", str(exc))],
            ))

    return failures


# ── Random scenario builders ───────────────────────────────────────────────────

def _random_scenario(
    rng: random.Random,
    idx: int,
) -> tuple[pd.DataFrame, list[str], EngineConfig, PortfolioConfig]:
    n_bars = rng.randint(5, 150)

    # Market price bounded to keep position values << capital (prevents negative equity).
    # Invariant guarantee: max_position_value = start_price * size ≤ capital / 20.
    # This ensures even 19 consecutive full-price losses can't bankrupt the account.
    start_price = rng.uniform(10.0, 1000.0)
    vol         = rng.uniform(0.002, 0.04)
    bars_df     = _random_bars(rng, n_bars, start_price, vol)

    capital = 100_000.0   # fixed; large enough to stay solvent with any generated size

    # Size ≤ capital / (start_price * 200): budget for 100 max-loss trades below 0
    max_size      = capital / (start_price * 200)
    position_size = round(rng.uniform(max_size * 0.1, max_size), 6)
    position_size = max(position_size, 1e-6)   # floor

    fee_rate     = rng.choice([0.0, 0.0005, 0.001, 0.002])
    slippage_pct = rng.choice([0.0, 0.0002, 0.0005, 0.001])

    sl_pct = rng.choice([None, None, 0.02, 0.05, 0.10, 0.15])
    tp_pct = rng.choice([None, None, 0.02, 0.05, 0.10, 0.20])

    engine_cfg = EngineConfig(
        position_size   = position_size,
        fee_rate        = fee_rate,
        slippage_pct    = slippage_pct,
        stop_loss_pct   = sl_pct,
        take_profit_pct = tp_pct,
    )
    port_cfg = PortfolioConfig(
        starting_capital = capital,
        sizing_mode      = SizingMode.FIXED_UNITS,
        position_size    = position_size,
    )

    signals = _random_signals(rng, n_bars)
    return bars_df, signals, engine_cfg, port_cfg


def _random_bars(
    rng: random.Random,
    n: int,
    start: float,
    vol: float,
) -> pd.DataFrame:
    """Generate n valid OHLCV bars from a geometric random walk."""
    rows = []
    price = start
    for _ in range(n):
        # Bar-level spread ± one candle body
        wick_up   = price * rng.uniform(0.0, vol * 2)
        wick_down = price * rng.uniform(0.0, vol * 2)
        high      = price + wick_up
        low       = max(price - wick_down, 1e-6)   # floor at positive price

        open_  = rng.uniform(low, high)
        close  = rng.uniform(low, high)
        rows.append((open_, high, low, close, 0.0))

        # Next bar: geometric step
        ret   = rng.gauss(0.0, vol)
        price = price * (1.0 + ret)
        price = max(price, 1e-6)

    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _random_signals(rng: random.Random, n: int) -> list[str]:
    """Generate a realistic, valid signal sequence (no two BUYs in a row)."""
    in_pos  = False
    signals = []
    for _ in range(n):
        if not in_pos:
            sig = rng.choices(["BUY", "HOLD"], weights=[25, 75])[0]
            if sig == "BUY":
                in_pos = True
        else:
            sig = rng.choices(["EXIT", "HOLD"], weights=[25, 75])[0]
            if sig == "EXIT":
                in_pos = False
        signals.append(sig)
    return signals


class _FixedSignalStrategy(StrategyBase):
    """Strategy that replays a pre-computed signal list."""

    def __init__(self, signals: list[str]) -> None:
        self._sigs = signals

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(
            [Signal(s) for s in self._sigs],
            index=bars.index,
        )
