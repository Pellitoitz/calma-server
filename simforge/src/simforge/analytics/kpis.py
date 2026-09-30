"""KPI layer (layer 2 of 3): deterministic calculations from raw run data.

Metrics are a flat dict {key: value} so they aggregate trivially across
replications and experiment scenarios. `METRIC_INFO` documents each one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.behaviors import ServerParams, TransportParams
from ..engine.base import NodeState, RunRecord
from ..validation.verifier import CompiledModel
from .stats import Stat, percentile, summarize

# key pattern -> (label, unit, definition)
METRIC_INFO: dict[str, tuple[str, str, str]] = {
    "units_completed": ("Units completed", "units", "Units reaching a Sink in [warm-up, horizon]"),
    "throughput_per_hour": ("Throughput", "units/h", "units_completed / measured hours"),
    "units_scrapped": ("Units scrapped", "units", "Units removed as scrap in [warm-up, horizon]"),
    "yield": ("Overall yield", "", "completed / (completed + scrapped)"),
    "avg_wip": ("Average WIP", "units", "Time-weighted number of units in the system"),
    "max_wip": ("Max WIP", "units", "Maximum units in the system"),
    "avg_lead_time_s": ("Average lead time", "s", "Mean (sink time - system entry time) of completed units"),
    "p90_lead_time_s": ("P90 lead time", "s", "90th percentile lead time"),
    "node.*.utilization": ("Utilization", "", "busy time / (slots x measured time)"),
    "node.*.blocked": ("Blocked", "", "Finished but downstream full, fraction of time"),
    "node.*.starved": ("Starved", "", "Idle with nothing to process, fraction of time"),
    "node.*.waiting_resource": ("Waiting resource", "", "Has a unit but waits operator/tool/carrier"),
    "node.*.down": ("Down", "", "Failed (MTBF/MTTR), fraction of time"),
    "node.*.processed": ("Processed", "units", "Units finished processing"),
    "node.*.avg_wait_s": ("Avg wait at node", "s", "Time from entering the node to start of processing (buffers: time in buffer)"),
    "node.*.avg_content": ("Avg content", "units", "Time-weighted buffer content"),
    "node.*.max_content": ("Max content", "units", "Maximum buffer content"),
    "node.*.oee": ("OEE", "", "Availability x Performance x Quality (see oee_definition)"),
    "resource.*.utilization": ("Utilization", "", "(working + walking) / (units x measured time)"),
    "resource.*.working": ("Working", "", "Working fraction"),
    "resource.*.walking": ("Walking", "", "Walking fraction"),
    "node.*.trips": ("Trips", "trips", "Transport trips delivered (counted at unload)"),
    "node.*.units_transported": ("Units transported", "units", "Units (or empty carriers) delivered by the transport"),
    "node.*.preemptions": ("Pre-emptions", "count", "Tasks at this node suspended by the dispatch strategy"),
    "resource.*.walking_h": ("Walking time", "h", "Hours walking unloaded to reach the next task location"),
    "resource.*.transporting_h": ("Transporting time", "h", "Hours travelling in transport tasks (loaded trip + empty return)"),
    "resource.*.working_h": ("Working time", "h", "Hours working at tasks (processing, loading, unloading)"),
    "resource.*.idle_h": ("Idle time", "h", "Hours with no task assigned"),
    "resource.*.preemptions": ("Pre-emptions", "count", "Tasks this resource abandoned for a more urgent one"),
    "resource.*.avg_in_use": ("Avg in use", "units", "Time-weighted units in use (carriers: racks in circulation)"),
}

OEE_DEFINITION = (
    "OEE per station = Availability x Performance x Quality over the measured window, per slot. "
    "Planned time = measured window (no shifts/breaks modelled in ISMS v0.1). "
    "Availability = (planned - down) / planned. "
    "Performance = ideal_cycle_time x processed / (planned - down); starvation, blocking and waiting for "
    "resources therefore count as PERFORMANCE losses. ideal_cycle_time = param 'ideal_cycle_time' if given, "
    "otherwise the mean process time (ASSUMED). Quality = (processed - rejects) / processed."
)


def metric_info(key: str) -> tuple[str, str, str]:
    if key in METRIC_INFO:
        return METRIC_INFO[key]
    parts = key.split(".")
    if len(parts) >= 3:
        generic = f"{parts[0]}.*.{'.'.join(parts[2:])}"
        if generic in METRIC_INFO:
            return METRIC_INFO[generic]
    return (key, "", "")


def compute_run_kpis(rec: RunRecord, cm: CompiledModel) -> dict[str, float]:
    T = rec.measured_s
    k: dict[str, float] = {}
    done = len(rec.completions)
    k["units_completed"] = done
    k["throughput_per_hour"] = done / (T / 3600) if T > 0 else 0.0
    k["units_scrapped"] = len(rec.scrapped)
    k["yield"] = done / (done + len(rec.scrapped)) if done + len(rec.scrapped) else float("nan")
    k["avg_wip"] = rec.level_avg.get("wip", 0.0)
    k["max_wip"] = rec.level_max.get("wip", 0.0)
    lts = [d - c for _, c, d in rec.completions]
    k["avg_lead_time_s"] = sum(lts) / len(lts) if lts else float("nan")
    k["p90_lead_time_s"] = percentile(lts, 90) if lts else float("nan")

    for nid, cn in cm.nodes.items():
        waits = rec.node_wait.get(nid, [])
        if nid in rec.node_state_time:
            slots = rec.node_slots[nid]
            st = rec.node_state_time[nid]
            denom = slots * T
            for s in NodeState.ALL:
                key = "utilization" if s == NodeState.BUSY else s
                k[f"node.{nid}.{key}"] = st.get(s, 0.0) / denom if denom else 0.0
            processed = rec.node_processed.get(nid, 0)
            k[f"node.{nid}.processed"] = processed
            k[f"node.{nid}.rejects"] = rec.node_rejects.get(nid, 0)
            k[f"node.{nid}.failures"] = rec.node_failures.get(nid, 0)
            k[f"node.{nid}.avg_wait_s"] = sum(waits) / len(waits) if waits else 0.0
            if isinstance(cn.params, TransportParams):
                k[f"node.{nid}.trips"] = rec.node_trips.get(nid, 0)
                k[f"node.{nid}.units_transported"] = rec.node_units_moved.get(nid, 0)
                k[f"node.{nid}.avg_load"] = (rec.node_units_moved.get(nid, 0) / rec.node_trips[nid]) if rec.node_trips.get(nid) else float("nan")
                continue
            k[f"node.{nid}.preemptions"] = rec.node_preemptions.get(nid, 0)
            p: ServerParams = cn.params  # type: ignore[assignment]
            if p.process_time is not None and denom:
                ideal = (p.ideal_cycle_time or p.process_time).mean_seconds() * (1 if p.ideal_cycle_time else p.work_units)
                down = st.get(NodeState.DOWN, 0.0)
                run_time = denom - down
                a = run_time / denom
                perf = min(1.0, ideal * processed / run_time) if run_time > 0 else 0.0
                q = (processed - rec.node_rejects.get(nid, 0)) / processed if processed else float("nan")
                k[f"node.{nid}.availability"] = a
                k[f"node.{nid}.performance"] = perf
                k[f"node.{nid}.quality"] = q
                k[f"node.{nid}.oee"] = a * perf * q if processed else float("nan")
        elif f"buffer:{nid}" in rec.level_avg:
            k[f"node.{nid}.avg_content"] = rec.level_avg[f"buffer:{nid}"]
            k[f"node.{nid}.max_content"] = rec.level_max[f"buffer:{nid}"]
            k[f"node.{nid}.avg_wait_s"] = sum(waits) / len(waits) if waits else 0.0

    for rid, n_units in rec.resource_units.items():
        st = rec.resource_state_time.get(rid, {})
        denom = n_units * T
        cats = {"working": 0.0, "walking": 0.0, "transporting": 0.0, "idle": 0.0}
        per_task: dict[str, float] = {}
        for state, secs in st.items():
            cat, _, task = state.partition(":")
            cats[cat] = cats.get(cat, 0.0) + secs
            if task:
                per_task[task] = per_task.get(task, 0.0) + secs
                k[f"resource.{rid}.{cat}_h.{task}"] = secs / 3600
        for cat, secs in cats.items():
            k[f"resource.{rid}.{cat}"] = secs / denom if denom else 0.0
            k[f"resource.{rid}.{cat}_h"] = secs / 3600
        for task, secs in per_task.items():
            k[f"resource.{rid}.task_h.{task}"] = secs / 3600
        k[f"resource.{rid}.preemptions"] = rec.resource_preemptions.get(rid, 0)
        k[f"resource.{rid}.avg_in_use"] = rec.level_avg.get(f"in_use:{rid}", 0.0)
        k[f"resource.{rid}.utilization"] = k[f"resource.{rid}.avg_in_use"] / n_units if n_units else 0.0
        prefix = f"carrier_at:{rid}:"
        for name, avg in rec.level_avg.items():
            if name.startswith(prefix):
                k[f"resource.{rid}.avg_at.{name[len(prefix):]}"] = avg
    # invariant: fractions of time can never exceed 100 %
    for key, v in k.items():
        if key.split(".")[-1] in _FRACTIONS and v == v and not -1e-9 <= v <= 1 + 1e-9:
            raise ValueError(f"KPI invariant violated: {key} = {v} outside [0, 1]")
    return k


_FRACTIONS = {"utilization", "blocked", "starved", "waiting_resource", "down", "working", "walking", "transporting", "idle", "yield"}


@dataclass
class ReplicatedKPIs:
    stats: dict[str, Stat] = field(default_factory=dict)
    n: int = 0

    def mean(self, key: str) -> float:
        s = self.stats.get(key)
        return s.mean if s else float("nan")

    def to_dict(self) -> dict:
        return {"n": self.n, "stats": {k: v.to_dict() for k, v in self.stats.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "ReplicatedKPIs":
        return cls({k: Stat(**v) for k, v in d["stats"].items()}, d["n"])


def aggregate(per_rep: list[dict[str, float]]) -> ReplicatedKPIs:
    keys: list[str] = []
    for d in per_rep:
        for key in d:
            if key not in keys:
                keys.append(key)
    return ReplicatedKPIs({key: summarize([d.get(key, float("nan")) for d in per_rep]) for key in keys}, len(per_rep))
