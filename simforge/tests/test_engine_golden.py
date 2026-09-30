"""Golden models: small systems whose results are known exactly or analytically.

Time convention: events occurring exactly at t = horizon are counted.
If any of these change, simulation semantics changed -> bump ENGINE_VERSION.
"""

import pytest

from simforge.domain.io import load_model
from simforge.domain.isms import Edge, Node, Resource
from simforge.domain.paths import set_value
from simforge.engine import DesEngine
from simforge.experiments.runner import run_simulation
from simforge.validation.verifier import compile_model

from .conftest import EXAMPLES, C, line


def run1(model, registry, seed=1, trace=False):
    cm = compile_model(model, registry)
    return DesEngine().run(cm, seed, trace=trace), cm


def test_single_machine_60s_1h_gives_60(registry):
    m = line([("m1", "machine", {"process_time": C(60)})])
    rec, _ = run1(m, registry)
    assert len(rec.completions) == 60
    assert rec.node_state_time["m1"]["busy"] == pytest.approx(3600)


def test_minutes_units_equivalent(registry):
    m = line([("m1", "machine", {"process_time": C(1, "min")})])
    rec, _ = run1(m, registry)
    assert len(rec.completions) == 60


def test_two_machines_in_series_exact(registry):
    # M1 60 s -> buffer -> M2 45 s. First out at 105 s, then every 60 s: floor((3600-105)/60)+1 = 59
    rec, _ = run1(load_model(EXAMPLES / "01_simple_line.yaml"), registry)
    assert len(rec.completions) == 59
    lts = [d - c for _, c, d in rec.completions]
    assert all(lt == pytest.approx(105) for lt in lts)


@pytest.mark.parametrize("cap", [1, 2, 5])
def test_buffer_blocking(registry, cap):
    # fast M1 (30 s) feeds slow M2 (60 s): M2 is the constraint, buffer fills, M1 blocks ~50%
    m = line([("m1", "machine", {"process_time": C(30)}), ("b", "buffer", {"capacity": cap}),
              ("m2", "machine", {"process_time": C(60)})], horizon_h=10)
    rec, _ = run1(m, registry)
    T = 36000
    assert len(rec.completions) == pytest.approx(600, abs=2)
    assert rec.level_max["buffer:b"] == cap
    assert rec.node_state_time["m1"]["blocked"] / T == pytest.approx(0.5, abs=0.02)
    # WIP = M1 (1) + buffer (cap) + M2 (1) once filled
    assert rec.level_avg["wip"] == pytest.approx(cap + 2, abs=0.1)


def test_shared_operator_mvp_exact(registry):
    # operator work content 80 s/unit; first completion at 140 s -> floor((28800-140)/80)+1 = 359
    res = run_simulation(load_model(EXAMPLES / "02_shared_operator.yaml"), registry)
    assert res.kpis.mean("units_completed") == 359
    assert res.kpis.mean("resource.operator_1.utilization") == pytest.approx(1.0, abs=0.01)
    th_bound = [f for f in res.findings if f.code == "THEORETICAL_CONSTRAINT"][0]
    assert th_bound.subject == "operator_1"
    assert th_bound.evidence["theoretical_max_per_hour"] == pytest.approx(45)


def test_two_operators_relieve_constraint(registry):
    m = set_value(load_model(EXAMPLES / "02_shared_operator.yaml"), "resources.operator_1.quantity", 2)
    res = run_simulation(m, registry)
    # now assembly (60 s) is the constraint -> ~480 in 8 h
    assert 470 <= res.kpis.mean("units_completed") <= 480


def test_operator_decision_log(registry):
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    rec, _ = run1(m, registry, trace=True)
    assert rec.decisions, "contested decisions must be logged"
    d = rec.decisions[0]
    assert {"t", "resource", "chosen_node", "candidates", "reason", "rule"} <= set(d)
    # priority rule: inspection (priority 1) beats assembly (priority 2)
    assert d["chosen_node"] == "inspection"
    assert rec.events and rec.events[0]["event"] == "created"


def test_priority_changes_behaviour(registry):
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    m_asm_first = set_value(set_value(m, "nodes.assembly.priority", 0), "nodes.inspection.priority", 5)
    r1 = run_simulation(m, registry)
    r2 = run_simulation(m_asm_first, registry)
    # assembly-first fills the buffer -> more WIP, longer lead time
    assert r2.kpis.mean("avg_wip") > r1.kpis.mean("avg_wip") + 2
    assert r2.kpis.mean("avg_lead_time_s") > r1.kpis.mean("avg_lead_time_s")


def test_yield_and_scrap(registry):
    m = line([("m1", "machine", {"process_time": C(10), "yield_rate": 0.8})], horizon_h=10)
    res = run_simulation(m, registry, replications=5)
    assert res.kpis.mean("yield") == pytest.approx(0.8, abs=0.02)
    assert res.kpis.mean("units_completed") + res.kpis.mean("units_scrapped") == pytest.approx(3600, abs=1)


