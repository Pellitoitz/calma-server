"""1.1-E: C06 economic assumptions editor and C17 productivity visibility."""

from __future__ import annotations

import json

import pytest

from simforge.domain.io import load_model
from simforge.experiments.runner import cache_key, components_fingerprint
from simforge.services import economics_editor as E
from simforge.services.app import SimForgeApp
from simforge.services.productivity import ROADMAP, productivity_panel

from .conftest import EXAMPLES

GOLDEN = EXAMPLES / "1_0_golden_project"


def M(value, basis="PER_PAID_HOUR", **kw) -> E.MoneyForm:
    return E.MoneyForm(value=value, currency=kw.pop("currency", "EUR"), basis=basis, **kw)


@pytest.fixture()
def golden():
    return load_model(GOLDEN / "model.yaml")


@pytest.fixture()
def proj(tmp_path):
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("econ edit")
    sf.save_model(p, load_model(GOLDEN / "model.yaml"), "golden")
    sf.approve_model(p, "eng")
    run = sf.run_simulation(p, replications=2)
    return sf, p, run


# ================================================================================ C06 basic
def test_edit_supported_field_and_physical_hash_invariance(golden):
    new = E.update_line_money(golden, "labor", 0, M(35.0, provenance={"status": "provided_by_client"}))
    assert new.economics.labor[0].rate.value == 35.0
    assert new.content_hash() == golden.content_hash() and new.economic_hash() != golden.economic_hash()
    again = E.update_line_money(golden, "labor", 0, M(35.0, provenance={"status": "provided_by_client"}))
    assert again.economic_hash() == new.economic_hash()  # deterministic economic identity
    assert new.model_dump(mode="json", exclude={"economics"}) == golden.model_dump(mode="json", exclude={"economics"})


def test_missing_stays_missing_and_explicit_zero_stays_zero(golden):
    miss = E.update_line_money(golden, "labor", 0, M(None))
    assert miss.economics.labor[0].rate.value is None and miss.economics.labor[0].rate.missing
    zero = E.update_line_money(golden, "labor", 0, M(0.0))
    assert zero.economics.labor[0].rate.value == 0.0 and not zero.economics.labor[0].rate.missing
    no_ann = E.set_annualization(golden, None)
    assert no_ann.economics.annualization is None  # not declared, never an assumed number of runs per year
    cap = E.update_line_money(golden, "capex", 0, M(None, basis="FIXED"))
    assert cap.economics.capex[0].amount.value is None  # missing CAPEX is never 0


def test_provenance_reference_and_date_preserved(golden):
    f = M(31.5, provenance={"status": "measured", "source": "payroll 2026"}, reference="HR-12", effective_date="2026-01-01")
    new = E.update_line_money(golden, "labor", 0, f)
    rate = new.economics.labor[0].rate
    assert (rate.provenance.status.value, rate.provenance.source, rate.reference, str(rate.effective_date)) == \
        ("measured", "payroll 2026", "HR-12", "2026-01-01")
    back = E.money_form(new.economics.labor[0].rate.model_dump(mode="json"))  # stored -> editor -> stored: identical
    assert E.update_line_money(new, "labor", 0, back).economic_hash() == new.economic_hash()
    assumed = E.update_line_money(golden, "machine", 0, M(18.0, basis="PER_PROCESSING_HOUR", provenance={"status": "assumed"}))
    assert assumed.economics.machine[0].rate.provenance.status.value == "assumed"  # never promoted


@pytest.mark.parametrize("form,match", [
    (dict(value=10.0, currency="euro", basis="PER_PAID_HOUR"), "currency"),
    (dict(value=float("inf"), currency="EUR", basis="PER_PAID_HOUR"), "finito"),
    (dict(value=10.0, currency="EUR", basis="PER_LIGHTYEAR"), "desconocida"),
    (dict(value=10.0, currency="EUR", basis="PER_UNIT"), "no calculable"),
    (dict(value=10.0, currency="EUR", basis="FIXED_PER_PERIOD"), "no calculable"),
    (dict(value=10.0, currency="EUR", basis="PER_PAID_HOUR", effective_date="31/12/2026"), "Fecha"),
])
def test_invalid_inputs_rejected(golden, form, match):
    with pytest.raises(E.EconomicsEditError, match=match):
        E.update_line_money(golden, "labor", 0, E.MoneyForm(**form))


def test_unknown_field_and_category_rejected(golden):
    with pytest.raises(E.EconomicsEditError):
        E.add_line(golden, "machine", {"node": "test", "colour": "red"}, M(1.0, basis="PER_CYCLE"))
    with pytest.raises(E.EconomicsEditError, match="Categoría"):
        E.add_line(golden, "taxes", {}, M(1.0, basis="FIXED"))
    with pytest.raises(Exception):
        E.MoneyForm(value=1.0, currency="EUR", basis="PER_CYCLE", colour="red")


def test_basis_options_are_the_existing_verifier_rules():
    from simforge.validation.economics import ALLOWED, MAINT_BASIS
    assert set(E.basis_options("machine")) == {b.value for b in ALLOWED["machine"]}
    assert E.basis_options("maintenance", "PER_PM") == [MAINT_BASIS["PER_PM"].value]
    assert "PER_UNIT" not in E.basis_options("material") and "FIXED_PER_PERIOD" not in E.basis_options("machine")


def test_existing_verifier_still_reports_category_rules_and_double_counting(golden, reg=None):
    from simforge.library.registry import ComponentRegistry
    from simforge.validation.economics import economics_issues
    reg = ComponentRegistry.load_default()
    bad = E.add_line(golden, "machine", {"node": "test"}, M(5.0, basis="PER_OPERATING_HOUR"))  # overlaps PER_PROCESSING_HOUR
    codes = {i.code for i in economics_issues(bad.economics, bad, reg)}
    assert codes  # double counting / overlapping bases surfaced by the existing verifier, not resolved by the editor


