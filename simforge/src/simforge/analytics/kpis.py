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
    "units_completed_before_horizon": ("Units completed (t < horizon)", "units", "Completions strictly before the horizon"),
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
    # calendars (engine >= 0.6.0); h = hours summed over units/slots of the measured window
    "*.*.calendar_time_h": ("Calendar time", "h", "Measured window (horizon - warm-up) x units/slots"),
    "*.*.planned_available_h": ("Planned available time", "h", "Time inside the calendar's available windows (shifts minus breaks, "
                                "with exceptions); for a node: its own calendar ∩ its operators'/tools' calendars"),
    "*.*.break_h": ("Break time", "h", "Breaks inside working windows"),
    "*.*.off_shift_h": ("Off-shift time", "h", "Neither working nor break (nights, weekends, holidays)"),
    "*.*.planned_availability_ratio": ("Planned availability", "", "planned_available_time / calendar_time"),
    "resource.*.working_planned_h": ("Working time (planned)", "h", "working:* + transporting:* inside planned time"),
    "resource.*.walking_planned_h": ("Walking time (planned)", "h", "walking inside planned time"),
    "resource.*.idle_available_h": ("Idle available time", "h", "Available and without task"),
    "resource.*.outside_planned_h": ("Work outside planned time", "h", "Still busy after availability ended (FINISH_CURRENT)"),
    "resource.*.planned_utilization": ("Utilization of planned time", "", "working_planned / planned_available (walking excluded)"),
    "node.*.planned_utilization": ("Utilization of planned time", "", "busy inside planned time / planned_available"),
    "node.*.paused_by_calendar_h": ("Paused by calendar", "h", "Operation interrupted (PAUSE_RESUME / STOP_RESTART), unit kept"),
    "node.*.busy_outside_planned_h": ("Busy outside planned time", "h", "FINISH_CURRENT overrun"),
    "node.*.blocked_planned_h": ("Blocked (planned)", "h", "Blocked inside planned time"),
    "node.*.starved_planned_h": ("Starved (planned)", "h", "Starved inside planned time"),
    # products and setups (engine >= 0.7.0); only for models with a `production` block
    "product.*.created": ("Created", "units", "Units of this product created (whole run)"),
    "product.*.completed": ("Completed", "units", "Units of this product reaching a Sink in [warm-up, horizon]"),
    "product.*.throughput_per_hour": ("Throughput", "units/h", "completed / measured hours"),
    "product.*.avg_wip": ("Average WIP", "units", "Time-weighted units of this product in the system"),
    "product.*.wip_end": ("WIP at end", "units", "Units of this product in the system at the horizon"),
    "product.*.avg_lead_time_s": ("Average lead time", "s", "Mean (sink time - creation time) of completed units"),
    "node.*.processing_time_h": ("Processing time", "h", "Time processing (busy + busy outside planned), summed over slots"),
    "node.*.utilization_processing": ("Utilization (processing)", "", "busy / (slots x measured time); same definition as node.*.utilization"),
    "node.*.setup_count": ("Setups", "count", "Setups completed in [warm-up, horizon]"),
    "node.*.setup_time_h": ("Setup time", "h", "Time in setup (inside + outside planned time); pauses not included"),
    "node.*.utilization_setup": ("Utilization (setup)", "", "setup time / (slots x measured time)"),
    "total_setup_count": ("Setups (all nodes)", "count", "Setups completed in [warm-up, horizon]"),
    "total_setup_time_h": ("Setup time (all nodes)", "h", "Sum of node setup time"),
    "setup_time_inside_planned_h": ("Setup time inside planned time", "h", "Calendars: setup while the node is planned"),
    "setup_time_outside_planned_h": ("Setup time outside planned time", "h", "Calendars: setup outside the node's planned time"),
    # maintenance & reliability (engine >= 0.8.0); only nodes with a `maintenance` block (machine condition time)
    "node.*.failure_count": ("Failures", "count", "Failures occurring in [warm-up, horizon]"),
    "node.*.corrective_downtime_h": ("Corrective downtime", "h", "From failure to repair end: waiting for the repair resource + active repair"),
    "node.*.waiting_for_repair_resource_h": ("Waiting for repair resource", "h", "DOWN, repair resource not yet granted"),
    "node.*.active_repair_time_h": ("Active repair time", "h", "Repair in progress (resource granted)"),
    "node.*.preventive_maintenance_count": ("PM executed", "count", "PM completed in [warm-up, horizon]"),
    "node.*.preventive_maintenance_time_h": ("PM time", "h", "PM in progress"),
    "node.*.waiting_for_pm_h": ("Waiting for PM", "h", "Machine reserved for a due PM (no activity in progress), PM not started: resource / calendar / end of instant"),
    "node.*.uptime_h": ("Uptime", "h", "Machine condition up (neither failed nor in / reserved for PM), any calendar state"),
    "node.*.downtime_h": ("Downtime (maintenance)", "h", "corrective downtime + PM time + waiting for PM"),
    "node.*.failure_exposure_h": ("Failure-clock exposure", "h", "Time that aged the machine in the window (ELAPSED: all but DOWN and active PM; OPERATING: declared states)"),
    "node.*.observed_mtbf_exposure_h": ("Observed MTBF (exposure)", "h", "failure_exposure_h / failure_count (NaN without failures)"),
    "node.*.observed_mean_active_repair_s": ("Observed mean active repair", "s", "Mean repair duration of repairs completed in the window (resource wait excluded)"),
    "node.*.observed_mean_corrective_downtime_s": ("Observed mean corrective downtime", "s", "Mean failure -> repair end of repairs completed in the window (wait included)"),
    "node.*.reliability_availability": ("Reliability availability", "", "(planned_available - corrective downtime inside planned) / planned_available; without calendars planned = measured window"),
}

