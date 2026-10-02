"""Same-instant semantics of the DES engine (contract: docs/simulation_engine.md, "Resolución de un instante").

Minimal hand-checkable models; assertions are about SEMANTICS (who competed, in which order, which state each
carrier is in), never about an arbitrary throughput figure.
"""

from __future__ import annotations

import pytest

from simforge.domain.isms import ISMSModel
from simforge.engine.des.engine import DesEngine
from simforge.library.registry import ComponentRegistry
from simforge.validation.verifier import compile_model

REG = ComponentRegistry.load_default()


def line(racks: int = 2, dispatch: str = "fifo", t_a: float = 10, t_m: float = 5, t_b: float = 10, **op_extra) -> ISMSModel:
    """source -> A (operator, takes a rack) -> M (automatic) -> B (operator, frees the rack) -> sink."""
    op = {"id": "op", "kind": "operator", "quantity": 1, "dispatch": dispatch, **op_extra}
    return ISMSModel.model_validate({
        "meta": {"name": "same-instant"},
        "simulation": {"horizon": {"value": 300, "unit": "s"}},
        "resources": [{"id": "racks", "kind": "carrier", "quantity": racks}, op],
        "nodes": [
            {"id": "src", "component": "source"},
            {"id": "asm", "component": "manual_assembly", "seize": [{"resource": "racks"}],
             "params": {"process_time": {"dist": "constant", "value": t_a}, "resources": [{"resource": "op"}]}},
            {"id": "mach", "component": "machine", "params": {"process_time": {"dist": "constant", "value": t_m}}},
            {"id": "rev", "component": "inspection", "release": ["racks"],
             "params": {"process_time": {"dist": "constant", "value": t_b}, "resources": [{"resource": "op"}]}},
            {"id": "out", "component": "sink"},
        ],
        "edges": [{"source": "src", "target": "asm"}, {"source": "asm", "target": "mach"}, {"source": "mach", "target": "rev"},
                  {"source": "rev", "target": "out"}],
    })


def run(model: ISMSModel, timing: str | None = None):
    if timing:
        model = model.model_copy(update={"simulation": model.simulation.model_copy(update={"dispatch_timing": timing})})
    return DesEngine().run(compile_model(model, REG), model.simulation.base_seed, trace=True)


def decisions(rec, resource: str = "op") -> list[dict]:
    return [d for d in rec.decisions if d["resource"] == resource and d["kind"] == "assign"]


def missed_simultaneous(rec, resource: str = "op") -> list[tuple[float, str]]:
    """Requests created at the instant t of an assignment (of a cause other than that assignment) that were not
    among its candidates. Creation time = t(later decision listing it) - waiting_s."""
    decs = decisions(rec, resource)
    out = []
    for i, d in enumerate(decs):
        cand = {(c["node"], c["entity"]) for c in d["candidates"]}
        for later in decs[i + 1:]:
            for c in later["candidates"]:
                if abs(later["t"] - c["waiting_s"] - d["t"]) < 1e-9 and (c["node"], c["entity"]) not in cand:
                    out.append((d["t"], c["node"]))
                    cand.add((c["node"], c["entity"]))
    return out


# --------------------------------------------------------------------------- contract: every request of the instant competes
def test_cascaded_same_instant_request_competes():
    """t=30: B finishes unit 1 -> operator AND rack free at the same instant. Unit 2 enters B and asks for the
    operator; unit 3 at A gets the freed rack (carrier decision) and then asks for the operator. Both requests are
    created at t=30 -> both must be candidates of the operator decision taken at t=30."""
    rec = run(line())
    d30 = next(d for d in decisions(rec) if abs(d["t"] - 30) < 1e-9)
    assert {c["node"] for c in d30["candidates"]} == {"asm", "rev"}
    assert missed_simultaneous(rec) == []


