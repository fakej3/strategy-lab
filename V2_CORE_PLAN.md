# Strategy Lab V2 — Core Reset

This branch is the controlled reset of Strategy Lab. The existing architecture is not being deleted; we are freezing feature expansion and proving the financial core before adding more research machinery.

## Current audit findings

The repository is already large and ambitious: the documented architecture contains engine, portfolio, research, jobs, automation, data, reports, server, database, facade, bot interfaces, and a verification layer. That is useful infrastructure, but it is too much surface area to treat as a single correctness unit.

The execution engine currently has explicit assumptions for signal timing, SL/TP priority, gap handling, slippage, fees, and end-of-data liquidation. Those assumptions are documented in both `ARCHITECTURE.md` and `engine/models.py`, and the executor has a substantial test suite. We will preserve those contracts unless a deterministic test proves they are wrong.

The first V2 goal is therefore not a rewrite. It is **financially auditable behavior**.

## V2 order of work

1. Golden accounting tests — tiny scenarios with hand-calculable answers.
2. Execution contract — signal timing, fills, fees, slippage, SL/TP, gaps, liquidation.
3. Portfolio contract — realized/unrealized equity, sizing, compounding, drawdown.
4. Metrics contract — every reported metric traced to tested source values.
5. Data contract — completeness, timestamp semantics, duplicates, gaps, failed downloads.
6. Out-of-sample contract — strict train/test separation and reproducible walk-forward folds.
7. Research statistics — bootstrap, multiple testing, Deflated Sharpe, robustness.
8. Only then: optimization, automation, UI expansion, and live/paper promotion.

## Rules for this branch

- Do not add a new research feature to compensate for an unverified core.
- Do not change financial calculations without a deterministic regression test.
- Every backtest result must be reproducible from explicit data, strategy, parameters, and execution assumptions.
- Prefer a small known-answer test over a large integration test when validating financial math.
- Passing tests is necessary, not sufficient: inspect the assumptions and independently calculate representative results.
- No live trading work until backtest and paper execution agree within explicit tolerances.

## First milestone

A strategy run must be explainable trade-by-trade:

`bars -> signal -> next-bar execution -> fill -> fees/slippage -> position -> exit -> net P&L -> portfolio equity`

Only after that chain is trusted will V2 move upward into statistical research.
