"""PRODUCTS tab (engine >= 0.7.0): read-only view of products, mix / explicit sequence, routes, product times and setup
configuration, plus per-product and setup KPIs of the last run. The configuration lives in the model's `production`
block (edited like the rest of the model; every change is a new version). No sequencing / optimisation here."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..cli_products import describe
from ..persistence.project import Project
from ..services.app import SimForgeApp
from ..validation.semantics import verify_model


def products_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("Primero crea un modelo.")
        return
    st.caption("SimForge representa la secuencia / el mix que defines; no elige ni optimiza secuencias.")
    st.code("\n".join(describe(model)), language=None)
    if getattr(model, "production", None) is None:
        return
    rep, _ = verify_model(model, app.registry)
    for i in rep.issues:
        if i.code.startswith(("PRODUCT", "MIX", "ROUTE", "ROUTING", "SETUP")) or (i.code == "MISSING" and "production" in (i.path or "")):
            (st.error if i.level.value == "error" else st.info)(str(i))
    last = st.session_state.get("last_run")
    if last is None or last.model_hash != model.content_hash():
        st.info("Ejecuta el modelo (pestaña Run & results) para ver los KPIs por producto y de setups.")
        return
    k = last.kpis
    prods = sorted({key.split(".")[1] for key in k.stats if key.startswith("product.")})
    st.subheader("KPIs por producto")
    st.dataframe(pd.DataFrame([{"product": p, **{m: k.mean(f"product.{p}.{m}") for m in
                                ("created", "completed", "throughput_per_hour", "avg_wip", "wip_end", "avg_lead_time_s")}}
                               for p in prods]), hide_index=True)
    nodes = sorted({key.split(".")[1] for key in k.stats if key.startswith("node.") and key.endswith(".setup_count")})
    if nodes:
        st.subheader("Setups")
        st.dataframe(pd.DataFrame([{"node": n, **{m: k.mean(f"node.{n}.{m}") for m in
                                    ("setup_count", "setup_time_h", "utilization_setup", "processing_time_h", "utilization_processing")}}
                                   for n in nodes]), hide_index=True)
