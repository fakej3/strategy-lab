"""Golden tests for deterministic experiment identity."""

from research.v2_experiment import ExperimentSpec, build_manifest, canonical_json, experiment_id


def spec():
    return ExperimentSpec(
        strategy_name="demo",
        strategy_version="1",
        dataset_fingerprint="sha256:data",
        code_commit="abc123",
        parameters={"lookback": 20, "threshold": 1.5},
        execution_model="next_open",
        fee_model="percentage",
        slippage_model="fixed_rate",
        sizing_model="risk_stop",
        random_seed=7,
        train_period="2020-01-01/2023-01-01",
        test_period="2023-01-01/2024-01-01",
    )


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})


def test_same_spec_has_same_id():
    assert experiment_id(spec()) == experiment_id(spec())


def test_material_parameter_change_changes_id():
    a = spec()
    b = ExperimentSpec(**{**a.__dict__, "parameters": {"lookback": 21, "threshold": 1.5}})
    assert experiment_id(a) != experiment_id(b)


def test_manifest_contains_identity_and_inputs():
    manifest = build_manifest(spec(), result={"sharpe": 1.2})
    assert manifest["experiment_id"] == experiment_id(spec())
    assert manifest["spec"]["dataset_fingerprint"] == "sha256:data"
    assert manifest["result"]["sharpe"] == 1.2
