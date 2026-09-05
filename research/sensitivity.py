"""Parameter sensitivity and robustness diagnostics for optimization results."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ParameterSensitivity:
    """Sensitivity summary for one parameter."""
    parameter: str
    best_value: Any
    best_score: float
    mean_score: float
    median_score: float
    score_std: float
    score_range: float
    normalized_range: float
    n_values: int
    n_observations: int
    robustness: str


@dataclass(frozen=True)
class SensitivityResult:
    """Complete parameter sensitivity report."""
    parameters: list[ParameterSensitivity]
    table: pd.DataFrame


def analyze_sensitivity(
    results: pd.DataFrame,
    parameter_space: dict[str, Sequence[Any]] | None = None,
    score_column: str = "score",
) -> SensitivityResult:
    """Analyze how optimization scores vary with each parameter.

    This is deliberately descriptive: it does not claim statistical
    significance and does not infer causality. For each parameter, scores are
    grouped by that parameter while averaging over the other dimensions.

    ``normalized_range`` is score range divided by the absolute best score;
    it is useful for comparing sensitivity across parameters, but is not a
    universal robustness probability.
    """
    if not isinstance(results, pd.DataFrame) or results.empty:
        raise ValueError("results must be a non-empty DataFrame")
    if score_column not in results.columns:
        raise ValueError(f"missing score column: {score_column}")

    numeric_score = pd.to_numeric(results[score_column], errors="coerce")
    clean = results.copy()
    clean[score_column] = numeric_score
    clean = clean[np.isfinite(clean[score_column].to_numpy(dtype=float))]
    if clean.empty:
        raise ValueError("results contains no finite scores")

    if parameter_space is None:
        parameter_space = {
            c: clean[c].drop_duplicates().tolist()
            for c in clean.columns
            if c != score_column
        }

    reports: list[ParameterSensitivity] = []
    table_parts: list[pd.DataFrame] = []

    for parameter, allowed_values in parameter_space.items():
        if parameter not in clean.columns:
            raise ValueError(f"parameter '{parameter}' is missing from results")
        values = list(allowed_values)
        grouped = clean.groupby(parameter, dropna=False)[score_column].agg(
            ["mean", "median", "std", "count", "min", "max"]
        )
        grouped = grouped.reindex(values).dropna(how="all")
        if grouped.empty:
            continue

        best_value = grouped["mean"].idxmax()
        best_score = float(grouped["mean"].max())
        mean_score = float(grouped["mean"].mean())
        median_score = float(grouped["mean"].median())
        score_std = float(grouped["mean"].std(ddof=1)) if len(grouped) > 1 else 0.0
        score_range = float(grouped["mean"].max() - grouped["mean"].min())
        normalized_range = score_range / max(abs(best_score), np.finfo(float).eps)

        if len(grouped) < 2:
            robustness = "insufficient"
        elif normalized_range <= 0.10:
            robustness = "stable"
        elif normalized_range <= 0.30:
            robustness = "moderate"
        else:
            robustness = "sensitive"

        reports.append(ParameterSensitivity(
            parameter=parameter,
            best_value=best_value,
            best_score=best_score,
            mean_score=mean_score,
            median_score=median_score,
            score_std=score_std,
            score_range=score_range,
            normalized_range=normalized_range,
            n_values=len(grouped),
            n_observations=int(grouped["count"].sum()),
            robustness=robustness,
        ))

        part = grouped.reset_index()
        part.insert(0, "parameter", parameter)
        table_parts.append(part)

    table = pd.concat(table_parts, ignore_index=True) if table_parts else pd.DataFrame()
    return SensitivityResult(parameters=reports, table=table)
