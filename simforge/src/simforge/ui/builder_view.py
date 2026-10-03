"""Model builder UI (1.1-B, inside the Model tab): structure, distributions and transport without YAML.

Every action calls services.model_builder (the same functions the tests use) and saves a new version through the
application service. Empty inputs mean NOT DECLARED: nothing is defaulted; the verifier shows what is MISSING.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ..domain.isms import ISMSModel, ResourceKind
from ..persistence.project import Project
from ..services import model_builder as B
from ..services.app import SimForgeApp
from ..validation.verifier import VerificationReport

ND = "(not declared)"
UNIT_ND = f"(not declared — domain default: {B.DOMAIN_DEFAULT_TIME_UNIT})"


def _number(text: str, what: str) -> int | float | None:
    """'' -> None (not declared); '3' -> 3; '2.5' -> 2.5; anything else is an error (never coerced)."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            raise B.BuilderError(f"'{what}': '{t}' no es un número.") from None


def _txt(v: Any) -> str:
    return "" if v is None else str(v)


def _apply(app: SimForgeApp, project: Project, fn, message: str) -> None:
    try:
        new = fn()
    except B.BuilderError as e:
        st.error(f"Not applied: {e}")
        return
    cur = project.current_model()
    if cur is not None and cur.model_dump(mode="json") == new.model_dump(mode="json"):
        st.info("No changes.")
        return
    v = app.save_model(project, new, message)
    st.toast(f"Saved as v{v}")
    st.rerun()


# ------------------------------------------------------------------------------------------------ distribution editor
def distribution_editor(key: str, raw: dict[str, Any] | None, label: str) -> B.DistributionForm | None:
    """Returns the form, or None when the family is NOT DECLARED. Raises BuilderError on invalid input."""
    form = B.distribution_to_form(raw) if raw else None
    fams = [ND, *B.DISTRIBUTIONS]
    c = st.columns([1, 2, 1])
    fam = c[0].selectbox(f"{label}: distribution", fams, index=fams.index(form.family) if form else 0, key=f"{key}_fam")
    if fam == ND:
        return None
    vals: dict[str, Any] = {}
    names = B.DISTRIBUTIONS[fam]
    pc = c[1].columns(len(names))
    for i, name in enumerate(names):
        cur = form.params.get(name) if form and form.family == fam else None
        if name == "values":
            txt = pc[i].text_input("values (comma separated)", ", ".join(_txt(x) for x in cur or []), key=f"{key}_{fam}_{name}")
            vals[name] = [_number(x, name) for x in txt.split(",") if x.strip()]
        else:
            v = _number(pc[i].text_input(name, _txt(cur), key=f"{key}_{fam}_{name}"), name)
            if v is not None:
                vals[name] = v
    units = [UNIT_ND, *B.TIME_UNIT_CHOICES]
    cur_unit = form.unit if form else None
    u = c[2].selectbox("unit", units, index=units.index(cur_unit) if cur_unit in units else 0, key=f"{key}_unit",
                       help="Not declared: the domain applies its default (s) without writing it into the model.")
    trunc = form.truncation if form else None
    with st.expander(f"{label}: truncation (explicit, optional)", expanded=False):
        declare = st.checkbox("Declare truncation", value=trunc is not None, key=f"{key}_tr_on")
        t = None
        if declare:
            tc = st.columns(5)
            lo = _number(tc[0].text_input("lower", _txt((trunc or {}).get("lower")), key=f"{key}_tr_lo"), "lower")
            hi = _number(tc[1].text_input("upper", _txt((trunc or {}).get("upper")), key=f"{key}_tr_hi"), "upper")
            reason = tc[2].text_input("reason", (trunc or {}).get("reason", ""), key=f"{key}_tr_reason")
            bts = ["PHYSICAL_BOUND", "MODELLING_BOUND"]
            bt = tc[3].selectbox("bound_type", bts, index=bts.index((trunc or {}).get("bound_type", bts[0])), key=f"{key}_tr_bt")
            ms = ["DECLARED", "FIT_THEN_TRUNCATE"]
            mt = tc[4].selectbox("method", ms, index=ms.index((trunc or {}).get("method", ms[0])), key=f"{key}_tr_m")
            t = {**({"lower": lo} if lo is not None else {}), **({"upper": hi} if hi is not None else {}),
                 "reason": reason, "bound_type": bt}
            if "method" in (trunc or {}) or mt != "DECLARED":
                t["method"] = mt
    return B.DistributionForm(family=fam, params=vals, unit=None if u == UNIT_ND else u, truncation=t)


