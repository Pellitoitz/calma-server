"""Diagnostic harness for the selective-soldering rack anomaly (docs/diagnostics/selective_rack_anomaly.md).

Builds EXACTLY the model used by tests/test_nl_selective.py (SELECTIVE_TEXT + ANSWERS), varies only
parameters.racks_count.value, and runs it with the engine's existing trace + operator decision log.
Read-only with respect to engine semantics: nothing here changes how the model is simulated.

    python scripts/diagnostics/selective_racks.py            # writes CSVs to docs/diagnostics/selective_rack_anomaly/
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from simforge.domain.isms import DispatchRule  # noqa: E402
from simforge.domain.paths import set_value  # noqa: E402
from simforge.engine.des.engine import DesEngine  # noqa: E402
from simforge.analytics.kpis import compute_run_kpis  # noqa: E402
from simforge.services.app import SimForgeApp  # noqa: E402
from simforge.validation.verifier import compile_model  # noqa: E402

from simforge import ENGINE_VERSION  # noqa: E402

# results are kept per engine version: outputs of an older engine are never overwritten by a newer one
OUT = ROOT / "docs" / "diagnostics" / "selective_rack_anomaly" / f"engine_{ENGINE_VERSION}"
SPEED = 1.2
SEL, BUF, ASM, TRN, INS = "selective_soldering", "buffer_de_entrada", "manual_assembly", "transport_1", "inspection"


@lru_cache
def base_model():
    from tests.test_nl_selective import ANSWERS, SELECTIVE_TEXT
    tmp = Path(tempfile.mkdtemp())
    app = SimForgeApp(workspace=tmp / "ws", library_dir=tmp / "lib", provider=None)
    p = app.create_project("diag")
    app.parse_process(p, SELECTIVE_TEXT)
    model = app.answer_questions(p, ANSWERS).outcome.model
    return model, app.registry


def model_for(racks: int, overrides: dict | None = None):
    model, reg = base_model()
    m = set_value(model, "parameters.racks_count.value", racks)
    for path, val in (overrides or {}).items():
        m = set_value(m, path, val)
    return m, reg


def run(racks: int, overrides: dict | None = None, trace: bool = True):
    m, reg = model_for(racks, overrides)
    cm = compile_model(m, reg)
    rec = DesEngine().run(cm, m.simulation.base_seed, trace=trace)
    return rec, compute_run_kpis(rec, cm), cm


def buffer_empty_full(rec, cap: int, horizon: float) -> tuple[float, float]:
    s = rec.series.get(f"buffer:{BUF}")
    if s is None:
        return float("nan"), float("nan")
    empty = full = 0.0
    pts = list(zip(s.t, s.v)) + [(horizon, None)]
    for (t0, v), (t1, _) in zip(pts, pts[1:]):
        dt = min(t1, horizon) - min(t0, horizon)
        empty += dt if v == 0 else 0
        full += dt if v >= cap else 0
    return empty, full


def walked_m(rec) -> float:
    walk = sum(e["seconds"] for e in rec.events if e["event"] == "operator_walking") * SPEED
    trips = sum(1 for e in rec.events if e["event"] == "trip_start")
    return walk + trips * 10.0  # loaded transport leg = 10 m (resolved transport distance)


def summary_row(racks: int, rec, k: dict) -> dict:
    H = rec.horizon_s
    st = rec.resource_state_time["operator_1"]
    sel = rec.node_state_time[SEL]
    empty, full = buffer_empty_full(rec, 3, H)
    return {
        "racks": racks,
        "production": k["units_completed"],
        "throughput_per_h": round(k["throughput_per_hour"], 3),
        "avg_wip": round(k["avg_wip"], 3), "max_wip": k["max_wip"],
        "selective_utilization": round(k[f"node.{SEL}.utilization"], 4),
        "selective_starved_s": round(sel.get("starved", 0.0), 1),
        "selective_blocked_s": round(sel.get("blocked", 0.0), 1),
        "operator_utilization": round(k["resource.operator_1.utilization"], 4),
        "operator_idle_s": round(st.get("idle", 0.0), 1),
        "operator_assembly_s": round(st.get(f"working:{ASM}", 0.0), 1),
        "operator_inspection_s": round(st.get(f"working:{INS}", 0.0), 1),
        "operator_load_unload_s": round(st.get(f"working:{TRN}", 0.0), 1),
        "operator_walking_s": round(st.get("walking", 0.0), 1),
        "operator_transporting_s": round(st.get(f"transporting:{TRN}", 0.0), 1),
        "trips": rec.node_trips.get(TRN, 0),
        "distance_walked_m (derived from trace)": round(walked_m(rec), 1),
        "avg_input_buffer": round(k[f"node.{BUF}.avg_content"], 4),
        "max_input_buffer": k[f"node.{BUF}.max_content"],
        "time_input_buffer_empty_s (derived)": round(empty, 1),
        "time_input_buffer_full_s (derived)": round(full, 1),
        "invariant_checks": rec.invariant_checks,
    }


def write_csv(name: str, rows: list[dict]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v) for k, v in r.items()})
    return path




# ----------------------------------------------------------------------------- counterfactuals (diagnostic only)


def second_operator_for_inspection(model):
    """DIAGNOSTIC: an independent operator (same travel data) for review only."""
    op = next(r for r in model.resources if r.id == "operator_1")
    op2 = op.model_copy(update={"id": "operator_2", "name": "Operario 2", "dispatch": DispatchRule.FIFO, "wip_target": None,
                                "home": INS, "quantity": 1})
    nodes = [n.model_copy(update={"params": {**n.params, "resources": [{"resource": "operator_2"}]}}) if n.id == INS else n
             for n in model.nodes]
    return model.model_copy(update={"resources": [*model.resources, op2], "nodes": nodes})


def run_variant(racks: int, overrides: dict | None = None, transform=None):
    m, reg = model_for(racks, overrides)
    if transform:
        m = transform(m)
    cm = compile_model(m, reg)
    rec = DesEngine().run(cm, m.simulation.base_seed, trace=True)
    return rec, compute_run_kpis(rec, cm)


VARIANTS = {
    "A_base_wip_target": {},
    "B_fifo": {"overrides": {"resources.operator_1.dispatch": "fifo", "resources.operator_1.wip_target": None}},
    "C_static_priority_feeders_first": {"overrides": {
        "resources.operator_1.dispatch": "priority", "resources.operator_1.wip_target": None,
        "nodes.transport_1.priority": 1, "nodes.manual_assembly.priority": 2, "nodes.inspection.priority": 3}},
    "C2_static_priority_review_first": {"overrides": {
        "resources.operator_1.dispatch": "priority", "resources.operator_1.wip_target": None,
        "nodes.inspection.priority": 1, "nodes.transport_1.priority": 2, "nodes.manual_assembly.priority": 3}},
    "D_independent_review_operator": {"transform": second_operator_for_inspection},
    "E_transport_near_zero": {"overrides": {"parameters.transport_1_load_time.value": 0, "parameters.transport_1_unload_time.value": 0,
                                            "nodes.transport_1.params.distance": {"value": 0.001, "unit": "m"}}},
    "F_wip_target_1": {"overrides": {"parameters.wip_target.value": 1}},
    "F_wip_target_2": {"overrides": {"parameters.wip_target.value": 2}},
    "F_wip_target_3": {"overrides": {"parameters.wip_target.value": 3}},
    "F_wip_target_4": {"overrides": {"parameters.wip_target.value": 4}},
    "G_immediate_dispatch": {"overrides": {"simulation.dispatch_timing": "immediate"}},
    "I_wip_target_without_rule1_unblock_protected": {"overrides": {"resources.operator_1.wip_target.unblock_protected": False}},
    "H_walking_free (speed 1000 m/s, operator only)": {"overrides": {"resources.operator_1.travel.speed": {"value": 1000, "unit": "m/s"}}},
}


def counterfactuals(racks_list=(1, 2, 3, 4)) -> list[dict]:
    rows = []
    for name, v in VARIANTS.items():
        row = {"variant": name}
        for n in racks_list:
            rec, k = run_variant(n, v.get("overrides"), v.get("transform"))
            st = rec.resource_state_time["operator_1"]
            row[f"prod_{n}"] = k["units_completed"]
            row[f"op1_walk_s_{n}"] = round(st.get("walking", 0.0), 1)
            row[f"op1_idle_s_{n}"] = round(st.get("idle", 0.0), 1)
            row[f"sel_blocked_s_{n}"] = round(rec.node_state_time[SEL].get("blocked", 0.0), 1)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------- trace analysis
TASK = {ASM: "assembly", INS: "inspection", TRN: "transport"}


def operator_intervals(rec) -> list[tuple[float, float, str, str]]:
    """(start, end, activity, location_after) from the event trace. Activities: walking, assembly, inspection,
    transport_load, transport_travel, transport_unload; idle = gaps."""
    iv, H = [], rec.horizon_s
    trips = {}
    for e in rec.events:
        t, ev, node = e["t"], e["event"], e["node"]
        if ev == "operator_walking":
            iv.append((t, t + e["seconds"], "walking", e["to"]))
        elif ev == "start_process" and node in (ASM, INS):
            trips[node] = t
        elif ev == "end_process" and node in (ASM, INS) and node in trips:
            iv.append((trips.pop(node), t, TASK[node], node))
        elif ev == "trip_start" and node == TRN:
            trips["trip"] = t
        elif ev == "loaded" and node == TRN:
            t0 = trips.pop("trip")
            iv.append((t0, t, "transport_load", ASM))
            iv.append((t, t + 10 / SPEED, "transport_travel", BUF))
            iv.append((t + 10 / SPEED, t + 10 / SPEED + 5, "transport_unload", BUF))
    iv.sort()
    out, cur, loc = [], 0.0, ASM
    for a, b, act, where in iv:
        if a > cur + 1e-9:
            out.append((cur, a, "idle", loc))
        out.append((a, b, act, where))
        cur, loc = max(cur, b), where
    if cur < H:
        out.append((cur, H, "idle", loc))
    return out


def selective_intervals(rec) -> list[tuple[float, float, str]]:
    """starved / busy / blocked periods of the selective from enter/start/end/leave events."""
    iv, last, state = [], 0.0, "starved"
    for e in rec.events:
        if e["node"] != SEL:
            continue
        ev, t = e["event"], e["t"]
        new = {"start_process": "busy", "end_process": "blocked", "leave": "starved"}.get(ev)
        if new and new != state:
            iv.append((last, t, state))
            last, state = t, new
    iv.append((last, rec.horizon_s, state))
    return [x for x in iv if x[1] > x[0] + 1e-9]


def activity_at(ops, t):
    for a, b, act, loc in ops:
        if a <= t < b:
            return act, loc
    return "end", None


def overlap_by_activity(ops, a, b) -> dict[str, float]:
    res: dict[str, float] = {}
    for x, y, act, _ in ops:
        o = min(b, y) - max(a, x)
        if o > 1e-9:
            res[act] = res.get(act, 0.0) + o
    return res


def decisions_rows(rec, racks: int) -> list[dict]:
    rows = []
    for x in rec.decisions:
        if x["resource"] != "operator_1":
            continue
        sysd = x["system"]
        rows.append({"t": x["t"], "time": x["time"], "selected_task": x["chosen_node"], "reason_code": x["reason_code"],
                     "decision_reason": x["reason"], "candidate_tasks": "|".join(c["node"] for c in x["candidates"]),
                     "previous_task": next(iter(x["current_task"].values()), None),
                     "feeding_wip": x["state"]["feed_wip"], "wip_target": x["state"]["target"],
                     "feed_detail": x["state"]["feed_detail"], "selective_state": x["state"].get(f"{SEL}_state"),
                     "input_buffer_level": sysd["buffers"].get(BUF), "available_racks": sysd["carriers_available"].get("racks"),
                     "transport_occupancy": sysd["transports"].get(TRN), "stations": sysd["stations"], "racks_total": racks})
    return rows


def rack_tracking(rec, racks: int) -> list[dict]:
    """Rack location per rack-holding entity, from the trace; conservation checked at every rack event
    against the pool's own 'available' count (logged at each seizure)."""
    where: dict[int, str] = {}
    rows = []
    ops = operator_intervals(rec)
    for e in rec.events:
        ent, ev, node = e["entity"], e["event"], e["node"]
        changed = True
        if ev == "carrier_seized":
            where[ent] = "assembly"
        elif ent in where and ev == "leave" and node == ASM:
            where[ent] = "transport"
        elif ent in where and ev == "enter_buffer":
            where[ent] = "input_buffer"
        elif ent in where and ev == "enter" and node == SEL:
            where[ent] = "selective"
        elif ent in where and ev == "enter" and node == INS:
            where[ent] = "review"
        elif ev == "carrier_released" and ent in where:
            where.pop(ent)
        else:
            changed = False
        if not changed:
            continue
        c = {k: sum(1 for v in where.values() if v == k) for k in ("assembly", "transport", "input_buffer", "selective", "review")}
        held = sum(c.values())
        row = {"t": e["t"], "event": ev, "entity": ent, "available": racks - held, **c, "total": racks,
               "sum_ok": racks - held + held == racks and held <= racks}
        if ev == "carrier_seized":
            row["engine_available_after_seize"] = e["available"]
            row["sum_ok"] = row["sum_ok"] and e["available"] == racks - held
        row["operator_activity"] = activity_at(ops, e["t"])[0]
        rows.append(row)
    return rows


