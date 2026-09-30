"""Streamlit views. Every button calls the application service; nothing is simulated in the UI."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from ..analytics.kpis import metric_info
from ..domain.io import ModelFormatError, dump_model, load_model, model_from_dict
from ..domain.isms import ExperimentSpec, Factor, ISMSModel
from ..domain.paths import diff, flatten, set_value
from ..engine.base import NodeState
from ..experiments.runner import SimulationResult
from ..library.registry import ComponentDef, save_user_component
from ..persistence.project import Project
from ..reporting.report import experiment_csv, fmt, results_csv
from ..services.app import SimForgeApp
from ..validation.verifier import Level, VerificationReport
from .charts import STATE_LABELS, experiment_line, station_states, wip_series

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


# --------------------------------------------------------------------------- helpers
def process_graph(model: ISMSModel, report: VerificationReport | None = None) -> str:
    bad = {i.path.split(".")[1] for i in (report.errors if report else []) if i.path and i.path.startswith("nodes.")}
    lines = ["digraph G {", "rankdir=LR; bgcolor=transparent;",
             'node [fontname="Helvetica", fontsize=11, style="rounded,filled", fillcolor="#f6f8fa", color="#57606a"];',
             'edge [color="#57606a"];']
    for n in model.nodes:
        p = n.params
        label = [n.name or n.id, f"[{n.component}]"]
        pt = p.get("process_time")
        if isinstance(pt, dict):
            label.append(f"{pt.get('value', pt.get('mean', pt.get('mode', '?')))} {pt.get('unit', 's')} ({pt['dist']})")
        elif n.component not in ("source", "sink", "buffer"):
            label.append("time: MISSING")
        if n.component == "buffer":
            label.append(f"cap {p.get('capacity', '∞')}")
        elif isinstance(p.get("capacity", 1), str) or p.get("capacity", 1) > 1:
            label.append(f"x{p['capacity']}")
        if "work_units" in p:
            label.append(f"× {p['work_units']} units")
        shape = {"source": "ellipse", "sink": "ellipse", "buffer": "cylinder"}.get(n.component, "box")
        if n.component in ("transport", "rack_transport"):
            shape = "cds"
            tp = n.params
            label.append(f"{(tp.get('distance') or {}).get('value', '?')} m @ {(tp.get('speed') or {}).get('value', '?')} m/s")
        extra = ', color="#cf222e", penwidth=2' if n.id in bad else ""
        lab = "\\n".join(str(x).replace('"', "'") for x in label)
        lines.append(f'"{n.id}" [label="{lab}", shape={shape}{extra}];')
    for e in model.edges:
        lab = (f' [label="{e.probability}"]' if isinstance(e.probability, str) else f' [label="{e.probability:.0%}"]') if e.probability not in (None, 1.0) else ""
        lines.append(f'"{e.source}" -> "{e.target}"{lab};')
    for n in model.nodes:
        for rid, tid in n.release_via.items():
            lines.append(f'"{n.id}" -> "{tid}" [style=dashed, label="empty {rid}", color="#8c959f"];')
            dest = model.node(tid).params.get("destination") if tid in [x.id for x in model.nodes] else None
            if dest:
                lines.append(f'"{tid}" -> "{dest}" [style=dashed, color="#8c959f"];')
        if n.params.get("on_reject", "scrap") != "scrap":
            lines.append(f'"{n.id}" -> "{n.params["on_reject"]}" [style=dashed, label="reject", color="#cf222e"];')
    for r in model.resources:
        users = [n.id for n in model.nodes if any(u.get("resource") == r.id for u in n.params.get("resources", []))]
        users += [n.id for n in model.nodes if any(s.resource == r.id for s in n.seize)]
        if users:
            lines.append(f'"res_{r.id}" [label="{r.name or r.id}\\n{r.kind.value} x{r.quantity}", shape=note, fillcolor="#ffffff"];')
            for u in dict.fromkeys(users):
                lines.append(f'"res_{r.id}" -> "{u}" [style=dotted, arrowhead=none, color="#8c959f"];')
    lines.append("}")
    return "\n".join(lines)


def status_panel(model: ISMSModel, report: VerificationReport) -> None:
    c = st.columns([2.2, 1, 1, 1, 1])
    c[0].metric("Readiness", report.readiness.value.replace("_", " "))
    c[1].metric("Confirmed values", report.confirmed_values)
    c[2].metric("Assumptions", len(model.assumptions))
    c[3].metric("Missing (required)", sum(1 for m in model.missing if m.required))
    c[4].metric("Errors / warnings", f"{len(report.errors)} / {len(report.warnings)}")
    if model.is_approved:
        st.success(f"✅ ENGINEER APPROVED by {model.approval.by} ({model.approval.at:%Y-%m-%d %H:%M})")
    elif model.approval.approved:
        st.warning("Model changed after approval: approval is no longer valid.")


def issues_table(report: VerificationReport) -> None:
    if not report.issues:
        st.success("No issues.")
        return
    icon = {Level.ERROR: "⛔", Level.WARNING: "⚠️", Level.INFO: "ℹ️"}
    st.dataframe(pd.DataFrame([{"": icon[i.level], "code": i.code, "message": i.message, "where": i.path or "", "hint": i.hint or ""}
                               for i in report.issues]), hide_index=True, width="stretch")


def _num(col, label: str, value, key: str, integer: bool = False, **kw):
    """Number input, or a text input when the value is a parameter expression ('$n_operators')."""
    if isinstance(value, str):
        return col.text_input(label + " (expr)", value=value, key=key, help="Parameter expression; edit the parameter in the table above")
    if integer:
        return int(col.number_input(label, value=int(value), key=key, step=1, **kw))
    return col.number_input(label, value=float(value), key=key, **kw)


def _save(app: SimForgeApp, project: Project, model: ISMSModel, msg: str) -> None:
    v = app.save_model(project, model, msg)
    st.toast(f"Saved as v{v}")
    st.rerun()


# --------------------------------------------------------------------------- assistant
def assistant_tab(app: SimForgeApp, project: Project) -> None:
    interp = app.interpreter(project).name
    st.caption(f"Interpreter: **{interp}**. The chat is only an interface: every change is applied to the ISMS model "
               "and saved as a new version. Numbers are always computed by the engine.")
    key = f"chat_{project.meta.slug}"
    hist = st.session_state.setdefault(key, [])
    for m in hist:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m.get("table") is not None:
                st.dataframe(m["table"], hide_index=True, width="stretch")
    pending = st.session_state.get(f"pending_{project.meta.slug}")
    if pending:
        st.warning(f"Pending confirmation: “{pending}”")
        c1, c2 = st.columns(2)
        if c1.button("Confirm", type="primary"):
            _handle(app, project, pending, hist, confirm=True)
            st.session_state.pop(f"pending_{project.meta.slug}")
            st.rerun()
        if c2.button("Cancel"):
            st.session_state.pop(f"pending_{project.meta.slug}")
            st.rerun()
    placeholder = "Describe your process..." if project.current_model() is None else "e.g. 'Cambia el buffer a 8', 'Prueba buffers entre 1 y 10', '¿Dónde está el cuello de botella?'"
    text = st.chat_input(placeholder)
    if text:
        hist.append({"role": "user", "text": text})
        _handle(app, project, text, hist)
        st.rerun()


def _handle(app: SimForgeApp, project: Project, text: str, hist: list, confirm: bool = False) -> None:
    try:
        if project.current_model() is None:
            pr = app.parse_process(project, text)
            m = pr.outcome.model
            lines = [f"**Model v{pr.version} created** ({pr.interpreter}) — {pr.report.summary()} — "
                     f"library reuse {pr.outcome.reuse_ratio:.0%}"]
            lines += [f"- `{c['component']}@{c['version']}` ← {c['step']} ({c['how']})" for c in pr.outcome.component_matches]
            if m.assumptions:
                lines.append("\n**ASSUMPTIONS**")
                lines += [f"- {a.text}" for a in m.assumptions]
            if m.missing:
                lines.append("\n**MISSING DATA / QUESTIONS**")
                lines += [f"- {'⛔' if q.required else '❓'} {q.question}" for q in m.missing]
            lines.append("\nReview it in the **Model** tab, then validate and run.")
            hist.append({"role": "assistant", "text": "\n".join(lines)})
            return
        r = app.command(project, text, confirm=confirm)
        table = None
        if r.changes:
            table = pd.DataFrame([{"parameter": p, "before": json.dumps(a, default=str), "after": json.dumps(b, default=str)} for p, a, b in r.changes])
        if r.findings:
            table = pd.DataFrame([{"finding": f.code, "subject": f.subject, "message": f.message,
                                   "evidence": ", ".join(f"{k}={v}" for k, v in f.evidence.items())} for f in r.findings])
        if r.experiment:
            table = pd.DataFrame(r.experiment.table(["throughput_per_hour", "avg_wip", "avg_lead_time_s"]))
            st.session_state["last_experiment"] = r.experiment.experiment_id
        if r.needs_confirmation:
            st.session_state[f"pending_{project.meta.slug}"] = text
        if r.simulation:
            st.session_state["last_run"] = r.simulation
        hist.append({"role": "assistant", "text": r.message, "table": table})
    except Exception as e:  # noqa: BLE001 - show a readable message, never a traceback
        hist.append({"role": "assistant", "text": f"⛔ {e}"})


# --------------------------------------------------------------------------- model
def model_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("No model yet. Describe the process in the Assistant tab, or load an example:")
        ex = st.selectbox("Example", sorted(p.name for p in EXAMPLES.glob("*.yaml")))
        if st.button("Load example into project"):
            _save(app, project, load_model(EXAMPLES / ex), f"loaded example {ex}")
        return
    report = app.validate_model(model)
    st.subheader(f"{model.meta.name}  ·  v{project.meta.current_version}")
    status_panel(model, report)
    st.graphviz_chart(process_graph(model, report), width="stretch")

    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("VALIDATE MODEL", width="stretch"):
        st.session_state["show_validation"] = True
    approver = c3.text_input("Engineer name", value=st.session_state.get("engineer", ""), label_visibility="collapsed", placeholder="Engineer name (for approval)")
    if c2.button("APPROVE MODEL", disabled=not report.ok or not approver, width="stretch",
                 help="Engineer validation: the model represents the real system well enough. Bound to this exact content."):
        st.session_state["engineer"] = approver
        app.approve_model(project, approver)
        st.rerun()
    if st.session_state.get("show_validation", True):
        issues_table(report)
    if model.assumptions or model.missing:
        with st.expander(f"Assumptions ({len(model.assumptions)}) and missing data ({len(model.missing)})", expanded=bool(model.missing)):
            for a in model.assumptions:
                st.markdown(f"- {'✅' if a.accepted else '❓'} {a.text}" + (f" `{a.path}`" if a.path else ""))
            for q in model.missing:
                st.markdown(f"- {'⛔ REQUIRED' if q.required else '❓ optional'}: {q.question}")
            if model.missing and st.button("Mark questions as answered (after editing the parameters)"):
                _save(app, project, model.model_copy(update={"missing": []}), "missing data resolved by engineer")

    st.markdown("#### Parameters")
    _param_editor(app, project, model)
    with st.expander("Advanced: edit ISMS (YAML)"):
        txt = st.text_area("ISMS", dump_model(model), height=400, label_visibility="collapsed")
        if st.button("Validate & save YAML"):
            try:
                new = model_from_dict(yaml.safe_load(txt))
                rep = app.validate_model(new)
                if rep.errors:
                    st.warning("Saved with verification errors (model is not executable yet).")
                _save(app, project, new, "YAML edit")
            except (ModelFormatError, yaml.YAMLError) as e:
                st.error(str(e))


def _param_editor(app: SimForgeApp, project: Project, model: ISMSModel) -> None:
    with st.form("params"):
        changes: dict[str, object] = {}
        s = model.simulation
        c = st.columns(5)
        changes["simulation.horizon.value"] = c[0].number_input("Horizon", value=float(s.horizon.value), min_value=0.0)
        changes["simulation.horizon.unit"] = c[1].selectbox("unit", ["h", "min", "s", "day"], index=["h", "min", "s", "day"].index(s.horizon.unit) if s.horizon.unit in ["h", "min", "s", "day"] else 0)
        changes["simulation.warmup.value"] = c[2].number_input(f"Warm-up ({s.warmup.unit})", value=float(s.warmup.value), min_value=0.0)
        changes["simulation.replications"] = c[3].number_input("Replications", value=s.replications, min_value=1, max_value=1000)
        changes["simulation.base_seed"] = c[4].number_input("Base seed", value=s.base_seed, step=1)
        changes["simulation.trace"] = st.checkbox("Debug mode (event log + operator decision log)", value=s.trace)
        if model.parameters:
            st.markdown("**Model parameters** (value empty = REQUIRED, not provided)")
            pdf = pd.DataFrame([{"id": p.id, "value": p.value, "unit": p.unit, "role": p.role, "description": p.description,
                                 "status": (p.provenance.status.value if p.provenance else ("REQUIRED" if p.value is None else ""))}
                                for p in model.parameters])
            edited = st.data_editor(pdf, hide_index=True, width="stretch", disabled=["id", "unit", "role", "description", "status"], key="params_editor")
            for i, p in enumerate(model.parameters):
                v = edited.loc[i, "value"]
                v = None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)
                if v != p.value:
                    changes[f"parameters.{p.id}.value"] = v
                    changes[f"parameters.{p.id}.provenance"] = {"status": "provided_by_client", "source": "ui"}
        for n in model.nodes:
            if n.component in ("source", "sink"):
                continue
            comp = app.registry.get(n.component) if app.registry.has(n.component) else None
            st.markdown(f"**{n.name or n.id}** · `{n.component}`" + (f" v{comp.version}" if comp else " ⛔ unknown component"))
            c = st.columns(5)
            if n.component == "buffer" or (comp and comp.behavior.value == "buffer"):
                cap = n.params.get("capacity")
                v = _num(c[0], "Capacity (0 = unlimited)", cap if isinstance(cap, str) else (cap or 0), f"cap_{n.id}", integer=True)
                changes[f"nodes.{n.id}.params.capacity"] = v or None
                continue
            if comp and comp.behavior.value == "transport":
                st.caption("Transport: edit distance/speed/load/unload in the parameters table or the YAML editor.")
                continue
            pt = n.params.get("process_time")
            if pt is None or pt.get("dist") == "constant":
                val = _num(c[0], f"Time ({(pt or {}).get('unit', 's')})", (pt or {}).get("value", 0.0), f"pt_{n.id}")
                if pt is not None or (not isinstance(val, str) and val > 0):
                    changes[f"nodes.{n.id}.params.process_time"] = {"dist": "constant", "value": val, "unit": (pt or {}).get("unit", "s"),
                                                                   **({"provenance": pt["provenance"]} if pt and pt.get("provenance") and pt.get("value") == val else {})}
            else:
                c[0].text_input("Time (distribution)", value=json.dumps({k: v for k, v in pt.items() if k != "provenance"}), disabled=True,
                                key=f"ptd_{n.id}", help="Edit non-constant distributions in the YAML editor")
            changes[f"nodes.{n.id}.params.capacity"] = _num(c[1], "Parallel slots", n.params.get("capacity", 1), f"c_{n.id}", integer=True)
            res_ids = [r.id for r in model.resources if r.kind.value != "carrier"]
            cur = [u["resource"] for u in n.params.get("resources", [])]
            sel = c[2].multiselect("Resources", res_ids, default=[x for x in cur if x in res_ids], key=f"r_{n.id}")
            changes[f"nodes.{n.id}.params.resources"] = [{"resource": x} for x in sel]
            changes[f"nodes.{n.id}.priority"] = c[3].number_input("Priority (lower = first)", value=n.priority, key=f"p_{n.id}")
            changes[f"nodes.{n.id}.params.yield_rate"] = _num(c[4], "Yield", n.params.get("yield_rate", 1.0), f"y_{n.id}")
        if model.resources:
            st.markdown("**Resources**")
        for r in model.resources:
            c = st.columns(3)
            c[0].markdown(f"{r.name or r.id} · *{r.kind.value}*")
            changes[f"resources.{r.id}.quantity"] = _num(c[1], "Quantity", r.quantity, f"q_{r.id}", integer=True)
            rules = ["fifo", "priority", "wip_target"]
            changes[f"resources.{r.id}.dispatch"] = c[2].selectbox("Dispatch rule", rules, index=rules.index(r.dispatch.value), key=f"d_{r.id}",
                                                                    help="wip_target = WIP_TARGET_PRIORITY (configure its parameters in YAML)")
        submitted = st.form_submit_button("SAVE MODEL", type="primary")
    if submitted:
        new = model
        try:
            for path, val in changes.items():
                if path.endswith(("replications", "base_seed", "capacity", "quantity", "priority")) and val is not None and not isinstance(val, str):
                    val = int(val)  # type: ignore[arg-type]
                new = set_value(new, path, val)
        except Exception as e:  # noqa: BLE001
            st.error(f"Invalid value: {e}")
            return
        d = diff(model, new, ignore_provenance=True)
        if not d:
            st.info("No changes.")
            return
        _save(app, project, new, "UI edit: " + "; ".join(f"{p}={b}" for p, _, b in d)[:200])


# --------------------------------------------------------------------------- run / results
def run_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("No model yet.")
        return
    report = app.validate_model(model)
    c1, c2, c3 = st.columns([1, 1, 2])
    reps = c1.number_input("Replications", value=model.simulation.replications, min_value=1, max_value=1000)
    trace = c2.checkbox("Debug trace", value=model.simulation.trace)
    if c3.button("RUN SIMULATION", type="primary", disabled=not report.ok, width="stretch"):
        with st.spinner("Simulating..."):
            st.session_state["last_run"] = app.run_simulation(project, model, replications=int(reps), trace=trace, keep_records=True)
    if not report.ok:
        st.error("The model has verification errors; fix them in the Model tab.")
        issues_table(report)
    runs = project.runs()
    if not runs:
        return
    last: SimulationResult | None = st.session_state.get("last_run")
    ids = [r["run_id"] for r in runs]
    default = ids.index(last.run_id) if last and last.run_id in ids else 0
    rid = st.selectbox("Run", ids, index=default, format_func=lambda i: next(f"{r['created_at']} · v{r['model_version']} · {r['replications']} rep · {i}" for r in runs if r["run_id"] == i))
    res = last if last and last.run_id == rid else project.load_run(rid)
    show_results(res, project)


def show_results(res: SimulationResult, project: Project | None = None) -> None:
    k = res.kpis
    cols = st.columns(5)
    for c, key in zip(cols, ["units_completed", "throughput_per_hour", "avg_wip", "avg_lead_time_s", "units_scrapped"]):
        st_ = k.stats.get(key)
        help_ = f"95% CI {fmt(key, st_.ci95_low)} – {fmt(key, st_.ci95_high)} (n={st_.n})" if st_ and st_.n > 1 else "single replication"
        c.metric(metric_info(key)[0] + (" /h" if key == "throughput_per_hour" else ""), fmt(key, k.mean(key)), help=help_)
    if k.n == 1:
        st.caption("Single replication: if the model is stochastic, this is NOT a conclusive result.")

    rows = []
    for key in k.stats:
        if key.startswith("node.") and key.endswith(".utilization"):
            node = key.split(".")[1]
            for i, s in enumerate(STATE_LABELS):
                sk = "utilization" if s == NodeState.BUSY else s
                rows.append({"station": node, "state": STATE_LABELS[s], "fraction": k.mean(f"node.{node}.{sk}"), "order": i})
    if rows:
        df = pd.DataFrame(rows)
        st.markdown("#### Station states")
        st.altair_chart(station_states(df), width="stretch")
        with st.expander("Table view"):
            st.dataframe(df.pivot(index="station", columns="state", values="fraction").style.format("{:.1%}"), width="stretch")
    res_rows = [{"resource": key.split(".")[1], "utilization": st_.mean, "walking": k.mean(key.replace("utilization", "walking"))}
                for key, st_ in k.stats.items() if key.startswith("resource.") and key.endswith(".utilization")]
    if res_rows:
        st.markdown("#### Resources")
        st.dataframe(pd.DataFrame(res_rows).style.format({"utilization": "{:.1%}", "walking": "{:.1%}"}), hide_index=True, width="stretch")
    if res.records and "wip" in res.records[0].series:
        s = res.records[0].series["wip"]
        st.markdown("#### WIP over time (replication 1)")
        st.altair_chart(wip_series([t / 3600 for t in s.t], s.v), width="stretch")
    st.markdown("#### Diagnostics (rule-based facts with evidence)")
    for f in res.findings:
        icon = {"flag": "🚩", "warning": "⚠️", "info": "ℹ️"}[f.severity]
        with st.expander(f"{icon} {f.message}"):
            st.json(f.evidence)
    with st.expander("All KPIs"):
        st.dataframe(pd.DataFrame([{"metric": key, "mean": v.mean, "std": v.std, "ci95_low": v.ci95_low, "ci95_high": v.ci95_high,
                                    "min": v.min, "max": v.max, "n": v.n} for key, v in k.stats.items()]), hide_index=True, width="stretch")
        st.download_button("Export CSV", results_csv(res), file_name=f"kpis_{res.run_id}.csv")
    with st.expander("Reproducibility"):
        st.json({k_: v for k_, v in res.to_dict().items() if k_ not in ("kpis", "per_replication", "findings")})
    rec = res.records[0] if res.records else None
    if rec and rec.decisions:
        st.markdown("#### Operator decision log")
        st.dataframe(pd.DataFrame([{**d, "candidates": "; ".join(f"{c['node']}(p{c['priority']}, waited {c['waiting_s']}s)" for c in d["candidates"]),
                                    "units": ",".join(d["units"])} for d in rec.decisions]), hide_index=True, width="stretch", height=260)
    if rec and rec.events:
        st.markdown("#### Event log")
        ev = pd.DataFrame(rec.events)
        flt = st.text_input("Filter (entity id, node, event)")
        if flt:
            ev = ev[ev.astype(str).apply(lambda r: r.str.contains(flt, case=False)).any(axis=1)]
        st.dataframe(ev, hide_index=True, width="stretch", height=300)


# --------------------------------------------------------------------------- experiments
def _numeric_paths(model: ISMSModel) -> list[str]:
    out = []
    for p, v in flatten(model).items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if p.startswith(("nodes.", "resources.", "parameters.", "simulation.horizon.value", "simulation.warmup.value")) and "provenance" not in p and not p.endswith((".x", ".y")):
            out.append(p)
    for n in model.nodes:  # capacity of buffers defined as unlimited is still a valid factor
        if n.component == "buffer" and f"nodes.{n.id}.params.capacity" not in out:
            out.append(f"nodes.{n.id}.params.capacity")
    return sorted(out)


def _parse_levels(text: str) -> list:
    text = text.strip()
    if "-" in text and "," not in text and text.count("-") == 1:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    vals = [json.loads(x.strip()) for x in text.split(",") if x.strip()]
    return vals


def experiments_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("No model yet.")
        return
    st.caption("Grid search. Each scenario uses the same seeds (common random numbers) for a fair comparison.")
    if model.experiments:
        pre = st.selectbox("Experiments defined in the model", ["—"] + [e.name for e in model.experiments])
    else:
        pre = "—"
    paths = _numeric_paths(model)
    nf = st.number_input("Number of factors", 1, 3, 1)
    factors = []
    for i in range(int(nf)):
        c1, c2 = st.columns([2, 1])
        default_path = paths.index(next((p for p in paths if p.endswith("capacity") and "buffer" in p), paths[0])) if paths else 0
        path = c1.selectbox(f"Factor {i + 1}", paths, index=default_path, key=f"fp{i}")
        levels = c2.text_input("Levels ('1-10' or '1,2,5')", "1-10" if i == 0 else "1,2", key=f"fl{i}")
        try:
            factors.append(Factor(path=path, values=_parse_levels(levels)))
        except Exception:  # noqa: BLE001
            st.error(f"Invalid levels for factor {i + 1}")
            return
    reps = st.number_input("Replications per scenario", 1, 200, model.simulation.replications)
    spec = next((e for e in model.experiments if e.name == pre), None) or ExperimentSpec(name=f"ui: {', '.join(f.path for f in factors)}", factors=factors, replications=int(reps))
    n = 1
    for f in spec.factors:
        n *= len(f.values)
    st.write(f"**{n} scenarios × {spec.replications or model.simulation.replications} replications**")
    if st.button("RUN EXPERIMENT", type="primary", disabled=not app.validate_model(model).ok):
        bar = st.progress(0.0)
        try:
            res = app.run_experiment(project, spec, model, progress=lambda i, t: bar.progress(i / t, f"scenario {i}/{t}"))
            st.session_state["last_experiment"] = res.experiment_id
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    exps = project.experiments()
    if not exps:
        return
    ids = [e["experiment_id"] for e in exps]
    cur = st.session_state.get("last_experiment")
    eid = st.selectbox("Results", ids, index=ids.index(cur) if cur in ids else 0,
                       format_func=lambda i: next(f"{e['created_at']} · {e['name']} · v{e['model_version']}" for e in exps if e["experiment_id"] == i))
    exp = project.load_experiment(eid)
    metric = st.selectbox("Metric", ["throughput_per_hour", "units_completed", "avg_wip", "avg_lead_time_s", "p90_lead_time_s"])
    table = pd.DataFrame(exp.table(["throughput_per_hour", "units_completed", "avg_wip", "avg_lead_time_s"]))
    if len(exp.spec.factors) == 1:
        fpath = exp.spec.factors[0].path
        rows = []
        for s in exp.scenarios:
            if s.result:
                stt = s.result.kpis.stats[metric]
                rows.append({"x": s.factors[fpath], "mean": stt.mean, "lo": stt.ci95_low, "hi": stt.ci95_high})
        if rows and all(isinstance(r["x"], (int, float)) for r in rows):
            df = pd.DataFrame(rows).rename(columns={"x": fpath.split(".")[-2] if fpath.endswith(("capacity", "quantity", "value")) else fpath})
            st.altair_chart(experiment_line(df, df.columns[0], "mean", metric_info(metric)[0]), width="stretch")
    st.dataframe(table, hide_index=True, width="stretch")
    st.download_button("Export CSV", experiment_csv(exp), file_name=f"experiment_{exp.experiment_id}.csv")


# --------------------------------------------------------------------------- library
def library_tab(app: SimForgeApp) -> None:
    c1, c2 = st.columns([3, 1])
    q = c1.text_input("Search components", placeholder="e.g. soldadura, inspección, buffer")
    cats = sorted({c.category for c in app.registry.all()})
    cat = c2.selectbox("Category", ["all"] + cats)
    comps = app.registry.search(q, category=None if cat == "all" else cat) if q else [c for c in app.registry.all() if cat in ("all", c.category)]
    st.dataframe(pd.DataFrame([{"id": c.id, "version": c.version, "name": c.name, "category": c.category, "behavior": c.behavior.value,
                                "status": c.validation_status.value, "origin": c.origin} for c in comps]), hide_index=True, width="stretch")
    if not comps:
        return
    sel = st.selectbox("Component", [c.id for c in comps])
    comp = app.registry.get(sel)
    st.markdown(comp.to_markdown())
    st.caption("Versions: " + ", ".join(app.registry.versions(sel)))
    with st.expander("Duplicate / new version (saved to your user library, never to client projects)"):
        new_id = st.text_input("New id", value=f"{comp.id}_custom" if comp.origin == "core" else comp.id)
        version = st.text_input("Version", value="1.0.0" if new_id != comp.id else _bump(comp.version))
        name = st.text_input("Name", value=comp.name)
        desc = st.text_area("Description", value=comp.description)
        defaults = st.text_area("Defaults (YAML)", value=yaml.safe_dump(comp.defaults))
        kw = st.text_input("Keywords (comma separated)", value=", ".join(comp.keywords))
        change = st.text_input("Change note", value="duplicated")
        if st.button("Save component"):
            try:
                new = ComponentDef(id=new_id, version=version, name=name, category="custom" if comp.origin == "core" and new_id != comp.id else comp.category,
                                   behavior=comp.behavior, description=desc, tags=comp.tags, keywords=[k.strip() for k in kw.split(",") if k.strip()],
                                   defaults=yaml.safe_load(defaults) or {}, param_docs=comp.param_docs, kpis=comp.kpis,
                                   changelog=[*comp.changelog, {"version": version, "change": change}])
                app.registry.register(new)  # validates defaults against the behaviour
                path = save_user_component(new, app.library_dir)
                st.success(f"Saved {new.key} → {path}")
            except Exception as e:  # noqa: BLE001
                st.error(str(e))


def _bump(v: str) -> str:
    parts = v.split(".")
    parts[-1] = str(int(parts[-1]) + 1) if parts[-1].isdigit() else "1"
    return ".".join(parts)


# --------------------------------------------------------------------------- report & project
def report_tab(app: SimForgeApp, project: Project) -> None:
    if project.current_model() is None:
        st.info("No model yet.")
        return
    runs = project.runs()
    exps = project.experiments()
    rid = st.selectbox("Run", [r["run_id"] for r in runs]) if runs else None
    eid = st.selectbox("Experiment (optional)", ["—"] + [e["experiment_id"] for e in exps])
    if st.button("GENERATE REPORT", type="primary"):
        paths = app.generate_report(project, rid, None if eid == "—" else eid)
        st.session_state["report_paths"] = {k: str(v) for k, v in paths.items()}
    paths = st.session_state.get("report_paths")
    if paths:
        c = st.columns(3)
        for col, (kind, p) in zip(c, paths.items()):
            col.download_button(f"Download {kind}", Path(p).read_bytes(), file_name=Path(p).name)
        st.caption("PDF: open the HTML and print to PDF. Native PDF/PowerPoint: NOT IMPLEMENTED.")
        with st.container(border=True):
            st.markdown(Path(paths["markdown"]).read_text(encoding="utf-8"))


def project_tab(app: SimForgeApp, project: Project) -> None:
    st.markdown("#### Versions")
    vs = project.versions()
    if vs:
        st.dataframe(pd.DataFrame([{"version": v.version, "created": v.created_at, "author": v.author, "message": v.message,
                                    "label": v.label or "", "hash": v.content_hash,
                                    "current": "●" if v.version == project.meta.current_version else "",
                                    "baseline": "★" if v.version == project.meta.baseline_version else ""} for v in vs]),
                     hide_index=True, width="stretch")
        nums = [v.version for v in vs]
        c = st.columns(4)
        a = c[0].selectbox("Compare", nums, index=max(0, len(nums) - 2))
        b = c[1].selectbox("with", nums, index=len(nums) - 1)
        if a != b:
            d = app.compare_versions(project, a, b)
            st.dataframe(pd.DataFrame([{"parameter": p, f"v{a}": json.dumps(x, default=str), f"v{b}": json.dumps(y, default=str)} for p, x, y in d]),
                         hide_index=True, width="stretch")
        pick = c[2].selectbox("Version", nums, index=len(nums) - 1, key="pickv")
        if c[3].button("Make current"):
            project.checkout(pick)
            st.rerun()
        if c[3].button("Set as BASELINE"):
            project.set_baseline(pick)
            st.rerun()
    st.markdown("#### Privacy: terms anonymised before any LLM call")
    terms = st.text_area("One per line: real term = placeholder", "\n".join(f"{k} = {v}" for k, v in project.meta.sensitive_terms.items()))
    est = st.number_input("Estimated hours to build this model manually (for productivity metrics)", value=float(project.meta.manual_model_estimated_hours or 0))
    if st.button("Save project settings"):
        project.meta.sensitive_terms = {l.split("=")[0].strip(): l.split("=")[1].strip() for l in terms.splitlines() if "=" in l}
        project.meta.manual_model_estimated_hours = est or None
        project.save_meta()
        st.toast("Saved")
    st.markdown("#### Productivity metrics")
    m = project.metrics()
    if project.meta.manual_model_estimated_hours and m.get("time_to_first_run_s") is not None:
        saved = 1 - (m["time_to_first_run_s"] / 3600) / project.meta.manual_model_estimated_hours
        m["time_saved_vs_manual_to_first_run"] = round(saved, 3)
    st.json({**m, "llm_usage": project.llm_usage_summary()})
    st.markdown("#### History")
    st.dataframe(pd.DataFrame(project.history()), hide_index=True, width="stretch", height=260)