OEE_DEFINITION = (
    "OEE per station = Availability x Performance x Quality over the measured window, per slot. "
    "Planned time = measured window. Only for stations WITHOUT calendars: for calendar-gated stations no OEE is "
    "reported yet (planned production time is available as node.*.planned_production_time_h). "
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
        if f"*.*.{'.'.join(parts[2:])}" in METRIC_INFO:
            return METRIC_INFO[f"*.*.{'.'.join(parts[2:])}"]
    return (key, "", "")


def compute_run_kpis(rec: RunRecord, cm: CompiledModel) -> dict[str, float]:
    T = rec.measured_s
    k: dict[str, float] = {}
    done = len(rec.completions)
    k["units_completed"] = done
    k["throughput_per_hour"] = done / (T / 3600) if T > 0 else 0.0
    k["units_completed_before_horizon"] = sum(1 for _, _, d in rec.completions if d < rec.horizon_s)
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
            gated = bool(rec.availability and nid in rec.availability["nodes"])
            if p.process_time is not None and denom and not gated:  # OEE needs a planned-time definition: see below
                ideal = (p.ideal_cycle_time or p.process_time).mean_seconds() * (1 if p.ideal_cycle_time else p.entity_time_factor())
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
    if rec.availability:
        _calendar_kpis(k, rec)
    prod = getattr(cm, "production", None)
    if prod is not None:
        _production_kpis(k, rec, cm, prod, T)
    if getattr(cm, "maintenance", None) is not None:
        _maintenance_kpis(k, rec, T)
    # invariant: fractions of time can never exceed 100 %
    for key, v in k.items():
        if key.split(".")[-1] in _FRACTIONS and v == v and not -1e-9 <= v <= 1 + 1e-9:
            raise ValueError(f"KPI invariant violated: {key} = {v} outside [0, 1]")
    return k


def _calendar_kpis(k: dict[str, float], rec: RunRecord) -> None:
    """Calendar metrics. Denominators are explicit: planned_* over PLANNED available time, *_ratio over calendar time.
    No OEE is reported for calendar-gated nodes: planned production time is now available, but the full
    Availability x Performance x Quality definition with calendars is a later phase (not invented here)."""
    av = rec.availability or {}
    for rid, row in av.get("resources", {}).items():
        st = rec.resource_state_time.get(rid, {})
        base = f"resource.{rid}"
        planned = row["planned_available_s"]
        working = sum(v for s, v in st.items() if s.startswith(("working:", "transporting:")))
        k[f"{base}.calendar_time_h"] = row["calendar_time_s"] / 3600
        k[f"{base}.planned_available_h"] = planned / 3600
        k[f"{base}.break_h"] = row["break_s"] / 3600
        k[f"{base}.off_shift_h"] = row["off_shift_s"] / 3600
        k[f"{base}.planned_availability_ratio"] = planned / row["calendar_time_s"] if row["calendar_time_s"] else 0.0
        k[f"{base}.working_planned_h"] = working / 3600
        k[f"{base}.walking_planned_h"] = st.get("walking", 0.0) / 3600
        k[f"{base}.idle_available_h"] = st.get("idle", 0.0) / 3600
        k[f"{base}.outside_planned_h"] = sum(v for s, v in st.items() if s.startswith("outside_planned:")) / 3600
        k[f"{base}.planned_utilization"] = working / planned if planned else float("nan")
    for nid, row in av.get("nodes", {}).items():
        st = rec.node_state_time.get(nid, {})
        base = f"node.{nid}"
        planned = row["planned_available_s"]
        k[f"{base}.calendar_time_h"] = row["calendar_time_s"] / 3600
        k[f"{base}.planned_available_h"] = planned / 3600
        k[f"{base}.break_h"] = row["break_s"] / 3600
        k[f"{base}.off_shift_h"] = row["off_shift_s"] / 3600
        k[f"{base}.planned_availability_ratio"] = planned / row["calendar_time_s"] if row["calendar_time_s"] else 0.0
        k[f"{base}.planned_utilization"] = st.get(NodeState.BUSY, 0.0) / planned if planned else float("nan")
        k[f"{base}.paused_by_calendar_h"] = st.get(NodeState.PAUSED, 0.0) / 3600
        k[f"{base}.busy_outside_planned_h"] = st.get(NodeState.BUSY_OUTSIDE, 0.0) / 3600
        k[f"{base}.blocked_planned_h"] = st.get(NodeState.BLOCKED, 0.0) / 3600
        k[f"{base}.starved_planned_h"] = st.get(NodeState.STARVED, 0.0) / 3600
        k[f"{base}.planned_production_time_h"] = planned / 3600


def _production_kpis(k: dict[str, float], rec: RunRecord, cm: CompiledModel, prod, T: float) -> None:
    """Per product and setup metrics (engine >= 0.7.0). Legacy metrics keep their definitions untouched."""
    for p in sorted(prod.setup_key):
        done = [(c, d) for eid, c, d in rec.completions if rec.entity_product.get(eid) == p]
        lts = [d - c for c, d in done]
        k[f"product.{p}.created"] = rec.created_by_product.get(p, 0)
        k[f"product.{p}.completed"] = len(done)
        k[f"product.{p}.throughput_per_hour"] = len(done) / (T / 3600) if T > 0 else 0.0
        k[f"product.{p}.avg_wip"] = rec.level_avg.get(f"wip:{p}", 0.0)
        k[f"product.{p}.wip_end"] = rec.wip_end_by_product.get(p, 0)
        k[f"product.{p}.avg_lead_time_s"] = sum(lts) / len(lts) if lts else float("nan")
    inside = outside = 0.0
    count = 0
    for nid, cn in cm.nodes.items():
        if cn.behavior.value != "server" or nid not in rec.node_state_time:
            continue
        st = rec.node_state_time[nid]
        denom = rec.node_slots[nid] * T
        k[f"node.{nid}.processing_time_h"] = (st.get(NodeState.BUSY, 0.0) + st.get(NodeState.BUSY_OUTSIDE, 0.0)) / 3600
        k[f"node.{nid}.utilization_processing"] = st.get(NodeState.BUSY, 0.0) / denom if denom else 0.0
        if nid in prod.setups:
            s_in, s_out = st.get(NodeState.SETUP, 0.0), st.get(NodeState.SETUP_OUTSIDE, 0.0)
            k[f"node.{nid}.setup_count"] = rec.node_setups.get(nid, 0)
            k[f"node.{nid}.setup_time_h"] = (s_in + s_out) / 3600
            k[f"node.{nid}.utilization_setup"] = (s_in + s_out) / denom if denom else 0.0
            inside, outside, count = inside + s_in, outside + s_out, count + rec.node_setups.get(nid, 0)
    if prod.setups:
        k["total_setup_count"] = count
        k["total_setup_time_h"] = (inside + outside) / 3600
        if rec.availability:
            k["setup_time_inside_planned_h"] = inside / 3600
            k["setup_time_outside_planned_h"] = outside / 3600


def _maintenance_kpis(k: dict[str, float], rec: RunRecord, T: float) -> None:
    """Maintenance metrics with explicit definitions (METRIC_INFO). No OEE is derived from them."""
    for nid, cond in rec.node_condition_time.items():
        b = f"node.{nid}"
        h = lambda s: cond.get(s, 0.0) / 3600  # noqa: E731
        wait, rep = h(NodeState.DOWN_WAITING_REPAIR), h(NodeState.REPAIR)
        fails = rec.node_failures.get(nid, 0)
        rows = [r for r in rec.maintenance if r["node"] == nid]
        repairs = [r for r in rows if r["type"] == "failure" and "t_repair_end" in r and r["t_repair_end"] > rec.warmup_s]
        pms = [r for r in rows if r["type"] == "pm" and "end" in r and r["counted"]]
        k[f"{b}.failure_count"] = fails
        k[f"{b}.corrective_downtime_h"] = wait + rep
        k[f"{b}.waiting_for_repair_resource_h"] = wait
        k[f"{b}.active_repair_time_h"] = rep
        k[f"{b}.preventive_maintenance_count"] = len(pms)
        k[f"{b}.preventive_maintenance_time_h"] = h(NodeState.PM)
        k[f"{b}.waiting_for_pm_h"] = h(NodeState.PM_WAITING)
        k[f"{b}.uptime_h"] = h("up")
        k[f"{b}.downtime_h"] = wait + rep + h(NodeState.PM) + h(NodeState.PM_WAITING)
        if nid in rec.failure_exposure_s:
            exp = rec.failure_exposure_s[nid] / 3600
            k[f"{b}.failure_exposure_h"] = exp
            k[f"{b}.observed_mtbf_exposure_h"] = exp / fails if fails else float("nan")
            k[f"{b}.observed_mean_active_repair_s"] = (sum(r["t_repair_end"] - r["t_repair_start"] for r in repairs) / len(repairs)
                                                      if repairs else float("nan"))
            k[f"{b}.observed_mean_corrective_downtime_s"] = (sum(r["t_repair_end"] - r["t_fail"] for r in repairs) / len(repairs)
                                                            if repairs else float("nan"))
            av = (rec.availability or {}).get("nodes", {}).get(nid)
            if av is not None:
                st = rec.node_state_time.get(nid, {})
                inside = st.get(NodeState.DOWN_WAITING_REPAIR, 0.0) + st.get(NodeState.REPAIR, 0.0)
                planned = av["planned_available_s"]
            else:
                inside, planned = (wait + rep) * 3600, T
            k[f"{b}.reliability_availability"] = (planned - inside) / planned if planned else float("nan")


_FRACTIONS = {"reliability_availability", "utilization_processing", "utilization_setup", "utilization", "blocked", "starved", "waiting_resource", "down", "working", "walking", "transporting", "idle", "yield",
              "planned_utilization", "planned_availability_ratio"}


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
