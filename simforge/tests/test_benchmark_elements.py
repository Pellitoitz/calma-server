"""Tests for the selective-soldering benchmark building blocks.

ALL NUMERIC VALUES IN THIS FILE ARE SYNTHETIC TEST DATA (chosen so results can be
computed by hand). None of them comes from, or should be used for, the real process.
"""

from __future__ import annotations

import pytest

from simforge.domain.io import model_from_dict
from simforge.domain.isms import WipTargetParams
from simforge.domain.paths import set_value
from simforge.engine import DesEngine
from simforge.engine.base import NodeState
from simforge.engine.des.dispatch import WipTargetPriority
from simforge.experiments.runner import run_experiment, run_simulation
from simforge.domain.isms import ExperimentSpec, Factor
from simforge.validation.verifier import Readiness, compile_model, verify


def C(v: float, unit: str = "s") -> dict:
    return {"dist": "constant", "value": v, "unit": unit}


def build(nodes: list[dict], resources: list[dict] | None = None, edges: list[tuple] | None = None,
          parameters: list[dict] | None = None, horizon_h: float = 1, trace: bool = False):
    ids = [n["id"] for n in nodes]
    return model_from_dict({
        "meta": {"name": "synthetic"},
        "simulation": {"horizon": {"value": horizon_h, "unit": "h"}, "trace": trace},
        "parameters": parameters or [], "resources": resources or [], "nodes": nodes,
        "edges": [{"source": a, "target": b, **({"probability": p} if p is not None else {})}
                  for a, b, p in (edges or [(a, b, None) for a, b in zip(ids, ids[1:])])],
    })


def transport_params(**kw) -> dict:
    p = {"distance": {"value": 10, "unit": "m"}, "speed": {"value": 1, "unit": "m/s"}, "load_time": C(2), "unload_time": C(3)}
    p.update(kw)
    return p


def line_with_transport(tp: dict, resources=None, positions=None):
    nodes = [{"id": "src", "component": "source"},
             {"id": "m1", "component": "machine", "params": {"process_time": C(10)}},
             {"id": "tr", "component": "transport", "params": tp},
             {"id": "out", "component": "sink"}]
    for n in nodes:
        if positions and n["id"] in positions:
            n["position"] = positions[n["id"]]
    return build(nodes, resources)


# =============================================================== TRANSPORT
def test_transport_one_unit_per_trip_exact(registry):
    # cycle = load 2 + travel 10 m / 1 m/s + unload 3 + empty return 10 = 25 s -> 3600/25 = 144
    res = run_simulation(line_with_transport(transport_params()), registry)
    k = res.kpis
    assert k.mean("units_completed") == 144
    assert k.mean("node.tr.trips") == 144
    assert k.mean("node.tr.avg_load") == 1
    bound = next(f for f in res.findings if f.code == "THEORETICAL_CONSTRAINT")
    assert bound.subject == "tr" and bound.evidence["theoretical_max_per_hour"] == pytest.approx(144)


def test_transport_capacity_two_full_batches(registry):
    # two units per 25 s trip; first delivery at 35 s -> deliveries at 35 + 25k -> 143 trips x 2
    res = run_simulation(line_with_transport(transport_params(capacity=2, batch="full", loading_area=2)), registry)
    assert res.kpis.mean("units_completed") == 286
    assert res.kpis.mean("node.tr.trips") == 143
    assert res.kpis.mean("node.tr.avg_load") == 2


def test_transport_resource_walks_back_by_positions(registry):
    # same 25 s cycle when the operator walks back 10 m (positions) instead of an explicit empty return
    m = line_with_transport(transport_params(return_empty=False, resources=[{"resource": "op"}]),
                            resources=[{"id": "op", "quantity": 1, "home": "m1", "travel": {"speed": {"value": 1, "unit": "m/s"}}}],
                            positions={"m1": {"x": 0}, "tr": {"x": 0}, "out": {"x": 10}})
    res = run_simulation(m, registry)
    assert res.kpis.mean("units_completed") == 144
    # per trip: 10 s transporting (loaded) + 10 s walking back unloaded; last walk-back cut by the horizon
    assert res.kpis.mean("resource.op.transporting_h") == pytest.approx(144 * 10 / 3600, abs=1e-9)
    assert res.kpis.mean("resource.op.walking_h") == pytest.approx(143 * 10 / 3600)  # 144th walk-back after the horizon
    assert res.kpis.mean("resource.op.working_h") == pytest.approx(144 * 5 / 3600)  # load 2 + unload 3


