"""Baseline vs alternative: facts, deltas, coverage mismatches, payback. Never a winner, a ranking or a recommendation.

Conventions (fixed, tested):
  delta   = alternative - baseline        (for costs: negative delta = lower cost in the alternative)
  savings = baseline cost - alternative cost   (positive = the alternative costs less)
Savings are computed only over cost categories INCLUDED (complete) in BOTH evaluations; the others are listed as
mismatches and never filled with 0. With a coverage mismatch the savings stay visible (labelled "common categories") but
payback / return need an engineer decision.
Paired (evidence of common random numbers: same seeds, same replications, same horizon and warm-up): per-replication
deltas delta_i = alt_i - base_i are summarised; otherwise the difference of means is shown, with no interval.
Checks are classified HARD_INCOMPATIBILITY (-> NOT_COMPARABLE) | WARNING | INFORMATIONAL; different physics is what
is being compared and never blocks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..analytics.stats import summarize
from .evaluate import EconomicEvaluation, _stat

PHYSICAL_KEYS = ("units_completed", "units_scrapped", "throughput_per_hour", "avg_lead_time_s", "avg_wip")
COMPARISON_FORMULAS: dict[str, str] = {
    "delta_v1": "alternative - baseline (paired: statistics of alt_i - base_i; unpaired: difference of means)",
    "savings_v1": "baseline evaluated cost - alternative evaluated cost, over categories INCLUDED in both",
    "annual_savings_v1": "savings_v1 x runs_per_year (same REPEAT_RUN basis in both)",
    "incremental_capex_v1": "alternative CAPEX - baseline CAPEX (both declared and complete; never an assumed 0)",
    "simple_payback_v1": "incremental CAPEX / annual evaluated savings (incremental CAPEX > 0 and savings > 0)",
    "annual_return_on_incremental_capex_v1": "annual evaluated savings / incremental CAPEX (incremental CAPEX > 0)",
}


@dataclass
class Comparison:
    baseline: str  # evaluation ids
    alternative: str
    status: str  # COMPARABLE | COMPARABLE_WITH_WARNINGS | NOT_COMPARABLE
    warnings: list[str]
    errors: list[str]
    paired: bool
    physical_deltas: dict[str, Any]
    cost_deltas: dict[str, Any]  # per common category + evaluated total over common categories
    savings: dict[str, Any]
    mismatched_categories: dict[str, list[str]]
    annual: dict[str, Any]
    capex: dict[str, Any]
    payback: dict[str, Any]
    annual_return_on_incremental_capex: dict[str, Any]
    revenue_delta: dict[str, Any] | None
    checks: list[dict[str, str]] = field(default_factory=list)  # {check, level, detail}
    informational: list[str] = field(default_factory=list)
    coverage_match: bool = True
    formulas: dict[str, str] = field(default_factory=lambda: dict(COMPARISON_FORMULAS))
    note: str = ("Facts only: SimForge compares and traces; it does not rank, choose or recommend. The engineer decides.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _diff(a: list[float], b: list[float], paired: bool) -> dict[str, Any]:
    if paired:
        return {"mode": "paired", **(_stat([y - x for x, y in zip(a, b)]) or {})}
    sa, sb = summarize(a), summarize(b)
    return {"mode": "unpaired", "mean": sb.mean - sa.mean + 0.0, "ci95_low": None, "ci95_high": None,
            "note": "different seeds/replications: difference of means only, no paired interval"}


def _comparability(base_model, alt_model, eb: EconomicEvaluation, ea: EconomicEvaluation) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(check, level, detail):
        checks.append({"check": check, "level": level, "detail": detail})
    if eb.currency != ea.currency:
        add("currency", "HARD_INCOMPATIBILITY", f"currency {eb.currency} != {ea.currency} (no FX)")
    if (eb.horizon_s, eb.warmup_s) != (ea.horizon_s, ea.warmup_s):
        add("horizon", "WARNING", f"physical horizon/warm-up differ ({eb.horizon_s}/{eb.warmup_s} s vs {ea.horizon_s}/{ea.warmup_s} s): "
            "absolute run costs cover different windows (no automatic normalisation)")
    if eb.replications != ea.replications:
        add("replications", "INFORMATIONAL", f"replications differ ({eb.replications} vs {ea.replications}): unpaired comparison")
    ab, aa = eb.annualized, ea.annualized
    if ab.get("status") == "AVAILABLE" and aa.get("status") == "AVAILABLE" and ab["runs_per_year"] != aa["runs_per_year"]:
        add("annualization", "WARNING", f"annualization basis differs ({ab['runs_per_year']} vs {aa['runs_per_year']} runs/year)")
    if base_model is not None and alt_model is not None:
        def sources(m):
            from ..library.registry import ComponentRegistry
            reg = ComponentRegistry.load_default(None)
            out = {}
            for n in m.nodes:
                try:
                    if reg.get(n.component).behavior.value == "source":
                        out[n.id] = n.params
                except Exception:  # noqa: BLE001
                    pass
            return out
        if sources(base_model) != sources(alt_model):
            add("demand", "WARNING", "arrival / demand assumptions (sources) differ: a raw economic delta may not be a like-for-like improvement")
        pb, pa = getattr(base_model, "production", None), getattr(alt_model, "production", None)
        gb = pb.model_dump(mode="json")["generation"] if pb else None
        ga = pa.model_dump(mode="json")["generation"] if pa else None
        if gb != ga:
            add("product_mix", "WARNING", "product mix / sequence differs: no normalisation or weighting is applied")
        cb, ca = getattr(base_model, "availability", None), getattr(alt_model, "availability", None)
        if (cb.calendar_hash() if cb else None) != (ca.calendar_hash() if ca else None):
            add("calendars", "WARNING", "calendars differ (fine if the calendar IS the alternative; check it is intended)")
    ub, ua = (eb.physical.get("units_completed") or {}).get("mean"), (ea.physical.get("units_completed") or {}).get("mean")
    if ub is not None and ua is not None and ub != ua:
        add("output", "INFORMATIONAL", f"good units differ ({ub:g} vs {ua:g}): absolute cost deltas are not per-unit deltas")
    return checks


def compare_evaluations(eb: EconomicEvaluation, ea: EconomicEvaluation, base_model=None, alt_model=None) -> Comparison:
    checks = _comparability(base_model, alt_model, eb, ea)
    paired = (eb.seeds == ea.seeds and eb.replications == ea.replications
              and (eb.horizon_s, eb.warmup_s) == (ea.horizon_s, ea.warmup_s))  # evidence of common random numbers
    phys = {}
    for k in PHYSICAL_KEYS:
        mb, ma = (eb.physical.get(k) or {}).get("mean"), (ea.physical.get(k) or {}).get("mean")
        if mb is not None and ma is not None:
            phys[k] = {"baseline": mb, "alternative": ma, "delta": ma - mb,
                       "delta_pct": (ma - mb) / mb * 100 if mb else None}
    cb, ca = set(eb.totals["included_categories"]), set(ea.totals["included_categories"])
    common = sorted(cb & ca)
    mism = {"only_baseline": sorted(cb - ca), "only_alternative": sorted(ca - cb)}
    coverage_match = not (mism["only_baseline"] or mism["only_alternative"])
    if not coverage_match:
        checks.append({"check": "coverage", "level": "WARNING", "detail": f"cost coverage differs {mism}: savings over common "
                       f"categories {common} only (missing categories are never 0); payback / return need an engineer decision"})
    cost_d, tb, ta = {}, [0.0] * eb.replications, [0.0] * ea.replications
    for c in common:
        vb, va = eb.totals["by_category_per_rep"][c], ea.totals["by_category_per_rep"][c]
        cost_d[c] = _diff(vb, va, paired)
        tb = [x + y for x, y in zip(tb, vb)]
        ta = [x + y for x, y in zip(ta, va)]
    cost_d["evaluated_total_common"] = _diff(tb, ta, paired)
    sav = _diff(ta, tb, paired)  # baseline - alternative
    savings = {"definition": f"baseline evaluated cost - alternative evaluated cost (common categories {common})",
               "formula_id": "savings_v1", **sav}
    # annual
    annual: dict[str, Any] = {"status": "MISSING"}
    ab, aa = eb.annualized, ea.annualized
    if ab.get("status") == "AVAILABLE" and aa.get("status") == "AVAILABLE":
        fb, fa = ab["runs_per_year"], aa["runs_per_year"]
        if fb == fa:
            annual = {"status": "AVAILABLE", "runs_per_year": fb,
                      "savings_per_year": _diff([x * fa for x in ta], [x * fb for x in tb], paired)}
        else:
            annual = {"status": "NOT_COMPARABLE", "reason": "different annualization bases"}
    else:
        annual["reason"] = "annualization missing in baseline and/or alternative (never assumed)"
    # CAPEX: incremental = alternative CAPEX - baseline CAPEX
    kb, ka = eb.capex, ea.capex
    if kb["missing"] or ka["missing"]:
        capex = {"status": "MISSING", "missing": {"baseline": kb["missing"], "alternative": ka["missing"]}}
    elif not kb["items"] or not ka["items"]:  # an undeclared CAPEX is unknown, never 0 (declare an explicit 0 item)
        capex = {"status": "NOT_DECLARED", "not_declared": [n for n, k in (("baseline", kb), ("alternative", ka)) if not k["items"]]}
    else:
        capex = {"status": "AVAILABLE", "formula_id": "incremental_capex_v1", "baseline": kb["total"], "alternative": ka["total"]}
        capex["incremental"] = capex["alternative"] - capex["baseline"] + 0.0
    payback = {"formula_id": "simple_payback_v1", "formula": "incremental CAPEX / annual evaluated savings"}
    ret = {"formula_id": "annual_return_on_incremental_capex_v1", "formula": "annual evaluated savings / incremental CAPEX"}
    statuses = {eb.status, ea.status}
    if annual.get("status") != "AVAILABLE" or capex.get("status") != "AVAILABLE":
        payback["status"] = ret["status"] = "UNDEFINED_METRIC"
        payback["reason"] = ret["reason"] = "needs valid annualization and complete, declared CAPEX in both"
    elif "REQUIRES_ENGINEER_DECISION" in statuses or not coverage_match:
        payback["status"] = ret["status"] = "REQUIRES_ENGINEER_DECISION"
        payback["reason"] = ret["reason"] = "cost coverage differs or a double count is pending: savings are not like-for-like"
    elif statuses != {"COMPLETE_FOR_REQUESTED_SCOPE"}:
        payback["status"] = ret["status"] = "UNDEFINED_METRIC"
        payback["reason"] = ret["reason"] = "economic inputs incomplete (PARTIAL_MISSING_INPUTS)"
    else:
        s, inc = annual["savings_per_year"]["mean"], capex["incremental"]
        payback.update(inputs={"incremental_capex": inc, "annual_savings": s})
        ret.update(inputs={"incremental_capex": inc, "annual_savings": s})
        if inc <= 0:
            payback["status"] = ret["status"] = "UNDEFINED_METRIC"
            payback["reason"] = ret["reason"] = "incremental CAPEX <= 0"
        elif s <= 0:
            payback["status"], payback["reason"] = "NOT_REACHED", "annual savings <= 0 (never a negative payback)"
            ret["status"], ret["value"] = "AVAILABLE", s / inc
        else:
            payback["status"], payback["years"] = "AVAILABLE", inc / s
            ret["status"], ret["value"] = "AVAILABLE", s / inc
    rev = None
    if eb.revenue.get("per_rep") is not None and ea.revenue.get("per_rep") is not None:
        rev = _diff(eb.revenue["per_rep"], ea.revenue["per_rep"], paired)
    errors = [c["detail"] for c in checks if c["level"] == "HARD_INCOMPATIBILITY"]
    warns = [c["detail"] for c in checks if c["level"] == "WARNING"]
    info = [c["detail"] for c in checks if c["level"] == "INFORMATIONAL"]
    status = "NOT_COMPARABLE" if errors else ("COMPARABLE_WITH_WARNINGS" if warns else "COMPARABLE")
    return Comparison(eb.evaluation_id, ea.evaluation_id, status, warns, errors, paired, phys, cost_d, savings, mism, annual,
                      capex, payback, ret, rev, checks=checks, informational=info, coverage_match=coverage_match)
