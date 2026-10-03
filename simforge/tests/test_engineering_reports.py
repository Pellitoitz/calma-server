"""1.1-D engineering reports (C12): run engineering report + scenario comparison report.

Fixtures simulate and evaluate ONCE (as a project would have stored them); building / rendering / exporting a report
must never simulate, recompute a formula or mutate anything.
"""

from __future__ import annotations

import json

import pytest

from simforge.analytics.workbench import KpiValue
from simforge.domain.io import load_model
from simforge.domain.paths import set_value
from simforge.reporting.engineering import (
    RunEngineeringReport,
    ValidationStatus,
    render_comparison_markdown,
    render_html,
    render_run_markdown,
)
from simforge.reporting.manifest import build_manifest
from simforge.services.app import SimForgeApp

from .conftest import EXAMPLES

GOLDEN = EXAMPLES / "1_0_golden_project"
FORBIDDEN = ("recommend", "should", "best", "worst", "optimal", "priority for improvement", "better choice",
             "preferred", "winner", "you must", "choose the")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    t = tmp_path_factory.mktemp("d")
    sf = SimForgeApp(workspace=t / "ws", library_dir=t / "lib", provider=None)
    p = sf.create_project("d report")
    sf.save_model(p, load_model(GOLDEN / "model.yaml"), "golden baseline")
    p.set_baseline(1)
    sf.approve_model(p, "eng")
    rb = sf.run_simulation(p, replications=3)
    eb = sf.evaluate_economics(p, rb.run_id)
    sf.save_model(p, load_model(GOLDEN / "alternative.yaml"), "alternative")
    ra = sf.run_simulation(p, replications=3)
    ea = sf.evaluate_economics(p, ra.run_id)
    rn = sf.run_simulation(p, replications=2)  # not evaluated, other replication count
    return sf, p, rb.run_id, ra.run_id, rn.run_id, eb.evaluation_id, ea.evaluation_id


def _strip_generated(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "generated_at"}


# ================================================================================ source equality
def test_run_report_reuses_the_workbench_exactly(env):
    sf, p, rb, *_ = env
    r = sf.engineering_report(p, rb)
    assert r.workbench.model_dump() == sf.results_workbench(p, rb).model_dump()
    run = p.load_run(rb)
    for v in r.workbench.overview:
        st = run.kpis.stats[v.metric]
        assert (v.mean, v.std, v.ci95_low, v.ci95_high, v.n) == (st.mean, st.std, st.ci95_low, st.ci95_high, st.n)
    md = render_run_markdown(r)
    tp = next(v for v in r.workbench.overview if v.metric == "throughput_per_hour")
    assert f"{tp.mean:.6g}" in md and f"{tp.ci95_low:.6g}" in md


def test_comparison_report_reuses_compare_runs_exactly(env):
    sf, p, rb, ra, *_ = env
    r = sf.comparison_report(p, rb, ra)
    assert r.physical.model_dump() == sf.compare_runs(p, rb, ra).model_dump()
    assert r.physical.comparison_mode == "PAIRED"
    m = r.physical.metric("units_completed")
    assert m.delta.mean == m.alternative_mean - m.baseline_mean or m.delta.mode == "PAIRED"
    md = render_comparison_markdown(r)
    assert f"{m.delta.mean:.6g}" in md and f"{m.delta.ci95_low:.6g}" in md and "delta = alternative - baseline" in md


