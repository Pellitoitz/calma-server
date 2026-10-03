"""1.1-B model building without YAML: structural builder (C01), distribution editor (C02), transport editor (C03).

Equivalence tests build the models FROM SCRATCH through services.model_builder (the layer the UI uses), never by
loading the reference YAML.
"""

from __future__ import annotations

import copy

import pytest

from simforge.domain.io import dump_model, load_model
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.services import model_builder as B
from simforge.services.model_builder import BuilderError, DistributionForm
from simforge.validation.semantics import verify_model

from .conftest import EXAMPLES

GOLDEN = EXAMPLES / "1_0_golden_project"


@pytest.fixture(scope="module")
def reg() -> ComponentRegistry:
    return ComponentRegistry.load_default()


def D(family: str, unit: str | None = None, **params) -> DistributionForm:
    return DistributionForm(family=family, params=params, unit=unit)


def _missing_paths(model, reg) -> set[str]:
    rep, _ = verify_model(model, reg)
    return {i.path for i in rep.issues if i.code == "MISSING"}


# ================================================================================ B7: example 01 from scratch
def build_example_01(reg):
    m = B.new_model("Simple line", {"value": 1, "unit": "h"}, description="Source -> M1 -> buffer -> M2 -> Sink")
    m = B.add_node(m, reg, "src", "source")
    m = B.add_node(m, reg, "m1", "machine", name="Machine 1")
    m = B.set_distribution(m, reg, "m1", "process_time", D("constant", value=60))  # unit NOT declared, as in the YAML
    m = B.add_node(m, reg, "buf", "buffer", name="Buffer")
    m = B.set_node_params(m, reg, "buf", {"capacity": 3})
    m = B.add_node(m, reg, "m2", "machine", name="Machine 2")
    m = B.set_distribution(m, reg, "m2", "process_time", D("constant", value=45))
    m = B.add_node(m, reg, "out", "sink")
    for a, b in (("src", "m1"), ("m1", "buf"), ("buf", "m2"), ("m2", "out")):
        m = B.add_edge(m, reg, a, b)
    return m


def test_example_01_built_from_scratch_equals_yaml_and_runs_59(reg, tmp_path):
    built = build_example_01(reg)
    ref = load_model(EXAMPLES / "01_simple_line.yaml")
    assert built.model_dump(mode="json") == ref.model_dump(mode="json")  # semantic representation
    assert built.content_hash() == ref.content_hash()
    assert dump_model(built) == dump_model(ref)
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("b01")
    sf.save_model(p, built, "built without YAML")
    assert sf.validate_model(p.current_model()).ok
    sf.approve_model(p, "eng")
    res = sf.run_simulation(p)
    assert res.model_hash == ref.content_hash() and res.kpis.mean("units_completed") == 59


# ================================================================================ B8: golden from scratch
def build_golden(reg):
    m = B.new_model("Golden line — baseline", {"value": 8, "unit": "h"},
                    description="1.0 reference workflow: assembly + buffer + test",
                    warmup={"value": 30, "unit": "min"}, replications=5, base_seed=1000)
    m = B.add_resource(m, "operator", 1, name="Assembly operator")
    m = B.add_node(m, reg, "arrivals", "source")
    m = B.set_node_params(m, reg, "arrivals", {"arrival": "interarrival"})
    m = B.set_distribution(m, reg, "arrivals", "interarrival", D("exponential", unit="s", mean=50))
    m = B.add_node(m, reg, "assembly", "manual_assembly", name="Manual assembly")
    m = B.set_distribution(m, reg, "assembly", "process_time", D("triangular", unit="s", low=30, mode=38, high=50))
    m = B.set_node_params(m, reg, "assembly", {"resources": [{"resource": "operator"}]})
    m = B.add_node(m, reg, "buffer", "buffer", name="Buffer", params={"capacity": 5})
    m = B.add_node(m, reg, "test", "machine", name="Test machine")
    m = B.set_distribution(m, reg, "test", "process_time", D("constant", unit="s", value=46))  # unit DECLARED, as in the YAML
    m = B.add_node(m, reg, "finished", "sink", name="Finished goods")
    for a, b in (("arrivals", "assembly"), ("assembly", "buffer"), ("buffer", "test"), ("test", "finished")):
        m = B.add_edge(m, reg, a, b)
    return m


