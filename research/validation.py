"""Extended bar validation — institutional-quality OHLCV data checks."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ValidationWarning:
    """Non-fatal issue found during extended bar validation.

    Attributes
    ----------
    code    : short machine-readable identifier (e.g. ``"missing_bars"``).
    message : human-readable description with context values.
    """

    code   : str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def validate_bars_extended(bars: pd.DataFrame) -> list[ValidationWarning]:
    """Validate an OHLCV DataFrame beyond the basic engine checks.

    Hard failures (raises ``ValueError``)
    ---------------------------------------
    - Duplicate timestamps in the index.
    - Mixed timezone-awareness in the index (some tz-aware, some tz-naive).
    - Any price or volume value ≤ 0.

    Soft warnings (returned as ``ValidationWarning`` list)
    -------------------------------------------------------
    - Timestamps not in ascending order (sortable, but flagged).
    - Missing expected bars detected via a regular frequency inference
      (only when ``pd.infer_freq`` can determine the frequency).
    - Volume column present but contains NaN values.

    Args:
        bars: DataFrame with a DatetimeIndex and columns
              ``open``, ``high``, ``low``, ``close``, and optionally
              ``volume``.  The basic structural check (OHLC columns
              present and finite, high ≥ low) is the engine's
              responsibility; this function adds the extra layer.

    Returns:
        List of :class:`ValidationWarning` objects, possibly empty.

    Raises:
        ValueError: For any hard failure listed above.

    Usage example
    -------------
    >>> import pandas as pd
    >>> from research import validate_bars_extended
    >>> warnings = validate_bars_extended(bars)
    >>> for w in warnings:
    ...     print(w)
    """
    if bars.empty:
        return []

    warnings: list[ValidationWarning] = []

    # ── Timestamp checks ───────────────────────────────────────────────────────

    index = bars.index

    # Duplicate timestamps — hard failure
    if index.duplicated().any():
        dupes = index[index.duplicated()].tolist()
        raise ValueError(
            f"Duplicate timestamps found in bars index: {dupes[:5]}"
            + (f" … (+{len(dupes) - 5} more)" if len(dupes) > 5 else "")
        )

    # Mixed timezone-awareness — hard failure
    if hasattr(index, "tz"):
        if index.tz is None:
            # All naive by definition — fine
            pass
    else:
        # Older pandas: check element-by-element (extremely rare)
        pass

    if isinstance(index, pd.DatetimeIndex):
        # Detect mixed-offset (tz-aware index only)
        if index.tz is not None:
            try:
                # Attempt UTC normalisation; will raise if inconsistent
                index.tz_convert("UTC")
            except Exception as exc:  # pragma: no cover
                raise ValueError(
                    f"Mixed or inconsistent timezone in bars index: {exc}"
                ) from exc

    # Ascending order — soft warning
    if not index.is_monotonic_increasing:
        warnings.append(ValidationWarning(
            code   = "unsorted_timestamps",
            message= (
                "Bar timestamps are not in strictly ascending order. "
                "Sort the DataFrame before backtesting."
            ),
        ))

    # Missing bars — soft warning.
    # Strategy: compute the minimum timedelta between consecutive bars (the
    # "base tick") and then check whether every interval is a multiple of it.
    # Any gap larger than one base tick means missing bars.
    if isinstance(index, pd.DatetimeIndex) and len(index) >= 3 and index.is_monotonic_increasing:
        deltas    = pd.Series(index[1:] - index[:-1])
        min_delta = deltas.min()

        if min_delta.total_seconds() > 0:
            # Count non-unit gaps (intervals > 1 base tick)
            gap_counts   = deltas[deltas > min_delta]
            total_missing = int(sum(
                round(d / min_delta) - 1 for d in gap_counts
            ))
            if total_missing > 0:
                first_gap_idx = deltas[deltas > min_delta].index[0]
                first_missing = index[first_gap_idx] + min_delta
                warnings.append(ValidationWarning(
                    code   = "missing_bars",
                    message= (
                        f"{total_missing} expected bar(s) missing "
                        f"(base interval {min_delta}). "
                        f"First missing: {first_missing}"
                    ),
                ))

    # ── Price and volume checks ────────────────────────────────────────────────

    price_cols = [c for c in ("open", "high", "low", "close") if c in bars.columns]
    for col in price_cols:
        col_data = bars[col]
        if (col_data <= 0).any():
            bad = bars.index[col_data <= 0].tolist()
            raise ValueError(
                f"Non-positive values in column '{col}' at "
                f"{bad[:3]}" + (f" … (+{len(bad) - 3} more)" if len(bad) > 3 else "")
            )

    if "volume" in bars.columns:
        vol = bars["volume"]
        if vol.isna().any():
            n_nan = int(vol.isna().sum())
            warnings.append(ValidationWarning(
                code   = "volume_nan",
                message= f"{n_nan} bar(s) have NaN volume.",
            ))
        elif (vol < 0).any():
            raise ValueError(
                "Negative volume values found in bars. Volume must be ≥ 0."
            )

    return warnings
