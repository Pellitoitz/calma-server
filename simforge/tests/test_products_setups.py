"""Engine 0.7.0: product mix, explicit sequences, product-specific processing/routing, setups / changeovers.
Every expected value is computed by hand in the test (no result was copied from the engine)."""

from __future__ import annotations

import copy

import pytest

from simforge.domain.io import dump_model, load_model, model_from_dict, save_model
from simforge.domain.paths import set_value
from simforge.engine.production_compile import SetupTransitionMissing
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import verify_model

from .conftest import EXAMPLES

REG = ComponentRegistry.load_default(None)
H = 3600.0
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def C(v):
    return {"dist": "constant", "value": v, "unit": "s"}


def build(products: dict, generation, processing=None, setups=None, routes=None, nodes=None, edges=None,
          horizon_h=1.0, resources=None, availability=None, machine_params=None, entities=None):
    nodes = nodes or [{"id": "src", "component": "source"}, {"id": "m", "component": "machine", "params": machine_params or {}},
                      {"id": "out", "component": "sink"}]
    edges = edges or [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}]
    prod = {"products": products, "generation": generation}
    if processing is not None:
        prod["processing"] = processing
    if setups is not None:
        prod["setups"] = setups
    if routes is not None:
        prod["routes"] = {p: {"nodes": r} for p, r in routes.items()}
    d = {"meta": {"name": "p7"}, "simulation": {"horizon": {"value": horizon_h, "unit": "h"}},
         "entities": entities or [{"id": p, "name": p.upper()} for p in products],
         "resources": resources or [], "nodes": nodes, "edges": edges, "production": prod}
    if availability is not None:
        d["availability"] = availability
    return model_from_dict(d)


def seq(*items, repeat=False):
    return {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": list(items), "repeat": repeat}}


def times(**kw):
    return {"m": {p: C(v) for p, v in kw.items()}}


def run(m, seed=None, reps=1):
    rep, cm = verify_model(m, REG)
    assert cm is not None, [str(i) for i in rep.errors]
    return run_simulation(m, REG, replications=reps, trace=True, keep_records=True, **({"base_seed": seed} if seed else {}))


def codes(m):
    rep, _ = verify_model(m, REG)
    return {i.code for i in rep.errors}


def ev(r, *names, node="m"):
    return [(e["t"], e["event"], e.get("entity")) for e in r.records[0].events if e["node"] == node and e["event"] in names]


ABC = {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}, "c": {"setup_key": "C"}}
MATRIX_123 = {"A": {"A": C(0), "B": C(5)}, "B": {"B": C(0), "C": C(7)}, "C": {"C": C(0), "A": C(11)}}


# ------------------------------------------------------------------------------------------- 30: manual 123 s
def test_30_manual_case_123_seconds():
    m = build(ABC, seq("a", "a", "b", "b", "c", "a"), times(a=10, b=20, c=30),
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": MATRIX_123}})
    r = run(m)
    rec = r.records[0]
    # A10 | A10 | A->B 5 | B20 | B20 | B->C 7 | C30 | C->A 11 | A10
    assert [d for _, _, d in rec.completions] == [10, 20, 45, 65, 102, 123]
    assert [(s["from"], s["to"], s["start"], s["end"]) for s in rec.setups] == [("A", "B", 20, 25), ("B", "C", 65, 72), ("C", "A", 102, 113)]
    st = rec.node_state_time["m"]
    assert st["busy"] == 100 and st["setup"] == 23 and rec.node_setups["m"] == 3
    k = r.kpis
    assert k.mean("node.m.setup_count") == 3 and k.mean("total_setup_count") == 3
    assert k.mean("total_setup_time_h") * 3600 == pytest.approx(23) and k.mean("node.m.processing_time_h") * 3600 == pytest.approx(100)
    assert k.mean("node.m.utilization") == k.mean("node.m.utilization_processing")  # legacy definition untouched
    # processing never starts while the slot is in setup (one slot: setup occupies the capacity)
    for s in rec.setups:
        assert not [t for t, _, _ in ev(r, "start_process") if s["start"] <= t < s["end"]]


# ------------------------------------------------------------------------------------------- 31: setup_key
def test_31_setup_key_family_no_setup_inside_family():
    prods = {"a1": {"setup_key": "FAMILY_A"}, "a2": {"setup_key": "FAMILY_A"}, "b": {"setup_key": "FAMILY_B"}}
    m = build(prods, seq("a1", "a2", "b"), times(a1=10, a2=10, b=10),
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "FAMILY_A", "matrix": {"FAMILY_A": {"FAMILY_B": C(8)}}}})
    rec = run(m).records[0]
    assert [(s["from"], s["to"], s["product"]) for s in rec.setups] == [("FAMILY_A", "FAMILY_B", "b")]
    assert [d for _, _, d in rec.completions] == [10, 20, 38]


