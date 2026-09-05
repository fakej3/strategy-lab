# Strategy Labs V2 — Core Audit

Branch: `strategy-lab-v2-core`

## Goal

Establish a trustworthy research core before adding more strategies, optimization, statistics, UI, or live trading.

## Findings from the first engine/portfolio pass

### P0 — Execution semantics are still strategy-specific and only partly enforceable

`StrategyBase` explicitly says causal signal generation is the strategy author's responsibility. The executor validates signal shape/values, but it cannot prove that a strategy did not use future bars. This is acceptable for a first engine, but V2 must treat causality as a research invariant and add targeted tests/helpers around it rather than claiming the engine makes lookahead impossible.

Source: `engine/strategy.py`, `engine/executor.py`.

### P0 — The engine is long-only while exposing `SELL`

`Signal.SELL` is documented as reserved for short entry but is currently treated as an exit. This is internally documented, but it is dangerous for research because a strategy author can reasonably interpret SELL as a short signal. V2 will make the supported execution domain explicit: long-only until short accounting is deliberately implemented and tested.

Source: `engine/strategy.py` and `engine/executor.py`.

### P0 — Portfolio sizing is implemented as a post-processing layer

For dynamic sizing, `PortfolioEngine` first runs the execution engine with unit size, then reconstructs PnL using the selected actual size. This can be mathematically valid only while every execution cost is strictly linear in size and execution price is independent of size. The current slippage model is fixed percentage, so that assumption currently holds, but it must be an explicit V2 invariant. It cannot later be extended to market-impact/order-book models without changing the architecture.

Source: `portfolio/engine.py`, `engine/models.py`.

### P1 — Portfolio equity and execution accounting need golden tests

The portfolio engine contains several important calculations: realized PnL, unrealized equity, drawdown, exposure, dynamic sizing, fees and slippage. These should not be trusted merely because unit tests pass. V2's golden tests will compare every result against hand-calculated scenarios.

### P1 — Bar-based SL/TP remains path-ambiguous

When both stop-loss and take-profit are inside the same candle, the executor deliberately gives SL priority. That is conservative, but it is an assumption rather than knowledge of the actual intrabar path. V2 should surface this explicitly in research metadata and ensure strategies cannot silently compare results from incompatible assumptions.

Source: `engine/executor.py`, `engine/models.py`.

### P1 — End-of-data liquidation is an assumption that affects metrics

Open positions are liquidated at the final close. This is reasonable for a backtest, but it must be included consistently in trade statistics and OOS evaluation. V2 will have a golden test for an open final position.

## V2 rule

No new strategy families, optimization, ML, live trading, or major UI work should be used as evidence of progress until the following are proven:

1. Deterministic execution on hand-built candles.
2. Exact transaction-cost accounting.
3. Exact portfolio sizing/accounting.
4. Known-answer tests for SL/TP/gaps/end-of-data.
5. Explicit long-only semantics.
6. Reproducible train/test separation.

The objective is not to make the system bigger. The objective is to make every number defensible.
