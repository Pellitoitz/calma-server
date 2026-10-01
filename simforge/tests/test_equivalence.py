"""Model A (manual) vs Model B (generated from natural language): textual vs structural vs result equivalence."""

import json
from pathlib import Path

import pytest

from simforge.domain.io import load_model
from simforge.domain.isms import ISMSModel
from simforge.domain.paths import set_value
from simforge.services.app import SimForgeApp

EXAMPLES = Path(__file__).parents[1] / "examples"
# same process as examples/02_shared_operator.yaml, described in words (priority stated, buffer sweep requested)
TEXT_B = ("Fuente infinita. Un operario monta una pieza durante 60 segundos. Después hay un buffer con capacidad 5. "
          "Una máquina procesa cada pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza durante "
          "20 segundos. La inspección tiene prioridad sobre el montaje. Simular durante 8 horas. Prueba buffers de 1 a 10.")


@pytest.fixture
def app(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


@pytest.fixture
def models(app):
    a = load_model(EXAMPLES / "02_shared_operator.yaml")
    b = app.parse_process(app.create_project("B"), TEXT_B).outcome.model
    return a, b


def test_generated_equals_manual_structurally_and_in_results(app, models):
    a, b = models
    spec, res = app.compare_models(a, b)
    assert not spec.textual_equal and not spec.json_equal  # different ids, names, parameter indirection, provenance
    assert spec.structurally_equivalent, spec.to_text()
    assert spec.node_mapping == {"src": "source", "assembly": "manual_assembly", "buffer_1": "buffer_1", "machine": "machine",
                                 "inspection": "inspection", "out": "sink"}
    assert res is not None and res.equivalent, res.to_text()
    kpis = {r["kpi"]: r for r in res.rows}
    assert kpis["units_completed"]["a"] == kpis["units_completed"]["b"] == 359
    for k in ("node.machine->machine.starved", "node.inspection->inspection.waiting_resource",
              "resource.operator_1->operator_1.utilization", "avg_lead_time_s", "avg_wip"):
        assert kpis[k]["ok"]


def test_textual_and_key_order(app):
    a = load_model(EXAMPLES / "02_shared_operator.yaml")
    spec, _ = app.compare_models(a, a.model_copy(deep=True), run=False)
    assert spec.textual_equal and spec.json_equal and spec.structurally_equivalent
    # field order changed in the source JSON -> not textually equal, same JSON, same system
    text_a = a.model_dump_json()
    reordered = json.dumps(dict(reversed(list(json.loads(text_a).items()))))
    spec, _ = app.compare_models(text_a, reordered, run=False)
    assert not spec.textual_equal and spec.json_equal and spec.structurally_equivalent


def test_units_ids_and_defaults_do_not_matter(app):
    a = load_model(EXAMPLES / "02_shared_operator.yaml")
    b = set_value(a, "nodes.assembly.params.process_time", {"dist": "constant", "value": 1, "unit": "min"})
    b = set_value(b, "nodes.machine.params.capacity", 1)  # library default made explicit
    raw = json.loads(b.model_dump_json().replace("buffer_1", "queue_x"))  # renamed everywhere (edges, experiments)
    b = ISMSModel.model_validate(raw)
    spec, _ = app.compare_models(a, b, run=False)
    assert spec.structurally_equivalent, spec.to_text()
    assert spec.node_mapping["buffer_1"] == "queue_x"


@pytest.mark.parametrize("path, value, category", [
    ("nodes.buffer_1.params.capacity", 6, "capacities"),
    ("nodes.inspection.params.process_time", {"dist": "constant", "value": 21}, "parameters"),
    ("resources.operator_1.dispatch", "fifo", "strategies"),
    ("nodes.assembly.priority", 0, "strategies"),
    ("resources.operator_1.quantity", 2, "resources"),
    ("simulation.horizon", {"value": 7, "unit": "h"}, "simulation"),
    ("experiments.0.factors.0.values", [1, 2, 3], "experiments"),
])
def test_differences_are_reported_by_category(app, path, value, category):
    a = load_model(EXAMPLES / "02_shared_operator.yaml")
    b = set_value(a, path, value)
    spec, res = app.compare_models(a, b)
    assert not spec.structurally_equivalent and res is None  # not equivalent -> results are not compared
    cats = {d.category for d in spec.differences}
    assert category in cats, spec.to_text()


def test_structural_difference_in_flow(app, models):
    a, _ = models
    c = load_model(EXAMPLES / "01_simple_line.yaml")
    spec, _ = app.compare_models(a, c, run=False)
    assert not spec.structurally_equivalent
    assert spec.by_category()["nodes"] or spec.by_category()["connections"]
    assert "STRUCTURAL EQUIVALENCE:    NO" in spec.to_text()


def test_priority_statement_is_a_rule_not_a_step(app):
    pr = app.parse_process(app.create_project("prio"), TEXT_B)
    m = pr.outcome.model
    assert [n.component for n in m.nodes].count("inspection") == 1
    op = m.resources[0]
    assert op.dispatch.value == "priority" and m.node("inspection").priority < m.node("manual_assembly").priority
    # an uninterpretable priority is not dropped: it becomes a custom rule candidate
    pr = app.parse_process(app.create_project("prio2"), TEXT_B.replace("La inspección tiene prioridad sobre el montaje.",
                                                                        "La prioridad depende del color de la pieza."))
    assert any("color" in c.description for c in pr.outcome.model.custom_rule_candidates)