@pytest.mark.parametrize("missing", ["distance", "speed", "load_time", "unload_time"])
def test_transport_required_params_are_never_defaulted(registry, missing):
    tp = transport_params()
    del tp[missing]
    rep, cm = verify(line_with_transport(tp), registry)
    assert cm is None and rep.readiness is Readiness.INCOMPLETE
    assert any(i.code == "MISSING" and i.path.endswith(missing) for i in rep.errors)


def test_transport_origin_destination_must_match_flow(registry):
    rep, _ = verify(line_with_transport(transport_params(origin="out")), registry)
    assert any(i.code == "BAD_TRANSPORT" for i in rep.errors)


def racks_loop(via: bool, racks: int = 1):
    nodes = [{"id": "src", "component": "source"},
             {"id": "assembly", "component": "manual_process", "seize": [{"resource": "racks"}], "params": {"process_time": C(10)}},
             {"id": "review", "component": "inspection", "release": ["racks"], "params": {"process_time": C(10)}},
             {"id": "out", "component": "sink"}]
    if via:
        nodes[2]["release_via"] = {"racks": "rack_return"}
    m = build(nodes, [{"id": "racks", "kind": "carrier", "quantity": racks}])
    if via:
        data = m.model_dump(mode="json")
        data["nodes"].append({"id": "rack_return", "component": "rack_transport",
                              "params": transport_params(origin="review", destination="assembly", distance={"value": 5, "unit": "m"},
                                                         load_time=C(0), unload_time=C(0), return_empty=False)})
        m = model_from_dict(data)
    return m


def test_empty_rack_return_transport_exact(registry):
    # 1 rack: assembly 10 + review 10 (+ return 5 m at 1 m/s = 5 s) -> cycle 20 s without / 25 s with transport
    no_via = run_simulation(racks_loop(via=False), registry)
    with_via = run_simulation(racks_loop(via=True), registry)
    assert no_via.kpis.mean("units_completed") == 180  # completions at 20, 40, ..., 3600
    assert with_via.kpis.mean("units_completed") == 144  # completions at 20 + 25k <= 3600
    assert with_via.kpis.mean("node.rack_return.trips") == 144  # last return: 3595 -> 3600 (events at the horizon count)
    loop = next(f for f in with_via.findings if f.code == "THEORETICAL_CONSTRAINT")
    assert loop.evidence["theoretical_max_per_hour"] == pytest.approx(144)  # carrier loop 25 s incl. return


def test_return_transport_must_not_be_in_product_flow(registry):
    m = racks_loop(via=True)
    data = m.model_dump(mode="json")
    data["edges"].append({"source": "rack_return", "target": "out"})
    rep, _ = verify(model_from_dict(data), registry)
    assert any(i.code == "BAD_TRANSPORT" for i in rep.errors)


# =============================================================== PARAMETERS & SECOND BRANCH
def selective_split(share, circuits=10):
    return build(
        [{"id": "src", "component": "source"},
         {"id": "q", "component": "buffer", "params": {"capacity": 5}},
         {"id": "branch1", "component": "selective_soldering", "params": {"process_time": C(1), "work_units": "$circuits_per_rack"}},
         {"id": "branch2", "component": "selective_soldering", "params": {"process_time": C(1), "work_units": "$circuits_per_rack"}},
         {"id": "out", "component": "sink"}],
        edges=[("src", "q", None), ("q", "branch1", "1 - $branch2_share"), ("q", "branch2", "$branch2_share"),
               ("branch1", "out", None), ("branch2", "out", None)],
        parameters=[{"id": "circuits_per_rack", "value": circuits, "unit": "circuits", "description": "synthetic"},
                    {"id": "branch2_share", "value": share, "min": 0, "max": 1, "description": "synthetic",
                     "provenance": {"status": "assumed", "note": "synthetic test value"}}],
        horizon_h=10)


def test_work_units_multiply_process_time(registry):
    # 1 s/circuit x 10 circuits = 10 s per rack; branch2_share = 0 would be invalid probability -> use share 0.5
    cm = compile_model(selective_split(0.5, circuits=10), registry)
    rec = DesEngine().run(cm, 1)
    busy = rec.node_state_time["branch1"]["busy"]
    assert busy == pytest.approx(rec.node_processed["branch1"] * 10, abs=10)


