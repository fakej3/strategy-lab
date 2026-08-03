"""Chart data helpers — produce JSON-serialisable structures for Canvas rendering."""
from __future__ import annotations

import json
from typing import Any


def equity_curve_data(equity_json: str | None, label: str = "Equity") -> dict:
    """Return {labels, values} ready for JS Canvas line chart."""
    if not equity_json:
        return {"labels": [], "values": []}
    try:
        points: list[dict] = json.loads(equity_json)
    except Exception:
        return {"labels": [], "values": []}
    if points and isinstance(points[0], (int, float)):
        # flat list of floats
        labels = list(range(len(points)))
        values = [round(float(p), 2) for p in points]
    else:
        labels = [p.get("date", p.get("t", i)) for i, p in enumerate(points)]
        values = [round(p.get("equity", p.get("v", 0)), 2) for p in points]
    return {"labels": labels, "values": values, "label": label}


def gate_distribution(results: list[Any]) -> dict:
    """Return {PASS: n, REJECT: n} counts."""
    counts: dict[str, int] = {}
    for r in results:
        d = getattr(r, "gate_decision", "UNKNOWN")
        counts[d] = counts.get(d, 0) + 1
    return counts


def sharpe_histogram(results: list[Any], bins: int = 20) -> dict:
    """Return histogram of Sharpe ratios: {edges: [...], counts: [...]}."""
    values = [r.sharpe_ratio for r in results if r.sharpe_ratio is not None]
    if not values:
        return {"edges": [], "counts": []}
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"edges": [lo, lo + 1], "counts": [len(values)]}
    step  = (hi - lo) / bins
    edges = [round(lo + i * step, 4) for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    return {"edges": edges, "counts": counts}


def top_n_bar(results: list[Any], metric: str = "sharpe_ratio", n: int = 10) -> dict:
    """Return {labels, values} for the top-N strategies by metric."""
    valid = [r for r in results if getattr(r, metric, None) is not None]
    top   = sorted(valid, key=lambda r: getattr(r, metric), reverse=True)[:n]
    labels = [f"{r.strategy_class}({r.symbol})" for r in top]
    values = [round(getattr(r, metric), 4) for r in top]
    return {"labels": labels, "values": values, "metric": metric}
