"""SimPy-backed implementation of the SimulationEngine interface."""

from __future__ import annotations

import simpy

from ... import ENGINE_NAME, ENGINE_VERSION
from ...domain.behaviors import Behavior
from ...validation.verifier import CompiledModel
from ..base import RunRecord
from .nodes import IndustrialBuffer, IndustrialNode, IndustrialServer, IndustrialSink, IndustrialSource, IndustrialTransport
from .calendar_runtime import CalendarClock
from .runtime import ResourcePool, SimContext, fmt_hms

# Convention: events occurring exactly at t = horizon are included.
_HORIZON_EPS = 1e-7

_NODE_CLASSES: dict[Behavior, type[IndustrialNode]] = {
    Behavior.SINK: IndustrialSink,
    Behavior.BUFFER: IndustrialBuffer,
    Behavior.SERVER: IndustrialServer,
    Behavior.SOURCE: IndustrialSource,
}


class DeadlockError(RuntimeError):
    """The system can no longer move (circular wait). Results of such a run are never reported."""


def _deadlock_report(ctx: SimContext) -> str:
    lines = [f"DEADLOCK at t={ctx.now:.3f}s ({fmt_hms(ctx.now)}): no event can occur before the horizon."]
    for pid, pool in ctx.pools.items():
        busy = {u.name: u.task for u in pool.units if u.busy}
        waiting = [r.node for r in pool.waiting]
        if busy or waiting:
            lines.append(f"  resource '{pid}': busy {busy}; waiting requests from {waiting}")
    snap = ctx.snapshot()
    lines.append(f"  stations {snap['stations']}; buffers {snap['buffers']}; transports {snap['transports']}; "
                 f"carriers available {snap['carriers_available']}")
    return "\n".join(lines)


class DesEngine:
    name = ENGINE_NAME
    version = ENGINE_VERSION

    def run(self, model: CompiledModel, seed: int, trace: bool = False) -> RunRecord:
        env = simpy.Environment()
        record = RunRecord(seed=seed, horizon_s=model.horizon_s, warmup_s=model.warmup_s,
                           engine=self.name, engine_version=self.version,
                           events=[] if trace else None, decisions=[] if trace else None)
        sim = model.model.simulation
        ctx = SimContext(env, seed, model.warmup_s, model.horizon_s, record, trace,
                         dispatch_timing=sim.dispatch_timing, check_invariants=sim.check_invariants)
        ctx.model = model.model
        positions = {n.id: (n.position.x, n.position.y) for n in model.model.nodes if n.position}
        ctx.node_rank = {n.id: i for i, n in enumerate(model.model.nodes)}
        ctx.production = getattr(model, "production", None)  # products/setups (engine >= 0.7.0); None = legacy
        ctx.maintenance = getattr(model, "maintenance", None)  # failure clocks / repair / PM (engine >= 0.8.0)
        rt = getattr(model, "availability", None)
        if rt is not None:  # calendars (engine >= 0.6.0); models without them never create a clock (legacy events)
            ctx.calendar = CalendarClock(ctx, rt)
        for i, r in enumerate(model.model.resources):
            ctx.pools[r.id] = ResourcePool(ctx, r, positions, index=i)
            if rt is not None and r.id in rt.resource_calendar:
                ctx.pools[r.id].set_calendar_label(ctx.calendar.label(rt.resource_calendar[r.id]))
        # sources last: they start pushing immediately and need every other node to exist
        order = sorted(model.nodes.values(), key=lambda c: c.behavior is Behavior.SOURCE)
        carrier_transports = {t for n in model.model.nodes for t in n.release_via.values()}
        for cn in order:
            if cn.behavior is Behavior.TRANSPORT:
                ctx.nodes[cn.node.id] = IndustrialTransport(ctx, cn, carrier_mode=cn.node.id in carrier_transports)
            else:
                ctx.nodes[cn.node.id] = _NODE_CLASSES[cn.behavior](ctx, cn)

        end = model.horizon_s + _HORIZON_EPS
        while True:
            t_next = env.peek()
            if t_next == float("inf"):  # (checked before 'past the horizon': inf > end)
                # nothing can ever happen again before the horizon: every process waits for another
                horizon_reached = ctx.calendar is not None and env.now >= model.horizon_s  # clock sentinel at the horizon
                if (ctx.live or any(p.waiting for p in ctx.pools.values())) and not horizon_reached:
                    raise DeadlockError(_deadlock_report(ctx))
                break
            if t_next > end:
                break
            env.step()

        for node in ctx.nodes.values():
            node.finalize()
        for pool in ctx.pools.values():
            pool.finalize()
        if rt is not None:
            _availability_record(ctx, model, record)
        ctx.wip.finalize()
        for tracker in ctx.product_wip.values():
            tracker.finalize()
        ctx.check_end()
        record.wip_end = ctx.wip.level
        if ctx.production is not None:
            for p in ctx.product_totals:
                record.wip_end_by_product[p] = sum(1 for e in ctx.live.values() if e.etype == p)
        record.invariant_checks = ctx.invariant_checks
        record.completion_times = [d for _, _, d in record.completions]
        for locs in ctx.carrier_locs.values():
            for tr in locs.values():
                tr.finalize()
        return record


