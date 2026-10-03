"""Results workbench (1.1-C): C10 consolidated results, C11 factual observations + Top-N, C13 KPI overlay on the graph.

Pure functions over a STORED run (`SimulationResult` loaded from the project): they never simulate, never recompute a
KPI definition and never mutate the run or the model. Every number is a stored aggregate (`kpis.stats`) or a stored
per-replication value (`per_replication`).

Contracts (fixed, tested):
  * NOT_AVAILABLE = the metric was not stored for that entity (missing is never 0).
    UNDEFINED     = the metric is stored but undefined (NaN, e.g. a lead time without completions).
  * n = 1: std and the 95 % CI are None (never 0); the stored statistics are reused, no new CI method.
  * Top-N = sort(metric, explicit order) then take N; ties broken by entity id (ascending). It is not a priority, a
    severity or an improvement potential. Entities without a defined value are excluded and listed.
  * Observations are deterministic templates that describe stored values; no recommendation, no causality, no LLM.
  * The graph overlay labels nodes of the run's own model version with stored values; no colour semantics.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..experiments.runner import SimulationResult
from .kpis import _FRACTIONS, metric_info
from .run_comparison import RunIdentity, identity

Status = Literal["AVAILABLE", "NOT_AVAILABLE", "UNDEFINED"]
Scope = Literal["system", "node", "resource", "product"]

OVERVIEW_METRICS = ("units_completed", "throughput_per_hour", "avg_wip", "max_wip", "avg_lead_time_s", "p90_lead_time_s",
                    "units_scrapped", "yield")
NODE_STATE = ("utilization", "blocked", "starved", "waiting_resource", "down", "processed", "rejects", "failures",
              "avg_wait_s", "preemptions")
NODE_OEE = ("availability", "performance", "quality", "oee")
NODE_TRANSPORT = ("trips", "units_transported", "avg_load")
QUEUES = ("avg_content", "max_content", "avg_wait_s")
SETUP = ("setup_count", "setup_time_h", "utilization_setup", "processing_time_h", "utilization_processing")
SETUP_SYSTEM = ("total_setup_count", "total_setup_time_h", "setup_time_inside_planned_h", "setup_time_outside_planned_h")
MAINTENANCE = ("failure_count", "corrective_downtime_h", "waiting_for_repair_resource_h", "active_repair_time_h",
               "preventive_maintenance_count", "preventive_maintenance_time_h", "waiting_for_pm_h", "uptime_h", "downtime_h",
               "failure_exposure_h", "observed_mtbf_exposure_h", "observed_mean_active_repair_s",
               "observed_mean_corrective_downtime_s", "corrective_reliability_availability",
               "corrective_downtime_inside_planned_h", "preventive_maintenance_time_inside_planned_h", "pm_due_occurrences",
               "mean_pm_delay_s", "max_pm_delay_s")
CALENDAR_NODE = ("calendar_time_h", "planned_available_h", "break_h", "off_shift_h", "planned_availability_ratio",
                 "planned_utilization", "paused_by_calendar_h", "busy_outside_planned_h", "blocked_planned_h",
                 "starved_planned_h", "planned_production_time_h")
RESOURCE = ("utilization", "working", "walking", "transporting", "idle", "working_h", "walking_h", "transporting_h",
            "idle_h", "avg_in_use", "preemptions")
CALENDAR_RESOURCE = ("calendar_time_h", "planned_available_h", "break_h", "off_shift_h", "planned_availability_ratio",
                     "working_planned_h", "walking_planned_h", "idle_available_h", "outside_planned_h", "planned_utilization")
PRODUCT = ("created", "completed", "throughput_per_hour", "avg_wip", "wip_end", "avg_lead_time_s")

# (scope, metric suffix) used by the factual observations: "highest stored value" statements only
OBSERVED = (("node", "utilization"), ("node", "blocked"), ("node", "starved"), ("node", "waiting_resource"),
            ("node", "down"), ("node", "avg_wait_s"), ("node", "avg_content"), ("node", "setup_time_h"),
            ("node", "corrective_downtime_h"), ("resource", "utilization"))
PHYSICAL_KPI_GAPS = (
    "setup transitions from -> to are not stored (only setup count and time per node)",
    "queue length / WIP over time are not stored (only time-weighted averages and maxima)",
    "resource waiting time per requester is not stored",
    "event and decision traces are stored only for runs executed in debug mode (CSV files), not in the run JSON",
)
TIE_BREAK = "value (in the requested order), then entity id ascending"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KpiValue(_Strict):
    metric: str  # stored key, e.g. node.m1.blocked
    scope: Scope
    entity: str | None = None
    name: str  # metric suffix, e.g. blocked
    label: str
    unit: str  # from METRIC_INFO ("" = dimensionless / fraction); never inferred
    status: Status
    n: int = 0
    mean: float | None = None
    std: float | None = None  # None when n = 1
    ci95_low: float | None = None
    ci95_high: float | None = None
    min: float | None = None
    max: float | None = None
    replications: list[float | None] = Field(default_factory=list)  # stored per-replication values (None = absent / NaN)


class EntityRow(_Strict):
    entity: str
    values: dict[str, KpiValue]  # one cell per table column; missing cells are NOT_AVAILABLE, never 0


class EntityTable(_Strict):
    key: str
    title: str
    scope: Scope
    columns: list[str]
    rows: list[EntityRow]


class TopNItem(_Strict):
    position: int  # 1..N in the requested order (a sort position, not a priority)
    entity: str
    metric: str
    value: float
    unit: str
    n: int


class TopN(_Strict):
    scope: Scope
    metric: str
    order: Literal["descending", "ascending"]
    n: int
    items: list[TopNItem]
    excluded: list[str]  # entities without a defined stored value (NOT_AVAILABLE / UNDEFINED)
    tie_break: str = TIE_BREAK
    run_id: str


class Observation(_Strict):
    template: str
    text: str
    scope: Scope
    metric: str
    entities: list[str]
    value: float
    unit: str
    n: int
    run_id: str


class OverlayValue(_Strict):
    node: str
    status: Status
    value: float | None = None
    text: str


class GraphOverlay(_Strict):
    run_id: str
    model_hash: str
    metric: str
    label: str
    unit: str
    nodes: list[OverlayValue]


class Workbench(_Strict):
    run: RunIdentity
    replications: int
    uncertainty: str
    overview: list[KpiValue]
    tables: list[EntityTable]
    system_setup: list[KpiValue]
    observations: list[Observation]
    gaps: list[str] = Field(default_factory=lambda: list(PHYSICAL_KPI_GAPS))
    note: str = ("Stored results only: nothing is simulated or recomputed. Facts are described, not interpreted; the "
                 "engineer decides.")


# ------------------------------------------------------------------------------------------------ values
def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v):
        return None
    return v


def kpi(run: SimulationResult, key: str) -> KpiValue:
    parts = key.split(".")
    if parts[0] in ("node", "resource", "product") and len(parts) >= 3:
        scope, entity, name = parts[0], parts[1], ".".join(parts[2:])
    else:
        scope, entity, name = "system", None, key
    label, unit, _ = metric_info(key)
    base = KpiValue(metric=key, scope=scope, entity=entity, name=name, label=label, unit=unit, status="NOT_AVAILABLE")
    st = run.kpis.stats.get(key)
    if st is None:
        return base
    reps = [_num(r.get(key)) for r in run.per_replication]
    mean = _num(st.mean)
    multi = st.n > 1
    return base.model_copy(update={
        "status": "AVAILABLE" if mean is not None else "UNDEFINED", "n": st.n, "mean": mean,
        "std": _num(st.std) if multi else None, "ci95_low": _num(st.ci95_low) if multi else None,
        "ci95_high": _num(st.ci95_high) if multi else None, "min": _num(st.min), "max": _num(st.max),
        "replications": reps})


def _entities(run: SimulationResult, scope: str, order: list[str] | None) -> list[str]:
    found = {k.split(".")[1] for k in run.kpis.stats if k.startswith(f"{scope}.") and len(k.split(".")) >= 3}
    first = [e for e in (order or []) if e in found]
    return first + sorted(found - set(first))


def entity_table(run: SimulationResult, key: str, title: str, scope: Scope, columns: tuple[str, ...],
                 order: list[str] | None = None) -> EntityTable | None:
    """Rows: entities with at least one of the columns stored; columns: those stored for at least one entity."""
    ents = _entities(run, scope, order)
    cols = [c for c in columns if any(f"{scope}.{e}.{c}" in run.kpis.stats for e in ents)]
    rows = [EntityRow(entity=e, values={c: kpi(run, f"{scope}.{e}.{c}") for c in cols})
            for e in ents if any(f"{scope}.{e}.{c}" in run.kpis.stats for c in cols)]
    return EntityTable(key=key, title=title, scope=scope, columns=cols, rows=rows) if rows else None


# ------------------------------------------------------------------------------------------------ C11
def top_n(run: SimulationResult, scope: Scope, metric: str, n: int = 5, order: Literal["descending", "ascending"] = "descending",
          entities: list[str] | None = None) -> TopN:
    if n < 1:
        raise ValueError("N debe ser >= 1.")
    vals, excluded = [], []
    for e in _entities(run, scope, entities):
        v = kpi(run, f"{scope}.{e}.{metric}")
        if v.status == "AVAILABLE":
            vals.append((v.mean, e, v))
        elif f"{scope}.{e}.{metric}" in run.kpis.stats or any(k.startswith(f"{scope}.{e}.") for k in run.kpis.stats):
            excluded.append(e)
    vals.sort(key=lambda x: (-x[0] if order == "descending" else x[0], x[1]))
    items = [TopNItem(position=i + 1, entity=e, metric=metric, value=m, unit=v.unit, n=v.n) for i, (m, e, v) in enumerate(vals[:n])]
    return TopN(scope=scope, metric=metric, order=order, n=n, items=items, excluded=sorted(excluded), run_id=run.run_id)


def fmt_value(name: str, unit: str, v: float) -> str:
    if name.split(".")[-1] in _FRACTIONS:
        return f"{v * 100:.1f} %"
    txt = f"{v:.4g}"
    return f"{txt} {unit}" if unit else txt


def observations(run: SimulationResult, order: list[str] | None = None) -> list[Observation]:
    """Deterministic 'highest stored value' statements (one per observed metric with at least two entities)."""
    out: list[Observation] = []
    for scope, metric in OBSERVED:
        t = top_n(run, scope, metric, n=10_000, entities=order)  # type: ignore[arg-type]
        if len(t.items) < 2:
            continue
        top = t.items[0].value
        tied = [i.entity for i in t.items if i.value == top]
        label, unit, _ = metric_info(f"{scope}.x.{metric}")
        val = fmt_value(metric, unit, top)
        n = t.items[0].n
        basis = f"mean of {n} replication{'s' if n != 1 else ''}, run {run.run_id}"
        if len(tied) == len(t.items):
            template = f"equal_{scope}_{metric}"
            text = f"All {len(t.items)} {scope}s with this metric recorded the same stored value of {label} ({val}; {basis})."
        else:
            template = f"highest_{scope}_{metric}"
            who = tied[0] if len(tied) == 1 else ", ".join(tied[:-1]) + " and " + tied[-1]
            text = (f"{who} recorded the highest stored value of {label} ({val}) among the {len(t.items)} {scope}s "
                    f"with this metric ({basis}).")
        out.append(Observation(template=template, text=text, scope=scope, metric=metric, entities=tied,
                               value=top, unit=unit, n=n, run_id=run.run_id))
    return out


# ------------------------------------------------------------------------------------------------ C13
def graph_overlay(run: SimulationResult, model, metric: str) -> GraphOverlay:
    """Stored value of node.<id>.<metric> for every node of the run's model (same content hash required)."""
    if model.content_hash() != run.model_hash:
        raise ValueError(f"El modelo ({model.content_hash()}) no es el del run {run.run_id} ({run.model_hash}).")
    label, unit, _ = metric_info(f"node.x.{metric}")
    vals = []
    for node in model.nodes:
        v = kpi(run, f"node.{node.id}.{metric}")
        text = fmt_value(metric, unit, v.mean) if v.status == "AVAILABLE" else v.status
        vals.append(OverlayValue(node=node.id, status=v.status, value=v.mean, text=text))
    return GraphOverlay(run_id=run.run_id, model_hash=run.model_hash, metric=metric, label=label, unit=unit, nodes=vals)