def test_branch_share_is_an_explicit_traceable_parameter(registry):
    res = run_simulation(selective_split(0.3), registry)
    k = res.kpis
    b1, b2 = k.mean("node.branch1.processed"), k.mean("node.branch2.processed")
    assert b2 / (b1 + b2) == pytest.approx(0.3, abs=0.03)
    m = set_value(selective_split(0.3), "parameters.branch2_share.value", 0.6)
    k2 = run_simulation(m, registry).kpis
    assert k2.mean("node.branch2.processed") > k.mean("node.branch2.processed")


def test_missing_parameter_makes_model_incomplete(registry):
    rep, cm = verify(selective_split(None), registry)
    assert cm is None and rep.readiness is Readiness.INCOMPLETE
    msg = " ".join(i.message for i in rep.errors if i.code == "MISSING")
    assert "branch2_share" in msg


def test_parameter_range_and_bad_expression(registry):
    rep, _ = verify(selective_split(1.5), registry)
    assert any(i.code == "PARAM_RANGE" for i in rep.errors)
    m = selective_split(0.3)
    data = m.model_dump(mode="json")
    data["edges"][1]["probability"] = "1 - $nope"
    rep, _ = verify(model_from_dict(data), registry)
    assert any(i.code == "BAD_EXPRESSION" for i in rep.errors)


def test_experiment_over_model_parameter(registry):
    exp = run_experiment(selective_split(0.3), ExperimentSpec(factors=[Factor(path="parameters.circuits_per_rack.value", values=[5, 10])]),
                         registry)
    th = [s.result.kpis.mean("throughput_per_hour") for s in exp.scenarios]
    assert th[0] > th[1]  # more circuits per rack -> fewer racks per hour


# =============================================================== WIP_TARGET_PRIORITY
class _Node:
    def __init__(self, occ=0, states=None):
        self._occ, self._st = occ, states or {}

    def occupancy(self):
        return self._occ

    def state_counts(self):
        return self._st


class _Req:
    def __init__(self, seq, node):
        self.seq, self.node, self.t, self.priority, self.entity, self.resume = seq, node, 0.0, 0, seq, False


class _Pool:
    def __init__(self, nodes):
        self.ctx = type("Ctx", (), {"nodes": nodes})()
        self.waiting, self.units = [], []


def _strategy(**kw):
    p = dict(protected_node="machine", feed_nodes=["feed"], feeder_nodes=["assembly"], target=2, count_feeder_in_process=False)
    p.update(kw)
    return WipTargetPriority(WipTargetParams(**p))


@pytest.mark.parametrize("feed, machine_state, expected, reason_part", [
    (0, {NodeState.BUSY: 1}, "assembly", "< target"),
    (1, {NodeState.BUSY: 1}, "assembly", "< target"),
    (2, {NodeState.BUSY: 1}, "review", ">= target"),
    (3, {NodeState.STARVED: 1}, "review", ">= target"),
    (0, {NodeState.BLOCKED: 1}, "review", "BLOCKED"),  # unblocking the protected node beats feeding it
])
def test_wip_target_rule_table(feed, machine_state, expected, reason_part):
    s = _strategy()
    pool = _Pool({"feed": _Node(feed), "machine": _Node(states=machine_state), "assembly": _Node()})
    chosen, reason, state = s.choose(pool, [_Req(2, "assembly"), _Req(1, "review")])
    assert chosen.node == expected and reason_part in reason
    assert state["feed_wip"] == feed and state["target"] == 2


def test_wip_target_single_class_and_in_process_counting():
    s = _strategy(count_feeder_in_process=True)
    pool = _Pool({"feed": _Node(1), "machine": _Node(states={NodeState.BUSY: 1}),
                  "assembly": _Node(states={NodeState.BUSY: 1})})
    chosen, reason, state = s.choose(pool, [_Req(1, "assembly"), _Req(2, "review")])
    assert state["feed_wip"] == 2 and chosen.node == "review"  # 1 in buffer + 1 being assembled
    chosen, reason, _ = s.choose(pool, [_Req(1, "assembly")])
    assert chosen.node == "assembly" and "only feeder" in reason


