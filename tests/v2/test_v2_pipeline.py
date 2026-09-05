"""Golden tests for mandatory research gates."""

import pytest
from research.v2_pipeline import GateStatus, ResearchPipeline


def test_all_pass_is_publishable():
    p = ResearchPipeline()
    result = p.run(
        data=[1, 2],
        validate=lambda x: x,
        research=lambda x: {"value": x},
        checks=[("causality", lambda _: True), ("accounting", lambda _: True)],
    )
    assert result.publishable
    assert [g.status for g in result.gates] == [GateStatus.PASS] * 3


def test_failed_gate_blocks_publishability():
    p = ResearchPipeline()
    with pytest.raises(RuntimeError):
        p.run(
            data=[1],
            validate=lambda x: x,
            research=lambda x: x,
            checks=[("causality", lambda _: (_ for _ in ()).throw(RuntimeError("future leak")))],
        )
    assert not p.gates[-1].status == GateStatus.PASS


def test_validation_failure_is_recorded():
    p = ResearchPipeline()
    with pytest.raises(ValueError):
        p.run(data=None, validate=lambda _: (_ for _ in ()).throw(ValueError("bad data")), research=lambda x: x, checks=[])
    assert p.gates[0].name == "data_validation"
    assert p.gates[0].status == GateStatus.FAIL
    assert not p.gates[0].detail == ""
