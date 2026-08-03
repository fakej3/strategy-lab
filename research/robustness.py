"""Parameter stability and robustness analysis — neighbor backtest evaluation."""
from __future__ import annotations

import math
from typing import Any, Type

import numpy as np
import pandas as pd


def analyze_robustness(
    bars: pd.DataFrame,
    strategy_class: Type,
    focal_params: dict,
    param_space: dict[str, list],
    bars_per_year: int = 8760,
    starting_capital: float = 100_000.0,
    fee_rate: float = 0.001,
    slippage_pct: float = 0.0005,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> dict[str, Any]:
    """Evaluate strategy stability across neighboring parameter combinations.

    Generates all combos differing from *focal_params* by exactly one
    parameter step (±1 position in each param's value list), then backtests
    each one.

    Returns:
      - robustness_score: % of valid neighbors with positive net_profit (0–100)
      - stability_score:  inversely proportional to Sharpe stddev (0–100)
      - sensitivity:      per-param mean |ΔSharpe / Δparam_value|
      - focal_sharpe:     focal combo Sharpe
      - neighbor_results: list of {params, net_profit, sharpe}

    Args:
        bars:             OHLCV DataFrame.
        strategy_class:   Strategy class to instantiate.
        focal_params:     The parameter set being evaluated.
        param_space:      Full parameter value lists (e.g. {"fast": [5,10,20]}).
        bars_per_year:    Annualisation factor for Sharpe computation.
        starting_capital: Starting capital for each backtest.
        fee_rate:         Per-trade fee rate.
        slippage_pct:     Per-trade slippage.
        stop_loss_pct:    Optional stop-loss %.
        take_profit_pct:  Optional take-profit %.
    """
    if not param_space or not focal_params:
        return _empty()

    focal_result = _quick_backtest(
        bars, strategy_class, focal_params,
        starting_capital, fee_rate, slippage_pct,
        stop_loss_pct, take_profit_pct, bars_per_year,
    )
    focal_sharpe = focal_result.get("sharpe", 0.0)

    neighbor_combos = _generate_neighbor_combos(focal_params, param_space)

    neighbor_results: list[dict] = []
    for nb_params in neighbor_combos:
        try:
            nb_result = _quick_backtest(
                bars, strategy_class, nb_params,
                starting_capital, fee_rate, slippage_pct,
                stop_loss_pct, take_profit_pct, bars_per_year,
            )
            neighbor_results.append({
                "params"    : nb_params,
                "net_profit": nb_result.get("net_profit", 0.0),
                "sharpe"    : nb_result.get("sharpe", 0.0),
            })
        except Exception:
            pass

    if not neighbor_results:
        return _empty()

    n_valid = len(neighbor_results)
    n_pos   = sum(1 for r in neighbor_results if r["net_profit"] > 0)

    robustness_score = (n_pos / n_valid) * 100.0

    sharpes   = np.array([r["sharpe"] for r in neighbor_results], dtype=float)
    sh_std    = float(sharpes.std(ddof=0)) if len(sharpes) > 1 else 0.0
    stability = max(0.0, min(100.0, 100.0 - (sh_std / (abs(focal_sharpe) + 0.5)) * 50.0))

    sensitivity = _compute_sensitivity(
        focal_params, focal_sharpe, param_space, neighbor_results
    )

    return {
        "robustness_score": round(robustness_score, 2),
        "stability_score" : round(stability, 2),
        "focal_sharpe"    : round(focal_sharpe, 4),
        "n_neighbors"     : n_valid,
        "n_profitable"    : n_pos,
        "sensitivity"     : sensitivity,
        "neighbor_results": [
            {
                "params"    : r["params"],
                "net_profit": round(r["net_profit"], 2),
                "sharpe"    : round(r["sharpe"], 4),
            }
            for r in neighbor_results
        ],
    }


def _generate_neighbor_combos(
    focal_params: dict,
    param_space: dict[str, list],
) -> list[dict]:
    """Combos differing from focal by exactly one param step (±1 position)."""
    combos: list[dict] = []
    for param_name, values in param_space.items():
        if param_name not in focal_params:
            continue
        focal_val = focal_params[param_name]
        try:
            idx = values.index(focal_val)
        except ValueError:
            continue

        for new_idx in (idx - 1, idx + 1):
            if 0 <= new_idx < len(values):
                nb = dict(focal_params)
                nb[param_name] = values[new_idx]
                combos.append(nb)

    # Deduplicate
    seen: set = set()
    unique: list[dict] = []
    for c in combos:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _quick_backtest(
    bars: pd.DataFrame,
    strategy_class: Type,
    params: dict,
    starting_capital: float,
    fee_rate: float,
    slippage_pct: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    bars_per_year: int,
) -> dict:
    """Lightweight backtest returning net_profit and Sharpe only."""
    from engine.models import EngineConfig
    from portfolio.engine import PortfolioEngine
    from portfolio.models import PortfolioConfig

    strategy = strategy_class(**params)
    eng_cfg  = EngineConfig(
        fee_rate        = fee_rate,
        slippage_pct    = slippage_pct,
        stop_loss_pct   = stop_loss_pct,
        take_profit_pct = take_profit_pct,
    )
    port_cfg = PortfolioConfig(starting_capital=starting_capital)
    result   = PortfolioEngine(port_cfg).run(bars, strategy, eng_cfg)

    eq  = result.equity_curve
    ret = eq.pct_change().dropna()
    std = float(ret.std(ddof=1))
    sharpe = (float(ret.mean()) / std * math.sqrt(bars_per_year)) if std > 0 else 0.0

    return {"net_profit": result.net_profit, "sharpe": sharpe}


def _compute_sensitivity(
    focal_params: dict,
    focal_sharpe: float,
    param_space: dict[str, list],
    neighbor_results: list[dict],
) -> dict[str, float | None]:
    """Per-param mean |ΔSharpe| / |Δparam_value|."""
    sensitivity: dict[str, float | None] = {}
    for param_name, values in param_space.items():
        if param_name not in focal_params:
            continue
        focal_val = focal_params[param_name]

        deltas: list[float] = []
        for r in neighbor_results:
            rp = r["params"]
            if rp.get(param_name) == focal_val:
                continue
            other_match = all(
                rp.get(k) == v
                for k, v in focal_params.items()
                if k != param_name
            )
            if other_match:
                delta_p = abs(rp[param_name] - focal_val)
                delta_s = abs(r["sharpe"] - focal_sharpe)
                if delta_p > 0:
                    deltas.append(delta_s / delta_p)

        sensitivity[param_name] = round(float(np.mean(deltas)), 6) if deltas else None

    return sensitivity


def _empty() -> dict:
    return {
        "robustness_score": None,
        "stability_score" : None,
        "focal_sharpe"    : None,
        "n_neighbors"     : 0,
        "n_profitable"    : 0,
        "sensitivity"     : {},
        "neighbor_results": [],
    }