def test_immediate_mode_unchanged_and_old_behaviour_documented():
    """`immediate` is the documented sensitivity mode (event order, first come first decided) and must not change.
    tests/data/same_instant_engine_0_2_0.json records engine 0.2.0, including its end_of_timestep contract violation
    (the 'asm' request created at t=30 did not compete)."""
    import json
    from pathlib import Path
    old = json.loads((Path(__file__).parent / "data" / "same_instant_engine_0_2_0.json").read_text())
    rec = run(line(), "immediate")
    now = [[round(d["t"], 6), d["chosen_node"], sorted(c["node"] for c in d["candidates"])] for d in decisions(rec)]
    assert now == old["immediate"]["decisions"]
    assert [30.0, "asm"] in old["end_of_timestep"]["missed_simultaneous"]  # the 0.2.0 violation, kept as evidence


# --------------------------------------------------------------------------- A-E: simultaneous events
def test_A_two_tasks_request_the_operator_at_the_same_instant():
    """Both requests created at t=30 compete; FIFO tie at the same time -> older unit first, and the log says so."""
    rec = run(line())
    d30 = next(d for d in decisions(rec) if abs(d["t"] - 30) < 1e-9)
    by_node = {c["node"]: c["entity"] for c in d30["candidates"]}
    assert d30["chosen_entity"] == min(by_node.values())  # unit 2 (review) is older than unit 3 (assembly)
    assert d30["chosen_node"] == "rev" and "older unit" in d30["reason"]


def test_B_carrier_and_operator_free_at_the_same_instant_resolution_order():
    """At t=30 the rack and the operator are freed together: the carrier decision is resolved first (technical
    order), so the task it enables (assembly) reaches the operator decision of the same instant."""
    rec = run(line())
    at30 = [d for d in rec.decisions if abs(d["t"] - 30) < 1e-9 and d["kind"] == "assign"]
    assert [d["resource"] for d in at30] == ["racks", "op"]
    assert {c["node"] for c in at30[1]["candidates"]} == {"asm", "rev"}


def test_C_automatic_operation_ends_when_operator_finishes_another_task():
    """t_m = t_a: the machine releases unit 1 to review exactly when the operator finishes assembling unit 2.
    The review request (created by the machine's completion) competes with the next assembly."""
    rec = run(line(racks=3, t_a=10, t_m=10, t_b=10))
    d20 = next(d for d in decisions(rec) if abs(d["t"] - 20) < 1e-9)
    assert {c["node"] for c in d20["candidates"]} == {"asm", "rev"}
    assert missed_simultaneous(rec) == []


def wip_line(target: int) -> ISMSModel:
    m = line(racks=10, dispatch="wip_target", t_a=10, t_m=25, t_b=10,
             wip_target={"protected_node": "mach", "feed_nodes": ["feed"], "feeder_nodes": ["asm"], "target": target,
                         "count_feeder_in_process": False})
    nodes = [*m.nodes[:2], ISMSModel.model_validate({"meta": {"name": "x"}, "nodes": [
        {"id": "feed", "component": "buffer", "params": {"capacity": 5}}]}).nodes[0], *m.nodes[2:]]
    edges = [{"source": "src", "target": "asm"}, {"source": "asm", "target": "feed"}, {"source": "feed", "target": "mach"},
             {"source": "mach", "target": "rev"}, {"source": "rev", "target": "out"}]
    return ISMSModel.model_validate({**m.model_dump(mode="json"), "nodes": [n.model_dump(mode="json") for n in nodes], "edges": edges})


def test_D_wip_crosses_target_exactly_when_operator_becomes_free():
    """When an assembly ends, the unit enters the feed buffer at the same instant the operator is freed. The decision
    of that instant must see the WIP AFTER the crossing (all same-instant events before decisions)."""
    rec = run(wip_line(target=1))
    ends = {round(e["t"], 6) for e in rec.events if e["event"] == "end_process" and e["node"] == "asm"}
    checked = 0
    for d in decisions(rec):
        if round(d["t"], 6) in ends and next(iter(d["current_task"].values())) == "asm":
            buf_now = d["system"]["buffers"]["feed"]
            assert d["state"]["feed_wip"] == buf_now  # the decision sees the state after the same-instant move
            if buf_now >= 1 and any(c["node"] == "rev" for c in d["candidates"]):
                assert d["chosen_node"] == "rev" and d["reason_code"] == "WIP_AT_OR_ABOVE_TARGET"
                checked += 1
    assert checked > 0  # the crossing really happens at an operator-release instant


