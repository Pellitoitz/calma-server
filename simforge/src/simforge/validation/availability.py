"""Validation of the `availability` extension (calendars, assignments, operation policies).

Levels: the frozen verifier's Level has ERROR / WARNING / INFO. REQUIRES_ENGINEER_DECISION is reported as
Level.ERROR with a code starting with `DECISION_` (it blocks execution like an error, but it is a decision the engineer
must take, not a defect): nothing is resolved silently.
"""

from __future__ import annotations

from typing import Any

from ..domain.calendar import (
    AVAILABLE,
    DAY_S,
    DAYS,
    AvailabilitySpec,
    Calendar,
    _Clock,
    expand,
    intersect,
    intersect_timelines,
    measure,
    union,
)
from ..domain.isms import ISMSModel, ResourceKind
from ..domain.units import Dimension
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level

POLICY_BEHAVIORS = ("server", "transport")
CALENDAR_NODE_BEHAVIORS = ("server", "source")


def _behavior(registry: ComponentRegistry, component: str) -> str | None:
    try:
        return registry.get(component).behavior.value
    except Exception:  # noqa: BLE001 - unknown component: the core verifier reports it
        return None


def _is_random(pt: Any) -> bool:
    if not isinstance(pt, dict):
        return False
    if pt.get("dist") == "constant":
        return False
    return not (pt.get("dist") == "empirical" and len(set(pt.get("values") or [])) <= 1)


def calendared_requirements(model: ISMSModel, spec: AvailabilitySpec, registry: ComponentRegistry) -> dict[str, list[str]]:
    """node id -> calendars that gate it (its own + those of the operators/tools it uses)."""
    out: dict[str, list[str]] = {}
    for n in model.nodes:
        beh = _behavior(registry, n.component)
        cals = []
        if n.id in spec.nodes:
            cals.append(spec.nodes[n.id])
        if beh in POLICY_BEHAVIORS:
            for use in n.params.get("resources", []) or []:
                rid = use.get("resource") if isinstance(use, dict) else None
                if rid in spec.resources:
                    cals.append(spec.resources[rid])
        if cals:
            out[n.id] = cals
    return out


