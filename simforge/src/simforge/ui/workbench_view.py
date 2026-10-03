"""Results workbench UI (1.1-C), inside the Run & results tab. Stored results only; nothing is simulated here."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..analytics.workbench import EntityTable, KpiValue, fmt_value, overlay_metrics, top_n
from ..persistence.project import Project
from ..services.app import SimForgeApp


def _cell(v: KpiValue) -> str:
    if v.status != "AVAILABLE":
        return v.status  # NOT_AVAILABLE / UNDEFINED: never shown as 0
    txt = fmt_value(v.name, v.unit, v.mean)
    if v.ci95_low is not None:
        txt += f" (95% CI {fmt_value(v.name, v.unit, v.ci95_low)} – {fmt_value(v.name, v.unit, v.ci95_high)})"
    return txt


def kpi_frame(values: list[KpiValue]) -> pd.DataFrame:
    return pd.DataFrame([{"metric": v.metric, "label": v.label, "unit": v.unit or "—", "status": v.status, "n": v.n,
                          "mean": v.mean, "std": v.std, "ci95_low": v.ci95_low, "ci95_high": v.ci95_high,
                          "min": v.min, "max": v.max} for v in values])


def table_frame(t: EntityTable) -> pd.DataFrame:
    return pd.DataFrame([{t.scope: r.entity, **{c: _cell(r.values[c]) for c in t.columns}} for r in t.rows])


def workbench_section(app: SimForgeApp, project: Project, run_id: str) -> None:
    st.markdown("### Results workbench")
    try:
        wb = app.results_workbench(project, run_id)
    except Exception as e:  # noqa: BLE001 - e.g. a run that no longer exists
        st.error(f"Workbench not available: {e}")
        return
    r = wb.run
    tag = f"v{r.model_version}" if r.model_version is not None else "unsaved model"
    st.caption(f"Run `{r.run_id}` · model {tag}{f' · scenario {r.scenario}' if r.scenario else ''} · hash `{r.model_hash}` · "
               f"{r.engine} {r.engine_version} · horizon {r.horizon_s:g} s · warm-up {r.warmup_s:g} s · "
               f"{wb.replications} replication(s) · seeds {r.seeds}")
    st.caption(wb.uncertainty + " " + wb.note)
    cols = st.columns(4)
    for i, v in enumerate([x for x in wb.overview if x.status != "NOT_AVAILABLE"][:8]):
        cols[i % 4].metric(v.label + (f" ({v.unit})" if v.unit else ""), _cell(v).split(" (95%")[0],
                           help=f"{v.metric} · n={v.n}" + (f" · 95% CI {v.ci95_low:.4g} – {v.ci95_high:.4g}" if v.ci95_low is not None else ""))
    with st.expander("KPI overview (stored statistics)"):
        st.dataframe(kpi_frame(wb.overview), hide_index=True, width="stretch")
    if wb.replications > 1:
        with st.expander("Replications (stored per-replication values)"):
            keys = [v.metric for v in wb.overview if v.status != "NOT_AVAILABLE"]
            pick = st.selectbox("Metric", keys, key="wb_rep_metric")
            v = next(x for x in wb.overview if x.metric == pick)
            st.dataframe(pd.DataFrame({"replication": range(1, len(v.replications) + 1), "seed": r.seeds,
                                       "value": v.replications}), hide_index=True, width="stretch")
            st.caption(f"mean {v.mean} · std {v.std} · 95% CI [{v.ci95_low}, {v.ci95_high}] · n {v.n}")
    for t in wb.tables:
        with st.expander(t.title):
            st.dataframe(table_frame(t), hide_index=True, width="stretch")
            if t.key == "setup" and wb.system_setup:
                st.dataframe(kpi_frame(wb.system_setup), hide_index=True, width="stretch")
    with st.expander("Factual observations (stored values, no interpretation)"):
        if not wb.observations:
            st.info("Not enough entities with comparable stored metrics.")
        for o in wb.observations:
            st.markdown(f"- {o.text}")
    with st.expander("Top-N by a stored metric (sorted values, not a priority)"):
        run = project.load_run(run_id)
        c = st.columns(4)
        scope = c[0].selectbox("Scope", ["node", "resource", "product"], key="wb_top_scope")
        names = sorted({".".join(k.split(".")[2:]) for k in run.kpis.stats if k.startswith(f"{scope}.") and len(k.split(".")) == 3})
        if names:
            metric = c[1].selectbox("Metric", names, key="wb_top_metric")
            order = c[2].selectbox("Order", ["descending", "ascending"], key="wb_top_order")
            n = int(c[3].number_input("N", 1, 100, 5, key="wb_top_n"))
            run_model = app._stored_model_of(project, run_id)
            order_ids = [x.id for x in run_model.nodes] if scope == "node" and run_model is not None else None
            t = top_n(run, scope, metric, n, order, entities=order_ids)  # type: ignore[arg-type]
            st.caption(f"sort({metric}, {order}) → first {n}; ties: {t.tie_break}")
            st.dataframe(pd.DataFrame([{"position": i.position, scope: i.entity, "metric": i.metric,
                                        "value": fmt_value(i.metric, i.unit, i.value), "n": i.n} for i in t.items]),
                         hide_index=True, width="stretch")
            if t.excluded:
                st.caption(f"Without a defined stored value (excluded): {', '.join(t.excluded)}")
        else:
            st.info(f"No stored {scope} metrics in this run.")
    with st.expander("KPIs on the process graph (this run's model version)"):
        run = project.load_run(run_id)
        names = overlay_metrics(run)
        if names:
            metric = st.selectbox("Node metric", names, index=names.index("utilization") if "utilization" in names else 0,
                                  key="wb_ov_metric")
            ov, model = app.graph_overlay(project, run_id, metric)
            if ov is None:
                st.info("The model of this run is not stored as a project version: no overlay.")
            else:
                from .views import process_graph
                st.caption(f"Run `{ov.run_id}` · model hash `{ov.model_hash}` · label = stored {ov.label}"
                           f"{f' ({ov.unit})' if ov.unit else ''} (mean over replications); no colour scale.")
                st.graphviz_chart(process_graph(model, overlay={x.node: f"{metric}: {x.text}" for x in ov.nodes}), width="stretch")
    with st.expander("Not stored by the engine (shown as NOT_AVAILABLE)"):
        for g in wb.gaps:
            st.markdown(f"- {g}")
