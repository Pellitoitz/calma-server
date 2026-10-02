"""Verification of economic assumptions (engine >= 0.9.0). Never blocks the physical model: these issues only gate the
economic evaluation. A MISSING value is a WARNING (partial evaluation, clearly labelled), not an error."""

from __future__ import annotations

from ..domain.economics import UNSUPPORTED_BASES, Basis, EconomicsSpec
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level

B = Basis
ALLOWED = {
    "labor": {B.PER_PAID_HOUR, B.PER_PLANNED_HOUR, B.PER_BUSY_HOUR, B.PER_CALENDAR_HOUR},
    "machine": {B.PER_PLANNED_HOUR, B.PER_PROCESSING_HOUR, B.PER_SETUP_HOUR, B.PER_OPERATING_HOUR, B.PER_CALENDAR_HOUR,
                B.PER_CYCLE, B.FIXED_PER_RUN},
    "energy": {B.PER_KWH},
    "material": {B.PER_CONSUMED_UNIT, B.PER_GOOD_UNIT},
    "scrap": {B.PER_SCRAP_UNIT},
    "downtime": {B.PER_CORRECTIVE_DOWNTIME_HOUR},
    "revenue": {B.PER_GOOD_UNIT},
    "capex": {B.FIXED},
}
MAINT_BASIS = {"REPAIR_LABOR": B.PER_BUSY_HOUR, "PM_LABOR": B.PER_BUSY_HOUR, "PER_FAILURE": B.PER_FAILURE, "PER_PM": B.PER_PM}
OVERLAPPING_MACHINE = [{B.PER_PROCESSING_HOUR, B.PER_OPERATING_HOUR}, {B.PER_SETUP_HOUR, B.PER_OPERATING_HOUR},
                       {B.PER_PLANNED_HOUR, B.PER_CALENDAR_HOUR}]