def test_golden_built_from_scratch_equals_physical_yaml(reg):
    built = build_golden(reg)
    ref = load_model(GOLDEN / "model.yaml")
    # economics (C06, 1.1-E) is not built by 1.1-B and is excluded from the physical hash by the existing contract
    assert built.economics is None and ref.economics is not None
    assert built.model_dump(mode="json", exclude={"economics"}) == ref.model_dump(mode="json", exclude={"economics"})
    assert built.content_hash() == ref.content_hash()


def test_golden_built_from_scratch_reproduces_the_golden_reference_output(reg):
    import json
    exp = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))["baseline"]
    res = run_simulation(build_golden(reg), reg)
    assert res.seeds == exp["seeds"] and res.kpis.mean("units_completed") == exp["units_completed"]


def test_construction_order_is_part_of_the_existing_hash(reg):
    """B-D02: the builder keeps the explicit order; a different order is a different hash (existing contract)."""
    m = build_example_01(reg)
    data = m.model_dump(mode="json")
    data["edges"] = list(reversed(data["edges"]))
    from simforge.domain.io import model_from_dict
    assert model_from_dict(data).content_hash() != m.content_hash()
    assert [n.id for n in m.nodes] == ["src", "m1", "buf", "m2", "out"]


# ================================================================================ C01 structural builder
def test_empty_model_requires_name_and_horizon_and_writes_nothing_else(reg):
    m = B.new_model("x", {"value": 2, "unit": "h"})
    assert m.nodes == [] and m.edges == [] and m.resources == []
    assert m.simulation.horizon.value == 2 and m.simulation.horizon.unit == "h"
    with pytest.raises(BuilderError, match="horizonte"):
        B.new_model("x", {})
    with pytest.raises(BuilderError, match="nombre"):
        B.new_model(" ", {"value": 1, "unit": "h"})
    with pytest.raises(BuilderError):
        B.new_model("x", {"value": 1, "unit": "parsec"})


def test_add_each_basic_component_and_missing_stays_missing(reg):
    m = B.new_model("x", {"value": 1, "unit": "h"})
    m = B.add_node(m, reg, "src", "source")
    m = B.add_node(m, reg, "buf", "buffer")
    m = B.add_node(m, reg, "srv", "machine")
    m = B.add_node(m, reg, "out", "sink")
    assert [(n.id, n.component, n.params) for n in m.nodes] == [("src", "source", {}), ("buf", "buffer", {}),
                                                                 ("srv", "machine", {}), ("out", "sink", {})]
    # nothing was invented: the process time is absent and reported as MISSING by the existing verifier
    assert "process_time" not in m.node("srv").params
    assert "nodes.srv.params.process_time" in _missing_paths(m, reg)


def test_connect_update_disconnect_keep_order(reg):
    m = build_example_01(reg)
    m = B.update_edge(m, "buf", "m2", 1.0)
    assert m.edges[2].probability == 1.0 and [(e.source, e.target) for e in m.edges][2] == ("buf", "m2")
    m = B.update_edge(m, "buf", "m2", None)
    assert m.edges[2].probability is None
    m2 = B.remove_edge(m, "m1", "buf")
    assert [(e.source, e.target) for e in m2.edges] == [("src", "m1"), ("buf", "m2"), ("m2", "out")]
    with pytest.raises(BuilderError, match="No existe la conexión"):
        B.remove_edge(m2, "m1", "buf")


@pytest.mark.parametrize("src,dst,match", [
    ("m1", "nope", "No existe el nodo"), ("m1", "m1", "consigo mismo"), ("out", "m1", "sumidero"),
    ("m1", "src", "fuente"), ("src", "m1", "ya existe")])
def test_invalid_connections_rejected(reg, src, dst, match):
    with pytest.raises(BuilderError, match=match):
        B.add_edge(build_example_01(reg), reg, src, dst)


def test_invalid_probability_rejected(reg):
    m = B.remove_edge(build_example_01(reg), "src", "m1")
    with pytest.raises(BuilderError):
        B.add_edge(m, reg, "src", "m1", probability=1.5)


