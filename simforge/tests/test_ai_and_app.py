"""AI layer + application service. No real API calls: MockLLMProvider / offline rules."""


import pytest

from simforge.ai.provider import MockLLMProvider
from simforge.ai.schemas import ProcessDraft
from simforge.domain.paths import get_value
from simforge.services.app import SimForgeApp
from simforge.validation.verifier import Readiness

MVP_TEXT = ("Fuente infinita. Un operario realiza montaje durante 60 segundos. Existe un buffer de 5 unidades. "
            "Una máquina tarda 45 segundos. El mismo operario inspecciona durante 20 segundos. Simular 8 horas.")


@pytest.fixture
def app(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def test_mvp_end_to_end_offline(app):
    """Objective #150: create project -> describe -> model -> validate -> run -> experiment -> save -> reopen."""
    p = app.create_project("MVP line")
    pr = app.parse_process(p, MVP_TEXT)
    m = pr.outcome.model
    assert [n.component for n in m.nodes] == ["source", "manual_assembly", "buffer", "machine", "inspection", "sink"]
    assert get_value(m, "nodes.buffer_1.params.capacity") == 5
    assert pr.report.readiness is Readiness.EXECUTABLE
    # shared operator conflict detected, strategy applied as explicit assumption + question asked
    assert any("FIFO" in a.text for a in m.assumptions)
    assert any("prioridad" in q.question for q in m.missing)
    assert pr.outcome.ungrounded == []
    assert pr.outcome.reuse_ratio == 1.0

    res = app.run_simulation(p)
    assert res.kpis.mean("units_completed") == 359  # FIFO: same as hand calculation
    # modify parameter by chat
    r = app.command(p, "Cambia el buffer a 8")
    assert r.changes == [("nodes.buffer_1.params.capacity", 5, 8)]
    assert get_value(p.current_model(), "nodes.buffer_1.params.capacity") == 8
    # experiment by chat
    r = app.command(p, "Prueba buffers entre 1 y 10")
    assert r.experiment and len(r.experiment.scenarios) == 10
    assert all(s.result for s in r.experiment.scenarios)
    # reopen
    slug = p.meta.slug
    p.close()
    p2 = app.open_project(slug)
    assert get_value(p2.current_model(), "nodes.buffer_1.params.capacity") == 8
    assert len(p2.runs()) >= 1 and len(p2.experiments()) == 1
    assert len(p2.versions()) == 2


def test_chat_commands(app):
    p = app.create_project("cmds")
    app.parse_process(p, MVP_TEXT)
    r = app.command(p, "Reduce montaje a 50 segundos")
    assert r.changes[0][0] == "nodes.manual_assembly.params.process_time.value"
    r = app.command(p, "Pon dos operarios")
    assert get_value(p.current_model(), "resources.operator_1.quantity") == 2
    r = app.command(p, "¿Dónde está el cuello de botella?")
    assert r.findings and all(f.evidence for f in r.findings)
    r = app.command(p, "Vuelve a la versión anterior")
    assert r.needs_confirmation
    r = app.command(p, "Vuelve a la versión anterior", confirm=True)
    assert get_value(p.current_model(), "resources.operator_1.quantity") == 1
    r = app.command(p, "haz algo raro con el flux")
    assert r.plan.question and not r.changes


def test_cache_reuses_results(app):
    p = app.create_project("cache")
    app.parse_process(p, MVP_TEXT)
    a = app.run_simulation(p)
    b = app.run_simulation(p)
    assert a.cache_hits == 0 and b.cache_hits == 1
    assert a.per_replication == b.per_replication


def test_approval_and_baseline(app):
    p = app.create_project("approve")
    app.parse_process(p, MVP_TEXT)
    v = app.approve_model(p, by="Asier")
    assert p.current_model().is_approved
    p.set_baseline(v)
    r = app.command(p, "Cambia el buffer a 3")
    assert r.needs_confirmation  # changing an approved model is important
    r = app.command(p, "Cambia el buffer a 3", confirm=True)
    assert not p.current_model().is_approved
    assert p.load_version(v).is_approved  # baseline snapshot untouched (immutable)
    assert app.compare_versions(p, v, r.new_version) == [("nodes.buffer_1.params.capacity", 5, 3)]


def test_export_import(app, tmp_path):
    p = app.create_project("Export me")
    app.parse_process(p, MVP_TEXT)
    app.run_simulation(p)
    pkg = app.workspace.export_project(p.meta.slug, tmp_path / "pkg")
    p2 = app.workspace.import_project(pkg)
    assert p2.meta.slug != p.meta.slug
    assert p2.current_model().content_hash() == p.current_model().content_hash()
    assert len(p2.runs()) == 1


# ------------------------------------------------------------------ LLM path (mocked)

def _mvp_draft(user: str, schema) -> dict:
    assert schema is ProcessDraft
    return {
        "model_name": "MVP", "horizon_value": 8, "horizon_unit": "h", "supply": "infinite",
        "resources": [{"id": "op", "name": "Operario", "kind": "operator", "quantity": 1}],
        "steps": [
            {"id": "assembly", "name": "Montaje", "component": "manual_assembly", "time": {"dist": "constant", "value": 60}, "resources": ["op"]},
            {"id": "buf", "name": "Buffer", "component": "buffer", "capacity": 5},
            {"id": "m", "name": "Máquina", "component": "machine", "time": {"dist": "constant", "value": 45}},
            # hallucinated value: 25 s is not in the text -> must be flagged as assumption
            {"id": "insp", "name": "Inspección", "component": "inspection", "time": {"dist": "constant", "value": 25}, "resources": ["op"]},
        ],
        "policies": [{"resource": "op", "rule": "priority", "priority_order": ["insp", "assembly"]}],
    }


def test_llm_interpreter_with_mock_and_grounding(tmp_path):
    mock = MockLLMProvider(_mvp_draft)
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=mock)
    p = app.create_project("llm")
    pr = app.parse_process(p, MVP_TEXT)
    m = pr.outcome.model
    assert pr.interpreter.startswith("llm:mock")
    assert "tiempo de Inspección = 25" in pr.outcome.ungrounded
    insp = m.node("insp")
    assert insp.params["process_time"]["provenance"]["status"] == "assumed"
    assert m.node("assembly").params["process_time"]["provenance"]["status"] == "provided_by_client"
    assert get_value(m, "resources.op.dispatch") == "priority"
    assert m.node("insp").priority < m.node("assembly").priority
    # usage logged
    assert p.llm_usage_summary()["requests"] == 1


