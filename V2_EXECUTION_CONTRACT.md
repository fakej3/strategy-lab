# Strategy Labs V2 — Execution Contract

This document is the canonical contract for the V2 backtest execution layer.

## 1. Causality

A strategy may generate a signal using information available through bar `T`.
A signal generated on `T` is eligible to fill no earlier than `T+1`.

A signal on the final available bar has no future bar and therefore creates no fill.

## 2. Fill timing

The default execution model fills eligible market orders at the next bar open.
The execution price must be recorded explicitly in the trade ledger.

## 3. Transaction costs

Fees are costs of execution, not delayed accounting adjustments.

- Entry fee occurs on the entry fill.
- Exit fee occurs on the exit fill.
- Slippage must be represented exactly once in the execution model; portfolio accounting must not subtract it a second time.

## 4. Stop-loss / take-profit ambiguity

OHLC candles do not reveal the intrabar order of high and low. If both a stop and target are touched inside one candle, V2 must use one documented deterministic policy rather than implying that the true intrabar sequence is known.

## 5. End-of-data

An open position at the end of the dataset is liquidated using the documented end-of-data price rule. The resulting trade is included in the ledger and its P&L is realized.

## 6. Trade-ledger invariant

For every trade:

`net_pnl = gross_pnl - entry_costs - exit_costs`

The exact decomposition must be auditable from the trade record.

## 7. Portfolio invariant

After all positions are realized:

`ending_equity = starting_capital + sum(realized_net_pnl)`

Any implementation that violates these invariants is not ready for research use.