def test_economics_sections_equal_the_stored_and_compared_economics(env):
    sf, p, rb, ra, _, eb, ea = env
    r = sf.comparison_report(p, rb, ra)
    assert r.economics.status == "AVAILABLE" and (r.economics.baseline_evaluation, r.economics.alternative_evaluation) == (eb, ea)
    ref = sf.compare_economics(p, eb, ea).to_dict()
    assert json.dumps(r.economics.comparison, sort_keys=True, default=str) == json.dumps(ref, sort_keys=True, default=str)
    md = render_comparison_markdown(r)
    assert ref["payback"]["status"] in md and ref["capex"]["status"] in md and ref["status"] in md
    run_r = sf.engineering_report(p, rb)
    ev = p.load_evaluation(eb)
    e = run_r.economics[0]
    assert (e.evaluation_id, e.status, e.currency, e.economic_hash) == (ev.evaluation_id, ev.status, ev.currency, ev.economic_hash)
    assert e.evaluated_total_cost == ev.totals["evaluated_total_cost"] and e.coverage == ev.coverage
    assert "evaluated_total_cost" in render_run_markdown(run_r)  # exact terminology, never "total cost"


# ================================================================================ missing / zero
def test_missing_economics_is_not_zero_and_explicit_selection(env):
    sf, p, rb, ra, rn, eb, ea = env
    r = sf.comparison_report(p, rb, rn)
    assert r.economics.status == "NOT_EVALUATED" and r.economics.comparison is None
    md = render_comparison_markdown(r)
    assert "NOT_EVALUATED" in md and "not a zero cost" in md
    assert sf.engineering_report(p, rn).economics == []
    assert "NOT_EVALUATED: no economic evaluation of this run" in render_run_markdown(sf.engineering_report(p, rn))
    wrong = sf.comparison_report(p, rb, ra, baseline_evaluation=ea, alternative_evaluation=eb)
    assert wrong.economics.status == "NOT_AVAILABLE" and "do not belong" in wrong.economics.reason


def test_missing_kpi_rendered_as_not_available_and_real_zero_as_zero(env):
    sf, p, rb, *_ = env
    r = sf.engineering_report(p, rb)
    ov = list(r.workbench.overview)
    ov[0] = KpiValue(metric="units_completed", scope="system", name="units_completed", label="Units completed",
                     unit="units", status="NOT_AVAILABLE")
    md = render_run_markdown(r.model_copy(update={"workbench": r.workbench.model_copy(update={"overview": ov})}))
    row = next(ln for ln in md.splitlines() if ln.startswith("| units_completed |"))
    assert "NOT_AVAILABLE" in row and "| 0 |" not in row
    nodes = next(t for t in r.workbench.tables if t.key == "nodes")
    test_down = next(rw for rw in nodes.rows if rw.entity == "test").values["down"]
    assert test_down.mean == 0.0 and "0.0 %" in render_run_markdown(r)  # a stored zero stays zero


# ================================================================================ validation, identity, manifest
def test_validation_status_always_present_and_never_promoted(env):
    sf, p, rb, ra, rn, *_ = env
    for md in (render_run_markdown(sf.engineering_report(p, rb)), render_comparison_markdown(sf.comparison_report(p, rb, ra))):
        assert "## Validation status" in md and "<h2>Validation status</h2>" in render_html(md, "x")
        for s in ("SYNTHETICALLY_VALIDATED", "NOT_REAL_DATA_VALIDATED", "NOT_EXECUTED"):
            assert s in md and s in render_html(md, "x")
    with pytest.raises(Exception):
        ValidationStatus(model_approval="APPROVED", real_data="REAL_DATA_VALIDATED")
    assert sf.engineering_report(p, rb).run.validation.model_approval == "APPROVED"
    assert sf.engineering_report(p, rn).run.validation.model_approval == "NOT_APPROVED"


def test_identity_and_deterministic_manifest(env):
    sf, p, rb, ra, *_ = env
    r1, r2 = sf.engineering_report(p, rb), sf.engineering_report(p, rb)
    assert _strip_generated(r1.model_dump()) == _strip_generated(r2.model_dump())
    assert r1.run.manifest == build_manifest(p, rb)
    run = p.load_run(rb)
    md = render_run_markdown(r1)
    for s in (rb, run.model_hash, run.engine_version, f"{run.horizon_s:.6g}", f"{run.warmup_s:.6g}",
              ", ".join(str(x) for x in run.seeds), p.meta.slug, "NO_BLOCK"):
        assert s in md
    c = sf.comparison_report(p, rb, ra)
    assert c.baseline.manifest == build_manifest(p, rb) and c.alternative.manifest == build_manifest(p, ra)
    assert c.baseline.identity.run_id == rb and c.alternative.identity.run_id == ra