def _calendar_issues(spec: AvailabilitySpec, cal: Calendar, add) -> None:
    p = f"availability.calendars.{cal.id}"
    # shifts: one generic week, absolute seconds from Monday 00:00, overnight windows included
    abs_w: list[tuple[float, float, str]] = []
    for di, d in enumerate(DAYS):
        for w in cal.weekly.get(d, []):  # type: ignore[call-overload]
            abs_w.append((di * DAY_S + w.start_s, di * DAY_S + w.end_s, f"{d} {w.label()}"))
    abs_w += [(a + 7 * DAY_S, b + 7 * DAY_S, lab) for a, b, lab in abs_w if a < DAY_S]  # wrap Sunday night -> Monday
    seen = set()
    for i, (a1, b1, l1) in enumerate(abs_w):
        for a2, b2, l2 in abs_w[i + 1:]:
            if a1 < b2 and a2 < b1 and (l1, l2) not in seen:
                seen.add((l1, l2))
                code = "CAL_DUPLICATE_SHIFT" if (a1, b1) == (a2, b2) else "CAL_SHIFT_OVERLAP"
                add(Level.ERROR, code, f"'{cal.id}': {l1} y {l2} se solapan: doble disponibilidad. Une o corrige los turnos.", p)
    working = union([(a, b) for a, b, _ in abs_w] + [(a - 7 * DAY_S, b - 7 * DAY_S) for a, b, _ in abs_w if b > 7 * DAY_S])
    brk_abs = []
    for b in cal.breaks:
        days = b.days or DAYS
        total, inside = 0.0, 0.0
        for d in days:
            di = DAYS.index(d)
            iv = (di * DAY_S + b.start_s, di * DAY_S + b.end_s)
            brk_abs.append(iv)
            total += iv[1] - iv[0]
            inside += measure(intersect([iv], working))
        if inside == 0:
            add(Level.WARNING, "CAL_BREAK_OUTSIDE_WORKING", f"'{cal.id}': el descanso {b.label()} nunca cae en tiempo de trabajo "
                "(no descuenta nada).", p)
        elif inside < total - 1e-6:
            add(Level.WARNING, "CAL_BREAK_PARTIAL", f"'{cal.id}': el descanso {b.label()} cae en parte fuera del turno: solo "
                "descuenta la parte dentro.", p)
    if measure(brk_abs) < sum(b - a for a, b in brk_abs) - 1e-6:
        add(Level.WARNING, "CAL_BREAKS_OVERLAP", f"'{cal.id}': hay descansos solapados: se unen (no se descuentan dos veces).", p)
    # exceptions
    if cal.exceptions and spec.mode != "dated":
        add(Level.ERROR, "CAL_EXCEPTIONS_NEED_DATES", f"'{cal.id}' tiene excepciones con fecha pero el modo es 'relative_week': "
            "usa mode 'dated' (con timezone) o expresa el cambio en el patrón semanal.", p)
    by_date: dict = {}
    for e in cal.exceptions:
        by_date.setdefault(e.date, []).append(e)
        if e.type == "NON_WORKING_DAY" and e.scope is None and cal.has_overnight:
            add(Level.ERROR, "DECISION_HOLIDAY_SCOPE", f"'{cal.id}' {e.date}: el calendario tiene turnos nocturnos; decide si el "
                "festivo quita los turnos que EMPIEZAN ese día (SHIFTS_STARTING_ON_DATE) o todo el día civil (CALENDAR_DAY).", p)
        if e.type != "NON_WORKING_DAY" and e.breaks_apply is None and cal.breaks:
            add(Level.ERROR, "DECISION_EXCEPTION_BREAKS", f"'{cal.id}' {e.date} {e.type}: decide si los descansos del calendario "
                "se aplican dentro de estos intervalos (breaks_apply true/false).", p)
    for d, es in by_date.items():
        types = {e.type for e in es}
        if "NON_WORKING_DAY" in types and len(types) > 1:
            add(Level.ERROR, "CAL_CONTRADICTORY_EXCEPTIONS", f"'{cal.id}' {d}: NON_WORKING_DAY junto con {sorted(types - {'NON_WORKING_DAY'})}.", p)
        if sum(e.type == "OVERRIDE_WORKING_INTERVALS" for e in es) > 1:
            add(Level.ERROR, "CAL_CONTRADICTORY_EXCEPTIONS", f"'{cal.id}' {d}: dos OVERRIDE_WORKING_INTERVALS el mismo día.", p)
        ivs = [w for e in es for w in e.intervals]
        for i, w1 in enumerate(ivs):
            for w2 in ivs[i + 1:]:
                if w1.start_s < w2.end_s and w2.start_s < w1.end_s:
                    add(Level.ERROR, "CAL_SHIFT_OVERLAP", f"'{cal.id}' {d}: intervalos de excepción solapados ({w1.label()}, {w2.label()}).", p)


