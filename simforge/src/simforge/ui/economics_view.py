"""ECONOMICS tab (engine >= 0.9.0): assumptions, coverage, breakdown, unit costs, annualization, CAPEX, comparison.
Evaluations re-use STORED physical runs (no simulation). Facts only: no ranking, no recommendation."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import yaml

from ..persistence.project import Project
from ..services.app import SimForgeApp
from ..validation.economics import economics_issues


def _m(s):
    return None if not isinstance(s, dict) else s.get("mean")


def economics_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("Primero crea un modelo.")
        return
    spec = getattr(model, "economics", None)
    st.caption("SimForge calcula, compara y traza consecuencias económicas de supuestos DECLARADOS. No recomienda: el "
               "ingeniero decide.")
    if spec is None:
        st.info("El modelo no tiene bloque 'economics' (supuestos económicos). Los resultados físicos no dependen de él.")
        return
    st.subheader("Supuestos")
    st.code(yaml.safe_dump(spec.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True), language="yaml")
    st.caption(f"economic_hash {spec.economic_hash()} · physical hash {model.content_hash()}")
    for i in economics_issues(spec, model, app.registry):
        (st.error if i.level.value == "error" else st.info)(str(i))
    runs = [r for r in project.runs(20)]
    if runs:
        rid = st.selectbox("Run físico a evaluar", [r["run_id"] for r in runs], key="econ_run")
        if st.button("Evaluar (sin re-simular)", key="econ_eval"):
            try:
                ev = app.evaluate_economics(project, rid)
                st.session_state["econ_last"] = ev.evaluation_id
            except ValueError as e:
                st.error(str(e))
    evs = project.evaluations()
    if not evs:
        st.info("Sin evaluaciones todavía (ejecuta el modelo en Run & results y evalúa ese run).")
        return
    ids = [e["evaluation_id"] for e in evs]
    sel = st.selectbox("Evaluación", ids, index=ids.index(st.session_state.get("econ_last", ids[-1])) if
                       st.session_state.get("econ_last") in ids else len(ids) - 1, key="econ_sel")
    ev = project.load_evaluation(sel)
    st.write(f"**{ev.status}** · run `{ev.run_id}` · {ev.currency} · {ev.uncertainty_label}")
    st.dataframe(pd.DataFrame([{"category": k, "coverage": v} for k, v in ev.coverage.items()]), hide_index=True)
    rows = [{"line": ln.line_id, "status": ln.status, "basis": ln.basis, "quantity": _m(ln.quantity), "unit": ln.unit,
             "rate": ln.parameter["value"], "provenance": ln.parameter["status"], "cost": _m(ln.value), "formula": ln.formula_id,
             "physical source": "; ".join(ln.physical_sources)} for ln in ev.lines]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    cats = {c: _m(v) for c, v in ev.totals["by_category"].items()}
    if cats:
        st.bar_chart(pd.Series(cats, name=f"evaluated cost ({ev.currency})"))
    st.write(f"evaluated_total_cost: **{_m(ev.totals['evaluated_total_cost'])}** {ev.currency} (suma de líneas INCLUDED; categorías completas "
             f"{ev.totals['included_categories']}; no es un coste completo de producción) · coste/unidad producida: {_m(ev.unit_costs['cost_per_produced_unit']) if isinstance(ev.unit_costs['cost_per_produced_unit'], dict) else 'UNDEFINED_METRIC'}"
             f" · coste/unidad buena: {_m(ev.unit_costs['cost_per_good_unit']) if isinstance(ev.unit_costs['cost_per_good_unit'], dict) else 'UNDEFINED_METRIC'}")
    st.write("Anualizado: " + (f"{_m(ev.annualized['evaluated_total_cost'])} {ev.currency}/año" if ev.annualized["status"] == "AVAILABLE"
                               else f"MISSING ({ev.annualized['reason']})"))
    st.write(f"CAPEX: {ev.capex['status']} · total {ev.capex['total'] if ev.capex['total'] is not None else '—'} · missing "
             f"{ev.capex['missing']} (inversión: no se anualiza)")
    if len(ids) >= 2:
        st.subheader("Comparación (delta = alternativa − base; ahorro = base − alternativa)")
        c1, c2 = st.columns(2)
        b = c1.selectbox("Base", ids, key="econ_base")
        a = c2.selectbox("Alternativa", ids, index=len(ids) - 1, key="econ_alt")
        if b != a:
            c = app.compare_economics(project, b, a)
            st.write(f"**{c.status}** · emparejada: {c.paired}")
            for w in [f"{x['level']} [{x['check']}] {x['detail']}" for x in c.checks]:
                st.warning(w)
            st.dataframe(pd.DataFrame([{"KPI": k, **v} for k, v in c.physical_deltas.items()]), hide_index=True)
            st.dataframe(pd.DataFrame([{"cost": k, "delta": v.get("mean"), "mode": v.get("mode")} for k, v in c.cost_deltas.items()]),
                         hide_index=True)
            st.write(f"Ahorro evaluado (run): {c.savings.get('mean')} · anual: "
                     f"{c.annual['savings_per_year']['mean'] if c.annual['status'] == 'AVAILABLE' else c.annual['status']} · "
                     f"payback simple: {c.payback.get('years', c.payback['status'])} ({c.payback['formula']})")
            st.caption(c.note)