def test_failures_reduce_availability(registry):
    fail = {"mtbf": C(1, "h"), "mttr": C(10, "min")}
    m = line([("m1", "machine", {"process_time": C(60), "failures": fail})], horizon_h=10)
    rec, _ = run1(m, registry)
    # deterministic: down 10 min every 70 min -> availability 60/70
    down = rec.node_state_time["m1"]["down"] / 36000
    assert down == pytest.approx(50 / 360, abs=0.01)  # 5 full failures x 600 s (+ partial) in 10 h
    assert len(rec.completions) == pytest.approx(36000 * (1 - down) / 60, abs=2)


def test_carriers_limit_wip_conwip(registry):
    m = load_model(EXAMPLES / "05_selective_soldering.yaml")
    wips = []
    for n in (1, 2, 4):
        res = run_simulation(set_value(m, "resources.racks.quantity", n), registry)
        wips.append(res.kpis.mean("avg_wip"))
        assert res.kpis.stats["max_wip"].max <= n + 1  # rack holders + 1 unit waiting for a rack at assembly
    assert wips[0] < wips[1] <= wips[2]


def test_walking_costs_time(registry):
    m = load_model(EXAMPLES / "05_selective_soldering.yaml")
    with_walk = run_simulation(m, registry)
    no_walk = run_simulation(set_value(m, "resources.operator_1.travel", None), registry)
    assert with_walk.kpis.mean("resource.operator_1.walking") > 0
    assert no_walk.kpis.mean("resource.operator_1.walking") == 0
    assert no_walk.kpis.mean("units_completed") > with_walk.kpis.mean("units_completed")


def test_warmup_excludes_transient(registry):
    m = line([("m1", "machine", {"process_time": C(60)})], horizon_h=2, warmup={"value": 1, "unit": "h"})
    res = run_simulation(m, registry)
    assert res.kpis.mean("units_completed") == 60  # completions in (3600, 7200]
    assert res.kpis.mean("throughput_per_hour") == 60


def test_interarrival_source_and_little_law(registry):
    m = line([("q", "buffer", {}), ("m1", "machine", {"process_time": {"dist": "exponential", "mean": 40}})],
             horizon_h=200, warmup={"value": 10, "unit": "h"}, kind="steady_state")
    m = set_value(m, "nodes.src.params", {"arrival": "interarrival", "interarrival": {"dist": "exponential", "mean": 60}})
    res = run_simulation(m, registry, replications=3)
    k = res.kpis
    assert k.mean("throughput_per_hour") == pytest.approx(60, rel=0.05)
    # M/M/1 with rho = 2/3: L = rho/(1-rho) = 2
    assert k.mean("avg_wip") == pytest.approx(2.0, rel=0.15)
    assert k.mean("avg_wip") == pytest.approx(k.mean("throughput_per_hour") / 3600 * k.mean("avg_lead_time_s"), rel=0.05)


def test_reproducibility_and_seeds(registry):
    m = load_model(EXAMPLES / "03_machine_breakdowns.yaml")
    m = set_value(m, "simulation.horizon.value", 8)
    a = run_simulation(m, registry, replications=3)
    b = run_simulation(m, registry, replications=3)
    c = run_simulation(m, registry, replications=3, base_seed=999)
    assert a.per_replication == b.per_replication
    assert a.per_replication != c.per_replication
    assert a.seeds == [7, 8, 9]


def test_parallel_capacity(registry):
    m = line([("m1", "machine", {"process_time": C(60), "capacity": 3})])
    rec, _ = run1(m, registry)
    assert len(rec.completions) == 180


def test_probabilistic_routing_split(registry):
    m = line([("m0", "machine", {"process_time": C(1)})], horizon_h=5)
    nodes = m.nodes[:-1] + [Node(id="a", component="machine", params={"process_time": C(0.5)}),
                            Node(id="b", component="machine", params={"process_time": C(0.5)}), m.nodes[-1]]
    edges = [Edge(source="src", target="m0"), Edge(source="m0", target="a", probability=0.3),
             Edge(source="m0", target="b", probability=0.7), Edge(source="a", target="out"), Edge(source="b", target="out")]
    m = m.model_copy(update={"nodes": nodes, "edges": edges})
    res = run_simulation(m, registry)
    tot = res.kpis.mean("node.a.processed") + res.kpis.mean("node.b.processed")
    assert res.kpis.mean("node.a.processed") / tot == pytest.approx(0.3, abs=0.02)


def test_resource_shortage_is_error_not_crash(registry):
    from simforge.validation.verifier import ModelError
    m = line([("m1", "manual_process", {"process_time": C(60), "resources": [{"resource": "op"}]})],
             resources=[Resource(id="op", quantity=0)])
    with pytest.raises(ModelError) as e:
        run_simulation(m, registry)
    assert "nunca podría procesar" in str(e.value)
