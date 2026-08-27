# Strategy Labs V2 — Trade Ledger Invariants

Every completed trade must be independently reconcilable from its ledger fields.

## Price/size invariant

For a long trade:

`gross_pnl = (exit_price - entry_price) * size`

For a short trade, the sign must reverse.

## Cost invariant

`net_pnl = gross_pnl - entry_fee - exit_fee`

Slippage costs are represented by the difference between raw market prices and recorded fill prices. They must not be subtracted again from `net_pnl` after the fill prices have incorporated slippage.

## Auditability

Every completed trade must contain enough information to reconstruct:

- when the signal occurred;
- when and where the position filled;
- position size;
- entry/exit fees;
- entry/exit slippage;
- gross P&L;
- net P&L;
- exit reason.

Aggregate metrics are not considered authoritative unless the underlying trade ledger reconciles.
