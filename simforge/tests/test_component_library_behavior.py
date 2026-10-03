"""1.1-E (C15): behaviour tests for the DRAFT library components, built around the frozen library YAMLs.

They document BEHAVIOR_TEST_COVERED evidence only. The metadata `validation_status` lives in the FREEZE-protected
YAMLs and is NOT promoted here (FREEZE_CHANGE_PROPOSAL, see docs/roadmap/1.1_roadmap.md).
Expected values derive from the declared contract (behaviour `server`, defaults) and hand calculation:
a single server fed by an infinite source with a constant time t completes floor(H / t) units per slot in H.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import verify_model

from .conftest import C, line

REG = ComponentRegistry.load_default()
DRAFT = sorted(c.id for c in REG.all() if c.validation_status.value == "draft")
TESTED_BEFORE = sorted(c.id for c in REG.all() if c.validation_status.value == "tested")


def test_inventory_is_the_audited_one():
    assert len(REG.all()) == 26 and len(DRAFT) == 19 and len(TESTED_BEFORE) == 7
    assert TESTED_BEFORE == ["buffer", "machine", "manual_process", "rack_transport", "sink", "source", "transport"]


@pytest.mark.parametrize("cid", DRAFT)
def test_draft_component_declared_contract(cid):
    comp = REG.get(cid)
    assert comp.behavior.value == "server" and comp.defaults == {"capacity": 1}
    assert comp.validation_status.value == "draft"  # metadata untouched (FREEZE): coverage is documented, not promoted
    p = comp.resolve_params({"process_time": C(30)})
    assert p.capacity == 1 and p.process_time.mean_seconds() == 30 and p.yield_rate == 1.0
    with pytest.raises(ValidationError):
        comp.resolve_params({"process_time": C(30), "teleport": True})  # unknown parameter rejected (extra="forbid")
    with pytest.raises(ValidationError):
        comp.resolve_params({"process_time": C(30), "capacity": 0})
    with pytest.raises(ValidationError):
        comp.resolve_params({"process_time": C(30), "yield_rate": 1.5})


@pytest.mark.parametrize("cid", DRAFT)
def test_draft_component_missing_time_is_reported(cid):
    m = line([("st", cid, {})], horizon_h=1)
    rep, _ = verify_model(m, REG)
    assert any(i.code == "MISSING" and i.path == "nodes.st.params.process_time" for i in rep.errors)


@pytest.mark.parametrize("cid", DRAFT)
@pytest.mark.parametrize("capacity,expected", [(None, 120), (2, 240)])
def test_draft_component_runs_as_its_declared_server_behaviour(cid, capacity, expected):
    params = {"process_time": C(30), **({"capacity": capacity} if capacity else {})}
    m = line([("st", cid, params)], horizon_h=1)
    rep, _ = verify_model(m, REG)
    assert rep.ok, rep.summary()
    res = run_simulation(m, REG)
    assert res.kpis.mean("units_completed") == expected  # floor(3600 / 30) per slot
    assert res.kpis.mean("node.st.utilization") == pytest.approx(1.0)


@pytest.mark.parametrize("cid", DRAFT)
def test_draft_component_yield_scraps_as_declared(cid):
    m = line([("st", cid, {"process_time": C(30), "yield_rate": 0.5})], horizon_h=1)
    res = run_simulation(m, REG, replications=3)
    done, scrap = res.kpis.mean("units_completed"), res.kpis.mean("units_scrapped")
    assert done + scrap == 120 and 0 < scrap < 120  # every processed unit is either good or scrapped


def test_coverage_summary():
    """Exact numbers reported in the checkpoint: every draft component has behaviour coverage, none promoted."""
    covered = [c for c in DRAFT if REG.get(c).behavior.value == "server"]
    assert (len(DRAFT), len(covered), len(DRAFT) - len(covered)) == (19, 19, 0)
