import pytest

from simforge.domain.io import load_model
from simforge.domain.isms import Approval, Edge, MissingInfo, Node, Resource
from simforge.domain.paths import set_value
from simforge.validation.verifier import Readiness, verify

from .conftest import EXAMPLES, C, line


def codes(rep):
    return {i.code for i in rep.errors}


def test_examples_are_executable(registry):
    for p in EXAMPLES.glob("*.yaml"):
        rep, cm = verify(load_model(p), registry)
        assert rep.ok, (p.name, [str(i) for i in rep.errors])
        assert rep.readiness is Readiness.EXECUTABLE


def test_missing_process_time_is_incomplete(registry):
    rep, cm = verify(line([("m1", "machine", {})]), registry)
    assert cm is None and rep.readiness is Readiness.INCOMPLETE
    assert "MISSING" in codes(rep)


def test_parser_missing_info_blocks(registry):
    m = line([("m1", "machine", {"process_time": C(5)})])
    m = m.model_copy(update={"missing": [MissingInfo(question="¿Qué hace el operario si...?")]})
    rep, _ = verify(m, registry)
    assert rep.readiness is Readiness.INCOMPLETE


def test_unknown_resource_readable_message(registry):
    m = line([("inspection", "inspection", {"process_time": C(5), "resources": [{"resource": "operator_1"}]})])
    rep, _ = verify(m, registry)
    msg = [i.message for i in rep.errors if i.code == "UNKNOWN_RESOURCE"][0]
    assert "operator_1" in msg and "no existe" in msg


def test_unknown_component(registry):
    rep, _ = verify(line([("x", "flux_capacitor", {})]), registry)
    assert "UNKNOWN_COMPONENT" in codes(rep)


def test_graph_errors(registry):
    m = line([("m1", "machine", {"process_time": C(5)})])
    orphan = m.model_copy(update={"nodes": m.nodes + [Node(id="lost", component="machine", params={"process_time": C(1)})]})
    rep, _ = verify(orphan, registry)
    assert {"ORPHAN", "DEAD_END"} <= codes(rep)
    bad_edge = m.model_copy(update={"edges": m.edges + [Edge(source="m1", target="ghost")]})
    assert "BAD_EDGE" in codes(verify(bad_edge, registry)[0])
    no_sink = m.model_copy(update={"nodes": m.nodes[:-1], "edges": m.edges[:-1]})
    assert "NO_SINK" in codes(verify(no_sink, registry)[0])


def test_routing_probabilities_must_sum_to_one(registry):
    m = line([("m1", "machine", {"process_time": C(5)})])
    nodes = m.nodes + [Node(id="m2", component="machine", params={"process_time": C(5)})]
    edges = m.edges + [Edge(source="m1", target="m2"), Edge(source="m2", target="out")]
    m2 = m.model_copy(update={"nodes": nodes, "edges": edges})
    assert "ROUTING_PROB" in codes(verify(m2, registry)[0])  # no probabilities
    edges = [e if not (e.source == "m1") else Edge(source="m1", target=e.target, probability=0.5) for e in edges]
    edges[-2] = Edge(source="m1", target="m2", probability=0.4)
    m3 = m.model_copy(update={"nodes": nodes, "edges": edges})
    assert "ROUTING_PROB" in codes(verify(m3, registry)[0])  # 0.5 + 0.4


def test_infinite_supply_into_unlimited_buffer(registry):
    rep, _ = verify(line([("b", "buffer", {}), ("m1", "machine", {"process_time": C(5)})]), registry)
    assert "UNBOUNDED_WIP" in codes(rep)


def test_bad_params_readable(registry):
    rep, _ = verify(line([("m1", "machine", {"process_time": C(5), "yield_rate": 1.5})]), registry)
    assert "BAD_PARAM" in codes(rep)


def test_warmup_must_be_less_than_horizon(registry):
    m = line([("m1", "machine", {"process_time": C(5)})], warmup={"value": 2, "unit": "h"})
    assert "WARMUP" in codes(verify(m, registry)[0])


def test_stochastic_single_replication_warns(registry):
    m = line([("m1", "machine", {"process_time": {"dist": "exponential", "mean": 5}})])
    rep, _ = verify(m, registry)
    assert "FEW_REPLICATIONS" in {i.code for i in rep.warnings}


def test_approval_bound_to_content(registry):
    m = load_model(EXAMPLES / "01_simple_line.yaml")
    approved = m.model_copy(update={"approval": Approval(approved=True, by="me", model_hash=m.content_hash())})
    assert verify(approved, registry)[0].readiness is Readiness.ENGINEER_APPROVED
    changed = set_value(approved, "nodes.buf.params.capacity", 9)
    rep, _ = verify(changed, registry)
    assert rep.readiness is Readiness.EXECUTABLE  # approval is NOT inherited by a modified model
    assert "APPROVAL_STALE" in {i.code for i in rep.warnings}


def test_seize_requires_carrier(registry):
    m = load_model(EXAMPLES / "05_selective_soldering.yaml")
    m = set_value(m, "resources.racks.kind", "operator")
    assert "SEIZE_KIND" in codes(verify(m, registry)[0])