def availability_issues(model: ISMSModel, registry: ComponentRegistry) -> list[Issue]:
    spec: AvailabilitySpec | None = getattr(model, "availability", None)
    if spec is None:
        return []
    out: list[Issue] = []

    def add(lvl, code, msg, path=None, hint=None):
        out.append(Issue(lvl, code, msg, path, hint))

    # mode / clock
    if spec.mode == "dated":
        if not spec.start_date:
            add(Level.ERROR, "CAL_START_DATE_MISSING", "modo 'dated' sin start_date.", "availability.start_date")
        if not spec.timezone:
            add(Level.ERROR, "CAL_TIMEZONE_MISSING", "modo 'dated' sin timezone: indica una zona IANA (p. ej. Europe/Madrid o UTC); "
                "no se asume ninguna.", "availability.timezone")
        else:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(spec.timezone)
            except Exception:  # noqa: BLE001
                add(Level.ERROR, "CAL_TIMEZONE_UNKNOWN", f"zona horaria desconocida '{spec.timezone}'.", "availability.timezone")
    ids = [c.id for c in spec.calendars]
    for d in {i for i in ids if ids.count(i) > 1}:
        add(Level.ERROR, "CAL_DUPLICATE_ID", f"calendario '{d}' definido dos veces.", "availability.calendars")
    for c in spec.calendars:
        _calendar_issues(spec, c, add)
    # assignments
    res = {r.id: r for r in model.resources}
    nodes = {n.id: n for n in model.nodes}
    for rid, cid in spec.resources.items():
        if rid not in res:
            add(Level.ERROR, "CAL_UNKNOWN_TARGET", f"calendario asignado a recurso inexistente '{rid}'.", f"availability.resources.{rid}")
        elif res[rid].kind is ResourceKind.CARRIER:
            add(Level.ERROR, "CAL_CARRIER_UNSUPPORTED", f"'{rid}' es un carrier (bastidor/palet): existe siempre; un calendario "
                "no tiene sentido físico en esta versión.", f"availability.resources.{rid}")
        if cid not in ids:
            add(Level.ERROR, "CAL_UNKNOWN_CALENDAR", f"'{rid}' referencia el calendario inexistente '{cid}'.", f"availability.resources.{rid}")
    for nid, cid in spec.nodes.items():
        if nid not in nodes:
            add(Level.ERROR, "CAL_UNKNOWN_TARGET", f"calendario asignado a nodo inexistente '{nid}'.", f"availability.nodes.{nid}")
        else:
            beh = _behavior(registry, nodes[nid].component)
            if beh not in CALENDAR_NODE_BEHAVIORS:
                add(Level.ERROR, "CAL_NODE_UNSUPPORTED", f"'{nid}' ({beh}): solo máquinas/puestos (server) y fuentes admiten calendario "
                    "propio; para transportes, asigna el calendario a sus recursos.", f"availability.nodes.{nid}")
        if cid not in ids:
            add(Level.ERROR, "CAL_UNKNOWN_CALENDAR", f"'{nid}' referencia el calendario inexistente '{cid}'.", f"availability.nodes.{nid}")
    for x in spec.always_available:
        if x not in res and x not in nodes:
            add(Level.ERROR, "CAL_UNKNOWN_TARGET", f"always_available: '{x}' no existe.", "availability.always_available")
        if x in spec.resources or x in spec.nodes:
            add(Level.ERROR, "CAL_CONTRADICTORY_ASSIGNMENT", f"'{x}' tiene calendario y está en always_available.", "availability.always_available")
    for r in model.resources:
        if r.kind is not ResourceKind.CARRIER and r.id not in spec.resources and r.id not in spec.always_available:
            add(Level.WARNING, "CAL_AVAILABILITY_UNDECLARED", f"'{r.id}' sin calendario: disponible siempre (compatibilidad). Si es "
                "intencionado, decláralo en always_available.", f"availability.resources.{r.id}")
    for n in model.nodes:
        if _behavior(registry, n.component) == "server" and n.id not in spec.nodes and n.id not in spec.always_available:
            add(Level.WARNING, "CAL_AVAILABILITY_UNDECLARED", f"'{n.id}' sin calendario propio: la máquina/puesto está disponible siempre "
                "(su capacidad la limitan los calendarios de sus recursos). Decláralo en always_available si es intencionado.",
                f"availability.nodes.{n.id}")
    if any(i.level is Level.ERROR and i.code.startswith(("CAL_UNKNOWN", "CAL_TIMEZONE", "CAL_START")) for i in out):
        return out
    # operation policies
    req = calendared_requirements(model, spec, registry)
    for nid in spec.operations:
        if nid not in nodes:
            add(Level.ERROR, "CAL_UNKNOWN_TARGET", f"política para nodo inexistente '{nid}'.", f"availability.operations.{nid}")
    for nid, cals in req.items():
        n = nodes[nid]
        beh = _behavior(registry, n.component)
        if beh not in POLICY_BEHAVIORS:
            continue
        pol = spec.operations.get(nid)
        path = f"availability.operations.{nid}"
        if pol is None or pol.at_unavailability is None:
            add(Level.ERROR, "DECISION_INTERRUPTION_POLICY", f"'{nid}' depende de calendarios {sorted(set(cals))}: decide qué pasa con una "
                "operación en curso cuando termina la disponibilidad: FINISH_CURRENT (termina), PAUSE_RESUME (pausa y continúa) o "
                "STOP_RESTART (se pierde y empieza de nuevo).", path)
        if pol is None or pol.start_rule is None:
            add(Level.ERROR, "DECISION_START_RULE", f"'{nid}': decide si una operación puede empezar aunque no quepa en el tiempo disponible "
                "restante (START_ANY_TIME) o solo si cabe entera (REQUIRE_FULL_WINDOW, solo tiempos deterministas).", path)
        if pol is None:
            continue
        if beh == "transport" and pol.at_unavailability not in (None, "FINISH_CURRENT"):
            add(Level.ERROR, "CAL_POLICY_UNSUPPORTED", f"'{nid}' es un transporte: en esta versión un viaje iniciado siempre termina "
                "(solo FINISH_CURRENT).", path)
        if pol.start_rule == "REQUIRE_FULL_WINDOW":
            if beh != "server":
                add(Level.ERROR, "CAL_POLICY_UNSUPPORTED", f"'{nid}': REQUIRE_FULL_WINDOW solo está soportado en máquinas/puestos.", path)
            elif _is_random(n.params.get("process_time")):
                add(Level.ERROR, "CAL_POLICY_UNSUPPORTED", f"'{nid}': REQUIRE_FULL_WINDOW con tiempo aleatorio NO está soportado: saber si "
                    "'cabe' exigiría conocer la muestra futura antes de empezar. Usa START_ANY_TIME o un tiempo determinista.", path)
    # horizon-based checks
    try:
        horizon = model.simulation.horizon.to_base(Dimension.TIME)
        tls = {c.id: expand(spec, c, horizon) for c in spec.calendars}
    except Exception as e:  # noqa: BLE001
        add(Level.ERROR, "CAL_EXPANSION_FAILED", f"no se pudo expandir el calendario: {e}", "availability")
        return out
    for c in spec.calendars:
        if not tls[c.id].available:
            add(Level.WARNING, "CAL_NO_AVAILABILITY_IN_HORIZON", f"'{c.id}' no tiene tiempo disponible en el horizonte simulado.",
                f"availability.calendars.{c.id}")
        if spec.mode == "dated" and spec.start_date:
            clock = _Clock(spec)
            for e in c.exceptions:
                if not 0 <= clock.at((e.date - spec.start_date).days, 0) < horizon:
                    add(Level.WARNING, "CAL_EXCEPTION_OUTSIDE_HORIZON", f"'{c.id}' excepción {e.date} fuera del horizonte simulado.",
                        f"availability.calendars.{c.id}")
    for nid, cals in req.items():
        common = intersect_timelines([tls[c] for c in cals if c in tls], horizon)
        pol = spec.operations.get(nid)
        pt = nodes[nid].params.get("process_time")
        if pol and pol.start_rule == "REQUIRE_FULL_WINDOW" and isinstance(pt, dict) and pt.get("dist") == "constant":
            try:
                from ..domain.units import to_base
                wu = nodes[nid].params.get("work_units", 1)
                factor = 1.0 if nodes[nid].params.get("work_units_aggregation") == "single_sample" else float(wu)
                need = to_base(float(pt["value"]), pt.get("unit", "s"), Dimension.TIME) * factor
                longest = max((b - a for a, b in common.available), default=0.0)
                if common.available and need > longest + 1e-9:
                    add(Level.WARNING, "CAL_NEVER_FITS", f"'{nid}': la operación ({need:g} s) es más larga que cualquier ventana disponible "
                        f"({longest:g} s): con REQUIRE_FULL_WINDOW no empezará nunca.", f"availability.operations.{nid}")
            except (TypeError, ValueError):
                pass  # parameter expressions: checked at run time
        if len(set(cals)) > 1 and not common.available:
            add(Level.WARNING, "CAL_NO_COMMON_AVAILABILITY", f"'{nid}': sus calendarios {sorted(set(cals))} no coinciden nunca en el "
                "horizonte: la operación no podrá ejecutarse.", f"availability.operations.{nid}")
    if spec.mode == "dated" and spec.timezone:
        _dst_issues(spec, add)
    return out