# ------------------------------------------------------------------------------------------- 32: asymmetric matrix
def test_32_asymmetric_matrix_never_mirrored():
    st = {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(10)}, "B": {"A": C(30)}}}}
    rec = run(build(ABC | {}, seq("a", "b", "a"), times(a=1, b=1, c=1), st)).records[0]
    assert sum(s["sampled_s"] for s in rec.setups) == 40
    # B->A missing: with a probabilistic mix every change can occur -> ERROR, never mirrored from A->B
    st_missing = {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(10)}}}}
    m = build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "b": 0.5}}},
              times(a=1, b=1), st_missing)
    rep, cm = verify_model(m, REG)
    assert cm is None and any(i.code == "SETUP_TRANSITION_MISSING" and "B→A" in i.message for i in rep.errors)


# ------------------------------------------------------------------------------------------- 33: initial state
def test_33_unconfigured_initial_state_needs_explicit_first_setup():
    st = {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "UNCONFIGURED", "constant": C(20),
                "from_unconfigured": {"A": C(50)}}}
    rec = run(build(ABC, seq("a", "b"), times(a=10, b=10, c=10), st)).records[0]
    assert [(s["from"], s["to"], s["sampled_s"]) for s in rec.setups] == [("UNCONFIGURED", "A", 50), ("A", "B", 20)]
    assert [d for _, _, d in rec.completions] == [60, 90]
    no_rule = copy.deepcopy(st)
    no_rule["m"]["from_unconfigured"] = {}
    assert "SETUP_TRANSITION_MISSING" in codes(build(ABC, seq("a", "b"), times(a=10, b=10, c=10), no_rule))
    # the constant changeover does NOT cover UNCONFIGURED -> key (never assumed)
    with pytest.raises(Exception):
        build(ABC, seq("a"), times(a=1, b=1, c=1), {"m": {"mode": "SEQUENCE_DEPENDENT"}})  # initial_state is required


# ------------------------------------------------------------------------------------------- 34: product times
def test_34_product_specific_processing_and_product_kpis():
    r = run(build(ABC, seq("a", "b", "c"), times(a=10, b=20, c=30)))
    rec = r.records[0]
    assert rec.node_state_time["m"]["busy"] == 60
    assert [d for _, _, d in rec.completions] == [10, 30, 60]
    k = r.kpis
    assert [k.mean(f"product.{p}.completed") for p in "abc"] == [1, 1, 1]
    assert [k.mean(f"product.{p}.avg_lead_time_s") for p in "abc"] == [10, 20, 30]  # infinite source: created on acceptance
    assert k.mean("product.a.created") + k.mean("product.b.created") + k.mean("product.c.created") == k.mean("units_completed")


def test_34b_missing_product_time_is_missing_never_borrowed():
    m = build(ABC, seq("a", "b", "c"), {"m": {"a": C(10), "b": C(20)}})
    rep, cm = verify_model(m, REG)
    assert cm is None and any(i.code == "MISSING" and "'c'" in i.message for i in rep.errors)
    assert rep.readiness.value == "INCOMPLETE"
    both = build(ABC, seq("a"), times(a=1, b=1, c=1), machine_params={"process_time": C(5)})
    assert "PRODUCT_TIME_AMBIGUOUS" in codes(both)


# ------------------------------------------------------------------------------------------- 35: routing
ROUTE_NODES = [{"id": "src", "component": "source"}, {"id": "m1", "component": "machine"},
               {"id": "m2", "component": "machine", "params": {"process_time": C(5)}},
               {"id": "insp", "component": "machine", "params": {"process_time": C(7)}}, {"id": "out", "component": "sink"}]
ROUTE_EDGES = [{"source": "src", "target": "m1"}, {"source": "m1", "target": "m2"}, {"source": "m1", "target": "insp"},
               {"source": "m2", "target": "out"}, {"source": "insp", "target": "out"}]


