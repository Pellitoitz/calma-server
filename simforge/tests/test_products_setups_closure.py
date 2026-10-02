"""Engine 0.7.0 technical closure: required transitions (repeat, initial -> first, families, mix, reachability, order
preservation), DISPATCH FIRST / SETUP SECOND, persistence of the setup state, setups interrupted on every path,
HOLD_ACQUIRED_RESOURCES during breakdowns, same-instant cases, conservation, hash and persistence."""

from __future__ import annotations

import copy

import pytest

from simforge.domain.io import load_model, model_from_dict, save_model
from simforge.domain.paths import set_value
from simforge.validation.production import required_transitions, visiting_products
from simforge.validation.semantics import verify_model

from .test_products_setups import ABC, REG, C, H, build, cal, calendar_setup_model, codes, ev, run, seq, times


def missing_pairs(m):
    rep, _ = verify_model(m, REG)
    return [i.message for i in rep.errors if i.code == "SETUP_TRANSITION_MISSING"]


def matrix_model(matrix, generation, initial="A", **kw):
    return build(ABC, generation, times(a=1, b=1, c=1),
                 {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": initial, "matrix": matrix, **kw}})


AB_BC = {"A": {"B": C(5)}, "B": {"C": C(7)}}


def state_audit(rec, node="m"):
    """Every setup: the state seen in the trace is `from` from start to completion, `to` only at setup_end; the state
    changes exactly once per completed setup and the chain of states is continuous."""
    prev = None
    for s in rec.setups:
        if prev is not None:
            assert s["from"] == prev
        mids = [e for e in rec.events if e["node"] == node and "setup_state" in e and s["start"] - 1e-5 <= e["t"] <= s["end"] + 1e-5
                and e["event"] != "setup_end"]
        assert all(e["setup_state"] == s["from"] for e in mids), mids
        ends = [e for e in rec.events if e["node"] == node and e["event"] == "setup_end" and e["entity"] == s["entity"]]
        assert len(ends) == 1 and ends[0]["setup_state"] == s["to"] and abs(ends[0]["t"] - s["end"]) < 1e-5
        prev = s["to"]


# --------------------------------------------------------------------------------- 1. EXPLICIT_SEQUENCE + repeat
def test_1_repeat_true_requires_last_to_first():
    gen = seq("a", "b", "c", repeat=True)
    assert any("C→A" in msg for msg in missing_pairs(matrix_model(AB_BC, gen)))
    assert not missing_pairs(matrix_model(AB_BC, seq("a", "b", "c")))  # repeat=false: C->A cannot occur
    ok = matrix_model(AB_BC | {"C": {"A": C(11)}}, gen)
    assert not missing_pairs(ok)
    rec = run(ok).records[0]
    assert [(s["from"], s["to"]) for s in rec.setups[:4]] == [("A", "B"), ("B", "C"), ("C", "A"), ("A", "B")]


def test_1b_repeat_with_same_first_and_last_key_needs_no_wrap_transition():
    m = matrix_model({"A": {"B": C(5)}, "B": {"A": C(3)}}, seq("a", "b", "a", repeat=True))
    assert not missing_pairs(m)


# --------------------------------------------------------------------------------- 2. initial state -> first product
def test_2_initial_state_to_first_product_is_required():
    gen = seq("a", "a", "c")
    assert any("B→A" in msg for msg in missing_pairs(matrix_model({"A": {"C": C(4)}}, gen, initial="B")))
    m = matrix_model({"B": {"A": C(9)}, "A": {"C": C(4)}}, gen, initial="B")
    rec = run(m).records[0]
    assert [(s["from"], s["to"], s["entity"]) for s in rec.setups] == [("B", "A", 1), ("A", "C", 3)]
    unconf = matrix_model({"A": {"C": C(4)}}, gen, initial="UNCONFIGURED")
    assert any("UNCONFIGURED→A" in msg for msg in missing_pairs(unconf))
    rec = run(matrix_model({"A": {"C": C(4)}}, gen, initial="UNCONFIGURED", from_unconfigured={"A": C(6)})).records[0]
    assert rec.setups[0]["from"] == "UNCONFIGURED" and rec.setups[0]["entity"] == 1  # the first product never skips it


# --------------------------------------------------------------------------------- 10. algorithm on setup keys
def test_10_required_transitions_use_setup_keys_deduplicated():
    prods = {"a1": {"setup_key": "FAMILY_A"}, "a2": {"setup_key": "FAMILY_A"}, "b": {"setup_key": "FAMILY_B"}}
    m = build(prods, seq("a1", "a2", "b", "a1", "a2", "b"), times(a1=1, a2=1, b=1),
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "UNCONFIGURED",
                     "matrix": {"FAMILY_A": {"FAMILY_B": C(5)}, "FAMILY_B": {"FAMILY_A": C(5)}},
                     "from_unconfigured": {"FAMILY_A": C(1)}}})
    vis = visiting_products(m, m.production, REG)["m"]
    pairs, basis = required_transitions(m, m.production, "m", vis, REG)
    assert basis == "sequence"
    assert pairs == {("UNCONFIGURED", "FAMILY_A"), ("FAMILY_A", "FAMILY_B"), ("FAMILY_B", "FAMILY_A")}  # never a1 -> a2