def timeline(rec, racks: int, until: float) -> list[dict]:
    """Every operator decision and every task start/end in [0, until], with system state."""
    ops = operator_intervals(rec)
    sel = selective_intervals(rec)
    dec = {round(r["t"], 6): r for r in decisions_rows(rec, racks)}
    rk = rack_tracking(rec, racks)
    rows = []
    marks = sorted({round(a, 6) for a, b, *_ in ops if a <= until} | set(k for k in dec if k <= until))
    for t in marks:
        act, loc = activity_at(ops, t)
        sstate = next((s for a, b, s in sel if a <= t < b), "end")
        racks_now = next((r for r in reversed(rk) if r["t"] <= t), {})
        d = dec.get(t, {})
        rows.append({"t": t, "operator_state": act, "operator_location": loc, "selective_state": sstate,
                     "feeding_wip": d.get("feeding_wip"), "wip_target": d.get("wip_target"),
                     "input_buffer_level": d.get("input_buffer_level"),
                     "available_racks": racks_now.get("available", racks),
                     **{f"racks_in_{k}": racks_now.get(k, 0) for k in ("assembly", "transport", "input_buffer", "selective", "review")},
                     "candidate_tasks": d.get("candidate_tasks"), "selected_task": d.get("selected_task"),
                     "decision_reason": d.get("decision_reason")})
    return rows


