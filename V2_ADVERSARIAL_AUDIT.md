# Strategy Labs V2 — Adversarial Audit

The purpose of this suite is to attack the research stack rather than demonstrate happy-path behavior.

## Threats covered

- future rows reaching a causal strategy;
- non-finite prices;
- duplicate observations;
- hidden gaps in datasets that explicitly declare continuity;
- impossible OHLC relationships.

## Review rule

A test is not evidence that the implementation passed until it has actually been executed. GitHub currently contains the tests, but this audit remains **unverified** until CI or a local test run produces results.

## Next adversarial targets

- same-bar execution leakage;
- SL/TP ordering assumptions;
- gap-through-stop behavior;
- repeated entry signals;
- final-bar fills;
- fee/slippage double counting;
- portfolio-to-ledger reconciliation;
- parameter/data snooping;
- train/test contamination.
