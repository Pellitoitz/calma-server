"""Chat edits are structured ISMS changes (the chat is never the model); corrections log; library-improvement candidates."""

from pathlib import Path

import pytest

from simforge.domain.expressions import resolve
from simforge.domain.paths import get_value
from simforge.library.registry import CORE_DIR
from simforge.services.app import SimForgeApp
from .test_nl_orchestration import MVP_SPEC_TEXT
from .test_nl_selective import ANSWERS, SELECTIVE_TEXT


@pytest.fixture
def app(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def _val(model, pid):
    return next(p for p in model.parameters if p.id == pid)


def _selective(app, name="sel"):
    p = app.create_project(name)
    app.parse_process(p, SELECTIVE_TEXT)
    app.answer_questions(p, ANSWERS)
    app.approve_model(p, by="engineer")
    return p


def _values(changes):
    return [c for c in changes if ".provenance" not in c[0]]


def test_input_buffer_from_to_is_a_structured_change(app):
    p = _selective(app)
    # the engineer states the current value: checked against the ISMS, nothing applied on mismatch
    v_before = p.meta.current_version
    r = app.command(p, "Cambia el buffer de entrada de 4 a 5")
    assert r.needs_confirmation and "vale 3" in r.message and p.meta.current_version == v_before
    r = app.command(p, "Cambia el buffer de entrada de 3 a 5", confirm=True)
    assert _values(r.changes) == [("parameters.buffer_de_entrada_capacity.value", 3, 5)]
    resolved, _ = resolve(p.current_model())
    assert get_value(resolved, "nodes.buffer_de_entrada.params.capacity") == 5
    prm = _val(p.current_model(), "buffer_de_entrada_capacity")
    assert prm.provenance.status.value == "provided_by_client" and prm.provenance.source == "chat"
    # the version diff shows the same structured change
    assert ("parameters.buffer_de_entrada_capacity.value", 3, 5) in _values(app.compare_versions(p, v_before, r.new_version))
    # a no-op does not create a version
    r = app.command(p, "pon el buffer a 5", confirm=True)
    assert "Sin cambios" in r.message and r.new_version is None


@pytest.mark.parametrize("request_text, pid, value", [
    ("La velocidad del operario es 1.0 m/s", "operator_walking_speed", 1.0),
    ("La distancia entre montaje y buffer de entrada es 800 cm", "dist_manual_assembly_buffer_de_entrada", 8.0),
    ("tiempo de carga 7 segundos", "transport_1_load_time", 7.0),
    ("descarga 4 s", "transport_1_unload_time", 4.0),
    ("WIP objetivo 3", "wip_target", 3.0),
    ("Ahora son 5 circuitos por bastidor", "circuitos_per_unit", 5.0),
    ("El montaje tarda 1 min por circuito", "manual_assembly_time", 60.0),
])
def test_named_parameter_edits(app, request_text, pid, value):
    p = _selective(app)
    r = app.command(p, request_text, confirm=True)
    assert not r.error and r.new_version, r.message
    assert _val(p.current_model(), pid).value == pytest.approx(value)
    changed = {c[0] for c in _values(r.changes)}
    assert changed == {f"parameters.{pid}.value"}


def test_ambiguous_or_unknown_edit_asks(app):
    p = _selective(app)
    r = app.command(p, "pon 7 por favor")
    assert r.plan.question and not r.changes


def test_corrections_log_only_for_ai_values(app):
    p = app.create_project("mvp")
    app.parse_process(p, MVP_SPEC_TEXT)
    # what-if on a value the user stated: NOT a correction
    app.command(p, "Cambia el buffer a 8", confirm=True)
    assert p.corrections() == []
    # the engineer says the stated value is wrong: correction with reason
    app.command(p, "La inspección tarda 25 segundos porque lo hemos medido", confirm=True)
    (c,) = p.corrections()
    assert (c["parameter"], c["component"], c["ai_value"], c["engineer_value"]) == ("inspection_time", "inspection", "20.0", "25.0")
    assert c["reason"] == "lo hemos medido"
    # assumed by the AI (racks baseline = 1) -> any change is a correction
    s = _selective(app, "sel2")
    app.command(s, "pon 3 bastidores", confirm=True)
    assert [c["parameter"] for c in s.corrections()] == ["racks_count"]


def test_experiment_by_chat_on_parameter(app):
    p = app.create_project("mvp")
    app.parse_process(p, MVP_SPEC_TEXT)
    app.approve_model(p, by="engineer")
    r = app.command(p, "prueba buffers de 1 a 10")
    assert r.experiment and len(r.experiment.scenarios) == 10
    assert r.experiment.spec.factors[0].path == "parameters.buffer_1_capacity.value"
    assert all(s.result for s in r.experiment.scenarios)


def test_library_improvement_candidates_never_modify_library(app):
    before = sorted((f.name, f.stat().st_mtime) for f in Path(CORE_DIR).glob("*.yaml"))
    for name in ("a", "b"):
        p = app.create_project(name)
        app.parse_process(p, MVP_SPEC_TEXT + " Si la máquina falla, el operario la repara.")
        app.command(p, "La inspección tarda 25 segundos porque lo hemos medido", confirm=True)
    cands = app.library_improvement_candidates()
    kinds = {c["kind"]: c for c in cands}
    assert set(kinds) == {"parameter_correction", "custom_rule"}
    pc = kinds["parameter_correction"]
    assert pc["status"] == "CANDIDATE_FOR_LIBRARY_IMPROVEMENT" and pc["component"] == "inspection" and pc["occurrences"] == 2
    assert pc["projects"] == ["a", "b"]
    assert kinds["custom_rule"]["occurrences"] == 2
    assert app.library_improvement_candidates(min_occurrences=3) == []
    assert sorted((f.name, f.stat().st_mtime) for f in Path(CORE_DIR).glob("*.yaml")) == before