def routed(**over):
    kw = dict(processing={"m1": {"a": C(3), "b": C(4)}}, nodes=ROUTE_NODES, edges=ROUTE_EDGES,
              routes={"a": ["src", "m1", "m2", "out"], "b": ["src", "m1", "insp", "out"]})
    kw.update(over)
    return build({"a": {}, "b": {}}, seq("a", "b", "a", "b"), **kw)


def test_35_each_product_visits_only_its_route():
    r = run(routed())
    visits: dict[int, list[str]] = {}
    for e in r.records[0].events:
        if e["event"] in ("enter", "created", "completed") and e["entity"] is not None:
            visits.setdefault(e["entity"], []).append(e["node"])
    assert visits == {1: ["src", "m1", "m2", "out"], 2: ["src", "m1", "insp", "out"],
                      3: ["src", "m1", "m2", "out"], 4: ["src", "m1", "insp", "out"]}
    assert r.records[0].entity_product == {1: "a", 2: "b", 3: "a", 4: "b"}


def test_35b_route_validation():
    assert "ROUTE_NO_EDGE" in codes(routed(routes={"a": ["src", "m2", "out"], "b": ["src", "m1", "insp", "out"]}))
    assert "MISSING" in codes(routed(routes={"a": ["src", "m1", "m2", "out"]}))
    assert "ROUTE_UNKNOWN_NODE" in codes(routed(routes={"a": ["src", "m1", "zz", "out"], "b": ["src", "m1", "insp", "out"]}))
    with_probs = copy.deepcopy(ROUTE_EDGES)
    with_probs[1]["probability"], with_probs[2]["probability"] = 0.5, 0.5
    assert "ROUTING_AMBIGUOUS" in codes(routed(edges=with_probs))
    # without routes, a branching node still needs probabilities (frozen rule, product-agnostic)
    assert "ROUTING_PROB" in codes(routed(routes=None))


# ------------------------------------------------------------------------------------------- 36: probabilistic mix
MIX = {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.6, "b": 0.3, "c": 0.1}}}


def mix_model(mix=None):
    return build(ABC, mix or MIX, times(a=10, b=10, c=10), horizon_h=0.5)


def products_of(r):
    return [e["product"] for e in r.records[0].events if e["event"] == "created"]


def test_36_mix_reproducible_and_seed_dependent_without_fragile_statistics():
    s1, s1b = products_of(run(mix_model(), seed=7)), products_of(run(mix_model(), seed=7))
    assert s1 == s1b and len(s1) == 181 and set(s1) <= {"a", "b", "c"}  # 0..1800 s every 10 s (t = horizon included)
    others = [products_of(run(mix_model(), seed=s)) for s in (8, 9, 10)]
    assert any(o != s1 for o in others)
    # the declaration order of the mix does not change the hash nor the sequence (draws use sorted product ids)
    rev = mix_model({"src": {"mode": "PROBABILISTIC_MIX", "mix": {"c": 0.1, "b": 0.3, "a": 0.6}}})
    assert rev.content_hash() == mix_model().content_hash() and products_of(run(rev, seed=7)) == s1


