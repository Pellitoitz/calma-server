"""1.1-C results workbench (C10), factual observations + Top-N (C11), KPI overlay on the graph (C13).

Runs are simulated ONCE by the fixtures (as a project would have stored them); the workbench itself must never
simulate, recompute or mutate anything.
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from simforge.analytics import workbench as W
from simforge.analytics.kpis import aggregate
from simforge.domain.io import load_model
from simforge.experiments.runner import SimulationResult, run_simulation
from simforge.library.registry import ComponentRegistry

from .conftest import EXAMPLES

GOLDEN = EXAMPLES / "1_0_golden_project"
FORBIDDEN = ("recommend", "should", "must improve", "best scenario", "worst scenario", "optimal", "optimiz",
             "priority for improvement", "needs improvement", "should increase", "should decrease", "bottleneck",
             "problem", "root cause", "improve", "better", "worse", "fix ", "action")


@pytest.fixture(scope="module")
def reg():
    return ComponentRegistry.load_default()


def R(per_rep, run_id="r1", seeds=None) -> SimulationResult:
    return SimulationResult(run_id=run_id, model_name="m", model_hash="h", component_versions={}, engine="simforge-des",
                            engine_version="0.9.0", app_version="1.0.0rc1",
                            seeds=seeds or [100 + i for i in range(len(per_rep))], started_at="2026-01-01T00:00:00+00:00",
                            wall_time_s=0.1, horizon_s=3600.0, warmup_s=0.0, kpis=aggregate(per_rep), per_replication=per_rep,
                            findings=[])


@pytest.fixture(scope="module")
def golden(reg):
    m = load_model(GOLDEN / "model.yaml")
    return m, run_simulation(m, reg)


@pytest.fixture(scope="module")
def setups_run(reg):
    from .test_products_setups import full_model
    m = full_model()
    return m, run_simulation(m, reg, replications=2)


@pytest.fixture(scope="module")
def maintenance_run(reg):
    from .test_maintenance import full_model
    m = full_model()
    return m, run_simulation(m, reg)


def _texts(wb: W.Workbench) -> list[str]:
    return [o.text for o in wb.observations] + [wb.note, wb.uncertainty] + wb.gaps


# ================================================================================ C10 KPI overview
def test_overview_values_are_the_stored_statistics(golden):
    m, run = golden
    wb = W.build_workbench(run, model=m)
    for v in wb.overview:
        st = run.kpis.stats[v.metric]
        assert (v.mean, v.n, v.std, v.ci95_low, v.ci95_high, v.min, v.max) == (st.mean, st.n, st.std, st.ci95_low,
                                                                               st.ci95_high, st.min, st.max)
        assert v.replications == [r[v.metric] for r in run.per_replication]
        assert v.unit == {"units_completed": "units", "throughput_per_hour": "units/h", "avg_lead_time_s": "s"}.get(v.metric, v.unit)
    assert wb.replications == 5 and wb.run.run_id == run.run_id and wb.run.model_hash == run.model_hash


def test_missing_is_not_available_real_zero_stays_zero_nan_is_undefined():
    run = R([{"units_completed": 0, "avg_lead_time_s": float("nan"), "node.a.blocked": 0.0, "node.b.blocked": 0.2,
              "node.b.starved": 0.1}])
    wb = W.build_workbench(run)
    o = {v.metric: v for v in wb.overview}
    assert o["units_completed"].status == "AVAILABLE" and o["units_completed"].mean == 0
    assert o["avg_lead_time_s"].status == "UNDEFINED" and o["avg_lead_time_s"].mean is None
    assert o["avg_wip"].status == "NOT_AVAILABLE" and o["avg_wip"].mean is None and o["avg_wip"].n == 0
    nodes = next(t for t in wb.tables if t.key == "nodes")
    a = next(r for r in nodes.rows if r.entity == "a")
    assert a.values["blocked"].mean == 0.0 and a.values["blocked"].status == "AVAILABLE"
    assert a.values["starved"].status == "NOT_AVAILABLE" and a.values["starved"].mean is None  # missing != 0


def test_single_replication_has_no_fake_std_or_ci():
    wb = W.build_workbench(R([{"units_completed": 7}]))
    v = wb.overview[0]
    assert v.n == 1 and v.std is None and v.ci95_low is None and v.ci95_high is None
    assert "Single replication" in wb.uncertainty


def test_replication_values_mean_std_ci_from_stored_run():
    run = R([{"units_completed": 10}, {"units_completed": 20}, {"units_completed": 30}])
    v = W.kpi(run, "units_completed")
    st = run.kpis.stats["units_completed"]
    assert v.replications == [10, 20, 30] and v.mean == 20 and v.std == pytest.approx(10)
    assert (v.ci95_low, v.ci95_high) == (st.ci95_low, st.ci95_high) and v.ci95_low < 20 < v.ci95_high


def test_serialisation_is_deterministic(golden):
    m, run = golden
    a, b = W.build_workbench(run, model=m), W.build_workbench(run, model=m)
    assert a.model_dump_json() == b.model_dump_json()
    W.Workbench.model_validate_json(a.model_dump_json())  # strict round trip


# ================================================================================ C10 tables
def test_node_and_resource_tables_follow_model_order_and_stored_values(golden):
    m, run = golden
    wb = W.build_workbench(run, model=m)
    nodes = next(t for t in wb.tables if t.key == "nodes")
    assert [r.entity for r in nodes.rows] == [n.id for n in m.nodes if any(k.startswith(f"node.{n.id}.") and
                                                                          k.split(".")[-1] in W.NODE_STATE for k in run.kpis.stats)]
    for row in nodes.rows:
        for c, v in row.values.items():
            key = f"node.{row.entity}.{c}"
            assert (v.mean == run.kpis.stats[key].mean) if key in run.kpis.stats else v.status == "NOT_AVAILABLE"
    res = next(t for t in wb.tables if t.key == "resources")
    assert [r.entity for r in res.rows] == ["operator"]
    assert res.rows[0].values["utilization"].mean == run.kpis.mean("resource.operator.utilization")
    assert res.rows[0].values["working_h"].unit == "h"
    queues = next(t for t in wb.tables if t.key == "queues")
    buf = next(r for r in queues.rows if r.entity == "buffer")
    assert buf.values["avg_content"].mean == run.kpis.mean("node.buffer.avg_content")
    assert next(r for r in queues.rows if r.entity == "test").values["avg_content"].status == "NOT_AVAILABLE"
    assert not any(t.key in ("setup", "maintenance", "calendar_nodes", "products") for t in wb.tables)  # no empty sections


def test_setup_section_shows_only_stored_setup_metrics(setups_run):
    m, run = setups_run
    wb = W.build_workbench(run, model=m)
    setup = next(t for t in wb.tables if t.key == "setup")
    assert [r.entity for r in setup.rows] == ["m"]
    assert setup.rows[0].values["setup_count"].mean == run.kpis.mean("node.m.setup_count")
    assert {v.metric for v in wb.system_setup} <= set(W.SETUP_SYSTEM) and wb.system_setup
    assert next(t for t in wb.tables if t.key == "products").rows
    assert any("from -> to" in g for g in wb.gaps)  # transitions are a declared PHYSICAL_KPI_GAP, not invented


def test_maintenance_and_calendar_sections_show_stored_values(maintenance_run):
    m, run = maintenance_run
    wb = W.build_workbench(run, model=m)
    mt = next(t for t in wb.tables if t.key == "maintenance")
    row = mt.rows[0]
    assert row.values["failure_count"].mean == run.kpis.mean(f"node.{row.entity}.failure_count")
    assert row.values["corrective_downtime_h"].unit == "h"
    cal = next(t for t in wb.tables if t.key == "calendar_nodes")
    r0 = cal.rows[0]
    for c in ("planned_available_h", "break_h", "off_shift_h"):
        if c in r0.values and r0.values[c].status == "AVAILABLE":
            assert r0.values[c].mean == run.kpis.mean(f"node.{r0.entity}.{c}")
    # the calendar of this fixture gates the node only: no resource calendar metric is stored -> no (empty) section
    assert not any(k.startswith("resource.") and k.endswith("planned_available_h") for k in run.kpis.stats)
    assert not any(t.key == "calendar_resources" for t in wb.tables)


def test_resource_calendar_section_from_stored_values():
    run = R([{"resource.op.planned_available_h": 7.25, "resource.op.break_h": 0.75, "resource.op.utilization": 0.5}])
    cal = next(t for t in W.build_workbench(run).tables if t.key == "calendar_resources")
    assert cal.columns == ["planned_available_h", "break_h"] and cal.rows[0].values["break_h"].mean == 0.75


# ================================================================================ C11 Top-N + observations
TOP = R([{"node.a.blocked": 0.3, "node.b.blocked": 0.5, "node.c.blocked": 0.3, "node.d.blocked": 0.1,
          "node.e.starved": 0.2, "node.f.blocked": float("nan")}])


def test_top_n_descending_ascending_ties_and_exclusions():
    d = W.top_n(TOP, "node", "blocked", 3)
    assert [(i.position, i.entity, i.value) for i in d.items] == [(1, "b", 0.5), (2, "a", 0.3), (3, "c", 0.3)]  # tie: id asc
    assert d.order == "descending" and "entity id" in d.tie_break
    assert d.excluded == ["e", "f"]  # e: not stored, f: undefined -> listed, never treated as 0
    a = W.top_n(TOP, "node", "blocked", 2, order="ascending")
    assert [i.entity for i in a.items] == ["d", "a"]
    big = W.top_n(TOP, "node", "blocked", 50)
    assert len(big.items) == 4
    with pytest.raises(ValueError):
        W.top_n(TOP, "node", "blocked", 0)


def test_top_n_has_no_evaluative_fields():
    keys = set(json.loads(W.top_n(TOP, "node", "blocked", 3).model_dump_json()).keys())
    item_keys = set(W.TopNItem.model_fields)
    assert not {k for k in keys | item_keys if any(w in k for w in ("priority", "severity", "score", "rank", "best", "worst"))}


def test_observations_are_deterministic_traceable_and_factual(golden):
    m, run = golden
    obs = W.observations(run, [n.id for n in m.nodes])
    assert obs == W.observations(run, [n.id for n in m.nodes])
    for o in obs:
        v = W.top_n(run, o.scope, o.metric, 10_000, entities=[n.id for n in m.nodes])
        assert o.value == v.items[0].value and o.run_id == run.run_id and run.run_id in o.text
        assert o.template.startswith(("highest_", "equal_"))
        if o.template.startswith("highest_"):
            assert all(e in o.text for e in o.entities)
        else:
            assert f"All {len(v.items)} " in o.text and len(o.entities) == len(v.items)
    util = next(o for o in obs if o.metric == "utilization")
    assert util.entities == ["test"] and "90.6 %" in util.text


def test_ties_and_all_equal_wording():
    run = R([{"node.a.down": 0.0, "node.b.down": 0.0, "node.a.blocked": 0.4, "node.b.blocked": 0.4, "node.c.blocked": 0.1}])
    obs = {o.metric: o for o in W.observations(run)}
    assert obs["down"].template == "equal_node_down" and obs["down"].text.startswith("All 2 nodes")
    assert obs["blocked"].entities == ["a", "b"] and "a and b recorded the highest" in obs["blocked"].text


@pytest.mark.parametrize("fixture", ["golden", "setups_run", "maintenance_run"])
def test_generated_language_has_no_recommendation_or_causality(request, fixture):
    m, run = request.getfixturevalue(fixture)
    for t in _texts(W.build_workbench(run, model=m)):
        low = t.lower()
        assert not [w for w in FORBIDDEN if w in low], t


# ================================================================================ C13 graph overlay
def test_graph_overlay_maps_stored_values_to_the_run_model(golden):
    m, run = golden
    ov = W.graph_overlay(run, m, "utilization")
    assert [x.node for x in ov.nodes] == [n.id for n in m.nodes] and ov.run_id == run.run_id
    by = {x.node: x for x in ov.nodes}
    assert by["test"].value == run.kpis.mean("node.test.utilization") and by["test"].text.endswith("%")
    assert by["buffer"].status == "NOT_AVAILABLE" and by["buffer"].value is None and by["buffer"].text == "NOT_AVAILABLE"
    zero = W.graph_overlay(run, m, "down")
    assert {x.node: x.value for x in zero.nodes}["test"] == 0.0  # a real stored zero stays 0
    other = m.model_copy(update={"nodes": m.nodes[:-1]})
    with pytest.raises(ValueError, match="no es el del run"):
        W.graph_overlay(run, other, "utilization")  # never mixes a model with another run's evidence


def test_overlay_dot_is_text_only_without_colour_semantics(golden):
    from simforge.ui.views import process_graph
    m, run = golden
    ov = W.graph_overlay(run, m, "utilization")
    dot = process_graph(m, overlay={x.node: f"utilization: {x.text}" for x in ov.nodes})
    assert "utilization: 90.6 %" in dot and "utilization: NOT_AVAILABLE" in dot
    assert process_graph(m) != dot and "#cf222e" not in dot  # no red/green added by the overlay


# ================================================================================ no resimulation, immutability
def test_workbench_never_simulates_and_never_mutates(tmp_path, monkeypatch, reg):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("wb")
    sf.save_model(p, load_model(GOLDEN / "model.yaml"), "golden")
    rid = sf.run_simulation(p).run_id
    stored = p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (rid,)).fetchone()[0]
    model_before = copy.deepcopy(p.current_model().model_dump(mode="json"))
    counts = [p.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "model_versions", "history")]
    from simforge.engine.des.engine import DesEngine
    import simforge.experiments.runner as runner
    calls = []
    monkeypatch.setattr(DesEngine, "run", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(runner, "run_simulation", lambda *a, **k: calls.append(1))
    wb = sf.results_workbench(p, rid)
    ov, _ = sf.graph_overlay(p, rid, "utilization")
    W.top_n(p.load_run(rid), "node", "blocked")
    assert calls == [] and wb.observations and ov.nodes
    assert p.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (rid,)).fetchone()[0] == stored
    assert p.current_model().model_dump(mode="json") == model_before
    assert [p.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "model_versions", "history")] == counts


def test_build_does_not_mutate_the_run_object(golden):
    m, run = golden
    before = json.dumps(run.to_dict(), sort_keys=True, default=str)
    W.build_workbench(run, model=m)
    W.graph_overlay(run, m, "blocked")
    assert json.dumps(run.to_dict(), sort_keys=True, default=str) == before
    assert not math.isnan(run.kpis.mean("units_completed"))


# ================================================================================ UI
def test_ui_workbench_in_run_tab_keeps_twelve_tabs(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("wb ui")
    sf.save_model(p, load_model(GOLDEN / "model.yaml"), "golden")
    rid = sf.run_simulation(p, replications=2).run_id
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception and len(at.tabs) == 12
    assert any(m.value == "### Results workbench" for m in at.markdown)
    assert any(rid in c.value and "replication(s)" in c.value for c in at.caption)
    texts = [x.value for x in at.markdown if x.value.startswith("- ")]
    assert any("recorded the highest stored value of Utilization" in t for t in texts)
    next(s for s in at.selectbox if s.key == "wb_ov_metric").select("blocked").run()
    assert not at.exception
    next(s for s in at.selectbox if s.key == "wb_top_metric").select("starved").run()
    assert not at.exception
    gen = [x.value for x in at.markdown if x.value.startswith("- ") and "recorded" in x.value]
    assert not [t for t in gen if any(w in t.lower() for w in FORBIDDEN)]
