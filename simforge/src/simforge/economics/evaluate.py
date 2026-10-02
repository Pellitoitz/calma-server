"""Economic evaluation of ONE stored physical run under ONE set of economic assumptions (no simulation).

physical_run (per-replication KPIs, persisted) + economic assumptions -> evaluation, identified by
run_id + economic_hash + ECONOMICS_ENGINE_VERSION. Each cost line is computed per replication (the economic inputs are
deterministic: the spread is SIMULATION_DERIVED_ECONOMIC_UNCERTAINTY) and keeps its audit trail: physical source keys,
physical quantity, parameter (value, currency, basis, provenance) and the versioned formula used.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from ..analytics.stats import summarize
from ..domain.economics import CATEGORIES, ECONOMICS_ENGINE_VERSION, OUT_OF_SCOPE, Basis, EconomicsSpec, Money

UNCERTAINTY_LABEL = "SIMULATION_DERIVED_ECONOMIC_UNCERTAINTY"

# formula registry: id -> definition (internal, versioned; never user expressions)
FORMULAS: dict[str, str] = {
    "labor_paid_v1": "rate[PER_PAID_HOUR] x paid_hours (paid_time rule) ",
    "labor_planned_v1": "rate[PER_PLANNED_HOUR] x planned_available_hours (all units)",
    "labor_busy_v1": "rate[PER_BUSY_HOUR] x busy_hours (working + walking + transporting, incl. outside planned)",
    "machine_hours_v1": "rate[PER_*_HOUR] x node hours of the basis",
    "machine_cycles_v1": "rate[PER_CYCLE] x node processed count",
    "energy_kwh_v1": "kWh = sum(declared power_kW[state] x node state hours); cost = price[PER_KWH] x kWh",
    "material_units_v1": "rate x units of the basis (PER_CONSUMED_UNIT = good + scrapped; PER_GOOD_UNIT = good)",
    "scrap_material_v1": "rate[PER_SCRAP_UNIT] x scrapped units",
    "maintenance_labor_v1": "rate[PER_BUSY_HOUR] x technician hours on '<node>#repair' / '<node>#pm' tasks",
    "maintenance_events_v1": "rate[PER_FAILURE | PER_PM] x failures / PM completed",
    "downtime_declared_v1": "rate[PER_CORRECTIVE_DOWNTIME_HOUR] x corrective downtime hours (declared cost only)",
    "fixed_per_run_v1": "amount[FIXED_PER_RUN]",
    "revenue_v1": "price[PER_GOOD_UNIT] x good units",
    "evaluated_total_cost_v1": "sum of INCLUDED cost lines (memo, revenue and REQUIRES_ENGINEER_DECISION lines excluded)",
    "cost_per_produced_unit_v1": "evaluated_total_cost / (good + scrapped units); UNDEFINED_METRIC if 0",
    "cost_per_good_unit_v1": "evaluated_total_cost / good units; UNDEFINED_METRIC if 0",
    "evaluated_net_result_v1": "revenue - evaluated_total_cost (only evaluated categories; NOT a profit)",
    "annualized_v1": "run value x runs_per_year (REPEAT_RUN)",
    "capex_total_v1": "sum of CAPEX items with a value (MISSING items listed, never 0)",
}


class EconomicsError(ValueError):
    pass


# ----------------------------------------------------------------------------------------- physical adapter
class PhysicalView:
    """Physical magnitudes of one replication, read ONLY from the stored KPIs of the run (+ model structure)."""

    def __init__(self, kpis: dict[str, float], measured_h: float, units: dict[str, int], slots: dict[str, int]):
        self.k, self.T, self.units, self.slots = kpis, measured_h, units, slots

    def _g(self, key: str) -> float | None:
        v = self.k.get(key)
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    def resource_busy_h(self, r: str):
        keys = [f"resource.{r}.{c}_h" for c in ("working", "walking", "transporting", "outside_planned")]
        return sum(self._g(k) or 0.0 for k in keys), keys

    def resource_planned_h(self, r: str):
        key = f"resource.{r}.planned_available_h"
        if self._g(key) is not None:
            return self._g(key), [key]
        return self.T * self.units[r], [f"measured window x {self.units[r]} unit(s) (no calendar: always available)"]

    def resource_task_h(self, r: str, task: str):
        keys = [f"resource.{r}.task_h.{task}", f"resource.{r}.task_h.working:{task}"]
        return sum(self._g(k) or 0.0 for k in keys), keys

    def node_processing_h(self, n: str):
        u, out = self._g(f"node.{n}.utilization"), self._g(f"node.{n}.busy_outside_planned_h") or 0.0
        if u is None:
            return None, []
        return u * self.slots[n] * self.T + out, [f"node.{n}.utilization x {self.slots[n]} slot(s) x window",
                                                  f"node.{n}.busy_outside_planned_h"]

    def node_setup_h(self, n: str):
        key = f"node.{n}.setup_time_h"
        return self._g(key), [key]

    def node_planned_h(self, n: str):
        key = f"node.{n}.planned_available_h"
        if self._g(key) is not None:
            return self._g(key), [key]
        return self.T * self.slots[n], [f"measured window x {self.slots[n]} slot(s) (no calendar)"]

    def count(self, key: str):
        return self._g(key), [key]

    def good(self, product: str | None = None):
        return self.count(f"product.{product}.completed" if product else "units_completed")

    def scrapped(self):
        return self.count("units_scrapped")


def physical_quantity(view: PhysicalView, basis: Basis, *, resource=None, node=None, paid_rule=None,
                      declared=None, product=None):
    """(quantity, unit, sources) of a basis. quantity None = NOT_APPLICABLE / NOT_AVAILABLE for this physical run."""
    B = Basis
    if resource is not None:
        if basis is B.PER_PAID_HOUR:
            if paid_rule == "CALENDAR_WINDOW":
                return view.T * view.units[resource], "h", [f"paid = measured window x {view.units[resource]} unit(s)"]
            if paid_rule == "PLANNED_AVAILABLE":
                q, s = view.resource_planned_h(resource)
                return q, "h", ["paid = planned available", *s]
            if paid_rule == "DECLARED":
                if declared is None:
                    return None, "h", ["declared_paid_hours_per_unit MISSING"]
                return declared * view.units[resource], "h", [f"paid = declared {declared} h x {view.units[resource]} unit(s)"]
            return None, "h", ["paid_time rule not declared"]
        if basis is B.PER_PLANNED_HOUR:
            q, s = view.resource_planned_h(resource)
            return q, "h", s
        if basis is B.PER_BUSY_HOUR:
            q, s = view.resource_busy_h(resource)
            return q, "h", s
        if basis is B.PER_CALENDAR_HOUR:
            return view.T * view.units[resource], "h", [f"measured window x {view.units[resource]} unit(s)"]
    if node is not None:
        if basis is B.PER_PROCESSING_HOUR:
            q, s = view.node_processing_h(node)
            return q, "h", s
        if basis is B.PER_SETUP_HOUR:
            q, s = view.node_setup_h(node)
            return q, "h", s
        if basis is B.PER_OPERATING_HOUR:
            p, sp = view.node_processing_h(node)
            st, ss = view.node_setup_h(node)
            return (None if p is None else p + (st or 0.0)), "h", sp + ss
        if basis is B.PER_PLANNED_HOUR:
            q, s = view.node_planned_h(node)
            return q, "h", s
        if basis is B.PER_CALENDAR_HOUR:
            return view.T * view.slots[node], "h", [f"measured window x {view.slots[node]} slot(s)"]
        if basis is B.PER_CYCLE:
            q, s = view.count(f"node.{node}.processed")
            return q, "cycles", s
        if basis is B.PER_FAILURE:
            q, s = view.count(f"node.{node}.failure_count")
            return q, "failures", s
        if basis is B.PER_PM:
            q, s = view.count(f"node.{node}.preventive_maintenance_count")
            return q, "PM", s
        if basis is B.PER_CORRECTIVE_DOWNTIME_HOUR:
            q, s = view.count(f"node.{node}.corrective_downtime_h")
            return q, "h", s
    if basis is B.PER_GOOD_UNIT:
        q, s = view.good(product)
        return q, "units", s
    if basis is B.PER_SCRAP_UNIT:
        q, s = view.scrapped()
        return q, "units", s
    if basis is B.PER_CONSUMED_UNIT:
        g, sg = view.good()
        sc, ss = view.scrapped()
        return (None if g is None or sc is None else g + sc), "units", sg + ss
    if basis is B.FIXED_PER_RUN:
        return 1.0, "run", ["evaluated run"]
    return None, "", [f"basis {basis.value} not calculable here"]


# ----------------------------------------------------------------------------------------- results
@dataclass
class Line:
    line_id: str
    category: str
    target: str  # resource / node / product / "run"
    scope: str  # "shared" | "product:<id>"
    basis: str
    formula_id: str
    status: str  # INCLUDED | MISSING | NOT_APPLICABLE | REQUIRES_ENGINEER_DECISION | MEMO | REVENUE
    parameter: dict[str, Any]
    physical_sources: list[str]
    unit: str
    quantity_per_rep: list[float | None]
    value_per_rep: list[float | None]
    quantity: dict[str, float] | None = None
    value: dict[str, float] | None = None
    note: str = ""


def _stat(values: list[float | None]) -> dict[str, float] | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    s = summarize(vals)
    return {"n": s.n, "mean": s.mean, "std": s.std, "ci95_low": s.ci95_low, "ci95_high": s.ci95_high,
            "min": s.min, "max": s.max}


@dataclass
class EconomicEvaluation:
    evaluation_id: str
    run_id: str
    physical_model_hash: str
    economic_hash: str
    economics_engine_version: str
    currency: str
    status: str
    replications: int
    seeds: list[int]
    horizon_s: float
    warmup_s: float
    lines: list[Line]
    coverage: dict[str, str]
    out_of_scope: list[str]
    totals: dict[str, Any]
    unit_costs: dict[str, Any]
    revenue: dict[str, Any]
    products: dict[str, Any]
    annualized: dict[str, Any]
    capex: dict[str, Any]
    issues: list[str]
    physical: dict[str, Any]  # physical KPIs used for comparisons (means), referenced from the run, not recomputed
    uncertainty_label: str = UNCERTAINTY_LABEL
    formulas: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EconomicEvaluation":
        d = dict(d)
        d["lines"] = [Line(**x) for x in d["lines"]]
        return cls(**d)

    def line(self, line_id: str) -> Line:
        return next(x for x in self.lines if x.line_id == line_id)


def _param(m: Money) -> dict[str, Any]:
    prov = m.provenance.model_dump(mode="json") if m.provenance else None
    return {"value": m.value, "currency": m.currency, "basis": m.basis.value, "provenance": prov,
            "status": "MISSING" if m.value is None else (prov or {}).get("status", "provided_by_client"),
            "reference": m.reference, "effective_date": str(m.effective_date) if m.effective_date else None}


def evaluate_run(run, model, spec: EconomicsSpec | None = None, registry=None) -> EconomicEvaluation:
    """Evaluate a stored physical run (SimulationResult) with the economic assumptions `spec` (default: model.economics).
    The model is used ONLY for its structure (units, slots, ids) and must be the physics of the run (same hash)."""
    from ..library.registry import ComponentRegistry
    from ..validation.economics import economics_issues
    from ..validation.semantics import verify_model
    spec = spec if spec is not None else getattr(model, "economics", None)
    if spec is None:
        raise EconomicsError("No hay supuestos económicos (bloque economics).")
    if model.content_hash() != run.model_hash:
        raise EconomicsError(f"El run {run.run_id} es de otra física (hash {run.model_hash} != {model.content_hash()}).")
    registry = registry or ComponentRegistry.load_default(None)
    rep, cm = verify_model(model, registry)
    if cm is None:
        raise EconomicsError("El modelo físico no verifica.")
    issues = economics_issues(spec, model, registry)
    errors = [i for i in issues if i.level.value == "error" and i.code != "REQUIRES_ENGINEER_DECISION"]
    if errors:
        raise EconomicsError("; ".join(str(i) for i in errors))
    red_lines = {i.path for i in issues if i.code == "REQUIRES_ENGINEER_DECISION"}
    units = {r.id: int(r.quantity) for r in cm.model.resources}
    slots = {nid: int(getattr(c.params, "capacity", getattr(c.params, "fleet", 1)) or 1) for nid, c in cm.nodes.items()}
    T = (run.horizon_s - run.warmup_s) / 3600
    views = [PhysicalView(k, T, units, slots) for k in run.per_replication]
    lines: list[Line] = []

    def add(line_id, category, target, money: Money, basis, formula, scope="shared", status=None, note="", **kw):
        qs, srcs, unit = [], [], ""
        for v in views:
            q, unit, s = physical_quantity(v, basis, **kw)
            qs.append(q)
            srcs = s
        if status is None:
            if line_id in red_lines:
                status = "REQUIRES_ENGINEER_DECISION"
            elif money.value is None or (kw.get("paid_rule") == "DECLARED" and kw.get("declared") is None):
                status = "MISSING"
            elif any(q is None for q in qs):
                status = "NOT_APPLICABLE"
            else:
                status = "INCLUDED"
        vals = [None if (q is None or money.value is None) else money.value * q for q in qs]
        ln = Line(line_id, category, target, scope, basis.value, formula, status, _param(money), srcs, unit, qs, vals, note=note)
        ln.quantity, ln.value = _stat(qs), _stat(vals)
        lines.append(ln)
        return ln

    B = Basis
    for i, x in enumerate(spec.labor):
        f = {B.PER_PAID_HOUR: "labor_paid_v1", B.PER_PLANNED_HOUR: "labor_planned_v1", B.PER_BUSY_HOUR: "labor_busy_v1"}[x.rate.basis]
        add(f"labor.{i}", "labor", x.resource, x.rate, x.rate.basis, f, resource=x.resource, paid_rule=x.paid_time,
            declared=x.declared_paid_hours_per_unit)
    for i, x in enumerate(spec.machine):
        f = "machine_cycles_v1" if x.rate.basis is B.PER_CYCLE else ("fixed_per_run_v1" if x.rate.basis is B.FIXED_PER_RUN else "machine_hours_v1")
        add(f"machine.{i}", "machine", x.node, x.rate, x.rate.basis, f, node=x.node)
    if spec.energy is not None:
        price = spec.energy.price
        if not spec.energy.power_kw:
            lines.append(Line("energy", "energy", "run", "shared", "PER_KWH", "energy_kwh_v1", "NOT_APPLICABLE", _param(price),
                              ["no declared electrical power: SimForge does not model energy (never estimated)"], "kWh",
                              [None] * len(views), [None] * len(views)))
        for nid, states in spec.energy.power_kw.items():
            kwh, srcs = [], []
            for v in views:
                total, ok = 0.0, True
                for state, kw in states.items():
                    q, s = v.node_processing_h(nid) if state == "PROCESSING" else v.node_setup_h(nid)
                    srcs = s
                    if q is None:
                        ok = False
                        break
                    total += kw * q
                kwh.append(total if ok else None)
            status = ("MISSING" if price.value is None else "NOT_APPLICABLE" if any(q is None for q in kwh) else "INCLUDED")
            vals = [None if q is None or price.value is None else price.value * q for q in kwh]
            ln = Line(f"energy.{nid}", "energy", nid, "shared", "PER_KWH", "energy_kwh_v1", status, _param(price),
                      [f"declared power_kW {states} x state hours", *srcs], "kWh", kwh, vals,
                      note="kWh CALCULATED post-run from DECLARED power; not part of the DES")
            ln.quantity, ln.value = _stat(kwh), _stat(vals)
            lines.append(ln)
    for i, x in enumerate(spec.material):
        scope = f"product:{x.product}" if x.product else "shared"
        add(f"material.{i}", "material", x.product or "run", x.rate, x.rate.basis, "material_units_v1", scope=scope, product=x.product)
        if x.rate.basis is B.PER_CONSUMED_UNIT and x.rate.value is not None:  # informative only (already inside)
            add(f"material.{i}.scrapped_share", "material", "run", x.rate, B.PER_SCRAP_UNIT, "scrap_material_v1", status="MEMO",
                note="scrapped units' material, ALREADY INCLUDED in the consumed-unit material line (memo, not added)")
    for i, x in enumerate(spec.scrap):
        add(f"scrap.{i}", "scrap", "run", x.rate, x.rate.basis, "scrap_material_v1")
    for i, x in enumerate(spec.maintenance):
        if x.kind in ("REPAIR_LABOR", "PM_LABOR"):
            task = x.node + ("#repair" if x.kind == "REPAIR_LABOR" else "#pm")
            qs = [v.resource_task_h(x.resource, task) for v in views]
            money = x.rate
            status = ("REQUIRES_ENGINEER_DECISION" if f"maintenance.{i}" in red_lines else "MISSING" if money.value is None else "INCLUDED")
            q = [a for a, _ in qs]
            vals = [None if money.value is None else money.value * a for a in q]
            ln = Line(f"maintenance.{i}", "maintenance", f"{x.resource}@{task}", "shared", money.basis.value,
                      "maintenance_labor_v1", status, _param(money), qs[0][1] if qs else [], "h", q, vals)
            ln.quantity, ln.value = _stat(q), _stat(vals)
            lines.append(ln)
        else:
            add(f"maintenance.{i}", "maintenance", x.node, x.rate, x.rate.basis, "maintenance_events_v1", node=x.node)
    for i, x in enumerate(spec.downtime):
        add(f"downtime.{i}", "downtime", x.node, x.rate, x.rate.basis, "downtime_declared_v1", node=x.node)
    for i, x in enumerate(spec.revenue):
        scope = f"product:{x.product}" if x.product else "shared"
        add(f"revenue.{i}", "revenue", x.product or "run", x.rate, x.rate.basis, "revenue_v1", scope=scope,
            status="REVENUE" if x.rate.value is not None else "MISSING", product=x.product)

    n = len(views)
    costs = [ln for ln in lines if ln.status == "INCLUDED"]
    total = [sum(ln.value_per_rep[r] for ln in costs) for r in range(n)]
    by_cat = {c: [sum(ln.value_per_rep[r] for ln in costs if ln.category == c) for r in range(n)] for c in CATEGORIES}
    # coverage (structured, no arbitrary percentage)
    coverage: dict[str, str] = {}
    for c in CATEGORIES:
        mine = [ln for ln in lines if ln.category == c and ln.status != "MEMO"]
        if any(ln.status == "REQUIRES_ENGINEER_DECISION" for ln in mine):
            coverage[c] = "REQUIRES_ENGINEER_DECISION"
        elif any(ln.status == "MISSING" for ln in mine) or (c in spec.scope and not mine):
            coverage[c] = "MISSING"
        elif mine and all(ln.status == "NOT_APPLICABLE" for ln in mine):
            coverage[c] = "NOT_APPLICABLE"
        elif any(ln.status == "INCLUDED" for ln in mine):
            coverage[c] = "INCLUDED"
        else:
            coverage[c] = "NOT_REQUESTED"
    if "REQUIRES_ENGINEER_DECISION" in coverage.values():
        status = "REQUIRES_ENGINEER_DECISION"
    elif "MISSING" in coverage.values():
        status = "PARTIAL_MISSING_INPUTS"
    else:
        status = "COMPLETE_FOR_REQUESTED_SCOPE"
    good = [v.good()[0] for v in views]
    scrap = [v.scrapped()[0] for v in views]
    produced = [None if g is None or s is None else g + s for g, s in zip(good, scrap)]
    cpp = [t / p if p else None for t, p in zip(total, produced)]
    cpg = [t / g if g else None for t, g in zip(total, good)]
    rev_lines = [ln for ln in lines if ln.status == "REVENUE"]
    revenue = [sum(ln.value_per_rep[r] for ln in rev_lines) for r in range(n)] if rev_lines else None
    net = [rv - t for rv, t in zip(revenue, total)] if revenue is not None else None
    # products: direct attributable (product-scoped lines) vs shared (never spread without a policy)
    products: dict[str, Any] = {"allocation_policy": spec.allocation_policy, "direct": {}, "shared": None}
    direct_lines = [ln for ln in costs if ln.scope.startswith("product:")]
    for p in sorted({ln.scope.split(":", 1)[1] for ln in direct_lines}):
        products["direct"][p] = _stat([sum(ln.value_per_rep[r] for ln in direct_lines if ln.scope == f"product:{p}") for r in range(n)])
    shared = [total[r] - sum(ln.value_per_rep[r] for ln in direct_lines) for r in range(n)]
    products["shared"] = _stat(shared)
    # annualization (never assumed)
    ann = spec.annualization
    if ann is None:
        annualized = {"status": "MISSING", "reason": "no annualization rule declared (never assumed)"}
    else:
        f = ann.runs_per_year
        annualized = {"status": "AVAILABLE", "formula_id": "annualized_v1", "mode": ann.mode, "runs_per_year": f,
                      "evaluated_total_cost": _stat([t * f for t in total]),
                      "by_category": {c: _stat([v * f for v in vs]) for c, vs in by_cat.items() if coverage[c] == "INCLUDED"},
                      "revenue": _stat([r * f for r in revenue]) if revenue is not None else None}
    # CAPEX (economic only; MISSING != 0)
    items = [{"category": c.category, "value": c.amount.value, "currency": c.amount.currency, "note": c.note,
              "status": "MISSING" if c.amount.value is None else "INCLUDED", "parameter": _param(c.amount)} for c in spec.capex]
    capex = {"formula_id": "capex_total_v1", "items": items,
             "total": sum(i["value"] for i in items if i["value"] is not None) if items else None,
             "missing": [i["category"] for i in items if i["value"] is None],
             "status": "NOT_DECLARED" if not items else ("PARTIAL_MISSING_INPUTS" if any(i["value"] is None for i in items) else "COMPLETE")}
    physical = {k: _stat([kp.get(k) for kp in run.per_replication]) for k in
                ("units_completed", "units_scrapped", "throughput_per_hour", "avg_lead_time_s", "avg_wip")}
    eid = hashlib.sha256(f"{run.run_id}|{spec.economic_hash()}|{ECONOMICS_ENGINE_VERSION}".encode()).hexdigest()[:12]
    return EconomicEvaluation(
        evaluation_id=eid, run_id=run.run_id, physical_model_hash=run.model_hash, economic_hash=spec.economic_hash(),
        economics_engine_version=ECONOMICS_ENGINE_VERSION, currency=spec.currency, status=status, replications=n,
        seeds=list(run.seeds), horizon_s=run.horizon_s, warmup_s=run.warmup_s, lines=lines, coverage=coverage,
        out_of_scope=list(OUT_OF_SCOPE),
        totals={"formula_id": "evaluated_total_cost_v1", "evaluated_total_cost": _stat(total), "per_rep": total,
                "by_category": {c: _stat(v) for c, v in by_cat.items() if coverage[c] == "INCLUDED"},
                "by_category_per_rep": {c: v for c, v in by_cat.items() if coverage[c] == "INCLUDED"},
                "included_categories": [c for c in CATEGORIES if coverage[c] == "INCLUDED"]},
        unit_costs={"cost_per_produced_unit": _stat(cpp) if all(v is not None for v in cpp) else "UNDEFINED_METRIC",
                    "cost_per_good_unit": _stat(cpg) if all(v is not None for v in cpg) else "UNDEFINED_METRIC",
                    "formula_ids": ["cost_per_produced_unit_v1", "cost_per_good_unit_v1"],
                    "denominators": {"produced": "good + scrapped units (window)", "good": "units completed (window)"}},
        revenue={"status": "NOT_DECLARED" if not spec.revenue else ("AVAILABLE" if revenue is not None else "MISSING"),
                 "revenue": _stat(revenue) if revenue is not None else None,
                 "evaluated_net_result": _stat(net) if net is not None else None,
                 "per_rep": revenue, "net_per_rep": net,
                 "note": "evaluated_net_result = revenue - evaluated_total_cost over the evaluated categories only; NOT a profit"},
        products=products, annualized=annualized, capex=capex,
        issues=[str(i) for i in issues], physical=physical, formulas=dict(FORMULAS))


def spec_from_json(text: str) -> EconomicsSpec:
    return EconomicsSpec.model_validate(json.loads(text))