def test_36b_mix_validation_never_normalises():
    assert "MIX_SUM" in codes(mix_model({"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.6, "b": 0.3, "c": 0.3}}}))
    assert "MIX_NEGATIVE" in codes(mix_model({"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 1.2, "b": -0.2}}}))
    assert "PRODUCT_UNKNOWN" in codes(mix_model({"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "zz": 0.5}}}))
    assert "PRODUCT_GENERATION_MISSING" in codes(build(ABC, {}, times(a=1, b=1, c=1)))
    no_entity = model_from_dict({**mix_model().model_dump(mode="json"), "entities": [{"id": "a", "name": "A"}]})
    assert "PRODUCT_UNKNOWN" in codes(no_entity)


def test_36c_legacy_model_consumes_no_product_random_numbers():
    legacy = load_model(EXAMPLES / "03_machine_breakdowns.yaml")
    assert "production" not in legacy.model_dump(mode="json")
    assert run_simulation(legacy, REG).kpis.mean("units_completed") == 1889.05


# ------------------------------------------------------------------------------------------- 37: setup + calendar
def cal(cid, a="06:00", b="14:00"):
    return {"id": cid, "weekly": {d: [{"start": a, "end": b}] for d in DAYS}}


def calendar_setup_model(policy="PAUSE_RESUME", setup_time=C(600), a_time=28500, seq_items=("a", "b"), proc_policy="PAUSE_RESUME"):
    return build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}, "c": {"setup_key": "C"}}, seq(*seq_items),
                 times(a=a_time, b=10, c=10),
                 {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "at_unavailability": policy,
                        "matrix": {"A": {"B": setup_time}, "B": {"C": setup_time}}, "resources": [{"resource": "tech"}]}},
                 resources=[{"id": "tech", "kind": "operator", "quantity": 1}], horizon_h=40,
                 availability={"mode": "relative_week", "calendars": [cal("mach"), cal("techc")], "nodes": {"m": "mach"},
                               "resources": {"tech": "techc"}, "always_available": ["src"],
                               "operations": {"m": {"at_unavailability": proc_policy, "start_rule": "START_ANY_TIME"}}})


def test_37_setup_pause_resume_across_shift_end():
    r = run(calendar_setup_model())
    # a: 06:00 + 28500 s = 13:55; A->B setup 600 s from 13:55: 300 s done at 14:00, PAUSE, 300 s at 06:00 next day
    tr = ev(r, "setup_start", "setup_paused_by_calendar", "setup_resume", "setup_end", "start_process")
    assert tr == [(6 * H, "start_process", 1), (13 * H + 55 * 60, "setup_start", 2), (14 * H, "setup_paused_by_calendar", 2),
                  (30 * H, "setup_resume", 2), (30 * H + 300, "setup_end", 2), (30 * H + 300, "start_process", 2)]
    rec = r.records[0]
    s = rec.setups[0]
    assert (s["from"], s["to"], s["end"]) == ("A", "B", 30 * H + 300)
    assert [i["cause"] for i in s["interruptions"]] == ["calendar"]
    assert rec.node_state_time["m"]["setup"] == 600  # active setup only; the pause is not setup time
    tech = rec.resource_state_time["tech"]
    assert tech["working:m#setup"] == 600 and not any(k.startswith("outside_planned") for k in tech)  # released at 14:00
    assert rec.completions[-1][2] == 30 * H + 310


def test_37b_setup_state_unchanged_until_setup_completes():
    # c arrives right after b: if the state had switched to B at setup START, the B->C change would be wrong/absent
    r = run(calendar_setup_model(seq_items=("a", "b", "c")))
    assert [(s["from"], s["to"]) for s in r.records[0].setups] == [("A", "B"), ("B", "C")]
    assert r.records[0].setups[1]["start"] == 30 * H + 310


def test_37c_setup_policy_is_required_and_independent_of_processing_policy():
    m = calendar_setup_model()
    data = m.model_dump(mode="json")
    data["production"]["setups"]["m"]["at_unavailability"] = None
    rep, cm = verify_model(model_from_dict(data), REG)
    assert cm is None and any(i.code == "MISSING" and "at_unavailability" in (i.path or "") for i in rep.errors)
    # processing FINISH_CURRENT, setup PAUSE_RESUME: the setup still pauses
    r = run(calendar_setup_model(proc_policy="FINISH_CURRENT"))
    assert ev(r, "setup_paused_by_calendar")


# ------------------------------------------------------------------------------------------- 38: STOP_RESTART
def test_38_setup_stop_restart_reuses_the_same_sample_and_rng_does_not_advance():
    uni = {"dist": "uniform", "low": 500, "high": 700, "unit": "s"}
    hit = run(calendar_setup_model("STOP_RESTART", uni, seq_items=("a", "b", "c")), seed=3).records[0]
    free = run(calendar_setup_model("STOP_RESTART", uni, a_time=1000, seq_items=("a", "b", "c")), seed=3).records[0]
    s_hit, s_free = hit.setups, free.setups
    assert [i["cause"] for i in s_hit[0]["interruptions"]] == ["calendar"] and not s_free[0]["interruptions"]
    assert s_hit[0]["sampled_s"] == s_free[0]["sampled_s"]  # same first draw
    assert s_hit[0]["end"] == 30 * H + s_hit[0]["sampled_s"]  # restarted at 06:00 with the SAME sample, progress lost
    assert s_hit[1]["sampled_s"] == s_free[1]["sampled_s"]  # the restart consumed no random number
    lost = [e for e in hit.events if e["event"] == "setup_restart_lost_work"]
    assert len(lost) == 1 and lost[0]["lost_s"] == 300


# ------------------------------------------------------------------------------------------- 39: setup + breakdown
def test_39_breakdown_during_setup_keeps_remaining_and_state_until_completion():
    fail = {"mtbf": C(50), "mttr": C(30)}  # down [50,80], [130,160], [210,240] (elapsed failure clock)
    m = build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, seq("a", "b"), {"m": {"a": C(10), "b": C(10)}},
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(100), "resources": [{"resource": "tech"}]}},
              resources=[{"id": "tech", "kind": "operator", "quantity": 1}], machine_params={"failures": fail})
    r = run(m)
    rec = r.records[0]
    s = rec.setups[0]
    # setup 10->50 (40 s), down, 80->130 (50 s), down, 160->170 (10 s): 100 s of work, ends at 170
    assert [i["cause"] for i in s["interruptions"]] == ["failure", "failure"]
    assert [i["remaining_s"] for i in s["interruptions"]] == [60, 10]
    assert (s["start"], s["end"]) == (10, 170) and rec.node_state_time["m"]["setup"] == 100
    assert ev(r, "setup_end", "start_process")[-2:] == [(170, "setup_end", 2), (170, "start_process", 2)]
    assert rec.completions[-1][2] == 180
    assert rec.resource_state_time["tech"]["working:m#setup"] == 160  # held during repairs, released once


# ------------------------------------------------------------------------------------------- 40: same instant
def test_40_same_instant_setup_end_at_shift_end_completes_and_is_deterministic():
    # a ends 13:50; A->B 600 s ends exactly 14:00 = SHIFT_END: complete, never paused
    m = calendar_setup_model(a_time=28200)
    traces = [run(m).records[0].events for _ in range(4)]
    assert all(t == traces[0] for t in traces)
    r = run(m)
    assert not ev(r, "setup_paused_by_calendar") and ev(r, "setup_end")[0][0] == 14 * H
    assert ev(r, "start_process")[-1][0] == 30 * H  # processing waits for the next shift (PAUSE_RESUME, START_ANY_TIME)


def test_40b_breakdown_exactly_at_setup_end_and_with_calendar_single_interruption():
    fail = {"mtbf": C(110), "mttr": C(30)}  # failure at 110 = end of the setup 10..110
    m = build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, seq("a", "b"), {"m": {"a": C(10), "b": C(10)}},
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(100)}}, machine_params={"failures": fail})
    traces = [run(m).records[0] for _ in range(3)]
    assert all(t.events == traces[0].events for t in traces)
    s = traces[0].setups
    assert len(s) == 1 and s[0]["end"] == 110 and all(i["remaining_s"] == 0 for i in s[0]["interruptions"])
    assert traces[0].completions[-1][2] == 150  # processing waits for the repair (110..140) then 10 s