def test_remove_node_safely(reg):
    m = build_example_01(reg)
    with pytest.raises(BuilderError, match="conexión"):
        B.remove_node(m, "buf")
    m2 = B.remove_node(m, "buf", cascade_edges=True)
    assert "buf" not in [n.id for n in m2.nodes]
    assert [(e.source, e.target) for e in m2.edges] == [("src", "m1"), ("m2", "out")]
    # a node referenced elsewhere (transport destination) is never removed silently, even with cascade
    t = B.add_node(m, reg, "move", "transport", params={"destination": "m2"})
    with pytest.raises(BuilderError, match="referenciado"):
        B.remove_node(t, "m2", cascade_edges=True)


def test_duplicate_unknown_and_invalid_rejected(reg):
    m = build_example_01(reg)
    with pytest.raises(BuilderError, match="Ya existe"):
        B.add_node(m, reg, "m1", "machine")
    with pytest.raises(BuilderError, match="desconocido"):
        B.add_node(m, reg, "x1", "teleporter")
    with pytest.raises(BuilderError, match="desconocido"):
        B.add_node(m, reg, "x1", "machine", params={"speed_of_light": 1})
    with pytest.raises(BuilderError):
        B.add_node(m, reg, "X-1", "machine")  # invalid id
    with pytest.raises(BuilderError):
        B.set_node_params(m, reg, "buf", {"capacity": -1})
    with pytest.raises(BuilderError):
        B.set_node_params(m, reg, "m1", {"capacity": 0})
    with pytest.raises(BuilderError):
        B.set_node_params(m, reg, "m1", {"yield_rate": 1.5})
    with pytest.raises(BuilderError, match="no existe"):
        B.set_node_params(m, reg, "m1", {"resources": [{"resource": "ghost"}]})


def test_resources_add_require_quantity_and_remove_safely(reg):
    m = build_golden(reg)
    with pytest.raises(BuilderError, match="Ya existe"):
        B.add_resource(m, "operator", 2)
    with pytest.raises(BuilderError, match="obligatoria"):
        B.add_resource(m, "op2", "")
    with pytest.raises(BuilderError):
        B.add_resource(m, "op2", -1)
    with pytest.raises(BuilderError, match="se usa en"):
        B.remove_resource(m, "operator")
    m2 = B.add_resource(m, "op2", 2, kind="tool")
    assert [r.id for r in m2.resources] == ["operator", "op2"]
    assert [r.id for r in B.remove_resource(m2, "op2").resources] == ["operator"]


def test_operations_never_mutate_the_input_model(reg):
    base = build_example_01(reg)
    snap, h = copy.deepcopy(base.model_dump(mode="json")), base.content_hash()
    B.add_node(base, reg, "extra", "buffer")
    B.set_distribution(base, reg, "m1", "process_time", D("constant", value=99))
    B.remove_node(base, "buf", cascade_edges=True)
    B.update_edge(base, "src", "m1", 0.5)
    assert base.model_dump(mode="json") == snap and base.content_hash() == h


# ================================================================================ C02 distributions
CASES = {
    "constant": {"value": 60},
    "uniform": {"low": 10, "high": 20},
    "triangular": {"low": 1, "mode": 2.5, "high": 4},
    "normal": {"mean": 30, "std": 3},
    "lognormal": {"mean": 30, "std": 4},
    "exponential": {"mean": 50},
    "gamma": {"shape": 2, "scale": 15.5},
    "weibull": {"shape": 1.5, "scale": 40},
    "empirical": {"values": [10, 12.5, 11]},
}


def test_editor_covers_exactly_the_domain_distributions():
    from simforge.domain.values import Duration
    domain = {c.model_fields["dist"].default for c in Duration.__origin__.__args__}  # type: ignore[attr-defined]
    assert set(B.DISTRIBUTIONS) == domain == set(CASES)


@pytest.mark.parametrize("family", sorted(CASES))
@pytest.mark.parametrize("unit", [None, "s", "min"])
def test_distribution_round_trip_through_model_yaml_and_editor(reg, tmp_path, family, unit):
    raw = B.distribution_from_form(D(family, unit=unit, **CASES[family]))
    assert raw == {"dist": family, **CASES[family], **({"unit": unit} if unit else {})}
    m = B.set_distribution(build_example_01(reg), reg, "m1", "process_time", D(family, unit=unit, **CASES[family]))
    p = tmp_path / "m.yaml"
    p.write_text(dump_model(m), encoding="utf-8")
    back = load_model(p)
    assert back.content_hash() == m.content_hash() and back.node("m1").params["process_time"] == raw
    form = B.distribution_to_form(back.node("m1").params["process_time"])
    assert form.unit_declared is (unit is not None)
    noop = B.set_distribution(back, reg, "m1", "process_time", form)  # no-op save from the editor
    assert noop.node("m1").params["process_time"] == raw and noop.content_hash() == back.content_hash()