# --------------------------------------------------------------------------------- 11. probabilistic mix
def test_11_mix_requires_every_reachable_change():
    mix = {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "b": 0.3, "c": 0.2}}}
    full = {"A": {"B": C(1), "C": C(1)}, "B": {"A": C(1), "C": C(1)}, "C": {"A": C(1), "B": C(1)}}
    assert not missing_pairs(matrix_model(full, mix))
    gap = copy.deepcopy(full)
    del gap["C"]["B"]  # "probably rare" is still possible
    rep, cm = verify_model(matrix_model(gap, mix), REG)
    assert cm is None and [i.message for i in rep.errors if i.code == "SETUP_TRANSITION_MISSING" and "C→B" in i.message]
    zero = {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "b": 0.5, "c": 0.0}}}  # c can never be produced
    assert not missing_pairs(matrix_model({"A": {"B": C(1)}, "B": {"A": C(1)}}, zero))


def test_11b_loss_or_reordering_on_the_path_forces_all_pairs():
    nodes = [{"id": "src", "component": "source"}, {"id": "insp", "component": "machine",
             "params": {"process_time": C(1), "yield_rate": 0.9}}, {"id": "m", "component": "machine"}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "insp"}, {"source": "insp", "target": "m"}, {"source": "m", "target": "out"}]
    # a, b, c with b scrapped upstream -> A->C at 'm' is reachable although not consecutive in the list
    m = build(ABC, seq("a", "b", "c"), times(a=1, b=1, c=1),
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": AB_BC}}, nodes=nodes, edges=edges)
    assert any("A→C" in msg for msg in missing_pairs(m))


# --------------------------------------------------------------------------------- 12. unreachable transitions
def test_12_only_products_that_reach_the_node_are_required():
    nodes = [{"id": "src", "component": "source"}, {"id": "m1", "component": "machine"}, {"id": "m", "component": "machine"},
             {"id": "insp", "component": "machine", "params": {"process_time": C(1)}}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "m1"}, {"source": "m1", "target": "m"}, {"source": "m1", "target": "insp"},
             {"source": "m", "target": "out"}, {"source": "insp", "target": "out"}]
    mix = {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.4, "b": 0.3, "c": 0.3}}}
    m = build(ABC, mix, {"m1": {"a": C(1), "b": C(1), "c": C(1)}, "m": {"a": C(1)}},
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {}}}, nodes=nodes, edges=edges,
              routes={"a": ["src", "m1", "m", "out"], "b": ["src", "m1", "insp", "out"], "c": ["src", "m1", "insp", "out"]})
    rep, cm = verify_model(m, REG)
    assert cm is not None, [str(i) for i in rep.errors]  # b and c never reach 'm': no B/C transitions demanded there
    assert required_transitions(m, m.production, "m", {"a"}, REG)[0] == set()


# --------------------------------------------------------------------------------- 3. DISPATCH FIRST, SETUP SECOND
def queue_model():
    nodes = [{"id": "src", "component": "source"}, {"id": "q", "component": "buffer", "params": {"capacity": 10}},
             {"id": "m", "component": "machine"}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "q"}, {"source": "q", "target": "m"}, {"source": "m", "target": "out"}]
    return build(ABC, seq("a", "b", "c"), times(a=100, b=1, c=1),
                 {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A",
                        "matrix": {"A": {"B": C(600), "C": C(0)}, "B": {"C": C(10)}}}}, nodes=nodes, edges=edges)