def _availability_record(ctx: SimContext, model, record: RunRecord) -> None:
    """Planned time per calendar-gated resource/node in the measured window, and the time-accounting invariants:
    planned states == planned calendar time; unplanned states == unplanned calendar time (no double counting)."""
    from ...domain.calendar import AVAILABLE, BREAK, OFF_SHIFT
    from ..base import NodeState
    rt = model.availability
    a, b = model.warmup_s, model.horizon_s
    out: dict = {"calendar_hash": rt.spec_hash, "resources": {}, "nodes": {}}
    for rid, cid in rt.resource_calendar.items():
        tl, n = rt.timelines[cid], record.resource_units.get(rid, 0)
        row = {"calendar": cid, "units": n, "calendar_time_s": (b - a) * n,
               "planned_available_s": tl.time_in(AVAILABLE, a, b) * n, "break_s": tl.time_in(BREAK, a, b) * n,
               "off_shift_s": tl.time_in(OFF_SHIFT, a, b) * n}
        st = record.resource_state_time.get(rid, {})
        unplanned_states = sum(v for k, v in st.items() if k in (BREAK, OFF_SHIFT) or k.startswith("outside_planned:"))
        planned_states = sum(st.values()) - unplanned_states
        row["planned_states_s"], row["unplanned_states_s"] = planned_states, unplanned_states
        if ctx.check_invariants and abs(planned_states - row["planned_available_s"]) > 1e-6 * max(1.0, b) or \
                ctx.check_invariants and abs(unplanned_states - (row["break_s"] + row["off_shift_s"])) > 1e-6 * max(1.0, b):
            ctx.violation(f"calendar time accounting of '{rid}': planned states {planned_states:.3f}s vs calendar "
                          f"{row['planned_available_s']:.3f}s; unplanned {unplanned_states:.3f}s vs "
                          f"{row['break_s'] + row['off_shift_s']:.3f}s")
        out["resources"][rid] = row
    for nid in rt.gating:
        # servers only: transport vehicle states are not split by calendar in this version (their operators are,
        # in the resource accounting above); sources have no state tracker
        if nid not in record.node_state_time or record.node_behavior.get(nid) != "server":
            continue
        tl, n = rt.node_timeline(nid), record.node_slots.get(nid, 1)
        row = {"calendars": rt.gating[nid], "slots": n, "calendar_time_s": (b - a) * n,
               "planned_available_s": tl.time_in(AVAILABLE, a, b) * n, "break_s": tl.time_in(BREAK, a, b) * n,
               "off_shift_s": tl.time_in(OFF_SHIFT, a, b) * n}
        st = record.node_state_time[nid]
        planned_states = sum(st.get(s, 0.0) for s in NodeState.PLANNED)
        unplanned_states = sum(st.get(s, 0.0) for s in NodeState.UNPLANNED)
        row["planned_states_s"], row["unplanned_states_s"] = planned_states, unplanned_states
        if ctx.check_invariants and abs(planned_states - row["planned_available_s"]) > 1e-6 * max(1.0, b):
            ctx.violation(f"calendar time accounting of node '{nid}': planned states {planned_states:.3f}s vs calendar "
                          f"{row['planned_available_s']:.3f}s")
        out["nodes"][nid] = row
    record.availability = out