def _dst_issues(spec: AvailabilitySpec, add) -> None:
    """Warn when a window boundary falls on a DST gap/fold (wall time that does not exist or exists twice)."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(spec.timezone)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return
    for c in spec.calendars:
        times = {w.start for ws in c.weekly.values() for w in ws} | {w.end for ws in c.weekly.values() for w in ws}
        for e in c.exceptions:
            times |= {w.start for w in e.intervals} | {w.end for w in e.intervals}
        year = spec.start_date.year if spec.start_date else 2026
        for t in times:
            if t == "24:00":
                continue
            h, m = (int(x) for x in t.split(":")[:2])
            for month in range(1, 13):
                for day in range(1, 32):
                    try:
                        local = dt.datetime(year, month, day, h, m, tzinfo=tz)
                    except ValueError:
                        continue
                    back = local.astimezone(dt.timezone.utc).astimezone(tz)
                    other = local.replace(fold=1)
                    gap = back.replace(tzinfo=None) != local.replace(tzinfo=None)
                    if gap or other.utcoffset() != local.utcoffset():
                        how = (f"no existe (salto de hora): se interpreta como {back:%H:%M} (zoneinfo, fold=0)" if gap else
                               "se repite (retraso de hora): se usa la PRIMERA ocurrencia (fold=0)")
                        add(Level.WARNING, "CAL_DST_BOUNDARY", f"'{c.id}': la hora {t} del {year}-{month:02d}-{day:02d} en {spec.timezone} "
                            f"{how}; ese turno dura más o menos de lo nominal. Revísalo o declara la hora explícitamente.",
                            f"availability.calendars.{c.id}")
                        break
                else:
                    continue
                break


def planned_summary(model: ISMSModel, registry: ComponentRegistry) -> list[dict]:
    """Planned availability per calendar-gated resource/node over the simulated horizon (for reports/UI)."""
    spec: AvailabilitySpec | None = getattr(model, "availability", None)
    if spec is None:
        return []
    horizon = model.simulation.horizon.to_base(Dimension.TIME)
    tls = {c.id: expand(spec, c, horizon) for c in spec.calendars}
    rows = []
    for rid, cid in spec.resources.items():
        tl = tls.get(cid)
        if tl:
            rows.append({"kind": "resource", "id": rid, "calendar": cid, "calendar_time_s": horizon,
                         "planned_available_s": tl.time_in(AVAILABLE, 0, horizon), "break_s": tl.time_in("break", 0, horizon),
                         "off_shift_s": tl.time_in("off_shift", 0, horizon)})
    for nid, cals in calendared_requirements(model, spec, registry).items():
        tl = intersect_timelines([tls[c] for c in cals if c in tls], horizon)
        pol = spec.operations.get(nid)
        rows.append({"kind": "node", "id": nid, "calendar": "∩".join(dict.fromkeys(cals)), "calendar_time_s": horizon,
                     "planned_available_s": tl.time_in(AVAILABLE, 0, horizon), "break_s": tl.time_in("break", 0, horizon),
                     "off_shift_s": tl.time_in("off_shift", 0, horizon),
                     "at_unavailability": pol.at_unavailability if pol else None, "start_rule": pol.start_rule if pol else None})
    return rows
