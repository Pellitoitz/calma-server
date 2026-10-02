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
    """verify() on the ISMS core + semantic warnings + extension blocks (calendars).

    Returns (report, compiled). With an `availability` block the compiled model is a CalendarCompiledModel; the
    approval state is re-evaluated on the FULL model (the core view has another hash)."""
    from .availability import availability_issues
    spec = getattr(model, "availability", None)
    core = model.core() if spec is not None else model  # type: ignore[attr-defined]
    rep, compiled = verify(core, registry)
    rep.issues.extend(semantic_issues(model, registry))
    if spec is None:
        return rep, compiled
    rep.issues = [i for i in rep.issues if i.code != "APPROVAL_STALE"]
    if model.approval.approved and not model.is_approved:
        rep.issues.append(Issue(Level.WARNING, "APPROVAL_STALE",
                                "El modelo cambió después de la aprobación del ingeniero: la aprobación ya no es válida."))
    cal_issues = availability_issues(model, registry)
    rep.issues.extend(cal_issues)
    if rep.readiness in (Readiness.EXECUTABLE, Readiness.ENGINEER_APPROVED):
        if any(i.level is Level.ERROR for i in cal_issues):
            rep.readiness = Readiness.CONFIGURED
        else:
            rep.readiness = Readiness.ENGINEER_APPROVED if model.is_approved else Readiness.EXECUTABLE
    if compiled is None or rep.errors:
        return rep, None
    from ..engine.calendar_compile import compile_availability
    return rep, compile_availability(compiled, model, registry)


__all__ = ["semantic_issues", "verify_model", "VerificationReport"]