def test_create_and_remove_economics_block(tmp_path):
    m = load_model(EXAMPLES / "01_simple_line.yaml")
    with pytest.raises(E.EconomicsEditError, match="créalo"):
        E.set_header(m, scope=["labor"])
    c = E.create_economics(m, "EUR", ["machine"])
    assert c.economics.currency == "EUR" and c.economics.scope == ["machine"] and c.content_hash() == m.content_hash()
    assert E.remove_economics(c).economics is None


# ================================================================================ C06 project: version, cache, no DES
def test_economic_edit_creates_version_keeps_physics_cache_and_approval(proj, monkeypatch):
    sf, p, run = proj
    cur = p.current_model()
    v0 = p.meta.current_version
    key_before = cache_key(cur.content_hash(), run.seeds[0], components_fingerprint(sf.registry, run.component_versions))
    stored = p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()[0]
    from simforge.engine.des.engine import DesEngine
    import simforge.experiments.runner as runner
    calls = []
    monkeypatch.setattr(DesEngine, "run", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(runner, "run_simulation", lambda *a, **k: calls.append(1))
    new = E.update_line_money(cur, "labor", 0, M(40.0, provenance={"status": "provided_by_client"}))
    v1 = sf.save_economics(p, new, "labor rate 40")
    after = p.load_version(v1)
    assert v1 == v0 + 1 and {x.version: x.parent for x in p.versions()}[v1] == v0
    assert p.load_version(v0).economics.labor[0].rate.value == 32.0  # previous version untouched
    assert after.content_hash() == cur.content_hash() and after.is_approved  # physical approval still valid
    assert cache_key(after.content_hash(), run.seeds[0], components_fingerprint(sf.registry, run.component_versions)) == key_before
    ev = sf.evaluate_economics(p, run.run_id)  # evaluation of the EXISTING run with the new assumptions
    assert calls == []
    assert p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()[0] == stored
    from simforge.economics import evaluate_run
    direct = evaluate_run(p.load_run(run.run_id), sf.run_model_of(p, run.run_id), after.economics, sf.registry)
    assert json.dumps(ev.to_dict(), sort_keys=True, default=str) == json.dumps(direct.to_dict(), sort_keys=True, default=str)
    assert ev.economic_hash == after.economic_hash()


def test_save_economics_refuses_physical_changes(proj):
    from simforge.domain.paths import set_value
    sf, p, _ = proj
    phys = set_value(p.current_model(), "nodes.buffer.params.capacity", 9)
    with pytest.raises(ValueError, match="economics"):
        sf.save_economics(p, phys, "sneaky")


def test_ui_economics_editor_saves_and_evaluates_without_des(proj, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    sf, p, run = proj
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(sf.workspace.root))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(sf.library_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception and len(at.tabs) == 12
    h0 = p.current_model().content_hash()
    next(s for s in at.selectbox if s.key == "ee_pick").select("labor.0").run()
    next(t for t in at.text_input if t.key == "ee_edit_labor.0_v").input("").run()  # empty -> MISSING
    next(b for b in at.button if b.key == "ee_edit_btn").click().run()
    assert not at.exception
    m = sf.open_project(p.meta.slug).current_model()
    assert m.economics.labor[0].rate.value is None and m.content_hash() == h0


# ================================================================================ C17 productivity
def test_productivity_panel_shows_recorded_values_verbatim_and_missing_as_not_available(proj):
    sf, p, _ = proj
    pp = productivity_panel(p)
    rec = {x.name: x for x in pp.recorded}
    assert rec["time_to_first_run_s"].status == "AVAILABLE" and rec["time_to_first_run_s"].value == p.metric("time_to_first_run_s")
    assert rec["time_to_first_run_s"].unit == "s" and rec["time_to_first_run_s"].source == "MEASURED"
    assert rec["ai_generation_s"].status == "NOT_AVAILABLE" and rec["ai_generation_s"].value is None  # no AI used: not 0
    road = {x.name: x for x in pp.roadmap}
    assert set(road) == set(ROADMAP)
    assert road["TIME_TO_FIRST_VALID_RUN"].value == p.metric("time_to_first_run_s")
    for name in ("TIME_TO_VALID_MODEL", "TIME_TO_DECISION_READY_COMPARISON", "ACTIVE_ENGINEERING_TIME", "NUMBER_OF_CORRECTION_LOOPS"):
        assert road[name].status == "NOT_AVAILABLE" and road[name].value is None and road[name].source == "NOT_INSTRUMENTED"
    counts = {x.name: x.value for x in pp.counts}
    assert counts["runs"] == 1 and counts["versions"] == len(p.versions()) and counts["ai_value_corrections"] == 0  # real zero
    assert pp.model_dump_json() == productivity_panel(p).model_dump_json()  # deterministic


def test_productivity_records_real_zero_and_user_values_without_reconstruction(proj):
    from simforge.services.productivity import record_engineer_time
    sf, p, _ = proj
    record_engineer_time(p, "correction_min", 0)
    record_engineer_time(p, "engineer_review_min", 12)
    rec = {x.name: x for x in productivity_panel(p).recorded}
    assert rec["correction_s_user"].value == 0 and rec["correction_s_user"].status == "AVAILABLE"
    assert rec["engineer_review_s_user"].value == 720 and rec["engineer_review_s_user"].source == "USER_PROVIDED"


def test_productivity_panel_language_is_factual(proj):
    sf, p, _ = proj
    text = productivity_panel(p).model_dump_json().lower()
    assert not [w for w in ("excellent", "efficient", "saved you", "% more", "great", "score") if w in text]