def test_40c_arrival_exactly_at_changeover_completion():
    # interarrival 5 s: a at 5 (1 s), b at 10 -> A->B setup 10..15; c arrives exactly at 15 (setup completion): it waits
    # in the buffer while b is processed 15..16, then B->C setup 16..20
    nodes = [{"id": "src", "component": "source", "params": {"arrival": "interarrival", "interarrival": C(5), "max_entities": 3}},
             {"id": "q", "component": "buffer", "params": {"capacity": 10}}, {"id": "m", "component": "machine"},
             {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "q"}, {"source": "q", "target": "m"}, {"source": "m", "target": "out"}]
    m = build(ABC, seq("a", "b", "c"), times(a=1, b=1, c=1),
              {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(5)}, "B": {"C": C(4)}}}},
              nodes=nodes, edges=edges)
    runs = [run(m).records[0] for _ in range(3)]
    assert all(x.events == runs[0].events for x in runs)
    assert [(s["start"], s["end"]) for s in runs[0].setups] == [(10, 15), (16, 20)]
    assert [d for _, _, d in runs[0].completions] == [6, 16, 21]


# ------------------------------------------------------------------------------------------- 41: conservation
def test_41_conservation_per_product_with_scrap():
    nodes = copy.deepcopy(ROUTE_NODES)
    nodes[3]["params"]["yield_rate"] = 0.7  # inspection scraps 30 %
    r = run(build({"a": {}, "b": {}}, {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "b": 0.5}}},
                  {"m1": {"a": C(3), "b": C(4)}}, nodes=nodes, edges=ROUTE_EDGES,
                  routes={"a": ["src", "m1", "m2", "out"], "b": ["src", "m1", "insp", "out"]}), seed=5)
    rec = r.records[0]
    scrapped = {p: sum(1 for eid, _, _ in rec.scrapped if rec.entity_product[eid] == p) for p in "ab"}
    done = {p: sum(1 for eid, _, _ in rec.completions if rec.entity_product[eid] == p) for p in "ab"}
    for p in "ab":
        assert rec.created_by_product[p] == done[p] + scrapped[p] + rec.wip_end_by_product[p]
    assert scrapped["a"] == 0 and scrapped["b"] > 0  # only b visits the inspection
    assert sum(done.values()) == len(rec.completions) and sum(rec.created_by_product.values()) == rec.created


