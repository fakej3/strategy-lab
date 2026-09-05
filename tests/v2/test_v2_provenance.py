"""Golden tests for deterministic provenance fingerprints."""

from research.v2_provenance import environment_fingerprint, fingerprint_records


def test_record_fingerprint_is_order_independent():
    assert fingerprint_records({"b": 2, "a": 1}) == fingerprint_records({"a": 1, "b": 2})


def test_material_input_change_changes_fingerprint():
    assert fingerprint_records([1, 2, 3]) != fingerprint_records([1, 2, 4])


def test_environment_fingerprint_changes_with_dependency_version():
    a = environment_fingerprint(python_version="3.12", dependencies={"numpy": "2.0"})
    b = environment_fingerprint(python_version="3.12", dependencies={"numpy": "2.1"})
    assert a != b