def economics_issues(spec: EconomicsSpec, model, registry: ComponentRegistry) -> list[Issue]:
    out: list[Issue] = []

    def add(lvl, code, msg, path=None, hint=None):
        out.append(Issue(lvl, code, msg, path, hint))
    nodes = {n.id: n for n in model.nodes}
    resources = {r.id for r in model.resources}
    prod = getattr(model, "production", None)
    maint = getattr(model, "maintenance", None)
    products = set(prod.products) if prod is not None else set()

    def setups_at(n):
        return prod is not None and n in prod.setups

    for path, m in spec.all_money():
        cat = path.split(".")[0]
        if m.currency != spec.currency:
            add(Level.ERROR, "ECONOMICS_CURRENCY_MIXED", f"{path}: {m.currency} != moneda de la evaluación {spec.currency} "
                "(sin conversión de divisas en 0.9).", f"economics.{path}")
        if m.basis in UNSUPPORTED_BASES:
            add(Level.ERROR, "ECONOMICS_BASIS_UNSUPPORTED", f"{path}: {m.basis.value} no calculable: {UNSUPPORTED_BASES[m.basis]}.",
                f"economics.{path}")
        elif cat in ALLOWED and m.basis not in ALLOWED[cat]:
            add(Level.ERROR, "ECONOMICS_BASIS_INVALID", f"{path}: la base {m.basis.value} no aplica a '{cat}' "
                f"(admitidas: {sorted(b.value for b in ALLOWED[cat])}).", f"economics.{path}")
        if m.value is None:
            add(Level.WARNING, "ECONOMIC_INPUT_MISSING", f"{path}: valor MISSING (evaluación parcial; nunca se usa un valor típico).",
                f"economics.{path}")
        elif m.value < 0:
            add(Level.ERROR, "ECONOMICS_NEGATIVE", f"{path}: valor negativo ({m.value}) no soportado.", f"economics.{path}")
        if m.provenance is not None:
            st = m.provenance.status.value
            if st == "default":
                add(Level.ERROR, "ECONOMICS_DEFAULT_VALUE", f"{path}: un valor económico no puede ser un default de librería.",
                    f"economics.{path}")
            elif st == "assumed":
                add(Level.INFO, "ECONOMICS_ASSUMED", f"{path}: valor ASSUMED (visible en la evaluación).", f"economics.{path}")
    # references and physical magnitudes
    for i, x in enumerate(spec.labor):
        p = f"economics.labor.{i}"
        if x.resource not in resources:
            add(Level.ERROR, "UNKNOWN_RESOURCE", f"labor: el recurso '{x.resource}' no existe.", p)
        if x.rate.basis is B.PER_PAID_HOUR and x.paid_time is None:
            add(Level.ERROR, "ECONOMICS_PAID_TIME_RULE_MISSING", f"labor '{x.resource}': PER_PAID_HOUR necesita paid_time "
                "(CALENDAR_WINDOW | PLANNED_AVAILABLE | DECLARED); no se asume paid = planned.", p)
        if x.rate.basis is not B.PER_PAID_HOUR and (x.paid_time is not None or x.declared_paid_hours_per_unit is not None):
            add(Level.ERROR, "ECONOMICS_CONTRADICTORY", f"labor '{x.resource}': paid_time sólo con PER_PAID_HOUR.", p)
        if x.declared_paid_hours_per_unit is not None and x.declared_paid_hours_per_unit < 0:
            add(Level.ERROR, "ECONOMICS_NEGATIVE", f"labor '{x.resource}': horas pagadas negativas.", p)
        if x.paid_time == "DECLARED" and x.declared_paid_hours_per_unit is None:
            add(Level.WARNING, "ECONOMIC_INPUT_MISSING", f"labor '{x.resource}': DECLARED sin declared_paid_hours_per_unit.", p)
    for i, x in enumerate(spec.machine):
        p = f"economics.machine.{i}"
        if x.node not in nodes:
            add(Level.ERROR, "UNKNOWN_NODE", f"machine: el nodo '{x.node}' no existe.", p)
        elif x.rate.basis is B.PER_SETUP_HOUR and not setups_at(x.node):
            add(Level.WARNING, "ECONOMICS_NOT_APPLICABLE", f"machine '{x.node}': PER_SETUP_HOUR sin setups en el nodo.", p)
    if spec.energy is not None:
        for nid, states in spec.energy.power_kw.items():
            p = f"economics.energy.power_kw.{nid}"
            if nid not in nodes:
                add(Level.ERROR, "UNKNOWN_NODE", f"energy: el nodo '{nid}' no existe.", p)
            for s, kw in states.items():
                if kw < 0:
                    add(Level.ERROR, "ECONOMICS_NEGATIVE", f"energy '{nid}': potencia negativa en {s}.", p)
                if s == "SETUP" and not setups_at(nid):
                    add(Level.WARNING, "ECONOMICS_NOT_APPLICABLE", f"energy '{nid}': potencia SETUP sin setups en el nodo.", p)
        if not spec.energy.power_kw:
            add(Level.WARNING, "ECONOMIC_INPUT_MISSING", "energy: potencia declarada MISSING: sin ella no hay kWh (SimForge "
                "no modela energía y no la estima; nunca 0).", "economics.energy")
    for cat in ("material", "revenue"):
        for i, x in enumerate(getattr(spec, cat)):
            if x.product is not None:
                if x.product not in products:
                    add(Level.ERROR, "PRODUCT_UNKNOWN", f"{cat}: el producto '{x.product}' no existe.", f"economics.{cat}.{i}")
                if x.rate.basis is not B.PER_GOOD_UNIT:
                    add(Level.ERROR, "ECONOMICS_BASIS_INVALID", f"{cat} por producto sólo con PER_GOOD_UNIT (el scrap por "
                        "producto no está en los resultados físicos).", f"economics.{cat}.{i}")
    for i, x in enumerate(spec.maintenance):
        p = f"economics.maintenance.{i}"
        if x.rate.basis is not MAINT_BASIS[x.kind]:
            add(Level.ERROR, "ECONOMICS_BASIS_INVALID", f"maintenance {x.kind}: base {MAINT_BASIS[x.kind].value} obligatoria.", p)
        if x.node not in nodes or maint is None or x.node not in maint.nodes:
            add(Level.ERROR, "ECONOMICS_NO_PHYSICAL_METRIC", f"maintenance: '{x.node}' no tiene bloque maintenance (no hay "
                "averías/PM físicos que valorar).", p)
        if x.kind.endswith("_LABOR") and x.resource not in resources:
            add(Level.ERROR, "UNKNOWN_RESOURCE", f"maintenance {x.kind}: recurso '{x.resource}' inexistente.", p)
    for i, x in enumerate(spec.downtime):
        p = f"economics.downtime.{i}"
        if maint is None or x.node not in maint.nodes or maint.nodes[x.node].failure is None:
            add(Level.ERROR, "ECONOMICS_NO_PHYSICAL_METRIC", f"downtime: '{x.node}' no tiene modelo de avería (maintenance).", p)
    if spec.annualization is not None and spec.annualization.runs_per_year <= 0:
        add(Level.ERROR, "ECONOMICS_ANNUALIZATION_INVALID", "runs_per_year debe ser > 0.", "economics.annualization")
    # double counting -> REQUIRES_ENGINEER_DECISION (never summed silently)
    red: set[str] = set()
    by_res: dict[str, list[int]] = {}
    for i, x in enumerate(spec.labor):
        by_res.setdefault(x.resource, []).append(i)
    for r, idx in by_res.items():
        if len(idx) > 1:
            red |= {f"labor.{i}" for i in idx}
    for i, x in enumerate(spec.maintenance):
        if x.kind.endswith("_LABOR") and x.resource in by_res:
            red.add(f"maintenance.{i}")
    by_node: dict[str, list[int]] = {}
    for i, x in enumerate(spec.machine):
        by_node.setdefault(x.node, []).append(i)
    for nid, idx in by_node.items():
        bases = [spec.machine[i].rate.basis for i in idx]
        for i in idx:
            b = spec.machine[i].rate.basis
            if bases.count(b) > 1 or any(b in pair and (pair - {b}) & set(bases) for pair in OVERLAPPING_MACHINE):
                red.add(f"machine.{i}")
    consumed = [i for i, x in enumerate(spec.material) if x.rate.basis is B.PER_CONSUMED_UNIT]
    if consumed:
        red |= {f"scrap.{i}" for i in range(len(spec.scrap))}
        if len(spec.material) > 1:
            red |= {f"material.{i}" for i in range(len(spec.material))}
    glob = [i for i, x in enumerate(spec.material) if x.product is None]
    if glob and any(x.product for x in spec.material):
        red |= {f"material.{i}" for i in range(len(spec.material))}
    if any(x.product is None for x in spec.revenue) and any(x.product for x in spec.revenue):
        red |= {f"revenue.{i}" for i in range(len(spec.revenue))}
    for path in sorted(red):
        add(Level.ERROR, "REQUIRES_ENGINEER_DECISION", f"{path}: posible doble conteo (mismo recurso/nodo/unidades valorados "
            "dos veces o categorías solapadas); no se suma hasta que el ingeniero lo resuelva.", path)
    return out