# ------------------------------------------------------------------------------------------- 42: persistence/hash
def full_model():
    return build(ABC, seq("a", "b", "c", repeat=True), times(a=10, b=20, c=30),
                 {"m": {"mode": "TARGET_DEPENDENT", "initial_state": "UNCONFIGURED", "by_target": {"A": C(3), "B": C(4), "C": C(5)},
                        "from_unconfigured": {"A": C(9)}, "resources": [{"resource": "tech"}]}},
                 resources=[{"id": "tech", "kind": "operator", "quantity": 1}])


def test_42_save_load_identical_hash_sequence_setups_results(tmp_path):
    m = full_model()
    save_model(m, tmp_path / "m.yaml")
    back = load_model(tmp_path / "m.yaml")
    assert back.content_hash() == m.content_hash() and back.production == m.production
    r1, r2 = run(m), run(back)
    assert r1.records[0].events == r2.records[0].events and r1.records[0].setups == r2.records[0].setups
    assert r1.per_replication == r2.per_replication


@pytest.mark.parametrize("path,value", [
    ("production.generation.src.repeat", False), ("production.processing.m.a.value", 11),
    ("production.products.a.setup_key", "Z"), ("production.setups.m.by_target.B.value", 5),
    ("production.setups.m.initial_state", "A"), ("production.setups.m.resources", []),
])
def test_42b_every_production_field_changes_hash_and_invalidates_approval(path, value):
    m = full_model()
    m = m.model_copy(update={"approval": m.approval.model_copy(update={"approved": True, "model_hash": m.content_hash()})})
    assert m.is_approved
    changed = set_value(m, path, value)
    assert changed.content_hash() != m.content_hash() and not changed.is_approved


def test_42c_project_versions_and_rebuild_keep_production(tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("p7")
    v1 = sf.save_model(p, full_model(), "products")
    assert p.load_version(v1).production == full_model().production
    sf.approve_model(p, by="eng")
    assert sf.run_simulation(p).kpis.mean("total_setup_count") >= 1


# ------------------------------------------------------------------------------------------- 43: legacy
def test_43_legacy_models_unchanged_hash_and_serialisation():
    from simforge.domain.isms import ISMSModel
    for f in ("01_simple_line.yaml", "02_shared_operator.yaml", "03_machine_breakdowns.yaml", "04_rework_routing.yaml",
              "05_selective_soldering.yaml"):
        m = load_model(EXAMPLES / f)
        core = ISMSModel.model_validate(m.model_dump(mode="json"))
        assert m.content_hash() == core.content_hash() and "production" not in dump_model(m)


# ------------------------------------------------------------------------------------------- verifier / limitations
def test_multi_slot_setup_node_is_an_explicit_error():
    m = build(ABC, seq("a", "b"), times(a=1, b=1, c=1),
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5)}}, machine_params={"capacity": 2})
    assert "SETUP_SEMANTICS_UNSUPPORTED_FOR_MULTI_SLOT_NODE" in codes(m)


