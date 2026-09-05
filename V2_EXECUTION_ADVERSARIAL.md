# V2 Execution Adversarial Rules

These cases are intentionally hostile because they expose the assumptions most likely to create inflated backtests.

## Causal boundary

The executor must pass a causal strategy only `bars[:i+1]` for signal generation at bar `i`. A strategy must never be able to inspect a future row through the normal V2 API.

## Gap-through-stop

For a long position, if the next bar opens below the stop, the simulated stop fill is the gap-open price rather than the stale stop price. This is a conservative and executable assumption for a marketable stop.

## Same-candle SL/TP collision

OHLC data cannot reveal whether the high or low occurred first. V2 currently gives stop-loss priority when both thresholds are touched in the same candle. This is a deterministic modeling assumption, not a claim about the true intrabar path.

## Exit timing

An exit signal generated on bar `i` is executed no earlier than the next bar. The signal bar's close must not be used as a fill for a normal next-bar market exit.

## Verification status

The adversarial tests are committed, but remain unverified until actually executed by CI or a local Python test run.
