"""DATA tab: UPLOAD -> PREVIEW -> VALIDATE -> ANALYZE -> FIT -> SELECT -> APPLY.

Thin layer over simforge.data.service.DataService (the same calls as `simforge data ...`). Nothing is applied to the model
without the explicit buttons of steps 5 and 6; every action asks who decides and why.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from ..data.dataset import GROUP_ROLES
from ..data.quantities import SUPPORT, Basis, QuantityType, support_table
from ..data.report import fit_text, profile_text
from ..persistence.project import Project
from ..services.app import SimForgeApp

BLUE = "#2a78d6"


def _err(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - domain errors are shown to the engineer, never swallowed
        st.error(str(e))
        return None


def data_tab(app: SimForgeApp, project: Project) -> None:
    ds = app.data(project)
    st.caption("Los datos miden · el sistema analiza · el ingeniero decide · el motor simula. Sin IA: todo determinista y auditable.")
    with st.expander("¿Qué magnitudes puede usar el motor?"):
        st.dataframe(pd.DataFrame(support_table()), hide_index=True)

    # ------------------------------------------------------------------ 1. upload + preview + import
    st.subheader("1 · Importar (CSV / XLSX)")
    up = st.file_uploader("Archivo de mediciones", type=["csv", "txt", "tsv", "xlsx", "xlsm"], key="data_up")
    if up:
        tmpdir = Path(tempfile.gettempdir()) / "simforge_uploads"
        tmpdir.mkdir(exist_ok=True)
        path = tmpdir / Path(up.name).name
        path.write_bytes(up.getvalue())
        from ..data.importers import list_sheets, preview
        sheet = None
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            sheets = _err(lambda: list_sheets(path)) or []
            sheet = st.selectbox("Hoja", sheets, index=None, placeholder="elige la hoja (no se asume la primera)")
        c1, c2, c3 = st.columns(3)
        delim = c1.selectbox("Separador", ["auto", ";", ",", "\\t", "|"], help="CSV: 'auto' detecta; si es ambiguo se pregunta")
        dec = c2.selectbox("Decimal", ["auto", ",", "."])
        header_row = c3.number_input("Fila de cabecera", min_value=1, value=1)
        kw = {"delimiter": None if delim == "auto" else delim.replace("\\t", "\t"), "decimal": None if dec == "auto" else dec,
              "header_row": int(header_row)}
        if path.suffix.lower() in (".csv", ".txt", ".tsv") or sheet:
            pv = _err(lambda: preview(path, sheet=sheet, n=15, **kw))
            if pv:
                st.caption(" · ".join(pv["notes"]))
                st.dataframe(pd.DataFrame(pv["first_rows"], columns=pv["columns"][:max((len(r) for r in pv["first_rows"]), default=0)]),
                             hide_index=True)
                st.write({c: t for c, t in pv["column_types"].items()})
                if pv["unit_hints"]:
                    st.info(f"Unidades sugeridas por la cabecera (NO aplicadas): {pv['unit_hints']}")
                with st.form("data_import"):
                    a, b = st.columns(2)
                    name = a.text_input("Nombre del dataset", value=Path(up.name).stem)
                    column = b.selectbox("Columna VALUE", pv["columns"])
                    q = a.selectbox("Magnitud", [x.value for x in QuantityType])
                    basis = b.selectbox("Base (a qué se refiere cada medida)", [x.value for x in Basis], index=len(Basis) - 1)
                    unit_mode = a.radio("Unidad", ["una para toda la columna", "columna de unidades"], horizontal=True)
                    unit = b.text_input("Unidad (ms, s, min, h, mm, cm, m, km, UNKNOWN)", value=pv["unit_hints"].get(column, ""))
                    unit_col = b.selectbox("Columna de unidades", [None] + pv["columns"])
                    ts = a.selectbox("Columna TIMESTAMP (opcional)", [None] + pv["columns"])
                    groups = {r: b.selectbox(f"Columna {r.upper()} (opcional)", [None] + pv["columns"], key=f"g_{r}") for r in GROUP_ROLES}
                    synthetic = a.checkbox("SYNTHETIC TEST DATA (no son medidas de planta)")
                    imported = a.checkbox("Exportado de un sistema (IMPORTED) en vez de medido (MEASURED)")
                    by = b.text_input("Importado por", value="engineer")
                    desc = st.text_input("Descripción")
                    if st.form_submit_button("Importar como nueva versión de dataset"):
                        r = _err(lambda: ds.import_file(
                            path, name, column, q, basis, unit=unit if unit_mode.startswith("una") else None,
                            unit_column=unit_col if not unit_mode.startswith("una") else None, sheet=sheet, timestamp=ts,
                            groups={k: v for k, v in groups.items() if v}, by=by, description=desc, synthetic=synthetic,
                            measurement_status="imported" if imported else "measured", **kw))
                        if r:
                            if r.duplicate_of:
                                st.warning(f"DUPLICADO: ya importado como {r.duplicate_of}")
                            else:
                                st.success(f"{r.meta.label}: {r.meta.counts}")
                            st.session_state["dataset"] = r.meta.dataset_id

    # ------------------------------------------------------------------ 2. validate + analyse
    metas = ds.list()
    if not metas:
        return
    st.subheader("2 · Validar y analizar")
    ids = [m.dataset_id for m in metas]
    cur = st.session_state.get("dataset")
    did = st.selectbox("Dataset", ids, index=ids.index(cur) if cur in ids else len(ids) - 1,
                       format_func=lambda i: next(m.label for m in metas if m.dataset_id == i))
    st.session_state["dataset"] = did
    meta = next(m for m in metas if m.dataset_id == did)
    roles = meta.mapping.group_columns()
    group, pooled = {}, False
    if roles:
        st.caption("Este dataset tiene columnas de grupo: los grupos NO se mezclan sin decisión explícita.")
        state = ds.state(did)
        cols = st.columns(len(roles) + 1)
        for col, r in zip(cols, roles):
            vals = sorted({state.obs(i).groups.get(r) for i in state.used})
            v = col.selectbox(r, ["(todos)"] + vals, key=f"sel_{r}")
            if v != "(todos)":
                group[r] = v
        pooled = cols[-1].checkbox("Mezclar grupos (pooled)", help="decisión explícita, queda registrada")
    prof = ds.profile(did, group=group, pooled=pooled)
    st.code(profile_text(prof), language=None)
    if "stats" in prof and prof["stats"]["n"]:
        _plots(prof)
        _row_actions(ds, did, prof)

    # ------------------------------------------------------------------ 3/4. fit + select
    if "stats" not in prof:
        return
    st.subheader("3 · Ajustar distribuciones (candidatos, no decisiones)")
    c1, c2, c3 = st.columns(3)
    pmin = c1.number_input("Mínimo físico (opcional)", value=None, help=f"en {meta.analysis_unit}")
    pmax = c2.number_input("Máximo físico (opcional)", value=None)
    by = c3.text_input("Ingeniero", value=st.session_state.get("engineer", ""), key="eng")
    st.session_state["engineer"] = by
    if st.button("Ajustar", disabled=not by):
        st.session_state["fit"] = _err(lambda: ds.fit(did, by=by, group=group, pooled=pooled, physical_min=pmin, physical_max=pmax))
    with st.expander("Validación temporal (holdout): ajustar con la primera parte, comprobar con la final"):
        frac = st.slider("Fracción para ajustar (propuesta 70 %)", 0.5, 0.9, 0.7, 0.05)
        if st.button("Ejecutar holdout"):
            from ..data.report import holdout_text
            h = _err(lambda: ds.holdout(did, frac, group=group, pooled=pooled, by=by or "engineer"))
            if h:
                st.code(holdout_text(h), language=None)
    fit = st.session_state.get("fit")
    if fit and fit.get("dataset_id") == did:
        st.code(fit_text(fit), language=None)
        ok = [c for c in fit["candidates"] if c.get("qq")]
        if ok:
            fam = st.selectbox("Q-Q de", [c["family"] for c in ok])
            c = next(x for x in ok if x["family"] == fam)
            df = pd.DataFrame({"teórico": c["qq"]["theoretical"], "observado": c["qq"]["observed"]})
            lim = [min(df.min()), max(df.max())]
            line = alt.Chart(pd.DataFrame({"x": lim, "y": lim})).mark_line(color="#999", strokeDash=[4, 4]).encode(x="x", y="y")
            st.altair_chart(alt.Chart(df).mark_circle(color=BLUE).encode(x="teórico", y="observado") + line, width="stretch")

    st.subheader("4 · Decisión del ingeniero")
    with st.form("decide"):
        decision = st.radio("Decisión", ["USE_EMPIRICAL", "USE_FITTED", "USE_DETERMINISTIC", "KEEP_WITHOUT_APPLYING", "REJECT"], horizontal=True)
        a, b = st.columns(2)
        cand = a.selectbox("Distribución (USE_FITTED)", [c["family"] for c in (fit or {}).get("candidates", []) if c.get("aic") is not None])
        deriv = b.selectbox("Origen del valor (USE_DETERMINISTIC)", ["MEAN", "MEDIAN", "ENGINEER_VALUE"])
        val = b.number_input("Valor del ingeniero", value=None)
        tl = a.number_input("Truncamiento inferior (opcional)", value=None)
        tr = a.text_input("Motivo del truncamiento")
        tbt = a.selectbox("Tipo de límite", [None, "MODELLING_BOUND", "PHYSICAL_BOUND"])
        accept = b.multiselect("Avisos aceptados explícitamente", ["VERY_SMALL_SAMPLE", "TRUNCATION_SHIFTS_MEAN",
                                                                  "DATA_OUTSIDE_PHYSICAL_BOUND", "TAIL_EXTRAPOLATION", "EXTREME_TAIL",
                                                                  "MASS_BELOW_OBSERVED_MIN", "MEAN_MISMATCH", "BELOW_PHYSICAL_MIN",
                                                                  "ABOVE_PHYSICAL_MAX"])
        reason = st.text_input("Motivo de la decisión")
        if st.form_submit_button("Registrar decisión", disabled=not by):
            ev = _err(lambda: ds.decide(did, decision, by, reason=reason, group=group, pooled=pooled, derivation=deriv,
                                        engineer_value=val, fit_id=(fit or {}).get("fit_id"), candidate=cand,
                                        truncation={"lower": tl, "reason": tr, "bound_type": tbt} if tl is not None else None, accept_warnings=accept))
            if ev:
                st.success(f"{ev.decision_id}: {ev.decision.value} -> {ev.distribution or 'nada que aplicar'}")

    # ------------------------------------------------------------------ 5. apply
    st.subheader("5 · Aplicar al modelo (nueva versión, aprobación invalidada)")
    st_ = ds.state(did)
    decs = [d for d in st_.decisions if d.distribution]
    model = project.current_model()
    if not decs or model is None:
        st.caption("Sin decisiones aplicables o sin modelo.")
        return
    sup = SUPPORT[meta.quantity_type]
    targets = [f"nodes.{n.id}.{t}" for n in model.nodes for t in sup["targets"]
               if app.registry.get(n.component).behavior.value in sup["behaviors"]]
    if not targets:
        st.warning(f"{meta.quantity_type.value}: {sup['note']}")
        return
    with st.form("apply"):
        d = st.selectbox("Decisión", [x.decision_id for x in decs], index=len(decs) - 1,
                         format_func=lambda i: next(f"{x.decision_id} {x.decision.value} {x.candidate or x.derivation or ''} ({x.by})"
                                                    for x in decs if x.decision_id == i))
        tgt = st.selectbox("Destino", targets)
        tb = st.selectbox("Base del destino (qué representa UNA muestra del parámetro)", [x.value for x in Basis],
                          index=[x.value for x in Basis].index(meta.basis.value))
        a, b, c = st.columns(3)
        factor = a.number_input("Factor de conversión de base (si difiere)", value=None)
        formula = b.text_input("Fórmula", placeholder="t_rack = 4 · t_circuito")
        inputs = c.text_input("Entradas (JSON)", placeholder='{"circuits_per_rack": 4}')
        agg = st.selectbox("Agregación de work_units del nodo destino", [None, "sum_iid", "scale_sample", "single_sample"],
                           help="sum_iid: X1+…+Xk (una muestra por unidad) · scale_sample: k·X · single_sample: X (entidad completa). "
                                "Obligatoria si work_units ≠ 1 y el tiempo es aleatorio y el nodo no la declara.")
        scale = st.checkbox("La conversión de base de una distribución es k·X (scale_sample)")
        if st.form_submit_button("Aplicar (crea nueva versión del modelo)"):
            import json
            conv = {"factor": factor, "formula": formula, "inputs": json.loads(inputs) if inputs else None} if factor else None
            if conv and scale:
                conv["aggregation"] = "scale_sample"
            r = _err(lambda: ds.apply(did, d, tgt, tb, by or "engineer", conversion=conv, aggregation=agg))
            if r:
                st.success(f"Modelo v{r['version']}: {r['target']} = {r['new']} ({r['provenance']}). {r['approval']}")
                for w in r["warnings"]:
                    st.warning(w)


def _plots(prof: dict) -> None:
    p = prof["plots"]
    u = prof.get("unit", "")
    h = p["histogram"]
    t1, t2, t3, t4 = st.tabs(["Histograma", "ECDF", "Boxplot", "Secuencia"])
    with t1:
        df = pd.DataFrame({"desde": h["edges"][:-1], "hasta": h["edges"][1:], "n": h["counts"]})
        st.altair_chart(alt.Chart(df).mark_bar(color=BLUE).encode(x=alt.X("desde:Q", title=u), x2="hasta", y="n:Q"), width="stretch")
    with t2:
        df = pd.DataFrame(p["ecdf"])
        st.altair_chart(alt.Chart(df).mark_line(interpolate="step-after", color=BLUE).encode(x=alt.X("x:Q", title=u), y="p:Q"),
                        width="stretch")
    with t3:
        df = pd.DataFrame({"v": p["sequence"]["value"]})
        st.altair_chart(alt.Chart(df).mark_boxplot(color=BLUE).encode(x=alt.X("v:Q", title=u)), width="stretch")
    with t4:
        df = pd.DataFrame({"i": p["sequence"]["i"], "v": p["sequence"]["value"]})
        st.altair_chart(alt.Chart(df).mark_line(point=True, color=BLUE).encode(x=alt.X("i:Q", title=f"orden ({prof['order']})"),
                                                                               y=alt.Y("v:Q", title=u)), width="stretch")


def _row_actions(ds, did: str, prof: dict) -> None:
    o = prof.get("outliers", {})
    with st.expander(f"Filas: outliers candidatos ({len(o.get('candidates', []))}), revisión, exclusiones"):
        if o.get("candidates"):
            st.dataframe(pd.DataFrame(o["candidates"]), hide_index=True)
        with st.form("rows"):
            a, b = st.columns(2)
            action = a.selectbox("Acción", ["KEEP", "EXCLUDE_FROM_FIT", "MARK_INVALID", "RESTORED", "ACCEPT_REVIEWED"])
            rows = b.text_input("Índices (idx), separados por comas", value=",".join(str(i) for i in o.get("unreviewed", [])))
            reason = a.text_input("Motivo (obligatorio)")
            by = b.text_input("Ingeniero", key="rows_by")
            if st.form_submit_button("Registrar acción"):
                idx = [int(x) for x in rows.replace(" ", "").split(",") if x]
                ev = _err(lambda: ds.act_rows(did, action, idx, reason, by, method="UI"))
                if ev:
                    st.success(f"{ev.action} {ev.rows}")
                    st.rerun()
