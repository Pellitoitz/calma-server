"""Semantic checks that complement the (frozen) verifier without changing it.

The verifier (validation/verifier.py) is part of the frozen LLM benchmark V1 contract, so new model-level warnings
live here and are appended to its report by `verify_model` (used by the app, CLI and reports). The benchmark keeps
calling the plain verifier.
"""

from __future__ import annotations

from typing import Any

from ..domain.isms import ISMSModel
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level, VerificationReport, verify


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
    """verify() + semantic warnings (warnings only: readiness is not changed)."""
    rep, compiled = verify(model, registry)
    rep.issues.extend(semantic_issues(model, registry))
    return rep, compiled


__all__ = ["semantic_issues", "verify_model", "VerificationReport"]