def test_3_fifo_queue_is_not_reordered_to_save_setups():
    rec = run(queue_model()).records[0]
    # machine set up for A; queue FIFO = b, c; A->C would cost 0 s, A->B 600 s: b still goes first
    assert [rec.entity_product[e] for e, _, _ in rec.completions] == ["a", "b", "c"]
    assert [(s["from"], s["to"], s["sampled_s"]) for s in rec.setups] == [("A", "B", 600), ("B", "C", 10)]
    assert [d for _, _, d in rec.completions] == [100, 701, 712]


def test_3b_resource_dispatch_ignores_setup_durations():
    # two stations need the same technician at t=1 for their setups: m1 a long one, m2 a short one
    def model(dispatch, prio):
        nodes = [{"id": "src", "component": "source", "params": {"max_entities": 2}}, {"id": "m1", "component": "machine", "priority": prio[0]},
                 {"id": "out", "component": "sink"}, {"id": "src2", "component": "source", "params": {"max_entities": 2}},
                 {"id": "m2", "component": "machine", "priority": prio[1]}, {"id": "out2", "component": "sink"}]
        edges = [{"source": "src", "target": "m1"}, {"source": "m1", "target": "out"}, {"source": "src2", "target": "m2"},
                 {"source": "m2", "target": "out2"}]
        gen = {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}, "src2": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "c"]}}
        st = lambda d: {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(d), "resources": [{"resource": "tech"}]}  # noqa: E731
        return build(ABC, gen, {"m1": {"a": C(1), "b": C(1)}, "m2": {"a": C(1), "c": C(1)}}, {"m1": st(600), "m2": st(5)},
                     resources=[{"id": "tech", "quantity": 1, "dispatch": dispatch}], nodes=nodes, edges=edges)
    fifo = run(model("fifo", (0, 0))).records[0]  # simultaneous: declaration order tie-break (m1 first), as in 0.6
    assert [(s["node"], s["start"]) for s in fifo.setups] == [("m1", 1), ("m2", 601)]
    prio = run(model("priority", (1, 0))).records[0]  # PRIORITY: m2 (lower number) first - static priority, not setup time
    assert [(s["node"], s["start"]) for s in prio.setups] == [("m2", 1), ("m1", 6)]


# --------------------------------------------------------------------------------- 4. state persists (idle/off-shift)
def test_4_setup_state_survives_idle_and_off_shift():
    nodes = [{"id": "src", "component": "source", "params": {"arrival": "interarrival", "interarrival": C(30000), "max_entities": 3}},
             {"id": "m", "component": "machine"}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}]
    m = build(ABC, seq("a", "a", "a"), times(a=10, b=1, c=1),
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "UNCONFIGURED", "constant": C(5),
                     "from_unconfigured": {"A": C(50)}, "at_unavailability": "PAUSE_RESUME"}},
              nodes=nodes, edges=edges, horizon_h=48,
              availability={"mode": "relative_week", "calendars": [cal("mach")], "nodes": {"m": "mach"}, "always_available": ["src"],
                            "operations": {"m": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}})
    rec = run(m).records[0]
    # arrivals 08:20 (day 1), 16:40 (off-shift, waits to 06:00 day 2), 01:00 day 2 (off-shift); only the first needs a setup
    assert [(s["from"], s["to"]) for s in rec.setups] == [("UNCONFIGURED", "A")] and rec.node_setups["m"] == 1
    assert len(rec.completions) == 3


# --------------------------------------------------------------------------------- 5. state + breakdown
def test_5_breakdown_does_not_change_setup_state():
    nodes = [{"id": "src", "component": "source", "params": {"arrival": "interarrival", "interarrival": C(50), "max_entities": 2}},
             {"id": "m", "component": "machine", "params": {"failures": {"mtbf": C(15), "mttr": C(30)}}}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}]
    m = build(ABC, seq("a", "a"), times(a=1, b=1, c=1), {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5)}},
              nodes=nodes, edges=edges)
    r = run(m)
    rec = r.records[0]
    assert rec.setups == [] and rec.node_failures["m"] >= 2  # configured A -> failure -> repair -> A: no setup
    assert all(e["setup_state"] == "A" for e in rec.events if e["event"] in ("down", "up"))