def _missing(report: VerificationReport, prefix: str) -> None:
    rows = [{"path": i.path, "level": i.level.value, "code": i.code, "message": i.message}
            for i in report.issues if i.path and i.path.startswith(prefix)]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ------------------------------------------------------------------------------------------------ new model
def new_model_form(app: SimForgeApp, project: Project) -> None:
    st.markdown("**Create an empty model (builder)**")
    c = st.columns([2, 1, 1])
    name = c[0].text_input("Model name", key="bld_new_name")
    hv = c[1].text_input("Horizon", key="bld_new_hv", placeholder="required, e.g. 8")
    hu = c[2].selectbox("Horizon unit", ["h", "min", "s", "day"], key="bld_new_hu")
    if st.button("CREATE MODEL", key="bld_new_btn"):
        def build():
            v = _number(hv, "horizon")
            return B.new_model(name, {"value": v, "unit": hu} if v is not None else {})
        _apply(app, project, build, f"new model '{name}' (builder)")


# ------------------------------------------------------------------------------------------------ builder section
def builder_section(app: SimForgeApp, project: Project, model: ISMSModel, report: VerificationReport) -> None:
    reg = app.registry
    st.caption("Structure, distributions and transport without YAML. Empty field = not declared (never a default); "
               "what is required and missing is listed as MISSING. The order of nodes, connections and resources is "
               "kept as built (it is part of the model hash).")
    nodes = B.summarize_nodes(model, reg)
    if nodes:
        st.dataframe(pd.DataFrame([n.model_dump() for n in nodes]), hide_index=True, width="stretch")

    st.markdown("**Add a node**")
    c = st.columns([1, 2, 2, 1])
    nid = c[0].text_input("Node id", key="bld_add_id", placeholder="e.g. m1")
    comps = [x.id for x in reg.all()]
    comp = c[1].selectbox("Component", comps, key="bld_add_comp",
                          format_func=lambda x: f"{x} ({reg.get(x).behavior.value}, {reg.get(x).validation_status.value})")
    nname = c[2].text_input("Name (optional)", key="bld_add_name")
    if c[3].button("ADD NODE", key="bld_add_btn", disabled=not nid.strip()):
        _apply(app, project, lambda: B.add_node(model, reg, nid.strip(), comp, name=nname or None), f"builder: add node {nid}")

    ids = [n.id for n in model.nodes]
    if ids:
        c = st.columns([2, 2, 1])
        rid = c[0].selectbox("Remove node", ids, key="bld_rm_node")
        cascade = c[1].checkbox("Also remove its connections", key="bld_rm_cascade")
        if c[2].button("REMOVE NODE", key="bld_rm_btn"):
            _apply(app, project, lambda: B.remove_node(model, rid, cascade_edges=cascade), f"builder: remove node {rid}")

        st.markdown("**Connections**")
        if model.edges:
            st.dataframe(pd.DataFrame([{"#": i, "source": e.source, "target": e.target,
                                        "probability": "" if e.probability is None else e.probability}
                                       for i, e in enumerate(model.edges)]), hide_index=True, width="stretch")
        c = st.columns([2, 2, 1, 1])
        es = c[0].selectbox("From", ids, key="bld_e_src")
        et = c[1].selectbox("To", ids, key="bld_e_dst")
        ep = c[2].text_input("Probability (optional)", key="bld_e_p")
        if c[3].button("CONNECT", key="bld_e_add"):
            def add_edge():
                p = ep.strip()
                return B.add_edge(model, reg, es, et, None if not p else (p if p.startswith("$") else _number(p, "probability")))
            _apply(app, project, add_edge, f"builder: connect {es} -> {et}")
        if model.edges:
            labels = [f"{e.source} → {e.target}" for e in model.edges]
            c = st.columns([2, 1, 1, 1])
            pick = c[0].selectbox("Connection", range(len(labels)), format_func=labels.__getitem__, key="bld_e_pick")
            e = model.edges[pick]
            np_ = c[1].text_input("New probability (empty = not declared)", _txt(e.probability), key="bld_e_np")
            if c[2].button("UPDATE CONNECTION", key="bld_e_upd"):
                _apply(app, project, lambda: B.update_edge(model, e.source, e.target, _number(np_, "probability")),
                       f"builder: probability {e.source} -> {e.target}")
            if c[3].button("DISCONNECT", key="bld_e_rm"):
                _apply(app, project, lambda: B.remove_edge(model, e.source, e.target), f"builder: disconnect {e.source} -> {e.target}")

    st.markdown("**Resources**")
    c = st.columns([1, 1, 1, 2, 1])
    r_id = c[0].text_input("Resource id", key="bld_r_id")
    kinds = [k.value for k in ResourceKind]
    r_kind = c[1].selectbox("Kind", kinds, key="bld_r_kind")
    r_q = c[2].text_input("Quantity (required)", key="bld_r_q")
    r_name = c[3].text_input("Resource name (optional)", key="bld_r_name")
    if c[4].button("ADD RESOURCE", key="bld_r_add", disabled=not r_id.strip()):
        _apply(app, project, lambda: B.add_resource(model, r_id.strip(), _number(r_q, "quantity") if r_q.strip() else "",
                                                     kind=r_kind, name=r_name or None), f"builder: add resource {r_id}")

    if ids:
        st.markdown("**Configure a node**")
        sel = st.selectbox("Node", ids, key="bld_cfg_node")
        try:
            _configure(app, project, model, report, sel)
        except B.BuilderError as e:
            st.error(f"Invalid input: {e}")


