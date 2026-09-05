# Strategy Labs V2 Execution Contract

This document is normative for the V2 long-only backtest path.

## Signal semantics

| Signal | V2 meaning |
|---|---|
| `BUY` | Open a long position when flat. A signal observed on bar `t` fills at bar `t+1` open. |
| `HOLD` | No position-state change. |
| `EXIT` | Close an open long position. If flat, no trade is created. |
| `SELL` | Legacy/compatibility alias for closing an open long. It does **not** open a short position in V2. |

Short selling is explicitly out of scope for the current V2 contract. A future short-enabled version must introduce an explicit contract rather than changing the meaning of `SELL` silently.

## Information boundary

A causal V2 strategy receives only data available through the signal bar. A signal generated from bar `t` cannot fill at bar `t` open; the earliest normal market-entry fill is bar `t+1` open.

## Intrabar exits

Once a long position is open, stop-loss and take-profit levels may trigger from the held bar's OHLC range. If the bar gaps through a stop/target, the opening price is used when the documented execution model requires it. OHLC data does not reveal the exact intrabar path, so when both SL and TP are touched in one bar, the engine must use its documented deterministic rule rather than pretending to know which happened first.

## Costs

Every fill is subject to the configured fee and slippage model. Reported `net_pnl` is the realised P&L after transaction fees; the fill prices already incorporate modeled slippage.

## End of data

A position still open on the final bar is liquidated at that bar's close and is marked `END_OF_DATA`.

## Position sizing

The execution engine's `position_size` is an absolute base-asset quantity. It is not a percentage of account equity and does not compound by itself. Capital-aware sizing belongs to the portfolio layer.

## Compatibility rule

The existing executor behavior is preserved by this document. Tests must enforce these semantics. Any intentional change to the contract requires changing this document and the corresponding golden/adversarial tests in the same change.