def test_5b_and_6_setup_state_changes_once_and_only_on_completion_on_every_path():
    fail = {"mtbf": C(50), "mttr": C(30)}
    brk = build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, seq("a", "b"), {"m": {"a": C(10), "b": C(10)}},
                {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(100)}}, machine_params={"failures": fail})
    uni = {"dist": "uniform", "low": 500, "high": 700, "unit": "s"}
    both = calendar_setup_model().model_dump(mode="json")
    both["nodes"][1]["params"]["failures"] = {"mtbf": C(50400), "mttr": C(3600)}
    cases = {"breakdown": brk, "pause_resume": calendar_setup_model(seq_items=("a", "b", "c")),
             "stop_restart": calendar_setup_model("STOP_RESTART", uni, seq_items=("a", "b", "c")),
             "calendar+breakdown same instant": model_from_dict(both)}
    for name, m in cases.items():
        rec = run(m).records[0]
        assert rec.setups, name
        state_audit(rec)
        pauses = [e for e in rec.events if e["event"] in ("setup_paused_by_calendar", "setup_restart_lost_work", "setup_resume", "down", "up")]
        assert pauses, name


# --------------------------------------------------------------------------------- 7. HOLD_ACQUIRED_RESOURCES
def test_7_setup_resources_are_held_during_a_breakdown():
    # tech does the A->B setup at m (10..170 with failures 50-80, 130-160); station 'o' asks for tech at 60 (m is down):
    # SETUP_BREAKDOWN_RESOURCE_POLICY = HOLD_ACQUIRED_RESOURCES -> 'o' only gets tech when the setup completes (170)
    nodes = [{"id": "src", "component": "source"}, {"id": "m", "component": "machine", "params": {"failures": {"mtbf": C(50), "mttr": C(30)}}},
             {"id": "out", "component": "sink"},
             {"id": "src2", "component": "source", "params": {"arrival": "interarrival", "interarrival": C(60), "max_entities": 1}},
             {"id": "o", "component": "manual_assembly", "params": {"process_time": C(5), "resources": [{"resource": "tech"}]}},
             {"id": "out2", "component": "sink"}]
    edges = [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}, {"source": "src2", "target": "o"},
             {"source": "o", "target": "out2"}]
    gen = seq("a", "b") | {"src2": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["c"]}}
    m = build(ABC, gen, times(a=10, b=10, c=1),
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(100), "resources": [{"resource": "tech"}]}},
              resources=[{"id": "tech", "kind": "operator", "quantity": 1}], nodes=nodes, edges=edges)
    r = run(m)
    rec = r.records[0]
    assert rec.setups[0]["end"] == 170 and [i["cause"] for i in rec.setups[0]["interruptions"]] == ["failure", "failure"]
    assert [t for t, _, _ in ev(r, "start_process", node="o")] == [170]
    assert rec.resource_state_time["tech"]["working:m#setup"] == 160


# --------------------------------------------------------------------------------- 14. conservation / WIP in setup
def test_14_entity_in_paused_setup_exists_exactly_once():
    m = calendar_setup_model()
    m = set_value(m, "simulation.horizon.value", 20)  # ends during the paused A->B setup (14:00 -> 06:00)
    r = run(m)
    rec = r.records[0]
    assert rec.wip_end == 1 and rec.wip_end_by_product == {"a": 0, "b": 1}
    assert rec.created_by_product["b"] == rec.wip_end_by_product["b"] and len(rec.completions) == 1
    assert rec.setups == []  # never completed -> no audit row, no count, state unchanged
    assert r.kpis.mean("node.m.setup_count") == 0 and r.kpis.mean("product.b.avg_wip") > 0


# --------------------------------------------------------------------------------- 15. same instant
def test_15a_setup_completing_exactly_at_shift_end_changes_state():
    rec = run(calendar_setup_model(a_time=28200)).records[0]
    assert rec.setups[0]["end"] == 14 * H and not rec.setups[0]["interruptions"]
    state_audit(rec)


