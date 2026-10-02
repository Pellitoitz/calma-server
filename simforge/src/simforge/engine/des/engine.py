"""SimPy-backed implementation of the SimulationEngine interface."""

from __future__ import annotations

import simpy

from ... import ENGINE_NAME, ENGINE_VERSION
from ...domain.behaviors import Behavior
from ...validation.verifier import CompiledModel
from ..base import RunRecord
from .nodes import IndustrialBuffer, IndustrialNode, IndustrialServer, IndustrialSink, IndustrialSource, IndustrialTransport
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
        for i, r in enumerate(model.model.resources):
            ctx.pools[r.id] = ResourcePool(ctx, r, positions, index=i)
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
                if ctx.live or any(p.waiting for p in ctx.pools.values()):
                    raise DeadlockError(_deadlock_report(ctx))
                break
            if t_next > end:
                break
            env.step()

        for node in ctx.nodes.values():
            node.finalize()
        for pool in ctx.pools.values():
            pool.finalize()
        ctx.wip.finalize()
        ctx.check_end()
        record.wip_end = ctx.wip.level
        record.invariant_checks = ctx.invariant_checks
        record.completion_times = [d for _, _, d in record.completions]
        for locs in ctx.carrier_locs.values():
            for tr in locs.values():
                tr.finalize()
        return record
