"""MAINTENANCE tab (engine >= 0.8.0): read-only view of failure models, repair and PM configuration, reliability KPIs
and the maintenance timeline of the last run. Edited in the model's `maintenance` block (new version on change)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..cli_maintenance import describe
from ..persistence.project import Project
from ..services.app import SimForgeApp
from ..validation.semantics import verify_model

KPIS = ("failure_count", "corrective_downtime_h", "waiting_for_repair_resource_h", "active_repair_time_h",
        "preventive_maintenance_count", "preventive_maintenance_time_h", "waiting_for_pm_h", "uptime_h",
        "reliability_availability", "observed_mtbf_exposure_h", "observed_mean_active_repair_s")


def maintenance_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("Primero crea un modelo.")
        return
    st.code("\n".join(describe(model)), language=None)
    if getattr(model, "maintenance", None) is None:
        return
    rep, _ = verify_model(model, app.registry)
    for i in rep.issues:
        if i.code.startswith("MAINTENANCE") or "maintenance" in (i.path or ""):
            (st.error if i.level.value == "error" else st.info)(str(i))
    last = st.session_state.get("last_run")
    if last is None or last.model_hash != model.content_hash():
        st.info("Ejecuta el modelo (pestaña Run & results) para ver KPIs de fiabilidad y la cronología de mantenimiento.")
        return
    k = last.kpis
    nodes = sorted(model.maintenance.nodes)
    st.dataframe(pd.DataFrame([{"node": n, **{m: k.mean(f"node.{n}.{m}") for m in KPIS}} for n in nodes]), hide_index=True)
    if last.records:
        rows = [{"node": x["node"], "type": x["type"], "pm": x.get("pm", ""),
                 "start": x.get("t_fail", x.get("due")), "repair/PM start": x.get("t_repair_start", x.get("start")),
                 "end": x.get("t_repair_end", x.get("end"))} for x in last.records[0].maintenance]
        st.subheader("Cronología de mantenimiento (réplica 1)")
        st.dataframe(pd.DataFrame(rows), hide_index=True)
