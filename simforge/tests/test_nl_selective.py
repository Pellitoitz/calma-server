"""Second AI test: selective soldering built from EXISTING library components (offline interpreter, no API calls).

The parser is not keyed to one sentence: paraphrases, other vocabulary and English must give the same structure.
"""

import pytest

from simforge.services.app import ApprovalRequired, SimForgeApp
from simforge.validation.verifier import Readiness

SELECTIVE_TEXT = """Tengo un proceso de soldadura selectiva.

Los circuitos se montan manualmente en bastidores.

Hay un número limitado de bastidores.

Después del montaje los bastidores se transportan hasta la selectiva.

Existe un buffer de entrada.

La selectiva procesa los bastidores.

Después pasan a revisión y limpieza.

El mismo operario realiza montaje, transporte y revisión.

Quiero que el operario mantenga alimentada la selectiva utilizando una estrategia de WIP objetivo.

Quiero probar entre 1 y 10 bastidores durante un turno de 8 horas."""

STRUCTURE = ["source", "manual_assembly", "rack_transport", "buffer", "selective_soldering", "inspection", "sink"]


@pytest.fixture
def app(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def _params(model):
    return {p.id: p for p in model.parameters}


def test_selective_structure_from_library(app):
    pr = app.parse_process(app.create_project("sel"), SELECTIVE_TEXT)
    o, m = pr.outcome, pr.outcome.model
    assert [n.component for n in m.nodes] == STRUCTURE
    kinds = {r.kind.value for r in m.resources}
    assert kinds == {"operator", "carrier"}
    op = next(r for r in m.resources if r.kind.value == "operator")
    assert op.dispatch.value == "wip_target" and op.wip_target.protected_node == "selective_soldering"
    # every task names the same operator (montaje, transporte, revisión)
    for nid in ("manual_assembly", "transport_1", "inspection"):
        node = m.node(nid)
        assert op.id in str(node.params), nid
    # matching: everything reused, nothing custom
    ids = {mt.match_id for mt in o.matches}
    assert {"rack_transport", "buffer", "selective_soldering", "shared_operator", "carrier", "wip_target_priority"} <= ids
    assert o.custom_count == 0 and o.reuse_ratio == 1.0
    # experiment on the racks parameter, 1..10
    assert m.experiments[0].factors[0].path == "parameters.racks_count.value"
    assert m.experiments[0].factors[0].values == list(range(1, 11))
    assert "Custom logic:\n- none" in o.plan.to_text()


def test_selective_never_invents_and_groups_questions(app):
    pr = app.parse_process(app.create_project("sel"), SELECTIVE_TEXT)
    o, m = pr.outcome, pr.outcome.model
    assert pr.report.readiness is Readiness.INCOMPLETE
    prm = _params(m)
    # nothing numeric was stated except the experiment range and the horizon -> all MISSING
    for pid in ("manual_assembly_time", "selective_soldering_time", "inspection_time", "buffer_de_entrada_capacity",
                "circuitos_per_unit", "operator_walking_speed", "wip_target", "transport_1_load_time"):
        assert prm[pid].value is None, pid
    assert prm["racks_count"].value == 1 and prm["racks_count"].provenance.status.value == "assumed"
    q = o.questions()
    assert len(q) == 12
    text = o.questions_text()
    assert text.startswith("Para poder ejecutar el modelo necesito 12 datos")
    for needle in ("circuitos por unidad/bastidor", "Distancia", "Velocidad del operario", "Capacidad de 'Buffer de entrada'",
                   "WIP objetivo", "racks vacíos"):
        assert needle in text, needle
    # "procesa los bastidores" -> time per rack, assembly/review per circuit
    assert any("'Selective soldering' (s)" in x for x in q)
    assert any("'Manual assembly' por circuito" in x for x in q)


ANSWERS = {"param:circuitos_per_unit": 4, "param:manual_assembly_time": 30, "param:transport_1_load_time": 5,
           "param:transport_1_unload_time": 5, "param:buffer_de_entrada_capacity": 3, "param:selective_soldering_time": 20,
           "param:inspection_time": 15, "param:dist_manual_assembly_buffer_de_entrada": 10,
           "param:dist_buffer_de_entrada_inspection": 5, "param:operator_walking_speed": 1.2, "param:wip_target": 2,
           "return_mode:racks": "immediate"}


def test_selective_answers_approval_run_and_experiment(app):
    p = app.create_project("sel")
    app.parse_process(p, SELECTIVE_TEXT)
    partial = app.answer_questions(p, {"param:circuitos_per_unit": 4})
    assert len(partial.outcome.questions()) == 11  # answers accumulate, nothing else changes
    pr = app.answer_questions(p, ANSWERS)
    assert pr.report.readiness is Readiness.EXECUTABLE
    prm = _params(pr.outcome.model)
    assert prm["wip_target"].value == 2 and prm["wip_target"].provenance.source == "answer"
    with pytest.raises(ApprovalRequired):
        app.run_simulation(p)
    app.approve_model(p, by="engineer")
    res = app.run_simulation(p)
    # 1 rack, single operator, everything sequential:
    # 4*30 assembly + 5 load + 10/1.2 transport + 5 unload + 20 selective + 5/1.2 walk + 4*15 review + 15/1.2 walk back
    cycle = 120 + 5 + 10 / 1.2 + 5 + 20 + 5 / 1.2 + 60 + 15 / 1.2
    assert res.kpis.mean("units_completed") == int(8 * 3600 // cycle)
    model = p.current_model()
    exp = app.run_experiment(p, model.experiments[0])
    assert len(exp.scenarios) == 10 and all(s.result for s in exp.scenarios)
    tp = [s.result.kpis.mean("units_completed") for s in exp.scenarios]
    assert tp[0] == res.kpis.mean("units_completed")
    assert max(tp) > tp[0]  # a second rack lets the operator overlap work with the selective


def test_selective_paraphrase_and_other_words(app):
    text = ("Proceso de soldadura selectiva. Un trabajador monta 6 placas por bastidor, 40 segundos por placa. "
            "Luego el trabajador lleva el bastidor a la selectiva, a 12 metros. Hay una cola de entrada con capacidad 4. "
            "La selectiva suelda cada bastidor en 90 segundos. Al final la misma persona revisa cada placa durante 10 segundos. "
            "Los bastidores vacíos vuelven inmediatamente. Hay 3 bastidores. Simular 8 horas.")
    pr = app.parse_process(app.create_project("para"), text)
    m = pr.outcome.model
    assert [n.component for n in m.nodes] == STRUCTURE
    assert len([r for r in m.resources if r.kind.value == "operator"]) == 1
    prm = _params(m)
    stated = {k: v.value for k, v in prm.items() if v.provenance and v.provenance.status.value == "provided_by_client"}
    assert stated["manual_assembly_time"] == 40 and stated["selective_soldering_time"] == 90
    assert stated["inspection_time"] == 10 and stated["racks_count"] == 3
    assert any(v == 4 for k, v in stated.items() if k.endswith("_capacity"))
    assert pr.outcome.ungrounded == []


def test_selective_english(app):
    text = ("I have a selective soldering process. Circuits are assembled manually on racks. "
            "After assembly the racks are transported to the selective. There is an input buffer. "
            "The selective processes the racks. Then they go to review and cleaning. "
            "The same operator does assembly, transport and review. Test between 1 and 10 racks during an 8 hour shift.")
    es = app.parse_process(app.create_project("es"), SELECTIVE_TEXT).outcome.model
    en = app.parse_process(app.create_project("en"), text).outcome.model
    assert [n.component for n in en.nodes] == [n.component for n in es.nodes]
    assert {r.kind.value for r in en.resources} == {"operator", "carrier"}


def test_unsupported_logic_becomes_custom_rule_candidate(app):
    text = SELECTIVE_TEXT + "\n\nSi la selectiva falla, el operario la repara antes de seguir con el montaje."
    proj = app.create_project("custom")
    pr = app.parse_process(proj, text)
    o, m = pr.outcome, pr.outcome.model
    assert len(m.custom_rule_candidates) == 1
    cand = m.custom_rule_candidates[0]
    assert cand.status == "proposed" and "falla" in cand.description and cand.reason_not_found
    assert o.custom_count == 1 and o.reuse_ratio < 1.0
    assert "CUSTOM_RULE_PENDING" in {i.code for i in pr.report.errors}  # cannot run until the engineer decides

    # the engineer decides: run WITHOUT the rule (explicitly reported), never silently
    app.decide_custom_rule(proj, cand.id, "deferred", by="engineer")
    rep = app.validate_model(proj.current_model())
    codes = {i.code for i in rep.issues}
    assert "CUSTOM_RULE_PENDING" not in codes and "CUSTOM_RULE_NOT_MODELLED" in codes
