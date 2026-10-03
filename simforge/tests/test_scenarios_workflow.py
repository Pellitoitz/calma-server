"""1.1-A scenario workflow: baseline -> clone -> modify -> verify -> approve -> run -> compare (service, CLI, UI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simforge.cli import run_cli
from simforge.domain.io import load_model
from simforge.domain.paths import PathError, set_value
from simforge.persistence.project import ProjectError
from simforge.services.app import ApprovalRequired, SimForgeApp

from .conftest import EXAMPLES

OP = "resources.operator_1.quantity"


def _model(ai: bool = False, reps: int = 2):
    m = set_value(load_model(EXAMPLES / "02_shared_operator.yaml"), "simulation.replications", reps)
    if ai:
        m = m.model_copy(update={"meta": m.meta.model_copy(update={"origin": "ai_generated"})})
    return m


@pytest.fixture()
def sf(tmp_path) -> SimForgeApp:
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


def _project(sf, ai: bool = False, approve: bool = False):
    p = sf.create_project("scn")
    sf.save_model(p, _model(ai), "init")
    if approve:
        sf.approve_model(p, "eng")
    p.set_baseline(p.meta.current_version)
    return p


def _table_counts(p) -> dict[str, int]:
    return {t: p.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("model_versions", "runs", "experiments", "history", "economic_evaluations")}


# 1 ---------------------------------------------------------------------------------------- lineage
def test_clone_preserves_lineage_and_becomes_current(sf):
    p = _project(sf)
    base = p.meta.baseline_version
    v = sf.clone_scenario(p, "two_ops", {OP: 2})
    info = {x.version: x for x in p.versions()}[v]
    assert info.parent == base and info.label == "scenario:two_ops"
    assert p.meta.scenarios == {"two_ops": v} and p.meta.current_version == v
    assert p.load_version(v).resource("operator_1").quantity == 2
    assert [c[0] for c in sf.compare_versions(p, base, v)] == [OP]
    assert any(h["action"] == "clone_scenario" for h in p.history())


def test_clone_from_explicit_version_records_that_parent(sf):
    p = _project(sf)
    v1 = sf.clone_scenario(p, "a", {OP: 2})
    v2 = sf.clone_scenario(p, "b", {"simulation.base_seed": 7}, from_version=v1)
    assert {x.version: x.parent for x in p.versions()}[v2] == v1
    assert p.load_version(v2).resource("operator_1").quantity == 2


# 2-4 -------------------------------------------------------------------------------------- approval contract
def test_modification_invalidates_approval_and_unchanged_clone_keeps_it(sf):
    p = _project(sf, approve=True)
    base = p.load_version(p.meta.baseline_version)
    assert base.is_approved
    changed = p.load_version(sf.clone_scenario(p, "changed", {OP: 2}))
    same = p.load_version(sf.clone_scenario(p, "same", {}))
    assert not changed.is_approved  # approval is bound to the content hash: never carried over to new content
    assert same.is_approved and same.content_hash() == base.content_hash()


def test_unapproved_changed_scenario_cannot_bypass_the_run_gate(sf):
    p = _project(sf, ai=True)  # AI-generated model: needs one engineer approval before running (1.0 rule)
    v = sf.clone_scenario(p, "two_ops", {OP: 2})
    model = p.load_version(v)
    assert sf.approval_pending(p, model)
    n_runs = len(p.runs())
    with pytest.raises(ApprovalRequired):
        sf.run_simulation(p, model)
    assert len(p.runs()) == n_runs


def test_approved_scenario_runs_and_scenario_moves_to_approved_version(sf):
    p = _project(sf, ai=True)
    v = sf.clone_scenario(p, "two_ops", {OP: 2})
    va = sf.approve_model(p, "eng")  # the scenario is current: the existing approval mechanism, nothing new
    assert p.meta.scenarios["two_ops"] == va and {x.version: x.parent for x in p.versions()}[va] == v
    m = p.load_version(va)
    assert m.is_approved and m.content_hash() == p.load_version(v).content_hash()
    res = sf.run_simulation(p, m)
    assert res.model_hash == m.content_hash()
    assert p.scenario_of(va) == "two_ops"


# 5-6 -------------------------------------------------------------------------------------- baseline untouched
def test_baseline_is_never_modified(sf):
    p = _project(sf, approve=True)
    b = p.meta.baseline_version
    path = p.root / f"versions/v{b:04d}.yaml"
    raw, h = path.read_bytes(), p.load_version(b).content_hash()
    sf.clone_scenario(p, "s", {OP: 2})
    sf.modify_scenario(p, "s", {OP: 3})
    sf.approve_model(p, "eng")
    sf.run_simulation(p)
    assert path.read_bytes() == raw and p.load_version(b).content_hash() == h and p.meta.baseline_version == b
    assert p.load_version(b).resource("operator_1").quantity == 1


def test_modify_scenario_creates_new_version_with_parent_head(sf):
    p = _project(sf)
    v1 = sf.clone_scenario(p, "s", {OP: 2})
    v2 = sf.modify_scenario(p, "s", {OP: 3})
    assert p.meta.scenarios["s"] == v2 and {x.version: x.parent for x in p.versions()}[v2] == v1
    assert p.load_version(v1).resource("operator_1").quantity == 2  # versions stay immutable
    with pytest.raises(ProjectError, match="Sin cambios"):
        sf.modify_scenario(p, "s", {OP: 3})


# 7 ---------------------------------------------------------------------------------------- comparison of scenario runs
def test_scenario_runs_compare_paired_with_identity(sf):
    p = _project(sf)
    rb = sf.run_simulation(p)
    sf.clone_scenario(p, "two_ops", {OP: 2})
    ra = sf.run_simulation(p)
    c = sf.compare_runs(p, rb.run_id, ra.run_id)
    assert c.comparison_mode == "PAIRED" and c.status == "COMPARABLE"
    assert c.baseline.is_baseline_version and c.alternative.scenario == "two_ops"
    m = c.metric("units_completed")
    assert m.baseline_mean == rb.kpis.mean("units_completed") and m.alternative_mean == ra.kpis.mean("units_completed")
    assert m.delta.mean == pytest.approx(ra.kpis.mean("units_completed") - rb.kpis.mean("units_completed"))


def test_scenario_with_other_horizon_is_not_comparable(sf):
    p = _project(sf)
    rb = sf.run_simulation(p)
    sf.clone_scenario(p, "short", {"simulation.horizon.value": 4})
    ra = sf.run_simulation(p)
    c = sf.compare_runs(p, rb.run_id, ra.run_id)
    assert c.status == "NOT_COMPARABLE" and all(m.delta is None for m in c.metrics)


def test_demand_change_is_flagged_from_the_model_versions(sf):
    p = _project(sf)
    rb = sf.run_simulation(p)
    sf.clone_scenario(p, "demand", {"nodes.src.params.max_entities": 50})
    ra = sf.run_simulation(p)
    c = sf.compare_runs(p, rb.run_id, ra.run_id)
    assert any(x.check == "demand" and x.level == "WARNING" for x in c.checks)
    assert c.status == "COMPARABLE_WITH_WARNINGS" and c.metric("units_completed").delta is not None


# 8 ---------------------------------------------------------------------------------------- same contracts in CLI and service
def test_cli_and_service_clone_produce_the_same_model(sf, tmp_path, monkeypatch):
    p = _project(sf)
    v = sf.clone_scenario(p, "two_ops", {OP: 2})
    ws2 = tmp_path / "ws2"
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(ws2))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "m.yaml"
    from simforge.domain.io import dump_model
    f.write_text(dump_model(_model()), encoding="utf-8")
    assert run_cli(["project", "new", "cli", "--model", str(f)])[0] == 0
    assert run_cli(["project", "baseline", "cli"])[0] == 0
    code, out = run_cli(["project", "scenario-clone", "cli", "two_ops", "--set", f"{OP}=2"])
    assert code == 0, out
    p2 = SimForgeApp(workspace=ws2, library_dir=tmp_path / "lib", provider=None).open_project("cli")
    assert p2.load_version(p2.meta.scenarios["two_ops"]).content_hash() == p.load_version(v).content_hash()


# 9 ---------------------------------------------------------------------------------------- controlled errors
def test_controlled_errors(sf):
    p = sf.create_project("nob")
    sf.save_model(p, _model(), "init")
    with pytest.raises(ProjectError, match="baseline"):
        sf.clone_scenario(p, "x", {OP: 2})
    p.set_baseline(1)
    with pytest.raises(ProjectError, match="nombre"):
        sf.clone_scenario(p, "  ", {})
    with pytest.raises(PathError):
        sf.clone_scenario(p, "x", {"resources.nope.quantity": 2})
    assert "x" not in p.meta.scenarios and len(p.versions()) == 1  # nothing saved on a failed clone
    sf.clone_scenario(p, "x", {OP: 2})
    with pytest.raises(ProjectError, match="ya existe"):
        sf.clone_scenario(p, "x", {OP: 3})
    with pytest.raises(ProjectError, match="No existe el escenario"):
        sf.modify_scenario(p, "nope", {OP: 3})
    r = sf.run_simulation(p)
    with pytest.raises(ProjectError, match="No existe la ejecución"):
        sf.compare_runs(p, r.run_id, "missing")
    with pytest.raises(ProjectError):
        sf.compare_runs(p, "missing", r.run_id)


# 10 / 14-15 ------------------------------------------------------------------------------- no side effects, no simulation, hashes
def test_comparison_has_no_persistence_side_effects_and_never_simulates(sf, monkeypatch):
    p = _project(sf)
    rb = sf.run_simulation(p)
    sf.clone_scenario(p, "two_ops", {OP: 2})
    ra = sf.run_simulation(p)
    counts, meta = _table_counts(p), (p.root / "project.json").read_text()
    hashes = [p.load_version(v.version).content_hash() for v in p.versions()]
    stored = [p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (i,)).fetchone()[0] for i in (rb.run_id, ra.run_id)]
    from simforge.engine.des.engine import DesEngine
    import simforge.experiments.runner as runner

    def boom(*a, **k):
        raise AssertionError("the comparator must not simulate")
    monkeypatch.setattr(DesEngine, "run", boom)
    monkeypatch.setattr(runner, "run_simulation", boom)
    c = sf.compare_runs(p, rb.run_id, ra.run_id)
    assert c.status == "COMPARABLE"
    assert _table_counts(p) == counts and (p.root / "project.json").read_text() == meta
    assert [p.load_version(v.version).content_hash() for v in p.versions()] == hashes
    assert [p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (i,)).fetchone()[0]
            for i in (rb.run_id, ra.run_id)] == stored
    assert c.baseline.model_hash == rb.model_hash and c.alternative.model_hash == ra.model_hash


def test_experiment_deltas_from_project(sf):
    from simforge.domain.isms import ExperimentSpec, Factor
    p = _project(sf)
    exp = sf.run_experiment(p, ExperimentSpec(name="e", factors=[Factor(path=OP, values=[1, 2])], replications=2))
    d = sf.experiment_deltas(p, exp.experiment_id, 0, ["units_completed"])
    s1 = d.scenarios[1].comparison.metric("units_completed")
    r0, r1 = (s.result for s in exp.scenarios)
    assert s1.delta.mode == "PAIRED"
    assert s1.delta.mean == pytest.approx(r1.kpis.mean("units_completed") - r0.kpis.mean("units_completed"))


# CLI ------------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def cli_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "m.yaml"
    from simforge.domain.io import dump_model
    f.write_text(dump_model(_model()), encoding="utf-8")
    for argv in (["project", "new", "c", "--model", str(f)], ["project", "baseline", "c"], ["project", "run", "c"],
                 ["project", "scenario-clone", "c", "two_ops", "--set", f"{OP}=2"], ["project", "run", "c"]):
        code, out = run_cli(argv)
        assert code == 0, out
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.open_project("c")
    runs = sorted(p.runs(), key=lambda r: r["model_version"])
    return sf, p, runs[0]["run_id"], runs[1]["run_id"]


def test_cli_compare_runs_happy_path_and_stable_output(cli_ws):
    _, _, b, a = cli_ws
    code, out = run_cli(["project", "compare-runs", "c", b, a])
    assert code == 0, out
    assert "PAIRED" in out and "delta = alternative - baseline" in out and "scenario 'two_ops'" in out
    assert "units_completed" in out and "does not rank" in out
    assert run_cli(["project", "compare-runs", "c", b, a]) == (code, out)
    j1, j2 = run_cli(["project", "compare-runs", "c", b, a, "--json"]), run_cli(["project", "compare-runs", "c", b, a, "--json"])
    assert j1 == j2 and json.loads(j1[1])["comparison_mode"] == "PAIRED"
    code, out = run_cli(["project", "compare-runs", "c", b, a, "--metric", "avg_wip"])
    assert code == 0 and "avg_wip" in out and "units_completed " not in out


@pytest.mark.parametrize("side", [0, 1])
def test_cli_compare_runs_invalid_run(cli_ws, side):
    _, _, b, a = cli_ws
    args = [b, "missing"] if side else ["missing", a]
    code, out = run_cli(["project", "compare-runs", "c", *args])
    assert code == 1 and "PERSISTENCE_ERROR" in out and "missing" in out and "Traceback" not in out


def test_cli_compare_runs_unpaired_and_not_comparable(cli_ws):
    sf, p, b, _ = cli_ws
    assert run_cli(["project", "run", "c", "--reps", "3"])[0] == 0
    r3 = next(r["run_id"] for r in p.runs() if r["replications"] == 3)
    code, out = run_cli(["project", "compare-runs", "c", b, r3])
    assert code == 0 and "mode: UNPAIRED" in out and "replications differ" in out
    assert run_cli(["project", "scenario-clone", "c", "short", "--set", "simulation.horizon.value=4"])[0] == 0
    assert run_cli(["project", "run", "c"])[0] == 0
    v_short = sf.open_project("c").meta.scenarios["short"]
    short = next(r["run_id"] for r in p.runs() if r["model_version"] == v_short)
    code, out = run_cli(["project", "compare-runs", "c", b, short])
    assert code == 1 and "NOT_COMPARABLE" in out and "HARD_INCOMPATIBILITY" in out


def test_cli_scenarios_set_and_errors(cli_ws):
    code, out = run_cli(["project", "scenario-set", "c", "two_ops", "--set", f"{OP}=3"])
    assert code == 0, out
    code, out = run_cli(["project", "scenarios", "c"])
    assert code == 0 and "two_ops" in out and "baseline: v1" in out
    code, out = run_cli(["project", "scenario-clone", "c", "two_ops", "--set", f"{OP}=2"])
    assert code == 1 and "ya existe" in out
    code, out = run_cli(["project", "scenario-clone", "c", "bad", "--set", "resources.nope.quantity=2"])
    assert code == 1 and "MODEL_VALIDATION_ERROR" in out
    code, out = run_cli(["project", "scenario-clone", "c", "bad", "--set", "novalue"])
    assert code == 2


def test_cli_project_experiment_prints_deltas_in_order(cli_ws):
    code, out = run_cli(["project", "experiment", "c", "--factor", f"{OP}=1,2", "--reps", "2"])
    assert code == 0, out
    assert out.index("#0 (reference)") < out.index("#1 ") and "Δ +0" in out
    assert not any(w in out.lower() for w in ("best", "winner", "recommended", "optimal"))


def test_cli_project_experiment_respects_approval_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "m.yaml"
    from simforge.domain.io import dump_model
    f.write_text(dump_model(_model(ai=True)), encoding="utf-8")
    assert run_cli(["project", "new", "g", "--model", str(f)])[0] == 0
    code, out = run_cli(["project", "experiment", "g", "--factor", f"{OP}=1,2"])
    assert code == 1 and "ENGINEER_DECISION_REQUIRED" in out


# UI -------------------------------------------------------------------------------------------------------------------
def _ui(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception
    return at


def _btn(at, key):
    return next(b for b in at.button if b.key == key)


def test_ui_scenario_workflow_clone_approve_run_compare(tmp_path, monkeypatch):
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = _project(sf, ai=True)
    p_slug = p.meta.slug
    at = _ui(tmp_path, monkeypatch)
    assert any("Baseline v1" in c.value for c in at.caption)
    # clone with one change
    next(t for t in at.text_input if t.key == "scn_name").input("two_ops").run()
    next(s for s in at.selectbox if s.key == "scn_clone_p0").select(OP).run()
    next(t for t in at.text_input if t.key == "scn_clone_v0").input("2").run()
    _btn(at, "scn_clone_btn").click().run()
    assert not at.exception
    p = sf.open_project(p_slug)
    v = p.meta.scenarios["two_ops"]
    assert p.load_version(v).resource("operator_1").quantity == 2
    # AI-origin model: the run gate holds until the engineer approves (same rule as the Run tab)
    assert _btn(at, "scn_run").disabled
    next(t for t in at.text_input if t.key == "scn_approver").input("ana").run()
    _btn(at, "scn_approve").click().run()
    assert not at.exception
    p = sf.open_project(p_slug)
    assert p.load_version(p.meta.scenarios["two_ops"]).is_approved
    assert not _btn(at, "scn_run").disabled
    _btn(at, "scn_run").click().run()
    assert not at.exception and any("COMPLETED" in s.value for s in at.success)


def test_ui_comparison_rendering_and_wording(tmp_path, monkeypatch):
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = _project(sf)
    rb = sf.run_simulation(p)
    sf.clone_scenario(p, "two_ops", {OP: 2})
    ra = sf.run_simulation(p)
    at = _ui(tmp_path, monkeypatch)
    assert next(s for s in at.selectbox if s.key == "scn_cmp_base").value == rb.run_id
    assert next(s for s in at.selectbox if s.key == "scn_cmp_alt").value == ra.run_id
    assert any("COMPARABLE · mode PAIRED" in s.value for s in at.success)
    tab = at.tabs[11]  # Project tab hosts the scenario workflow (RC1 tab count unchanged)
    texts = [x.value for x in tab.caption] + [x.value for x in tab.markdown] + [x.value for x in tab.success]
    assert any("delta = alternative - baseline" in t for t in texts)
    assert not [t for t in texts if any(w in t.lower() for w in ("best", "winner", "recommended", "optimal", "superior"))]
    # a hard incompatibility is shown as an error, not as deltas
    sf.clone_scenario(p, "short", {"simulation.horizon.value": 4})
    rs = sf.run_simulation(p)
    at.run()
    next(s for s in at.selectbox if s.key == "scn_cmp_alt").select(rs.run_id).run()
    assert not at.exception and any("NOT_COMPARABLE" in e.value for e in at.error)


def test_ui_experiment_deltas_table(tmp_path, monkeypatch):
    from simforge.domain.isms import ExperimentSpec, Factor
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = _project(sf)
    sf.run_experiment(p, ExperimentSpec(name="e", factors=[Factor(path=OP, values=[1, 2])], replications=2))
    at = _ui(tmp_path, monkeypatch)
    assert any(s.key == "exp_ref" for s in at.selectbox)
    assert any("delta = scenario - reference scenario" in c.value for c in at.caption)