def test_unit_omitted_vs_explicit_decision_b_d01(reg):
    m = build_example_01(reg)  # m1: unit NOT declared
    form = B.distribution_to_form(m.node("m1").params["process_time"])
    assert form.unit is None and not form.unit_declared and form.effective_unit == "s"  # shown, not persisted
    noop = B.set_distribution(m, reg, "m1", "process_time", form)
    assert "unit" not in noop.node("m1").params["process_time"] and noop.content_hash() == m.content_hash()
    explicit = B.set_distribution(m, reg, "m1", "process_time", form.model_copy(update={"unit": "s"}))
    assert explicit.node("m1").params["process_time"]["unit"] == "s"
    assert explicit.content_hash() != m.content_hash()  # omitted and explicit do not collapse (current representation)
    back = B.set_distribution(explicit, reg, "m1", "process_time", B.distribution_to_form(explicit.node("m1").params["process_time"]))
    assert back.node("m1").params["process_time"]["unit"] == "s"  # explicit stays explicit
    minutes = B.set_distribution(m, reg, "m1", "process_time", form.model_copy(update={"unit": "min"}))
    assert minutes.content_hash() != m.content_hash()  # a unit change is a semantic edit
    with pytest.raises(BuilderError):
        B.distribution_from_form(form.model_copy(update={"unit": "m"}))  # length, not time
    with pytest.raises(BuilderError):
        B.distribution_from_form(form.model_copy(update={"unit": "fortnight"}))


@pytest.mark.parametrize("family,params", [
    ("constant", {"value": -1}), ("uniform", {"low": 5}), ("triangular", {"low": 5, "mode": 1, "high": 4}),
    ("normal", {"mean": 0, "std": 1}), ("exponential", {"mean": 0}), ("gamma", {"shape": -1, "scale": 1}),
    ("empirical", {"values": []}), ("constant", {"value": 1, "mean": 3}), ("pareto", {"alpha": 1}),
])
def test_invalid_distributions_rejected(family, params):
    with pytest.raises(BuilderError):
        B.distribution_from_form(D(family, **params))


def test_unknown_distribution_field_in_model_is_an_error_not_dropped():
    with pytest.raises(BuilderError, match="desconocido"):
        B.distribution_to_form({"dist": "constant", "value": 1, "colour": "red"})


def test_truncation_preserved_and_validated(reg):
    trunc = {"lower": 5, "upper": 90, "reason": "physical limits", "bound_type": "PHYSICAL_BOUND", "method": "DECLARED"}
    f = DistributionForm(family="normal", params={"mean": 40, "std": 10}, truncation=trunc)
    m = B.set_distribution(build_example_01(reg), reg, "m1", "process_time", f)
    raw = m.node("m1").params["process_time"]
    assert raw["truncation"] == trunc
    back = B.distribution_to_form(raw)
    assert back.truncation == trunc and B.distribution_from_form(back, raw) == raw
    with pytest.raises(BuilderError):
        B.distribution_from_form(f.model_copy(update={"truncation": {"lower": 5, "reason": "x", "bound_type": "PHYSICAL_BOUND"}}))
    with pytest.raises(BuilderError):
        B.distribution_from_form(f.model_copy(update={"truncation": {"lower": 9, "upper": 3, "reason": "bad", "bound_type": "MODELLING_BOUND"}}))


def test_provenance_and_datalink_kept_on_noop_and_replaced_on_semantic_edit(reg):
    link = {"dataset_id": "ds1", "dataset_version": 1, "content_hash": "abc", "source_file": "t.xlsx", "column": "T",
            "original_unit": "s", "basis": "PER_CIRCUIT", "n_used": 40, "decision": "FITTED", "decided_by": "ana",
            "decided_at": "2026-01-01T00:00:00Z"}
    raw = {"dist": "lognormal", "mean": 30, "std": 4, "unit": "s",
           "provenance": {"status": "measured", "source": "t.xlsx", "data": link}}
    m = set_value(build_example_01(reg), "nodes.m1.params.process_time", raw)
    stored = m.node("m1").params["process_time"]
    noop = B.set_distribution(m, reg, "m1", "process_time", B.distribution_to_form(stored))
    assert noop.node("m1").params["process_time"] == stored  # provenance + DataLink (basis included) intact
    edited = B.set_distribution(m, reg, "m1", "process_time", D("lognormal", unit="s", mean=31, std=4))
    assert edited.node("m1").params["process_time"]["provenance"] == B.UI_PROVENANCE  # no stale dataset claim


