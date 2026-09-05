"""Information-boundary tests for the integrated V2 runner."""

import pandas as pd
from research.v2_runner import run_signal_execution


def test_signal_sees_only_current_and_past_bars_and_executes_next_bar():
    df = pd.DataFrame(
        {"open": [10, 11, 12], "high": [11, 12, 13], "low": [9, 10, 11], "close": [10, 11, 12]},
        index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )
    seen_lengths = []
    executions = []

    def signal(history):
        seen_lengths.append(len(history))
        return history.close.iloc[-1]

    def execute(bar_index, signal_value, bar):
        executions.append((bar_index, signal_value, bar.name))
        return bar_index

    result = run_signal_execution(df, signal, execute)
    assert seen_lengths == [1, 2]
    assert executions[0][0] == 1
    assert executions[0][1] == 10
    assert executions[1][0] == 2
    assert executions[1][1] == 11
    assert len(result.signals) == len(result.executions) == 2
