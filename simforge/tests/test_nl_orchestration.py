"""Natural language -> ISMS orchestration (offline interpreter, no API calls).

Reproducible MVP: parse -> missing information -> ISMS -> component matching -> model build ->
validation -> engineer approval -> run -> KPIs.
"""

import pytest

from simforge.domain.expressions import resolve
from simforge.domain.paths import get_value
from simforge.services.app import ApprovalRequired, SimForgeApp
from simforge.validation.verifier import Readiness

MVP_SPEC_TEXT = ("Fuente infinita. Un operario monta una pieza durante 60 segundos. Después hay un buffer con capacidad 5. "
                 "Una máquina procesa cada pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza "
                 "durante 20 segundos. Simular durante 8 horas.")


@pytest.fixture
def app(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def _params(model):
    return {p.id: p for p in model.parameters}


def test_mvp_orchestration_reproducible(app):
    p = app.create_project("MVP orchestration")
    # 1. parse
    pr = app.parse_process(p, MVP_SPEC_TEXT)
    o, m = pr.outcome, pr.outcome.model
    assert m.meta.origin == "ai_generated"
    assert m.meta.generated_by["prompt_version"] == "offline_rules_v2"
    assert m.meta.generated_by["compiler"] == "compiler_v2"
    assert o.draft.unparsed == [] and o.draft.custom_rules == []  # nothing silently dropped
    # 2. missing information: none required; the FIFO choice is an assumption + optional question
    assert o.questions() == []
    assert all(not q.required for q in m.missing)
    assert any("prioridad" in q.question for q in m.missing)
    assert any("FIFO" in a.text for a in m.assumptions)
    # 3. ISMS: every number is a traceable parameter stated by the user
    prm = _params(m)
    assert {k: v.value for k, v in prm.items()} == {"manual_assembly_time": 60, "buffer_1_capacity": 5, "machine_time": 45,
                                                    "inspection_time": 20, "operator_1_count": 1}
    assert all(v.provenance.status.value == "provided_by_client" for v in prm.values())
    assert o.ungrounded == []
    assert m.simulation.horizon.value == 8 and m.simulation.horizon.unit == "h"
    # 4. component matching
    assert [n.component for n in m.nodes] == ["source", "manual_assembly", "buffer", "machine", "inspection", "sink"]
    assert o.reused_count == 8 and o.custom_count == 0 and o.reuse_ratio == 1.0
    report = o.matching_report()
    assert "REUSE RATIO: 100%" in report and "shared_operator" in report and "fifo" in report
    # 5. model build plan
    plan = o.plan.to_text()
    assert "Source\n→ Manual assembly\n→ Buffer 1\n→ Machine\n→ Inspection\n→ Sink" in plan
    assert "Operario: FIFO" in plan and "Custom logic:\n- none" in plan
    # 6. validation
    assert pr.report.readiness is Readiness.EXECUTABLE
    # 7. engineer approval is required before the first run
    with pytest.raises(ApprovalRequired):
        app.run_simulation(p)
    assert app.approval_pending(p, m)
    app.approve_model(p, by="engineer")
    assert not app.approval_pending(p, p.current_model())
    # 8-9. run + KPIs (same as the hand calculation of the FIFO shared operator line)
    res = app.run_simulation(p)
    assert res.kpis.mean("units_completed") == 359
    assert p.metric("reuse_ratio") == 1.0 and p.metric("custom_logic_count") == 0
    assert p.metric("engineer_review_s") is not None


def test_english_description_gives_same_isms(app):
    en = ("Infinite source. An operator assembles a part for 60 seconds. Then there is a buffer with capacity 5. "
          "A machine processes each part for 45 seconds. Finally the same operator inspects each part for 20 seconds. "
          "Simulate 8 hours.")
    es = app.parse_process(app.create_project("es"), MVP_SPEC_TEXT).outcome.model
    en_m = app.parse_process(app.create_project("en"), en).outcome.model
    assert [n.component for n in en_m.nodes] == [n.component for n in es.nodes]
    assert {k: v.value for k, v in _params(en_m).items()} == {k: v.value for k, v in _params(es).items()}


@pytest.mark.parametrize("queue_word", ["una cola", "un almacén intermedio", "un buffer"])
@pytest.mark.parametrize("worker", ["operario", "trabajador", "persona"])
def test_language_variations(app, queue_word, worker):
    text = (f"Fuente infinita. Un {worker} monta una pieza durante 60 segundos. Después hay {queue_word} con capacidad 5. "
            f"Una máquina procesa cada pieza durante 45 segundos. Finalmente el mismo {worker} inspecciona cada pieza "
            "durante 20 segundos. Simular durante 8 horas.").replace("Un persona", "Una persona").replace("el mismo persona", "la misma persona")
    m = app.parse_process(app.create_project("var"), text).outcome.model
    assert [n.component for n in m.nodes] == ["source", "manual_assembly", "buffer", "machine", "inspection", "sink"]
    assert len(m.resources) == 1 and m.resources[0].kind.value == "operator"
    assert m.node("inspection").params["resources"][0]["resource"] == m.resources[0].id


def test_missing_time_is_asked_never_invented(app):
    text = "Fuente infinita. Un operario monta una pieza. Una máquina procesa cada pieza durante 45 segundos. Simular 8 horas."
    p = app.create_project("missing")
    pr = app.parse_process(p, text)
    o, m = pr.outcome, pr.outcome.model
    assert pr.report.readiness is not Readiness.EXECUTABLE
    assert _params(m)["manual_assembly_time"].value is None
    assert any("Manual assembly" in q or "montaje" in q.lower() for q in o.questions())
    assert o.questions_text().startswith("Para poder ejecutar el modelo necesito")
    # answering the question makes it runnable; the answer is USER_PROVIDED
    pr2 = app.answer_questions(p, {"param:manual_assembly_time": 60})
    assert pr2.report.readiness is Readiness.EXECUTABLE
    prm = _params(pr2.outcome.model)["manual_assembly_time"]
    assert prm.value == 60 and prm.provenance.status.value == "provided_by_client" and prm.provenance.source == "answer"


def test_resolved_model_has_numeric_values(app):
    m = app.parse_process(app.create_project("res"), MVP_SPEC_TEXT).outcome.model
    resolved, errors = resolve(m)
    assert resolved is not None
    assert get_value(resolved, "nodes.buffer_1.params.capacity") == 5