@pytest.mark.parametrize("setups,code", [
    ({"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(5), "Q": C(1)}}}}, "SETUP_UNKNOWN_KEY"),
    ({"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"A": C(3), "B": C(5)}}}}, "SETUP_DIAGONAL"),
    ({"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "Q", "matrix": {"A": {"B": C(5)}}}}, "SETUP_UNKNOWN_KEY"),
    ({"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5), "resources": [{"resource": "nobody"}]}}, "UNKNOWN_RESOURCE"),
    ({"out": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5)}}, "SETUP_NOT_SERVER"),
])
def test_setup_verifier_errors(setups, code):
    assert code in codes(build(ABC, seq("a", "b"), times(a=1, b=1, c=1), setups))


def test_missing_setup_key_and_wip_target_setup_resource_are_errors():
    m = build({"a": {}, "b": {"setup_key": "B"}}, seq("a", "b"), {"m": {"a": C(1), "b": C(1)}},
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "B", "constant": C(5)}})
    assert "MISSING" in codes(m)
    wt = build(ABC, seq("a", "b"), times(a=1, b=1, c=1),
               {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5), "resources": [{"resource": "op"}]}},
               resources=[{"id": "op", "quantity": 1, "dispatch": "wip_target",
                           "wip_target": {"protected_node": "m", "feed_nodes": ["m"], "feeder_nodes": ["m"], "target": 1}}])
    assert "SETUP_RESOURCE_WIP_TARGET_UNSUPPORTED" in codes(wt)


def test_wip_target_with_setup_node_counts_setup_unit_once_and_not_in_process():
    # op (WIP_TARGET) feeds 'asm' (with setups by machine only) and serves 'review'; the unit in setup is held by asm
    # (occupancy) but is not "in process" (only BUSY/BLOCKED are, as in 0.6) - conservation checked at every step
    nodes = [{"id": "src", "component": "source"},
             {"id": "asm", "component": "manual_assembly", "params": {"resources": [{"resource": "op"}]}},
             {"id": "buf", "component": "buffer", "params": {"capacity": 5}},
             {"id": "prot", "component": "machine", "params": {"process_time": C(40)}}, {"id": "out", "component": "sink"},
             {"id": "src2", "component": "source", "params": {"arrival": "interarrival", "interarrival": C(60)}},
             {"id": "review", "component": "manual_assembly", "params": {"process_time": C(20), "resources": [{"resource": "op"}]}},
             {"id": "out2", "component": "sink"}]
    edges = [{"source": "src", "target": "asm"}, {"source": "asm", "target": "buf"}, {"source": "buf", "target": "prot"},
             {"source": "prot", "target": "out"}, {"source": "src2", "target": "review"}, {"source": "review", "target": "out2"}]
    gen = {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"], "repeat": True},
           "src2": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["c"], "repeat": True}}
    m = build(ABC, gen, {"asm": {"a": C(30), "b": C(30)}},
              {"asm": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(15)}},
              resources=[{"id": "op", "quantity": 1, "dispatch": "wip_target",
                          "wip_target": {"protected_node": "prot", "feed_nodes": ["buf"], "feeder_nodes": ["asm"], "target": 2}}],
              nodes=nodes, edges=edges, horizon_h=2)
    r = run(m)
    rec = r.records[0]
    assert rec.node_setups["asm"] > 10 and rec.invariant_checks > 0
    snaps = [d for d in rec.decisions if d["system"]["stations"].get("asm", {}).get("setup")]
    assert snaps  # the slot in setup is visible as its own state to the dispatch log
    assert all(d["state"]["feed_detail"]["asm(in process)"] == 0 for d in snaps if d["rule"] == "wip_target")
    assert all(rec.created_by_product[p] == sum(1 for e, _, _ in rec.completions if rec.entity_product[e] == p)
               + rec.wip_end_by_product[p] for p in rec.created_by_product)


def overtaking_model(matrix):
    # sequence b, a: b takes the slow branch, a the fast one -> a can reach 'm' first: the order at 'm' is NOT the sequence
    nodes = [{"id": "src", "component": "source"}, {"id": "slow", "component": "machine"}, {"id": "fast", "component": "machine"},
             {"id": "m", "component": "machine"}, {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "slow"}, {"source": "src", "target": "fast"}, {"source": "slow", "target": "m"},
             {"source": "fast", "target": "m"}, {"source": "m", "target": "out"}]
    return build({"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, seq("b", "a"),
                 {"slow": {"b": C(100)}, "fast": {"a": C(1)}, "m": {"a": C(1), "b": C(1)}},
                 {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "B", "matrix": matrix}},
                 routes={"b": ["src", "slow", "m", "out"], "a": ["src", "fast", "m", "out"]}, nodes=nodes, edges=edges)


