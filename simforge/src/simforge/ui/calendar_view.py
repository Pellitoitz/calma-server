"""CALENDAR / SHIFTS tab: create calendars, shifts, breaks, exceptions; assign them; choose end-of-shift policies.

Same operations as `simforge calendar ...` (domain/calendar_edit.py). Every change is a new model version (the approval
is invalidated by the content hash). No YAML editing required.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..domain import calendar_edit as ce
from ..domain.calendar import DAYS, week_view
from ..persistence.project import Project
from ..services.app import SimForgeApp
from ..validation.availability import availability_issues, planned_summary

POLICIES = ["FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART"]
POLICY_HELP = ("FINISH_CURRENT: la operación iniciada termina aunque acabe el turno · PAUSE_RESUME: se pausa y continúa "
               "con el trabajo restante · STOP_RESTART: se pierde lo hecho y empieza de nuevo")
RULES = ["START_ANY_TIME", "REQUIRE_FULL_WINDOW"]


def _apply(app: SimForgeApp, project: Project, fn, msg: str) -> None:
    try:
        new = fn()
    except Exception as e:  # noqa: BLE001 - shown to the engineer
        st.error(str(e))
        return
    v = app.save_model(project, new, msg)
    st.toast(f"Saved as v{v} (approval must be renewed)")
    st.rerun()


def calendar_tab(app: SimForgeApp, project: Project) -> None:
    model = project.current_model()
    if model is None:
        st.info("Primero crea un modelo.")
        return
    av = getattr(model, "availability", None)
    st.caption("El calendario decide CUÁNDO está disponible un recurso; la estrategia de dispatch decide QUÉ trabajo hace.")
    if av is None:
        st.info("Este modelo no tiene calendarios: todo está disponible siempre (comportamiento legacy).")
    # ---------------------------------------------------------------- setup
    with st.expander("1 · Modo del calendario", expanded=av is None):
        with st.form("cal_setup"):
            mode = st.radio("Modo", ["relative_week", "dated"], horizontal=True,
                            index=0 if av is None or av.mode == "relative_week" else 1,
                            help="relative_week: semana tipo (lunes 06:00...). dated: fechas reales, festivos y excepciones")
            c1, c2, c3, c4 = st.columns(4)
            wd = c1.selectbox("t=0: día (semana tipo)", DAYS, index=DAYS.index(av.start_weekday) if av else 0)
            t0 = c2.text_input("t=0: hora", value=av.start_time if av else "00:00")
            d0 = c3.text_input("t=0: fecha (dated)", value=str(av.start_date) if av and av.start_date else "")
            tz = c4.text_input("Zona horaria (dated)", value=av.timezone or "" if av else "", placeholder="Europe/Madrid")
            if st.form_submit_button("Guardar modo"):
                _apply(app, project, lambda: ce.setup(model, mode, wd, t0, d0 or None, tz or None), f"calendars: mode {mode}")
    if av is None:
        return
    # ---------------------------------------------------------------- view
    st.subheader("Resumen semanal")
    for c in av.calendars:
        st.code(week_view(av, c), language=None)
    rows = planned_summary(model, app.registry)
    if rows:
        st.caption(f"Tiempo planificado en el horizonte simulado ({model.simulation.horizon.value:g} "
                   f"{model.simulation.horizon.unit} transcurridas, no horas productivas)")
        st.dataframe(pd.DataFrame([{"tipo": r["kind"], "id": r["id"], "calendario": r["calendar"],
                                    "planificado h": round(r["planned_available_s"] / 3600, 2),
                                    "descansos h": round(r["break_s"] / 3600, 2), "fuera de turno h": round(r["off_shift_s"] / 3600, 2),
                                    "fin de disponibilidad": r.get("at_unavailability"), "regla de inicio": r.get("start_rule")}
                                   for r in rows]), hide_index=True)
    issues = availability_issues(model, app.registry)
    for i in issues:
        tag = "REQUIRES_ENGINEER_DECISION" if i.code.startswith("DECISION_") else i.level.value.upper()
        (st.error if i.level.value == "error" else st.warning)(f"{tag} · {i.code}: {i.message}")
    # ---------------------------------------------------------------- calendars
    st.subheader("2 · Calendarios: turnos y descansos")
    with st.form("cal_edit"):
        ids = [c.id for c in av.calendars]
        a, b = st.columns(2)
        cid = a.text_input("Id del calendario", placeholder="turno_manana")
        name = b.text_input("Nombre", placeholder="Turno de mañana")
        days = st.multiselect("Días", DAYS, default=DAYS[:5])
        shifts = a.text_input("Turnos", placeholder="06:00-14:00, 14:00-22:00   (22:00-06:00 cruza medianoche)")
        breaks = b.text_input("Descansos (esos días)", placeholder="10:00-10:15, 12:30-13:00")
        if st.form_submit_button("Crear / reemplazar patrón semanal"):
            _apply(app, project, lambda: ce.upsert_calendar(
                model, cid, name, {d: ce.parse_windows(shifts) for d in days},
                [{**w, "days": days} for w in ce.parse_windows(breaks)] if breaks else []), f"calendar {cid}: {days} {shifts}")
        st.caption(f"Existentes: {', '.join(ids) or '—'}")
    if not av.calendars:
        return
    with st.form("cal_exc"):
        st.markdown("**Excepciones** (solo modo dated)")
        a, b, c = st.columns(3)
        ecal = a.selectbox("Calendario", [x.id for x in av.calendars])
        edate = b.text_input("Fecha", placeholder="2026-10-12")
        etype = c.selectbox("Tipo", ["NON_WORKING_DAY", "OVERRIDE_WORKING_INTERVALS", "OVERTIME", "EXTRA_SHIFT"])
        eint = a.text_input("Intervalos", placeholder="06:00-12:00")
        ereason = b.text_input("Motivo")
        ebreaks = c.selectbox("¿Se aplican los descansos?", [None, True, False], help="obligatorio si el calendario tiene descansos")
        escope = a.selectbox("Festivo: alcance", [None, "SHIFTS_STARTING_ON_DATE", "CALENDAR_DAY"],
                             help="obligatorio con turnos nocturnos")
        if st.form_submit_button("Añadir excepción"):
            exc = {"date": edate, "type": etype, "intervals": ce.parse_windows(eint) if eint else [], "reason": ereason,
                   "breaks_apply": ebreaks, "scope": escope}
            _apply(app, project, lambda: ce.add_exception(model, ecal, exc), f"calendar {ecal}: {etype} {edate}")
    # ---------------------------------------------------------------- assignments & policies
    st.subheader("3 · Asignación a recursos y máquinas")
    targets = [("resource", r.id) for r in model.resources if r.kind.value != "carrier"]
    targets += [("node", n.id) for n in model.nodes if app.registry.get(n.component).behavior.value in ("server", "source")]
    current = {**{k: v for k, v in av.resources.items()}, **{k: v for k, v in av.nodes.items()},
               **{x: "ALWAYS_AVAILABLE" for x in av.always_available}}
    st.dataframe(pd.DataFrame([{"tipo": k, "id": t, "calendario": current.get(t, "— sin declarar (siempre disponible) —")}
                               for k, t in targets]), hide_index=True)
    with st.form("cal_assign"):
        a, b = st.columns(2)
        tgt = a.selectbox("Recurso / nodo", [f"{k}:{t}" for k, t in targets])
        tcal = b.selectbox("Calendario a asignar", ["ALWAYS_AVAILABLE"] + [x.id for x in av.calendars])
        if st.form_submit_button("Asignar"):
            kind, t = tgt.split(":", 1)
            _apply(app, project, lambda: ce.assign(model, t, tcal, kind), f"calendar: {kind} {t} -> {tcal}")
    st.subheader("4 · Qué pasa cuando termina la disponibilidad")
    st.caption(POLICY_HELP)
    with st.form("cal_policy"):
        ops = [n.id for n in model.nodes if app.registry.get(n.component).behavior.value in ("server", "transport")]
        a, b, c = st.columns(3)
        node = a.selectbox("Operación (nodo)", ops)
        pol = av.operations.get(node) if ops else None
        at = b.selectbox("Fin de disponibilidad", POLICIES, index=POLICIES.index(pol.at_unavailability) if pol and pol.at_unavailability else 0)
        rule = c.selectbox("Regla de inicio", RULES, index=RULES.index(pol.start_rule) if pol and pol.start_rule else 0,
                           help="REQUIRE_FULL_WINDOW: no empieza si no cabe entera (solo tiempos deterministas)")
        reason = st.text_input("Motivo (opcional)")
        if st.form_submit_button("Guardar decisión"):
            _apply(app, project, lambda: ce.set_policy(model, node, at, rule, reason), f"calendar policy {node}: {at}, {rule}")
