"""Semantic checks that complement the (frozen) verifier without changing it.

The verifier (validation/verifier.py) is part of the frozen LLM benchmark V1 contract, so new model-level warnings
live here and are appended to its report by `verify_model` (used by the app, CLI and reports). The benchmark keeps
calling the plain verifier.
"""

from __future__ import annotations

from typing import Any

from ..domain.isms import ISMSModel
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level, Readiness, VerificationReport, verify


def _is_random(pt: Any) -> bool:
    if not isinstance(pt, dict):
        return False
    if pt.get("dist") == "constant":
        return False
    if pt.get("dist") == "empirical" and len(set(pt.get("values") or [])) <= 1:
        return False
    return True


def semantic_issues(model: ISMSModel, registry: ComponentRegistry) -> list[Issue]:
    out: list[Issue] = []
    for n in model.nodes:
        p = n.params
        if "work_units" not in p:
            continue
        try:
            beh = registry.get(n.component).behavior.value
        except Exception:  # noqa: BLE001 - unknown component: the verifier reports it
            continue
        if beh != "server":
            continue
        wu = p.get("work_units", 1)
        if wu == 1 or p.get("work_units_aggregation") or not _is_random(p.get("process_time")):
            continue
        out.append(Issue(Level.WARNING, "WORK_UNITS_AGGREGATION_UNDECLARED",
                         f"'{n.id}': work_units = {wu} con tiempo aleatorio y sin work_units_aggregation: se aplica el "
                         "comportamiento histórico k·X (una muestra multiplicada, Var = k²·Var(X)).",
                         f"nodes.{n.id}.params.work_units_aggregation",
                         "Declara sum_iid (X1+…+Xk, una muestra por unidad), scale_sample (k·X) o single_sample (X)."))
    return out


def verify_model(model: ISMSModel, registry: ComponentRegistry):
    """verify() on the ISMS core + semantic warnings + extension blocks (calendars, production).

    Returns (report, compiled). With an extension block the compiled model is a CalendarCompiledModel (availability
    and/or production runtime); the approval state is re-evaluated on the FULL model (the core view has another hash)."""
    from .availability import availability_issues
    from .maintenance import maintenance_issues
    from .production import production_issues, verification_view
    spec = getattr(model, "availability", None)
    prod = getattr(model, "production", None)
    maint = getattr(model, "maintenance", None)
    if spec is None and prod is None and maint is None:
        # non-physical blocks (economics) never reach the frozen verifier: it sees the physical core (same content hash)
        physical = model.core() if getattr(model, "economics", None) is not None else model  # type: ignore[attr-defined]
        rep, compiled = verify(physical, registry)
        rep.issues.extend(semantic_issues(model, registry))
        return rep, compiled
    core = model.core()  # type: ignore[attr-defined]
    timed, routed = set(), set()
    if prod is not None:
        core, timed, routed = verification_view(core, prod)
    rep, compiled = verify(core, registry)
    rep.confirmed_values -= len(timed)  # neutral placeholders are not values of the model
    rep.issues.extend(semantic_issues(model, registry))
    rep.issues = [i for i in rep.issues if i.code != "APPROVAL_STALE"]
    if model.approval.approved and not model.is_approved:
        rep.issues.append(Issue(Level.WARNING, "APPROVAL_STALE",
                                "El modelo cambió después de la aprobación del ingeniero: la aprobación ya no es válida."))
    prod_issues = production_issues(model, registry, compiled) + maintenance_issues(model, registry, compiled)
    ext_issues = availability_issues(model, registry) + prod_issues
    if (prod is not None or maint is not None) and model.simulation.replications < 5 \
            and not any(i.code == "FEW_REPLICATIONS" for i in rep.issues):
        durs = []
        if prod is not None:
            durs += [d for t in prod.processing.values() for d in t.values()] + [d for s in prod.setups.values() for d in s.durations()]
        if maint is not None:
            for nm in maint.nodes.values():
                if nm.failure is not None:
                    durs += [nm.failure.time_to_failure, nm.failure.repair_time]
                durs += [t.duration for t in nm.preventive]
        mixes = prod is not None and any(g.mode == "PROBABILISTIC_MIX" for g in prod.generation.values())
        if any(not d.is_deterministic for d in durs) or mixes:
            ext_issues.append(Issue(Level.WARNING, "FEW_REPLICATIONS",
                                    f"Modelo estocástico con {model.simulation.replications} replicación(es): los resultados "
                                    "no son concluyentes.", "simulation.replications", "Usa ≥ 10 replicaciones (30 recomendado)."))
    rep.issues.extend(ext_issues)
    if rep.readiness in (Readiness.EXECUTABLE, Readiness.ENGINEER_APPROVED):
        if any(i.level is Level.ERROR and i.code == "MISSING" for i in prod_issues):
            rep.readiness = Readiness.INCOMPLETE
        elif any(i.level is Level.ERROR for i in ext_issues):
            rep.readiness = Readiness.CONFIGURED
        else:
            rep.readiness = Readiness.ENGINEER_APPROVED if model.is_approved else Readiness.EXECUTABLE
    if compiled is None or rep.errors:
        return rep, None
    for nid in timed:  # placeholders out: the engine must take product times, never this value
        compiled.nodes[nid].params.process_time = None
    for nid in routed:
        compiled.nodes[nid].successors = []
    from ..engine.calendar_compile import CalendarCompiledModel, compile_availability
    if spec is not None:
        out = compile_availability(compiled, model, registry)
    else:
        out = CalendarCompiledModel(model=compiled.model, nodes=compiled.nodes, horizon_s=compiled.horizon_s,
                                    warmup_s=compiled.warmup_s, component_versions=compiled.component_versions)
    if prod is not None:
        from ..engine.production_compile import compile_production
        out.production = compile_production(model, prod, out)
    if maint is not None:
        from ..engine.maintenance_compile import compile_maintenance
        out.maintenance = compile_maintenance(model, maint)
    return rep, out


__all__ = ["semantic_issues", "verify_model", "VerificationReport"]
