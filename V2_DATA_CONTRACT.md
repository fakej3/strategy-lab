# Strategy Labs V2 — Research Dataset Contract

A backtest result is only as trustworthy as the dataset supplied to it.
V2 therefore separates dataset validation from execution.

## Structural requirements

A validated research dataset must have:

- a `DatetimeIndex`;
- unique timestamps;
- strictly increasing timestamps;
- numeric, finite OHLC values;
- positive OHLC prices;
- valid OHLC relationships (`low <= open/close <= high` and `low <= high`).

If volume is present, it must be numeric, finite, and non-negative. A research
run that explicitly requires positive volume must declare that requirement in
its `DatasetSpec`.

## Continuity

Continuity is **not universally required**. Markets have legitimate closures,
weekends, holidays, and session gaps. When a particular research dataset is
expected to be contiguous (for example, a pre-normalized crypto hourly series),
the expected frequency must be explicitly declared and validated.

## What this contract does not claim

This validator cannot establish that the data is economically correct. It does
not by itself detect survivorship bias, corporate-action errors, bad symbol
mapping, stale quotes, exchange outages, or incorrect vendor adjustments.
Those require source-aware validation and provenance checks upstream.

## Fail-closed principle

A dataset that violates a declared contract must stop the research run rather
than silently repairing itself. Automatic repair can hide data problems and
change the experiment.