def overlay_metrics(run: SimulationResult) -> list[str]:
    names = {".".join(k.split(".")[2:]) for k in run.kpis.stats if k.startswith("node.") and len(k.split(".")) == 3}
    return sorted(names)


# ------------------------------------------------------------------------------------------------ C10
def build_workbench(run: SimulationResult, run_identity: RunIdentity | None = None, model=None) -> Workbench:
    order = [n.id for n in model.nodes] if model is not None else None
    res_order = [r.id for r in model.resources] if model is not None else None
    specs = [("nodes", "Nodes: states and flow", "node", NODE_STATE, order),
             ("oee", "Nodes: OEE (stations without calendars)", "node", NODE_OEE, order),
             ("queues", "Buffers and waiting", "node", QUEUES, order),
             ("transport", "Transport", "node", NODE_TRANSPORT, order),
             ("resources", "Resources", "resource", RESOURCE, res_order),
             ("setup", "Setup (nodes with setups)", "node", SETUP, order),
             ("maintenance", "Maintenance (nodes with a maintenance block)", "node", MAINTENANCE, order),
             ("calendar_nodes", "Calendar: nodes", "node", CALENDAR_NODE, order),
             ("calendar_resources", "Calendar: resources", "resource", CALENDAR_RESOURCE, res_order),
             ("products", "Products", "product", PRODUCT, None)]
    tables = [t for t in (entity_table(run, *s) for s in specs) if t is not None]
    reps = len(run.per_replication)
    unc = ("95 % confidence intervals from the stored replication statistics (Student t)." if reps > 1 else
           "Single replication: no standard deviation or confidence interval (not a conclusive result for a stochastic model).")
    return Workbench(run=run_identity or identity(run), replications=reps, uncertainty=unc,
                     overview=[kpi(run, k) for k in OVERVIEW_METRICS],
                     tables=tables, system_setup=[kpi(run, k) for k in SETUP_SYSTEM if k in run.kpis.stats],
                     observations=observations(run, order))