def test_server_work_units_and_aggregation_preserved(reg):
    m = B.set_node_params(build_example_01(reg), reg, "m1", {"work_units": 4, "work_units_aggregation": "sum_iid"})
    m = B.set_distribution(m, reg, "m1", "process_time", D("normal", mean=10, std=1))
    p = m.node("m1").params
    assert p["work_units"] == 4 and p["work_units_aggregation"] == "sum_iid"
    with pytest.raises(BuilderError):
        B.set_node_params(m, reg, "m1", {"work_units": 2.5})  # sum_iid needs an integer number of units
    with pytest.raises(BuilderError):
        B.set_node_params(m, reg, "m1", {"work_units_aggregation": "average"})


def test_removing_a_distribution_makes_it_missing_again(reg):
    m = B.set_distribution(build_example_01(reg), reg, "m1", "process_time", None)
    assert "process_time" not in m.node("m1").params
    assert "nodes.m1.params.process_time" in _missing_paths(m, reg)


# ================================================================================ C03 transport
def transport_line(reg):
    m = B.new_model("t", {"value": 1, "unit": "h"})
    m = B.add_resource(m, "driver", 1, kind="operator")
    for nid, comp in (("src", "source"), ("a", "machine"), ("move", "transport"), ("b", "machine"), ("out", "sink")):
        m = B.add_node(m, reg, nid, comp)
    for a, b in (("src", "a"), ("a", "move"), ("move", "b"), ("b", "out")):
        m = B.add_edge(m, reg, a, b)
    m = B.set_distribution(m, reg, "a", "process_time", D("constant", value=30))
    return B.set_distribution(m, reg, "b", "process_time", D("constant", value=30))


FULL_TRANSPORT = {"distance": {"value": 20, "unit": "m"}, "speed": {"value": 1, "unit": "m/s"}, "capacity": 2, "fleet": 1,
                  "load_time": D("constant", value=5), "unload_time": D("constant", unit="s", value=4),
                  "resources": [{"resource": "driver"}], "return_empty": True, "batch": "immediate",
                  "reserve_destination": False, "loading_area": 2, "origin": "a", "destination": "b"}


def test_transport_missing_fields_are_reported_not_defaulted(reg):
    m = transport_line(reg)
    assert m.node("move").params == {}
    missing = _missing_paths(m, reg)
    assert {f"nodes.move.params.{f}" for f in ("distance", "speed", "load_time", "unload_time")} <= missing


def test_transport_all_fields_round_trip_and_run(reg, tmp_path):
    m = B.set_transport(transport_line(reg), reg, "move", FULL_TRANSPORT)
    p = m.node("move").params
    assert set(p) == set(FULL_TRANSPORT)
    assert p["load_time"] == {"dist": "constant", "value": 5} and p["unload_time"]["unit"] == "s"
    f = tmp_path / "t.yaml"
    f.write_text(dump_model(m), encoding="utf-8")
    back = load_model(f)
    assert back.content_hash() == m.content_hash() and back.node("move").params == p
    assert verify_model(back, reg)[0].ok
    assert run_simulation(back, reg).kpis.mean("units_completed") > 0
    assert set(B.TRANSPORT_FIELDS) == set(FULL_TRANSPORT)  # every existing field is exposed, nothing invented


@pytest.mark.parametrize("change,match", [
    ({"origin": "nowhere"}, "inexistente"), ({"destination": "nowhere"}, "inexistente"),
    ({"distance": {"value": -5, "unit": "m"}}, "negativa"), ({"speed": {"value": 0, "unit": "m/s"}}, "> 0"),
    ({"speed": {"value": 1, "unit": "s"}}, "speed"), ({"capacity": 0}, "capacity"), ({"fleet": 0}, "fleet"),
    ({"resources": [{"resource": "ghost"}]}, "no existe"), ({"teleport": True}, "desconocido"),
    ({"batch": "full", "capacity": 3, "loading_area": 1}, "loading_area"),
])
def test_invalid_transport_rejected(reg, change, match):
    with pytest.raises(BuilderError, match=match):
        B.set_transport(transport_line(reg), reg, "move", change)