def test_privacy_anonymisation_and_minimal_context(tmp_path):
    mock = MockLLMProvider(_mvp_draft)
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=mock)
    p = app.create_project("secret")
    p.meta.sensitive_terms = {"ACME Motors": "CLIENT_A", "REF-778": "PRODUCT_1"}
    p.save_meta()
    (p.root / "attachments" / "confidential.csv").write_text("secret data")
    app.parse_process(p, "Para ACME Motors, la referencia REF-778: " + MVP_TEXT)
    sent = mock.calls[0]["system"] + mock.calls[0]["user"]
    assert "ACME" not in sent and "REF-778" not in sent
    assert "CLIENT_A" in sent and "PRODUCT_1" in sent
    assert "secret data" not in sent


def test_llm_edit_plan_validated_deterministically(tmp_path):
    def responder(user, schema):
        if schema is ProcessDraft:
            return _mvp_draft(user, schema)
        return {"operations": [{"intent": "set", "path": "nodes.buf.params.capacity", "value_json": "8"},
                               {"intent": "set", "path": "nodes.ghost.params.capacity", "value_json": "3"}]}
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=MockLLMProvider(responder))
    p = app.create_project("edit")
    app.parse_process(p, MVP_TEXT)
    r = app.command(p, "cambia buffer a 8")
    assert r.error and "ghost" in r.error  # invalid path rejected, nothing applied
    assert get_value(p.current_model(), "nodes.buf.params.capacity") == 5