def starvation_rows(rec, racks: int) -> tuple[list[dict], dict]:
    ops = operator_intervals(rec)
    decs = decisions_rows(rec, racks)
    rows, agg = [], {}
    for a, b, s in selective_intervals(rec):
        if s != "starved":
            continue
        prev_act, loc = activity_at(ops, a - 1e-6) if a > 0 else ("start", ASM)
        last_dec = next((d for d in reversed(decs) if d["t"] <= a), None)
        by = overlap_by_activity(ops, a, b)
        for k, v in by.items():
            agg[k] = agg.get(k, 0.0) + v
        rows.append({"starvation_start": round(a, 3), "starvation_end": round(b, 3), "duration": round(b - a, 3),
                     "feeding_wip_before": last_dec["feeding_wip"] if last_dec else None,
                     "operator_previous_task": prev_act, "operator_location": loc,
                     "why_no_rack_available": "no rack in buffer/transport: operator was " + ", ".join(
                         f"{k} {v:.1f}s" for k, v in sorted(by.items(), key=lambda kv: -kv[1])),
                     "last_operator_decision": last_dec["selected_task"] if last_dec else None,
                     "decision_reason": last_dec["reason_code"] if last_dec else None})
    return rows, {k: round(v, 1) for k, v in agg.items()}