# ================================================================================ products / setups, maintenance, provenance
def _project_with(sf, name, model):
    p = sf.create_project(name)
    sf.save_model(p, model, name)
    return p, sf.run_simulation(p).run_id


def test_products_setups_configuration_and_results_kept_apart(env):
    from .test_products_setups import full_model
    sf = env[0]
    p, rid = _project_with(sf, "prod", full_model())
    r = sf.engineering_report(p, rid)
    secs = {c.section for c in r.configuration}
    assert {"products", "setups"} <= secs
    setup_cfg = next(c for c in r.configuration if c.section == "setups")
    assert setup_cfg.facts["mode"] == "TARGET_DEPENDENT"
    md = render_run_markdown(r)
    assert "Configuration: setups (model version of the run, not a result)" in md
    assert "Setup transitions from -> to of this run: **NOT_AVAILABLE**" in md
    run = p.load_run(rid)
    st = next(t for t in r.workbench.tables if t.key == "setup")
    assert st.rows[0].values["setup_count"].mean == run.kpis.mean("node.m.setup_count")


def test_maintenance_report_values_equal_source(env):
    from .test_maintenance import full_model
    sf = env[0]
    p, rid = _project_with(sf, "maint", full_model())
    r = sf.engineering_report(p, rid)
    cfg = next(c for c in r.configuration if c.section == "maintenance")
    assert cfg.facts["failure_clock"] == "OPERATING_TIME" and cfg.facts["repair_resources"] == ["tech"]
    run = p.load_run(rid)
    mt = next(t for t in r.workbench.tables if t.key == "maintenance")
    for c in ("failure_count", "corrective_downtime_h"):
        assert mt.rows[0].values[c].mean == run.kpis.mean(f"node.{mt.rows[0].entity}.{c}")
    assert any(c.section == "calendars" for c in r.configuration)


def test_provenance_section_preserves_statuses(env):
    sf = env[0]
    link = {"dataset_id": "ds1", "dataset_version": 2, "content_hash": "abc", "source_file": "t.xlsx", "column": "T",
            "original_unit": "s", "basis": "PER_CIRCUIT", "n_used": 40, "decision": "FITTED", "decided_by": "ana",
            "decided_at": "2026-01-01T00:00:00Z"}
    m = load_model(GOLDEN / "model.yaml")
    m = set_value(m, "nodes.test.params.process_time",
                  {"dist": "constant", "value": 46, "unit": "s", "provenance": {"status": "measured", "source": "t.xlsx", "data": link}})
    m = set_value(m, "parameters", [{"id": "k", "value": None, "description": "required factor"}])
    p = sf.create_project("prov")
    sf.save_model(p, m, "prov")
    model = p.current_model()
    r_rows = __import__("simforge.reporting.engineering", fromlist=["provenance_rows"]).provenance_rows(model)
    by = {x.path: x for x in r_rows}
    meas = by["nodes.test.params.process_time"]
    assert (meas.status, meas.dataset, meas.basis, meas.decision) == ("measured", "ds1@2", "PER_CIRCUIT", "FITTED")
    assert by["parameters.k.value"].status == "MISSING"
    assert any(x.status == "assumed" for x in r_rows)  # golden economics rates are 'assumed'


# ================================================================================ language, html/markdown
def test_generated_report_language_has_no_prescription(env):
    sf, p, rb, ra, *_ = env
    for md in (render_run_markdown(sf.engineering_report(p, rb)), render_comparison_markdown(sf.comparison_report(p, rb, ra))):
        low = md.lower()
        assert not [w for w in FORBIDDEN if w in low]