def test_15d_repair_and_calendar_back_at_the_same_instant_single_acquire():
    # setup paused at 14:00; failure 17:00 repaired exactly at 06:00 (= shift start): one resume, one acquire
    m = calendar_setup_model()
    data = m.model_dump(mode="json")
    data["nodes"][1]["params"]["failures"] = {"mtbf": C(17 * H), "mttr": C(13 * H)}
    runs = [run(model_from_dict(data)).records[0] for _ in range(3)]
    assert all(x.events == runs[0].events for x in runs)
    rec = runs[0]
    resumes = [e for e in rec.events if e["event"] == "setup_resume"]
    acquires = [e for e in rec.events if e["event"] == "wait_resource" and e.get("task") == "m#setup" and e["resume"]]
    assert [e["t"] for e in resumes] == [30 * H] and len(acquires) == 1
    assert rec.setups[0]["end"] == 30 * H + 300 and rec.resource_state_time["tech"]["working:m#setup"] == 600
    state_audit(rec)


# --------------------------------------------------------------------------------- 13. capacity > 1
def test_13_capacity_two_is_rejected_before_running_never_degraded():
    m = build(ABC, seq("a", "b"), times(a=1, b=1, c=1),
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5)}}, machine_params={"capacity": 2})
    rep, cm = verify_model(m, REG)
    assert cm is None and "SETUP_SEMANTICS_UNSUPPORTED_FOR_MULTI_SLOT_NODE" in codes(m)


# --------------------------------------------------------------------------------- 16/17. hash, approval, persistence
def closure_model():
    prods = {"a1": {"setup_key": "FAMILY_A"}, "a2": {"setup_key": "FAMILY_A"}, "b": {"setup_key": "FAMILY_B"}}
    return build(prods, seq("a1", "a2", "b", repeat=True), times(a1=900, a2=1200, b=600),
                 {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "FAMILY_B", "at_unavailability": "PAUSE_RESUME",
                        "matrix": {"FAMILY_A": {"FAMILY_B": C(1200)}, "FAMILY_B": {"FAMILY_A": C(1800)}},
                        "resources": [{"resource": "tech"}]}},
                 resources=[{"id": "tech", "kind": "operator", "quantity": 1}], horizon_h=40,
                 availability={"mode": "relative_week", "calendars": [cal("mach"), cal("techc", "07:00", "15:00")],
                               "nodes": {"m": "mach"}, "resources": {"tech": "techc"}, "always_available": ["src"],
                               "operations": {"m": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}})


@pytest.mark.parametrize("path,value", [
    ("production.generation.src.repeat", False), ("production.setups.m.initial_state", "FAMILY_A"),
    ("production.products.b.setup_key", "FAMILY_A"), ("production.setups.m.matrix.FAMILY_A.FAMILY_B.value", 1100),
    ("production.setups.m.resources", []), ("production.setups.m.at_unavailability", "STOP_RESTART"),
])
def test_16_hash_and_approval(path, value):
    m = closure_model()
    m = m.model_copy(update={"approval": m.approval.model_copy(update={"approved": True, "model_hash": m.content_hash()})})
    changed = set_value(m, path, value)
    assert m.is_approved and changed.content_hash() != m.content_hash() and not changed.is_approved


def test_17_save_load_run_identical(tmp_path):
    m = closure_model()
    save_model(m, tmp_path / "m.yaml")
    back = load_model(tmp_path / "m.yaml")
    assert back.content_hash() == m.content_hash() and back.production == m.production and back.availability == m.availability
    r1, r2 = run(m), run(back)
    a, b = r1.records[0], r2.records[0]
    assert a.events == b.events and a.setups == b.setups and r1.per_replication == r2.per_replication
    assert [(s["from"], s["to"]) for s in a.setups][:2] == [("FAMILY_B", "FAMILY_A"), ("FAMILY_A", "FAMILY_B")]
    state_audit(a)


def test_19_legacy_models_create_no_production_stream():
    from simforge.engine.des.engine import DesEngine
    from simforge.engine.des.runtime import SimContext

    from .conftest import EXAMPLES
    seen: list[tuple] = []
    orig = SimContext.rng

    def spy(self, *key):
        seen.append(key)
        return orig(self, *key)
    SimContext.rng = spy
    try:
        m = load_model(EXAMPLES / "03_machine_breakdowns.yaml")
        _, cm = verify_model(m, REG)
        DesEngine().run(cm, 1)
    finally:
        SimContext.rng = orig
    assert seen and not any(k[-1] in ("product_mix", "setup") for k in seen)