def detect_period(rec, racks: int) -> str:
    """Smallest repeating operator-task pattern after the first hour (detected, not assumed)."""
    code = {ASM: "A", TRN: "T", INS: "I"}
    s = "".join(code[d["selected_task"]] for d in decisions_rows(rec, racks) if d["t"] >= 3600)
    for p in range(1, 13):
        for off in range(p):
            body = s[off:off + p * ((len(s) - off) // p)]
            if len(body) >= 3 * p and body == body[:p] * (len(body) // p):
                return body[:p] if body[:p].startswith("A") or "A" not in body[:p] else \
                    body[:p][body[:p].index("A"):] + body[:p][:body[:p].index("A")]
    return s[:12]


def cycle_stats(rec, racks: int, period: str | None = None) -> dict:
    period = period or detect_period(rec, racks)
    """Steady-state cycle: decision sequence repeating `period` (e.g. 'ATATII'), measured after the 1st hour."""
    decs = [d for d in decisions_rows(rec, racks) if d["t"] >= 3600]
    code = {ASM: "A", TRN: "T", INS: "I"}
    s = "".join(code[d["selected_task"]] for d in decs)
    i = s.find(period)
    starts = []
    while i != -1:
        starts.append(decs[i]["t"])
        i = s.find(period, i + len(period))
    durs = [b - a for a, b in zip(starts, starts[1:]) if abs((b - a) - (starts[1] - starts[0])) < 1e-6] if len(starts) > 1 else []
    ops = operator_intervals(rec)
    a, b = starts[0], starts[1]
    by = overlap_by_activity(ops, a, b)
    sel = selective_intervals(rec)
    sel_by: dict[str, float] = {}
    for x, y, st in sel:
        o = min(b, y) - max(a, x)
        if o > 0:
            sel_by[st] = sel_by.get(st, 0.0) + o
    done = sum(1 for _, _, d in rec.completions if a + 1e-6 < d <= b + 1e-6)  # completion at a (logged times rounded to 1e-6) closes the previous cycle
    return {"racks": racks, "cycle_pattern": period, "cycle_s": round(b - a, 3), "identical_cycles_after_1h": len(durs) + 1,
            "units_per_cycle": done, "s_per_unit": round((b - a) / max(done, 1), 3),
            **{f"op_{k}_s": round(v, 3) for k, v in sorted(by.items())},
            **{f"sel_{k}_s": round(v, 3) for k, v in sorted(sel_by.items())},
            "theoretical_8h_units_at_this_cycle": round(rec.horizon_s / ((b - a) / max(done, 1)), 2)}


def feed_wip_probe(racks: int = 2) -> list[dict]:
    """DIAGNOSTIC: sample WIP_TARGET_PRIORITY.feed_wip whenever the transport changes state (not only at decisions)
    to check whether one physical rack can be counted twice (assembly BLOCKED + transport BUSY during loading)."""
    from simforge.engine.des import nodes as _nodes
    samples: list[dict] = []
    orig = _nodes.IndustrialTransport._set

    def patched(self, v, state):
        orig(self, v, state)
        pool = self.ctx.pools["operator_1"]
        feed, detail = pool.strategy.feed_wip(pool)
        # independent reference: physical state of each live unit (exactly one location per unit)
        phys = {e.id: e.location for e in self.ctx.live.values()}
        candidates = {i for i, loc in phys.items() if loc in (ASM, BUF, TRN, f"reserved:{TRN}")}
        samples.append({"t": round(self.ctx.now, 6), "transport_state": state, "feed_wip": feed, **detail,
                        "units_by_state": {loc: sorted(i for i, x in phys.items() if x == loc) for loc in sorted(set(phys.values()))},
                        "physical_units_that_could_count": len(candidates),
                        "same_unit_counted_twice": feed > len(candidates)})

    _nodes.IndustrialTransport._set = patched
    try:
        m, reg = model_for(racks)
        DesEngine().run(compile_model(m, reg), m.simulation.base_seed, trace=False)
    finally:
        _nodes.IndustrialTransport._set = orig
    return samples


def missed_simultaneous_requests(rec, resource: str = "operator_1") -> list[dict]:
    """Contract check (docs/benchmark_operator_logic.md: 'every request created at that instant competes'):
    requests created at the instant t of an assignment that were NOT among its candidates.
    A request's creation time = (time of a later decision listing it) - waiting_s."""
    decs = [d for d in rec.decisions if d["resource"] == resource and d["kind"] == "assign"]
    out = []
    for i, d in enumerate(decs):
        cand = {(c["node"], c["entity"]) for c in d["candidates"]}
        for later in decs[i + 1:]:
            if later["t"] - d["t"] > 600:
                break
            for c in later["candidates"]:
                created = round(later["t"] - c["waiting_s"], 3)
                if abs(created - d["t"]) < 1e-3 and (c["node"], c["entity"]) not in cand:
                    out.append({"decision_t": d["t"], "decision_chosen": d["chosen_node"], "decision_reason": d["reason_code"],
                                "decision_candidates": "|".join(x["node"] for x in d["candidates"]),
                                "missed_request_node": c["node"], "missed_request_entity": c["entity"],
                                "seen_at_t": later["t"]})
                    cand.add((c["node"], c["entity"]))
    return out


def main() -> None:
    rows = [summary_row(n, *run(n)[:2]) for n in range(1, 11)]
    write_csv("01_reproduction_1_to_10_racks.csv", rows)
    for n in (2, 3):
        rec, _, _ = run(n)
        write_csv(f"02_operator_decisions_{n}racks.csv", decisions_rows(rec, n))
        write_csv(f"03_timeline_first30min_{n}racks.csv", timeline(rec, n, 1800))
        write_csv(f"04_selective_starvation_{n}racks.csv", starvation_rows(rec, n)[0])
        write_csv(f"07_rack_conservation_{n}racks.csv", rack_tracking(rec, n))
        write_csv(f"08_feed_wip_probe_{n}racks.csv", feed_wip_probe(n))
        write_csv(f"09_missed_simultaneous_requests_{n}racks.csv", missed_simultaneous_requests(rec))
    agg = []
    for n in (2, 3):
        rec, _, _ = run(n)
        agg.append({"racks": n, **{f"starved_while_{k}_s": v for k, v in starvation_rows(rec, n)[1].items()}})
    write_csv("04b_starvation_by_operator_activity.csv", agg)
    write_csv("05_counterfactuals.csv", counterfactuals())
    write_csv("06_cycles.csv", [cycle_stats(run(n)[0], n) for n in (1, 2, 3, 4)])
    print(f"CSV written to {OUT}")


if __name__ == "__main__":
    main()