def _configure(app: SimForgeApp, project: Project, model: ISMSModel, report: VerificationReport, nid: str) -> None:
    reg = app.registry
    n = model.node(nid)
    beh = B.behavior_of(reg, n.component).value
    p = n.params
    k = f"bld_{nid}"
    _missing(report, f"nodes.{nid}")
    res_ids = [r.id for r in model.resources]

    def resources_value(selected: list[str]):
        prev = {u["resource"]: u for u in p.get("resources", []) if isinstance(u, dict)}
        if not selected:
            return [] if "resources" in p else None
        return [prev.get(r, {"resource": r}) for r in selected]

    if beh == "source":
        arr = [ND, "infinite", "interarrival"]
        a = st.selectbox("arrival", arr, index=arr.index(p["arrival"]) if p.get("arrival") in arr else 0, key=f"{k}_arr")
        dist = distribution_editor(f"{k}_ia", p.get("interarrival"), "interarrival")
        mx = _number(st.text_input("max_entities", _txt(p.get("max_entities")), key=f"{k}_max"), "max_entities")
        if st.button("APPLY", key=f"{k}_apply"):
            def build():
                m = B.set_node_params(model, reg, nid, {"arrival": None if a == ND else a, "max_entities": mx})
                return B.set_distribution(m, reg, nid, "interarrival", dist)
            _apply(app, project, build, f"builder: configure source {nid}")
    elif beh == "server":
        dist = distribution_editor(f"{k}_pt", p.get("process_time"), "process_time")
        c = st.columns(4)
        cap = _number(c[0].text_input("capacity (parallel slots)", _txt(p.get("capacity")), key=f"{k}_cap"), "capacity")
        wu = _number(c[1].text_input("work_units", _txt(p.get("work_units")), key=f"{k}_wu"), "work_units")
        aggs = [ND, "sum_iid", "scale_sample", "single_sample"]
        ag = c[2].selectbox("work_units_aggregation", aggs, index=aggs.index(p["work_units_aggregation"])
                            if p.get("work_units_aggregation") in aggs else 0, key=f"{k}_agg")
        cur = [u["resource"] for u in p.get("resources", []) if isinstance(u, dict)]
        rs = c[3].multiselect("resources", res_ids, default=[r for r in cur if r in res_ids], key=f"{k}_res")
        if st.button("APPLY", key=f"{k}_apply"):
            def build():
                m = B.set_node_params(model, reg, nid, {"capacity": cap, "work_units": wu,
                                                        "work_units_aggregation": None if ag == ND else ag,
                                                        "resources": resources_value(rs)})
                return B.set_distribution(m, reg, nid, "process_time", dist)
            _apply(app, project, build, f"builder: configure {nid}")
    elif beh == "buffer":
        c = st.columns(2)
        cap = _number(c[0].text_input("capacity (empty = not declared: unlimited)", _txt(p.get("capacity")), key=f"{k}_cap"), "capacity")
        ds = [ND, "fifo", "lifo"]
        d = c[1].selectbox("discipline", ds, index=ds.index(p["discipline"]) if p.get("discipline") in ds else 0, key=f"{k}_disc")
        if st.button("APPLY", key=f"{k}_apply"):
            _apply(app, project, lambda: B.set_node_params(model, reg, nid, {"capacity": cap, "discipline": None if d == ND else d}),
                   f"builder: configure buffer {nid}")
    elif beh == "transport":
        _transport(app, project, model, nid, k, resources_value, res_ids)
    else:
        st.info("A sink has no parameters.")