def test_html_and_markdown_carry_the_same_critical_values(env):
    sf, p, rb, ra, *_ = env
    r = sf.comparison_report(p, rb, ra)
    md = render_comparison_markdown(r)
    html = render_html(md, "x")
    m = r.physical.metric("throughput_per_hour")
    for s in (rb, ra, f"{m.delta.mean:.6g}", r.physical.status, r.physical.comparison_mode, r.economics.status,
              r.economics.comparison["payback"]["status"]):
        assert s in md and s in html, s


# ================================================================================ no resimulation, immutability, export
def test_reports_never_simulate_nor_mutate(env, tmp_path, monkeypatch):
    sf, p, rb, ra, *_ = env
    tables = ("runs", "model_versions", "history", "economic_evaluations", "experiments")
    counts = [p.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables]
    stored = [p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (i,)).fetchone()[0] for i in (rb, ra)]
    evals = p.db.execute("SELECT * FROM economic_evaluations ORDER BY evaluation_id").fetchall()
    versions = [p.load_version(v.version).model_dump(mode="json") for v in p.versions()]
    from simforge.engine.des.engine import DesEngine
    import simforge.experiments.runner as runner
    calls = []
    monkeypatch.setattr(DesEngine, "run", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(runner, "run_simulation", lambda *a, **k: calls.append(1))
    paths = sf.export_engineering_report(p, sf.engineering_report(p, rb), tmp_path)
    paths2 = sf.export_engineering_report(p, sf.comparison_report(p, rb, ra), tmp_path)
    assert calls == []
    assert [p.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables] == counts
    assert [p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (i,)).fetchone()[0] for i in (rb, ra)] == stored
    assert [tuple(x) for x in p.db.execute("SELECT * FROM economic_evaluations ORDER BY evaluation_id").fetchall()] == [tuple(x) for x in evals]
    assert [p.load_version(v.version).model_dump(mode="json") for v in p.versions()] == versions
    for ps in (paths, paths2):
        assert {k: v.exists() for k, v in ps.items()} == {"markdown": True, "html": True, "json": True}
    RunEngineeringReport.model_validate_json(paths["json"].read_text(encoding="utf-8"))  # strict typed model


def test_existing_1_0_report_is_unchanged(env):
    sf, p, rb, *_ = env
    md = sf.generate_report(p, run_id=rb)["markdown"].read_text(encoding="utf-8")
    assert "## 9. Validation status" in md and "## Reproducibility" in md


# ================================================================================ CLI + UI
def test_cli_engineering_and_comparison_reports(env, tmp_path, monkeypatch):
    from simforge.cli import run_cli
    sf, p, rb, ra, *_ = env
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(sf.workspace.root))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(sf.library_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out = run_cli(["project", "engineering-report", p.meta.slug, rb, "-o", str(tmp_path)])
    assert code == 0 and (tmp_path / f"engineering_run_{rb}.md").exists(), out
    code, out = run_cli(["project", "comparison-report", p.meta.slug, rb, ra, "-o", str(tmp_path)])
    assert code == 0 and "economics: AVAILABLE" in out and (tmp_path / f"comparison_{rb}_vs_{ra}.html").exists()
    code, out = run_cli(["project", "comparison-report", p.meta.slug, rb, "missing", "-o", str(tmp_path)])
    assert code == 1 and "PERSISTENCE_ERROR" in out


def test_ui_report_tab_builds_engineering_reports_twelve_tabs(env, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest
    sf, p, rb, ra, *_ = env
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(sf.workspace.root))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(sf.library_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception and len(at.tabs) == 12
    next(s for s in at.selectbox if s.key == "er_run").select(rb).run()
    next(b for b in at.button if b.key == "er_run_btn").click().run()
    assert not at.exception and any("Run engineering report" in m.value for m in at.markdown)
    next(s for s in at.selectbox if s.key == "er_base").select(rb).run()
    next(s for s in at.selectbox if s.key == "er_alt").select(ra).run()
    next(b for b in at.button if b.key == "er_cmp_btn").click().run()
    assert not at.exception and any("Scenario comparison report" in m.value for m in at.markdown)