def test_E_transport_reservation_at_the_same_instant_as_a_wip_change():
    """Selective model: the transport reserves the assembled rack at the instant the operator is assigned to it.
    During reservation/loading the rack is seen by two sources (assembly place + transport) and counts ONCE."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "diagnostics"))
    import selective_racks as S
    samples = S.feed_wip_probe(2)
    at120 = [p for p in samples if abs(p["t"] - 120) < 1e-9]
    assert at120 and all(p["feed_wip"] == 1 for p in at120)
    assert any(p["shared"] == 1 for p in at120) and not any(p["same_unit_counted_twice"] for p in samples)


# --------------------------------------------------------------------------- strong carrier invariant
def test_carrier_states_are_single_and_include_reserved_for_transport(monkeypatch):
    import sys
    from pathlib import Path
    from simforge.engine.des import runtime
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "diagnostics"))
    import selective_racks as S
    seen: set[str] = set()
    orig = runtime.SimContext.check_carriers

    def spy(self, rid=None):
        orig(self, rid)
        for pool in self.pools.values():
            if pool.spec.kind.value == "carrier":
                seen.update(u.cstate for u in pool.units)
    monkeypatch.setattr(runtime.SimContext, "check_carriers", spy)
    S.run(3, trace=False)
    assert {"available", "manual_assembly", "reserved:transport_1", "transport_1", "selective_soldering", "inspection"} <= seen


@pytest.mark.parametrize("defect", ["duplicate", "lost", "no_owner", "never_collected"])
def test_carrier_invariant_detects_defects(monkeypatch, defect):
    from simforge.engine.des import nodes, runtime

    if defect == "duplicate":  # carrier released to the pool but still held by the entity
        def bad(ctx, e, resource, via=None):
            for rid, units in e.carriers:
                if rid == resource:
                    ctx.pools[rid].release(units)
            ctx.check_carriers(resource)
        monkeypatch.setattr(nodes, "release_carrier", bad)
    elif defect == "lost":  # carrier vanishes from the entity
        monkeypatch.setattr(nodes, "release_carrier", lambda ctx, e, resource, via=None: (e.carriers.clear(), ctx.check_carriers()))
    elif defect == "no_owner":  # removed from the entity, never returned to the pool
        def orphan(ctx, e, resource, via=None):
            e.carriers[:] = [c for c in e.carriers if c[0] != resource]
            ctx.check_carriers(resource)
        monkeypatch.setattr(nodes, "release_carrier", orphan)
    with pytest.raises(runtime.InvariantViolation):
        if defect == "never_collected":
            _stale_grant_scenario()
        else:
            run(line())


def _stale_grant_scenario():
    """Directly exercise the 'granted but never collected' check on a running context."""
    import simpy
    from simforge.engine.base import RunRecord
    from simforge.engine.des.runtime import ResourcePool, SimContext
    from simforge.domain.isms import Resource
    env = simpy.Environment()
    ctx = SimContext(env, 1, 0, 100, RunRecord(seed=1, horizon_s=100, warmup_s=0, engine="x", engine_version="x"), False)
    pool = ResourcePool(ctx, Resource(id="racks", kind="carrier", quantity=1), {})
    ctx.pools["racks"] = pool
    pool.request("asm", 1, 0, None)  # granted at t=0 by the end-of-instant resolution, nobody collects it
    env.run(until=5)
    ctx.check_carriers()


# --------------------------------------------------------------------------- determinism
@pytest.mark.parametrize("build", ["line", "selective_3", "wip"])
def test_repeatability(build):
    import json
    import sys
    from pathlib import Path
    from simforge.analytics.kpis import compute_run_kpis

    def once():
        if build == "selective_3":
            sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "diagnostics"))
            import selective_racks as S
            rec, k, _ = S.run(3)
            return rec, k
        m = line() if build == "line" else wip_line(1)
        cm = compile_model(m, REG)
        rec = DesEngine().run(cm, m.simulation.base_seed, trace=True)
        return rec, compute_run_kpis(rec, cm)
    runs = [once() for _ in range(3)]
    dump = [(json.dumps(r.events, sort_keys=True, default=str), json.dumps(r.decisions, sort_keys=True, default=str),
             json.dumps(k, sort_keys=True, default=str)) for r, k in runs]
    assert dump[0] == dump[1] == dump[2]