def shared_operator_line(dispatch: str, target=2, preempt_below=None, review_s=14, trace=True):
    res = {"id": "op", "quantity": 1, "dispatch": dispatch}
    if dispatch == "wip_target":
        res["wip_target"] = {"protected_node": "machine", "feed_nodes": ["feed"], "feeder_nodes": ["assembly"],
                             "target": target, "preempt_below": preempt_below}
    return build([
        {"id": "src", "component": "source"},
        {"id": "assembly", "component": "manual_assembly", "priority": 2, "params": {"process_time": C(15), "resources": [{"resource": "op"}]}},
        {"id": "feed", "component": "buffer", "params": {"capacity": 3}},
        {"id": "machine", "component": "machine", "params": {"process_time": C(30)}},
        {"id": "outq", "component": "buffer", "params": {"capacity": 2}},
        {"id": "review", "component": "inspection", "priority": 1, "params": {"process_time": C(review_s), "resources": [{"resource": "op"}]}},
        {"id": "out", "component": "sink"}], [res], horizon_h=8, trace=trace)


def test_wip_target_decisions_follow_the_rule_and_are_fully_logged(registry):
    cm = compile_model(shared_operator_line("wip_target", target=2), registry)
    rec = DesEngine().run(cm, 1, trace=True)
    assert rec.decisions and all(d["rule"] == "wip_target" for d in rec.decisions)
    contested = [d for d in rec.decisions if d["contested"]]
    assert contested
    for d in rec.decisions:
        assert {"state", "candidates", "reason", "chosen_node"} <= set(d)
        assert {"feed_wip", "target", "feed_detail", "machine_state"} <= set(d["state"])
    for d in contested:
        nodes = {c["node"] for c in d["candidates"]}
        feed, blocked = d["state"]["feed_wip"], d["state"]["machine_state"].get("blocked", 0) > 0
        if blocked and nodes - {"assembly"}:
            assert d["chosen_node"] != "assembly"
        elif feed < 2 and "assembly" in nodes:
            assert d["chosen_node"] == "assembly", d
        elif nodes - {"assembly"}:
            assert d["chosen_node"] != "assembly", d


def test_wip_target_is_comparable_with_fifo_and_priority(registry):
    results = {r: run_simulation(shared_operator_line(r, trace=False), registry).kpis for r in ("fifo", "priority", "wip_target")}
    for k in results.values():  # same model, same seeds: operator is not the constraint -> machine fully fed
        assert k.mean("node.machine.utilization") > 0.99
        assert 955 <= k.mean("units_completed") <= 960


def test_preemption_suspends_and_resumes_without_losing_work(registry):
    # review 60 s makes the operator the constraint; pre-emption at feed < 1 interrupts reviews
    cm = compile_model(shared_operator_line("wip_target", target=2, preempt_below=1, review_s=60), registry)
    rec = DesEngine().run(cm, 1, trace=True)
    pre = [d for d in rec.decisions if d["kind"] == "preempt"]
    assert pre and all(d["chosen_node"] == "review" and "preempt_below" in d["reason"] for d in pre)
    events = rec.events
    suspended = [e for e in events if e["event"] == "preempted"]
    resumed = [e for e in events if e["event"] == "resume_process"]
    assert len(suspended) == rec.node_preemptions["review"] >= 1
    assert {e["entity"] for e in suspended} <= {e["entity"] for e in resumed} | {None}
    # work conservation: busy time == processed x 60 s (+ at most one unfinished review)
    busy = rec.node_state_time["review"]["busy"]
    assert 0 <= busy - rec.node_processed["review"] * 60 < 60 + 1e-6


@pytest.mark.parametrize("patch, code", [
    ({"target": None}, "MISSING"),
    ({"feeder_nodes": ["machine"]}, "BAD_WIP_TARGET"),  # machine does not use the operator
    ({"protected_node": "feed"}, "BAD_WIP_TARGET"),  # must be a station
    ({"preempt_below": 5}, "BAD_PARAM"),  # > target
])
def test_wip_target_verification(registry, patch, code):
    m = shared_operator_line("wip_target")
    data = m.model_dump(mode="json")
    data["resources"][0]["wip_target"].update(patch)
    rep, _ = verify(model_from_dict(data), registry)
    assert any(i.code == code for i in rep.errors), [str(i) for i in rep.errors]


def test_wip_target_target_can_be_a_parameter(registry):
    m = shared_operator_line("wip_target")
    data = m.model_dump(mode="json")
    data["resources"][0]["wip_target"]["target"] = "$wip_target"
    data["parameters"] = [{"id": "wip_target", "value": None}]
    rep, _ = verify(model_from_dict(data), registry)
    assert rep.readiness is Readiness.INCOMPLETE
    data["parameters"][0]["value"] = 2
    assert verify(model_from_dict(data), registry)[0].ok