def test_overtaking_paths_require_every_reachable_transition_before_running():
    rep, cm = verify_model(overtaking_model({"B": {"A": C(5)}}), REG)
    assert cm is None and any(i.code == "SETUP_TRANSITION_MISSING" and "A→B" in i.message for i in rep.errors)
    assert not any(i.code == "SETUP_TRANSITIONS_FROM_SEQUENCE" for i in rep.issues)
    rec = run(overtaking_model({"B": {"A": C(5)}, "A": {"B": C(7)}})).records[0]
    assert [(x["from"], x["to"], x["product"]) for x in rec.setups] == [("B", "A", "a"), ("A", "B", "b")]


def test_runtime_guard_stops_on_an_undefined_transition():
    # defensive guard (never reached through the verifier): the engine never defaults a missing transition
    from simforge.engine.des.engine import DesEngine
    rep, cm = verify_model(overtaking_model({"B": {"A": C(5)}, "A": {"B": C(7)}}), REG)
    st = cm.production.setups["m"]
    cm.production.setups["m"] = type(st).model_validate({**st.model_dump(mode="json"), "matrix": {"B": {"A": C(5)}}})
    with pytest.raises(SetupTransitionMissing):
        DesEngine().run(cm, 1)


# ------------------------------------------------------------------------------------------- CLI / UI (minimal)
def test_cli_products_show_and_run(tmp_path):
    from typer.testing import CliRunner

    from simforge.cli import app as cli
    save_model(full_model(), tmp_path / "m.yaml")
    out = CliRunner().invoke(cli, ["products", "show", str(tmp_path / "m.yaml")])
    assert out.exit_code == 0, out.output
    assert "EXPLICIT_SEQUENCE [a, b, c] repeat=True" in out.output and "UNCONFIGURED → A: 9.0 s" in out.output
    out = CliRunner().invoke(cli, ["products", "run", str(tmp_path / "m.yaml"), "--seed", "1"])
    assert out.exit_code == 0, out.output
    assert "engine 0.9.0" in out.output and "node m: setups" in out.output and "total setups" in out.output


def test_ui_products_tab(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    ws = tmp_path / "ws"
    sf = SimForgeApp(workspace=ws, library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("UI products")
    sf.save_model(p, full_model(), "products")
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(ws))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("Setups en 'm': TARGET_DEPENDENT" in c.value for c in at.code)


def test_40d_setup_resource_released_exactly_when_setup_requests_it():
    # 'o' holds tech 0..20; m processes a 0..20 then needs tech for A->B at 20: granted at 20 (same instant, deterministic)
    nodes = [{"id": "src", "component": "source"}, {"id": "m", "component": "machine"}, {"id": "out", "component": "sink"},
             {"id": "src2", "component": "source", "params": {"max_entities": 1}},
             {"id": "o", "component": "manual_assembly", "params": {"process_time": C(20), "resources": [{"resource": "tech"}]}},
             {"id": "out2", "component": "sink"}]
    edges = [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}, {"source": "src2", "target": "o"},
             {"source": "o", "target": "out2"}]
    gen = seq("a", "b") | {"src2": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["c"]}}
    m = build(ABC, gen, times(a=20, b=5, c=1),
              {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(10), "resources": [{"resource": "tech"}]}},
              resources=[{"id": "tech", "kind": "operator", "quantity": 1}], nodes=nodes, edges=edges)
    runs = [run(m).records[0] for _ in range(3)]
    assert all(x.events == runs[0].events for x in runs)
    assert [(s["start"], s["end"]) for s in runs[0].setups] == [(20, 30)]


def test_40e_calendar_and_breakdown_same_instant_during_setup_single_interruption():
    # setup A->B 13:55..; at 14:00 shift end AND failure (MTBF 50400 s = 14:00): ONE interruption, one release
    m = calendar_setup_model()
    data = m.model_dump(mode="json")
    data["nodes"][1]["params"]["failures"] = {"mtbf": C(50400), "mttr": C(3600)}
    r = run(model_from_dict(data))
    s = r.records[0].setups[0]
    assert len(s["interruptions"]) == 1 and s["interruptions"][0]["remaining_s"] == 300
    assert s["end"] == 30 * H + 300 and r.records[0].resource_state_time["tech"]["working:m#setup"] == 600
