"""Scenarios tab (1.1-A): baseline -> clone -> modify -> verify -> approve -> run -> compare.

Every action calls the application service (same contracts as the CLI). The comparison is computed on demand from
stored runs; it describes deltas and never ranks or recommends.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ..analytics.run_comparison import HEADLINE_METRICS, PhysicalComparison
from ..persistence.project import Project
from ..services.app import SimForgeApp
from .views import _numeric_paths, issues_table


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _changes_form(model, prefix: str) -> dict[str, object]:
    paths = _numeric_paths(model)
    n = int(st.number_input("Number of changes", 0, 5, 1, key=f"{prefix}_n"))
    changes: dict[str, object] = {}
    for i in range(n):
        c1, c2 = st.columns([2, 1])
        path = c1.selectbox(f"Parameter {i + 1}", paths, key=f"{prefix}_p{i}")
        txt = c2.text_input(f"New value {i + 1}", key=f"{prefix}_v{i}", placeholder="e.g. 2 or 1.5")
        if path and txt.strip():
            changes[path] = _value(txt.strip())
    return changes


def comparison_frame(c: PhysicalComparison, show_all: bool = False) -> pd.DataFrame:
    rows = []
    for m in c.metrics:
        if not show_all and m.metric not in HEADLINE_METRICS and not m.metric.endswith(".utilization"):
            continue
        d = m.delta
        rows.append({"metric": m.metric, "label": m.label, "unit": m.unit, "baseline": m.baseline_mean,
                     "alternative": m.alternative_mean, "delta (alt - base)": d.mean if d else None,
                     "CI95 low": d.ci95_low if d else None, "CI95 high": d.ci95_high if d else None,
                     "n": d.n if d else None, "status": m.status, "reason": m.reason or ""})
    return pd.DataFrame(rows)


def show_comparison(c: PhysicalComparison, key: str) -> None:
    show = {"COMPARABLE": st.success, "COMPARABLE_WITH_WARNINGS": st.warning, "NOT_COMPARABLE": st.error}[c.status]
    show(f"{c.status} · mode {c.comparison_mode}")
    st.caption(c.delta_convention)
    for side, i in (("Baseline", c.baseline), ("Alternative", c.alternative)):
        tag = f"v{i.model_version}" if i.model_version is not None else "unsaved model"
        tag += f" · scenario '{i.scenario}'" if i.scenario else (" · baseline version" if i.is_baseline_version else "")
        st.caption(f"{side}: run `{i.run_id}` · {tag} · hash `{i.model_hash}` · {i.engine} {i.engine_version} · "
                   f"horizon {i.horizon_s:g} s · warm-up {i.warmup_s:g} s · {i.replications} rep · seeds {i.seeds}")
    for e in c.pairing_evidence:
        st.caption(f"pairing: {e}")
    for ch in c.checks:
        {"HARD_INCOMPATIBILITY": st.error, "WARNING": st.warning}.get(ch.level, st.info)(f"[{ch.level}] {ch.check}: {ch.detail}")
    show_all = st.checkbox("Show all metrics", key=f"{key}_all")
    st.dataframe(comparison_frame(c, show_all), hide_index=True, width="stretch")
    st.download_button("Export comparison (JSON)", c.model_dump_json(indent=2), key=f"{key}_dl",
                       file_name=f"comparison_{c.baseline.run_id}_{c.alternative.run_id}.json")
    st.caption(c.note)


def scenarios_tab(app: SimForgeApp, project: Project) -> None:
    st.caption("Baseline → clone → modify → verify → approve → run → compare. Comparisons are facts (delta = "
               "alternative − baseline); SimForge does not rank or recommend scenarios.")
    versions = [v.version for v in project.versions()]
    if not versions:
        st.info("No model yet.")
        return
    base = project.meta.baseline_version
    st.markdown("#### 1 · Baseline")
    if base is None:
        st.info("Choose the baseline version: scenarios are derived from it.")
        pick = st.selectbox("Baseline version", versions, index=len(versions) - 1, key="scn_base_pick")
        if st.button("SET BASELINE", key="scn_set_base"):
            project.set_baseline(pick)
            st.rerun()
        return
    bm = project.load_version(base)
    st.caption(f"Baseline v{base} · hash `{bm.content_hash()}` · approved: {'YES' if bm.is_approved else 'NO'}")

    st.markdown("#### 2 · Clone a scenario")
    name = st.text_input("Scenario name", key="scn_name")
    src = st.selectbox("Clone from version", versions, index=versions.index(base), key="scn_from")
    changes = _changes_form(project.load_version(src), "scn_clone")
    if st.button("CLONE SCENARIO", key="scn_clone_btn", disabled=not name.strip()):
        try:
            v = app.clone_scenario(project, name, changes, from_version=src, by=st.session_state.get("engineer") or "engineer")
            st.session_state["scn_selected"] = name.strip()
            st.toast(f"Scenario '{name.strip()}' = v{v}")
            st.rerun()
        except Exception as e:  # noqa: BLE001 - invalid path / value / name: shown, nothing saved
            st.error(f"Not created: {e}")

    names = sorted(project.meta.scenarios)
    scenario_version = None
    if names:
        st.markdown("#### 3 · Scenario: modify · verify · approve · run")
        cur = st.session_state.get("scn_selected")
        sel = st.selectbox("Scenario", names, index=names.index(cur) if cur in names else 0, key="scn_pick")
        v = scenario_version = project.meta.scenarios[sel]
        model = project.load_version(v)
        parent = next((x.parent for x in project.versions() if x.version == v), None)
        rep = app.validate_model(model)
        pending = app.approval_pending(project, model)
        st.caption(f"v{v} · parent v{parent} · hash `{model.content_hash()}` · approved: "
                   f"{'YES' if model.is_approved else 'NO'} · approval required to run: {'YES' if pending else 'NO'} · "
                   f"verification: {rep.summary()}")
        d = app.compare_versions(project, base, v)
        st.dataframe(pd.DataFrame([{"parameter": p, f"baseline v{base}": json.dumps(a, default=str),
                                    f"scenario v{v}": json.dumps(b, default=str)} for p, a, b in d]),
                     hide_index=True, width="stretch")
        if not rep.ok:
            issues_table(rep)
        with st.expander("Modify this scenario (new version)"):
            mods = _changes_form(model, "scn_mod")
            if st.button("APPLY CHANGES", key="scn_mod_btn", disabled=not mods):
                try:
                    app.modify_scenario(project, sel, mods, by=st.session_state.get("engineer") or "engineer")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Not applied: {e}")
        a1, a2 = st.columns([2, 1])
        approver = a1.text_input("Engineer name", value=st.session_state.get("engineer", ""), key="scn_approver",
                                 label_visibility="collapsed", placeholder="Engineer name (for approval)")
        if a2.button("APPROVE SCENARIO", key="scn_approve", disabled=not rep.ok or not approver or model.is_approved):
            st.session_state["engineer"] = approver
            if project.meta.current_version != v:
                project.checkout(v)
            try:
                app.approve_model(project, approver)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        r1, r2 = st.columns([1, 2])
        reps = r1.number_input("Replications", value=model.simulation.replications, min_value=1, max_value=1000, key="scn_reps")
        if r2.button("RUN SCENARIO", key="scn_run", type="primary", disabled=not rep.ok or pending):
            from ..errors import user_message
            try:
                with st.spinner("RUNNING..."):
                    res = app.run_simulation(project, model, replications=int(reps))
                st.success(f"COMPLETED — run {res.run_id}")
            except Exception as e:  # noqa: BLE001
                st.error(f"FAILED — {user_message(e)}")
        if pending:
            st.warning("This scenario needs engineer approval before it can run (same rule as the Run tab).")

    runs = project.runs(200)
    st.markdown("#### 4 · Compare two runs")
    if len(runs) < 1:
        st.info("No stored runs yet.")
        return
    ids = [r["run_id"] for r in runs]
    label = {r["run_id"]: f"{r['created_at']} · v{r['model_version']} · {r['replications']} rep · {r['run_id']}" for r in runs}
    # defaults by version (not by timestamp order): latest run of the baseline version / of the selected scenario
    base_runs = [r["run_id"] for r in runs if r["model_version"] == base]
    alt_runs = [r["run_id"] for r in runs if scenario_version is not None and r["model_version"] == scenario_version]
    b_default = ids.index(base_runs[0]) if base_runs else len(ids) - 1
    a_default = ids.index(alt_runs[0]) if alt_runs else 0
    c1, c2 = st.columns(2)
    b_id = c1.selectbox("Baseline run", ids, index=b_default, format_func=label.get, key="scn_cmp_base")
    a_id = c2.selectbox("Alternative run", ids, index=a_default, format_func=label.get, key="scn_cmp_alt")
    try:
        show_comparison(app.compare_runs(project, b_id, a_id), "scn_cmp")
    except Exception as e:  # noqa: BLE001
        st.error(f"Comparison not possible: {e}")