def test_transport_editor_refuses_non_transport_nodes(reg):
    with pytest.raises(BuilderError, match="no es un transporte"):
        B.set_transport(transport_line(reg), reg, "a", {"capacity": 2})


def test_transport_field_removed_becomes_missing(reg):
    m = B.set_transport(transport_line(reg), reg, "move", FULL_TRANSPORT)
    m = B.set_transport(m, reg, "move", {"speed": None})
    assert "speed" not in m.node("move").params and "nodes.move.params.speed" in _missing_paths(m, reg)


# ================================================================================ B9 extensions + approval
def _extended_models():
    from .test_maintenance import full_model as maintenance_model
    return [maintenance_model(), load_model(GOLDEN / "model.yaml")]


@pytest.mark.parametrize("which", [0, 1])
def test_basic_edit_preserves_blocks_the_editor_does_not_handle(reg, which):
    m = _extended_models()[which]
    keep = ("production", "maintenance", "availability", "economics", "experiments", "custom_rule_candidates", "assumptions")
    before = {k: m.model_dump(mode="json").get(k) for k in keep}
    node = next(n for n in m.nodes if n.component not in ("source", "sink"))
    edited = B.update_node(m, reg, node.id, name="renamed by the builder")
    edited = B.set_node_params(edited, reg, node.id, {"capacity": 2})
    after = {k: edited.model_dump(mode="json").get(k) for k in keep}
    assert after == before  # compared explicitly: economics is not in the physical hash
    assert edited.node(node.id).name == "renamed by the builder"
    assert any(before[k] for k in ("production", "maintenance", "availability", "economics"))


def test_semantic_edit_invalidates_approval(reg, tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("ap")
    sf.save_model(p, build_example_01(reg), "built")
    sf.approve_model(p, "eng")
    approved = p.current_model()
    assert approved.is_approved
    edited = B.set_distribution(approved, reg, "m1", "process_time", D("constant", value=61))
    assert edited.content_hash() != approved.content_hash() and not edited.is_approved
    v = sf.save_model(p, edited, "builder edit")
    assert not p.load_version(v).is_approved
    # existing contract: the whole node (its name included) is in the content hash, so a rename also needs approval
    renamed = B.update_node(approved, reg, "m1", name="Machine one")
    assert renamed.content_hash() != approved.content_hash() and not renamed.is_approved


def test_builder_saved_ai_model_still_needs_approval_to_run(reg, tmp_path):
    from simforge.services.app import ApprovalRequired, SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("ai")
    m = build_example_01(reg)
    m = m.model_copy(update={"meta": m.meta.model_copy(update={"origin": "ai_generated"})})
    sf.save_model(p, B.set_distribution(m, reg, "m1", "process_time", D("constant", value=62)), "edit")
    with pytest.raises(ApprovalRequired):
        sf.run_simulation(p)


# ================================================================================ UI (Model tab)
def _ui(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception
    return at


def _sf(tmp_path):
    from simforge.services.app import SimForgeApp
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def test_preexisting_param_editor_noop_save_does_not_materialize_defaults(tmp_path, monkeypatch):
    """Pre-existing 1.0 bug found in 1.1-B: SAVE MODEL without any change wrote unit 's', capacity 1, resources [],
    yield_rate 1.0 and 60 -> 60.0 into every node (new version, new hash, approval lost)."""
    sf = _sf(tmp_path)
    p = sf.create_project("noop")
    sf.save_model(p, load_model(EXAMPLES / "01_simple_line.yaml"), "01")
    h0, n0 = p.current_model().content_hash(), len(p.versions())
    at = _ui(tmp_path, monkeypatch)
    next(b for b in at.button if b.label == "SAVE MODEL").click().run()
    assert not at.exception
    p = sf.open_project(p.meta.slug)
    assert len(p.versions()) == n0 and p.current_model().content_hash() == h0
    assert p.current_model().node("m1").params == {"process_time": {"dist": "constant", "value": 60}}