def _quantity(col, label: str, cur: dict | None, units: list[str], key: str) -> dict | None:
    v = _number(col.text_input(label, _txt((cur or {}).get("value")), key=f"{key}_v"), label)
    u = col.selectbox(f"{label} unit", units, index=units.index(cur["unit"]) if cur and cur.get("unit") in units else 0, key=f"{key}_u")
    return None if v is None else {"value": v, "unit": u}


def _transport(app, project, model, nid, k, resources_value, res_ids) -> None:
    reg = app.registry
    p = model.node(nid).params
    others = [ND, *[n.id for n in model.nodes if n.id != nid]]
    c = st.columns(4)
    dist = _quantity(c[0], "distance", p.get("distance"), ["m", "cm", "mm", "km"], f"{k}_dist")
    speed = _quantity(c[1], "speed", p.get("speed"), ["m/s", "m/min", "km/h"], f"{k}_speed")
    origin = c[2].selectbox("origin", others, index=others.index(p["origin"]) if p.get("origin") in others else 0, key=f"{k}_or")
    dest = c[3].selectbox("destination", others, index=others.index(p["destination"]) if p.get("destination") in others else 0, key=f"{k}_de")
    load = distribution_editor(f"{k}_lt", p.get("load_time"), "load_time")
    unload = distribution_editor(f"{k}_ut", p.get("unload_time"), "unload_time")
    c = st.columns(4)
    cap = _number(c[0].text_input("capacity (units per trip)", _txt(p.get("capacity")), key=f"{k}_cap"), "capacity")
    fleet = _number(c[1].text_input("fleet (parallel trips)", _txt(p.get("fleet")), key=f"{k}_fleet"), "fleet")
    la = _number(c[2].text_input("loading_area", _txt(p.get("loading_area")), key=f"{k}_la"), "loading_area")
    cur = [u["resource"] for u in p.get("resources", []) if isinstance(u, dict)]
    rs = c[3].multiselect("resources", res_ids, default=[r for r in cur if r in res_ids], key=f"{k}_res")

    def tri(label: str, key: str):
        opts = [ND, "true", "false"]
        cur_v = p.get(key)
        v = st.selectbox(label, opts, index=0 if cur_v is None else (1 if cur_v else 2), key=f"{k}_{key}")
        return None if v == ND else v == "true"
    c = st.columns(3)
    with c[0]:
        ret = tri("return_empty", "return_empty")
    with c[1]:
        res_dest = tri("reserve_destination", "reserve_destination")
    bs = [ND, "immediate", "full"]
    batch = c[2].selectbox("batch", bs, index=bs.index(p["batch"]) if p.get("batch") in bs else 0, key=f"{k}_batch")
    if st.button("APPLY", key=f"{k}_apply"):
        changes = {"distance": dist, "speed": speed, "origin": None if origin == ND else origin,
                   "destination": None if dest == ND else dest, "capacity": cap, "fleet": fleet, "loading_area": la,
                   "resources": resources_value(rs), "return_empty": ret, "reserve_destination": res_dest,
                   "batch": None if batch == ND else batch}
        if load is not None:
            changes["load_time"] = load
        elif "load_time" in p:
            changes["load_time"] = None
        if unload is not None:
            changes["unload_time"] = unload
        elif "unload_time" in p:
            changes["unload_time"] = None
        _apply(app, project, lambda: B.set_transport(model, reg, nid, changes), f"builder: configure transport {nid}")
