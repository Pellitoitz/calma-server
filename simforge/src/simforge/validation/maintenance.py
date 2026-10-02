"""Verification of the `maintenance` extension block (engine >= 0.8.0). No physical default is ever assumed."""

from __future__ import annotations

from ..domain.isms import ISMSModel
from ..domain.maintenance import EXPOSURE_STATES, MaintenanceSpec
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level


def _behavior(registry: ComponentRegistry, component: str) -> str | None:
    try:
        return registry.get(component).behavior.value
    except Exception:  # noqa: BLE001 - unknown component: the core verifier reports it
        return None


def _const(d) -> float | None:
    return d.mean_seconds() if d is not None and d.is_deterministic else None


def maintenance_issues(model: ISMSModel, registry: ComponentRegistry, compiled=None) -> list[Issue]:
    spec: MaintenanceSpec | None = getattr(model, "maintenance", None)
    if spec is None:
        return []
    out: list[Issue] = []

    def add(lvl, code, msg, path=None, hint=None):
        out.append(Issue(lvl, code, msg, path, hint))
    nodes = {n.id: n for n in model.nodes}
    resources = {r.id: r for r in model.resources}
    av = getattr(model, "availability", None)
    prod = getattr(model, "production", None)

    def held_while_down(nid: str) -> set[str]:
        """Resources a node keeps while it is DOWN (processing/setup resources of an interrupted activity)."""
        n = nodes[nid]
        p = n.params if isinstance(n.params, dict) else {}
        held = {u.get("resource") for u in p.get("resources", []) or [] if isinstance(u, dict)}
        if prod is not None and nid in prod.setups:
            held |= {u.resource for u in prod.setups[nid].resources}
        return held
    can_fail = {n.id for n in model.nodes if isinstance(n.params, dict) and n.params.get("failures")}
    can_fail |= {nid for nid, nm in spec.nodes.items() if nm.failure is not None}
    held_by_failing = set().union(*(held_while_down(n) for n in can_fail if n in nodes)) if can_fail else set()

    def check_resources(uses, path, what, repair: bool):
        if len(uses) > 1:
            add(Level.ERROR, "MAINTENANCE_MULTI_RESOURCE_UNSUPPORTED",
                f"{what}: más de un recurso no está soportado en 0.8 (adquisición secuencial con riesgo de bloqueo).", path)
        for u in uses:
            r = resources.get(u.resource)
            if r is None:
                add(Level.ERROR, "UNKNOWN_RESOURCE", f"{what} requiere '{u.resource}', que no existe.", path)
                continue
            if isinstance(r.quantity, int) and r.quantity < u.quantity:
                add(Level.ERROR, "RESOURCE_SHORT", f"{what} requiere {u.quantity} × '{r.id}' y sólo hay {r.quantity}.", path)
            if r.kind.value == "carrier":
                add(Level.ERROR, "MAINTENANCE_CARRIER_UNSUPPORTED", f"'{r.id}' es un carrier: no es un recurso de mantenimiento.", path)
            if r.dispatch.value == "wip_target":
                add(Level.ERROR, "MAINTENANCE_RESOURCE_WIP_TARGET_UNSUPPORTED",
                    f"'{r.id}' usa WIP_TARGET: la clasificación de tareas de mantenimiento no está definida en 0.8.", path)
            if repair and u.resource in held_by_failing:
                add(Level.ERROR, "MAINTENANCE_RESOURCE_DEADLOCK_RISK",
                    f"'{u.resource}' repara '{what}' y también lo retiene una máquina averiable mientras está DOWN "
                    "(recurso de proceso/setup): posible bloqueo circular.", path,
                    "Usa un recurso de reparación distinto de los recursos de proceso/setup de máquinas averiables.")

    for nid, nm in spec.nodes.items():
        path = f"maintenance.nodes.{nid}"
        if nid not in nodes:
            add(Level.ERROR, "MAINTENANCE_UNKNOWN_NODE", f"El nodo '{nid}' no existe.", path)
            continue
        if _behavior(registry, nodes[nid].component) != "server":
            add(Level.ERROR, "MAINTENANCE_NOT_SERVER", f"'{nid}' no es una estación de proceso: no admite mantenimiento.", path)
            continue
        params = nodes[nid].params if isinstance(nodes[nid].params, dict) else {}
        cap = compiled.nodes[nid].params.capacity if compiled is not None and nid in compiled.nodes else params.get("capacity", 1)
        if cap != 1:
            add(Level.ERROR, "MAINTENANCE_MULTI_SLOT_UNSUPPORTED",
                f"'{nid}' tiene capacity = {cap}: actividad en curso / reserva para PM por slot o por nodo no está "
                "definida; 0.8 sólo soporta mantenimiento con capacity 1.", f"nodes.{nid}.params.capacity")
        if nm.failure is not None and params.get("failures"):
            add(Level.ERROR, "MAINTENANCE_LEGACY_CONFLICT", f"'{nid}' tiene params.failures (legacy) y maintenance.failure.",
                f"nodes.{nid}.params.failures", "Usa uno de los dos (el legacy conserva su contrato histórico).")
        if not nm.failure and not nm.preventive:
            add(Level.WARNING, "MAINTENANCE_EMPTY", f"'{nid}' no define failure ni preventive.", path)
        own_cal = av is not None and nid in av.nodes
        f = nm.failure
        if f is not None:
            fp = f"{path}.failure"
            bad = [s for s in f.exposure if s not in EXPOSURE_STATES]
            if bad:
                add(Level.ERROR, "MAINTENANCE_EXPOSURE_UNSUPPORTED", f"exposure {bad} no soportado: sólo {list(EXPOSURE_STATES)} "
                    "(IDLE, OFF_SHIFT, BREAK, DOWN, WAITING_RESOURCE y MAINTENANCE no envejecen la máquina en 0.8).", f"{fp}.exposure")
            if f.clock == "OPERATING_TIME" and not f.exposure:
                add(Level.ERROR, "MISSING", f"'{nid}': OPERATING_TIME necesita exposure explícito (p. ej. [PROCESSING]).", f"{fp}.exposure")
            if f.clock == "ELAPSED_TIME" and f.exposure:
                add(Level.ERROR, "MAINTENANCE_CONTRADICTORY", f"'{nid}': ELAPSED_TIME no admite exposure (el reloj corre siempre "
                    "salvo durante la avería y el PM activo).", f"{fp}.exposure")
            if len(set(f.exposure)) != len(f.exposure):
                add(Level.ERROR, "MAINTENANCE_CONTRADICTORY", f"'{nid}': exposure con estados repetidos.", f"{fp}.exposure")
            if f.time_to_failure.mean_seconds() <= 0:
                add(Level.ERROR, "BAD_PARAM", f"'{nid}': time_to_failure debe ser > 0.", f"{fp}.time_to_failure")
            if f.repair_time.mean_seconds() <= 0:
                add(Level.ERROR, "BAD_PARAM", f"'{nid}': repair_time debe ser > 0.", f"{fp}.repair_time")
            if f.repair_age_effect == "NO_RESET":
                add(Level.ERROR, "MAINTENANCE_REPAIR_NO_RESET_UNSUPPORTED",
                    f"'{nid}': NO_RESET tras una reparación correctiva dejaría la edad en el umbral ya alcanzado (fallo "
                    "inmediato); exigiría reparación mínima / edad virtual, no soportadas en 0.8.", f"{fp}.repair_age_effect")
            check_resources(f.repair_resources, f"{fp}.repair_resources", f"la reparación de '{nid}'", repair=True)
            gated = av is not None and any(u.resource in av.resources for u in f.repair_resources)
            if gated and f.resource_unavailability_policy is None:
                add(Level.ERROR, "MISSING", f"'{nid}': el recurso de reparación tiene calendario; declara "
                    "resource_unavailability_policy (FINISH_CURRENT es la única soportada en 0.8).", f"{fp}.resource_unavailability_policy")
        ids = [t.id for t in nm.preventive]
        if len(ids) != len(set(ids)):
            add(Level.ERROR, "MAINTENANCE_CONTRADICTORY", f"'{nid}': ids de PM repetidos {ids}.", f"{path}.preventive")
        for i, t in enumerate(nm.preventive):
            tp = f"{path}.preventive[{i}]"
            if t.trigger == "CALENDAR_BASED":
                fd, ev = _const(t.first_due), _const(t.every) if t.every is not None else None
                if fd is None or fd < 0:
                    add(Level.ERROR, "BAD_PARAM", f"PM '{t.id}': first_due debe ser una constante >= 0.", f"{tp}.first_due")
                if t.every is not None and (ev is None or ev <= 0):
                    add(Level.ERROR, "BAD_PARAM", f"PM '{t.id}': every debe ser una constante > 0.", f"{tp}.every")
            else:
                th = _const(t.usage_threshold)
                if th is None or th <= 0:
                    add(Level.ERROR, "BAD_PARAM", f"PM '{t.id}': usage_threshold debe ser una constante > 0.", f"{tp}.usage_threshold")
                bad = [s for s in t.usage_states if s not in EXPOSURE_STATES]
                if bad:
                    add(Level.ERROR, "MAINTENANCE_EXPOSURE_UNSUPPORTED", f"PM '{t.id}': usage_states {bad} no soportado.", f"{tp}.usage_states")
            if t.duration.mean_seconds() <= 0:
                add(Level.ERROR, "BAD_PARAM", f"PM '{t.id}': duration debe ser > 0.", f"{tp}.duration")
            check_resources(t.resources, f"{tp}.resources", f"el PM '{t.id}' de '{nid}'", repair=False)
            gated = own_cal or (av is not None and any(u.resource in av.resources for u in t.resources))
            if gated and t.at_unavailability is None:
                add(Level.ERROR, "MISSING", f"PM '{t.id}': '{nid}' o su recurso tiene calendario; declara at_unavailability "
                    "(FINISH_CURRENT es la única soportada en 0.8).", f"{tp}.at_unavailability")
    return out
