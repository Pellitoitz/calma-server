"""SimPy-backed implementation of the SimulationEngine interface."""

from __future__ import annotations

import simpy

from ... import ENGINE_NAME, ENGINE_VERSION
from ...domain.behaviors import Behavior
from ...validation.verifier import CompiledModel
from ..base import RunRecord
from .nodes import IndustrialBuffer, IndustrialNode, IndustrialServer, IndustrialSink, IndustrialSource, IndustrialTransport
from .runtime import ResourcePool, SimContext

# Convention: events occurring exactly at t = horizon are included.
_HORIZON_EPS = 1e-7

_NODE_CLASSES: dict[Behavior, type[IndustrialNode]] = {
    Behavior.SINK: IndustrialSink,
    Behavior.BUFFER: IndustrialBuffer,
    Behavior.SERVER: IndustrialServer,
    Behavior.SOURCE: IndustrialSource,
}


class DesEngine:
    name = ENGINE_NAME
    version = ENGINE_VERSION

    def run(self, model: CompiledModel, seed: int, trace: bool = False) -> RunRecord:
        env = simpy.Environment()
        record = RunRecord(seed=seed, horizon_s=model.horizon_s, warmup_s=model.warmup_s,
                           engine=self.name, engine_version=self.version,
                           events=[] if trace else None, decisions=[] if trace else None)
        ctx = SimContext(env, seed, model.warmup_s, model.horizon_s, record, trace)
        ctx.model = model.model
        positions = {n.id: (n.position.x, n.position.y) for n in model.model.nodes if n.position}
        for r in model.model.resources:
            ctx.pools[r.id] = ResourcePool(ctx, r, positions)
        # sources last: they start pushing immediately and need every other node to exist
        order = sorted(model.nodes.values(), key=lambda c: c.behavior is Behavior.SOURCE)
        carrier_transports = {t for n in model.model.nodes for t in n.release_via.values()}
        for cn in order:
            if cn.behavior is Behavior.TRANSPORT:
                ctx.nodes[cn.node.id] = IndustrialTransport(ctx, cn, carrier_mode=cn.node.id in carrier_transports)
            else:
                ctx.nodes[cn.node.id] = _NODE_CLASSES[cn.behavior](ctx, cn)

        env.run(until=model.horizon_s + _HORIZON_EPS)

        for node in ctx.nodes.values():
            node.finalize()
        for pool in ctx.pools.values():
            pool.finalize()
        ctx.wip.finalize()
        record.wip_end = ctx.wip.level
        return record
