"""Economic assumptions editor UI (1.1-E, C06), inside the existing Economics tab.

Collects and validates input, calls services.economics_editor + SimForgeApp.save_economics, and shows the existing
verifier issues. It computes no cost: evaluation is the existing 0.9 service (button below the editor, no DES).
Empty value = MISSING (never 0); an explicit 0 is data.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ..domain.economics import CATEGORIES
from ..domain.values import ValueStatus
from ..persistence.project import Project
from ..services import economics_editor as E
from ..services.app import SimForgeApp

ND = "(not declared)"


def _num(text: str, what: str) -> float | None:
    t = (text or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        raise E.EconomicsEditError(f"'{what}': '{t}' no es un número.") from None


def _save(app: SimForgeApp, project: Project, fn, message: str) -> None:
    try:
        new = fn()
        v = app.save_economics(project, new, message, by=st.session_state.get("engineer") or "engineer")
    except (E.EconomicsEditError, ValueError) as e:
        st.error(f"Not saved: {e}")
        return
    st.toast(f"Economic assumptions saved as v{v} (physical model unchanged)")
    st.rerun()


def _money_inputs(key: str, currency: str, bases: list[str], cur: dict[str, Any] | None) -> E.MoneyForm:
    c = st.columns([1, 2, 2, 2])
    val = _num(c[0].text_input("value (empty = MISSING)", "" if not cur or cur.get("value") is None else str(cur["value"]),
                               key=f"{key}_v"), "value")
    basis = c[1].selectbox("basis", bases, index=bases.index(cur["basis"]) if cur and cur.get("basis") in bases else 0,
                           key=f"{key}_b")
    statuses = [ND, *[s.value for s in ValueStatus if s is not ValueStatus.DEFAULT]]
    prov = (cur or {}).get("provenance") or {}
    status = c[2].selectbox("provenance", statuses, index=statuses.index(prov["status"]) if prov.get("status") in statuses else 0,
                            key=f"{key}_ps")
    source = c[3].text_input("source / reference", (cur or {}).get("reference") or "", key=f"{key}_ref")
    provenance = None if status == ND else {**{k: v for k, v in prov.items() if k != "status"}, "status": status}
    return E.MoneyForm(value=val, currency=currency, basis=basis, provenance=provenance, reference=source or None,
                       effective_date=(cur or {}).get("effective_date"))


def economics_editor(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    spec = getattr(model, "economics", None)
    with st.expander("Edit economic assumptions (no simulation; physical model unchanged)", expanded=spec is None):
        st.caption("Bases offered per category are those the economics 0.9 verifier accepts. Empty value = MISSING "
                   "(never 0). Every save creates a new model version with the same physical hash.")
        if spec is None:
            c = st.columns([1, 3, 1])
            ccy = c[0].text_input("Currency (ISO)", key="ee_new_ccy", placeholder="EUR")
            scope = c[1].multiselect("Scope (categories to evaluate)", list(CATEGORIES), key="ee_new_scope")
            if c[2].button("CREATE ECONOMICS", key="ee_new_btn", disabled=not ccy.strip()):
                _save(app, project, lambda: E.create_economics(model, ccy.strip(), scope), "economics: created")
            return
        c = st.columns([1, 3, 1])
        ccy = c[0].text_input("Currency (ISO)", spec.currency, key="ee_ccy")
        scope = c[1].multiselect("Scope", list(CATEGORIES), default=list(spec.scope), key="ee_scope")
        if c[2].button("SAVE HEADER", key="ee_head_btn"):
            _save(app, project, lambda: E.set_header(model, ccy.strip(), scope), "economics: currency / scope")
        data = spec.model_dump(mode="json")
        rows = []
        for cat in E.LINE_CATEGORIES:
            for i, line in enumerate(data.get(cat) or []):
                money = line[E.MONEY_FIELD[cat]]
                rows.append({"line": f"{cat}.{i}", **{k: v for k, v in line.items() if k != E.MONEY_FIELD[cat]},
                             "value": "MISSING" if money.get("value") is None else money["value"], "currency": money["currency"],
                             "basis": money["basis"], "provenance": (money.get("provenance") or {}).get("status", "—")})
        if rows:
            st.dataframe(pd.DataFrame(rows).astype(str), hide_index=True, width="stretch")
        st.markdown("**Add a line**")
        cat = st.selectbox("Category", list(E.LINE_CATEGORIES), key="ee_cat")
        fields: dict[str, Any] = {}
        fc = st.columns(3)
        nodes = [n.id for n in model.nodes]
        res = [r.id for r in model.resources]
        kind = None
        if cat == "labor":
            fields["resource"] = fc[0].selectbox("resource", res or [""], key="ee_f_res")
            pt = fc[1].selectbox("paid_time (PER_PAID_HOUR)", [ND, "CALENDAR_WINDOW", "PLANNED_AVAILABLE", "DECLARED"], key="ee_f_pt")
            fields["paid_time"] = None if pt == ND else pt
        elif cat in ("machine", "downtime"):
            fields["node"] = fc[0].selectbox("node", nodes, key="ee_f_node")
        elif cat == "maintenance":
            kind = fc[0].selectbox("kind", list(E.MAINT_BASIS), key="ee_f_kind")
            fields["kind"] = kind
            fields["node"] = fc[1].selectbox("node", nodes, key="ee_f_mnode")
            if kind.endswith("_LABOR"):
                fields["resource"] = fc[2].selectbox("resource", res or [""], key="ee_f_mres")
        elif cat in ("material", "scrap", "revenue"):
            prods = [ND, *sorted(getattr(getattr(model, "production", None), "products", {}) or {})]
            p = fc[0].selectbox("product (optional)", prods, key="ee_f_prod")
            fields["product"] = None if p == ND else p
        elif cat == "capex":
            fields["category"] = fc[0].text_input("CAPEX category", key="ee_f_capcat")
            fields["note"] = fc[1].text_input("note", key="ee_f_note") or None
        try:
            form = _money_inputs("ee_add", spec.currency, E.basis_options(cat, kind), None)
        except E.EconomicsEditError as e:
            st.error(str(e))
            form = None
        if st.button("ADD LINE", key="ee_add_btn", disabled=form is None):
            _save(app, project, lambda: E.add_line(model, cat, fields, form), f"economics: add {cat} line")
        if rows:
            st.markdown("**Edit or remove a line**")
            ids = [r["line"] for r in rows]
            pick = st.selectbox("Line", ids, key="ee_pick")
            pcat, idx = pick.split(".")[0], int(pick.split(".")[1])
            line = data[pcat][idx]
            try:
                eform = _money_inputs(f"ee_edit_{pick}", spec.currency,
                                      E.basis_options(pcat, line.get("kind")), line[E.MONEY_FIELD[pcat]])
            except E.EconomicsEditError as e:
                st.error(str(e))
                eform = None
            c = st.columns(2)
            if c[0].button("SAVE LINE", key="ee_edit_btn", disabled=eform is None):
                _save(app, project, lambda: E.update_line_money(model, pcat, idx, eform), f"economics: edit {pick}")
            if c[1].button("REMOVE LINE", key="ee_rm_btn"):
                _save(app, project, lambda: E.remove_line(model, pcat, idx), f"economics: remove {pick}")
        st.markdown("**Annualization**")
        c = st.columns([2, 1])
        cur_a = spec.annualization.runs_per_year if spec.annualization else None
        try:
            rpy = _num(c[0].text_input("runs_per_year (empty = not declared)", "" if cur_a is None else str(cur_a), key="ee_rpy"),
                       "runs_per_year")
        except E.EconomicsEditError as e:
            st.error(str(e))
            rpy = "invalid"
        if c[1].button("SAVE ANNUALIZATION", key="ee_ann_btn", disabled=rpy == "invalid"):
            prov = spec.annualization.provenance.model_dump(mode="json") if spec.annualization and spec.annualization.provenance else None
            _save(app, project, lambda: E.set_annualization(model, rpy, prov), "economics: annualization")
