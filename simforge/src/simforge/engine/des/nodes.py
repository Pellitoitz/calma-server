"""Industrial building blocks executed by the DES kernel.

Flow protocol: every receiving node exposes `enter(entity)` (a generator).
It completes when the node has *accepted* the entity (space available). The
upstream node keeps its own slot until then -> blocking-after-service, so
buffer capacities and WIP limits genuinely constrain the flow.
"""

from __future__ import annotations

from typing import Generator

import simpy

from ...domain.behaviors import BufferParams, ServerParams, SourceParams
from ...validation.verifier import CompiledNode
from ..base import NodeState
from .runtime import Entity, LevelTracker, SimContext, StateTracker, Unit

Proc = Generator[simpy.Event, object, object]


class IndustrialNode:
    def __init__(self, ctx: SimContext, cn: CompiledNode):
        self.ctx = ctx
        self.cn = cn
        self.id = cn.node.id
        self.route_rng = ctx.rng(self.id, "routing")
        ctx.record.node_behavior[self.id] = cn.behavior.value
        ctx.record.node_wait[self.id] = []

    def enter(self, entity: Entity, on_accept=None) -> Proc:  # pragma: no cover - abstract
        raise NotImplementedError

    def next_node(self) -> "IndustrialNode":
        succ = self.cn.successors
        if len(succ) == 1:
            return self.ctx.nodes[succ[0][0]]
        r, acc = self.route_rng.random(), 0.0
        for target, p in succ:
            acc += p
            if r < acc:
                return self.ctx.nodes[target]
        return self.ctx.nodes[succ[-1][0]]

    def record_wait(self, entity: Entity) -> None:
        if self.ctx.counting:
            self.ctx.record.node_wait[self.id].append(self.ctx.now - entity.node_entered)

    def finalize(self) -> None:
        pass


class IndustrialSource(IndustrialNode):
    def __init__(self, ctx: SimContext, cn: CompiledNode):
        super().__init__(ctx, cn)
        self.p: SourceParams = cn.params  # type: ignore[assignment]
        self.rng = ctx.rng(self.id, "arrivals")
        self.etype = self.p.entity_type or "unit"
        ctx.env.process(self._run())

    def _admit(self, e: Entity) -> None:
        e.created = self.ctx.now
        self.ctx.record.created += 1
        self.ctx.wip.change(+1)
        self.ctx.log("created", e, self.id)

    def _push(self, e: Entity) -> Proc:
        yield from self.next_node().enter(e)

    def _run(self) -> Proc:
        n = 0
        while self.p.max_entities is None or n < self.p.max_entities:
            n += 1
            e = self.ctx.new_entity(self.etype)
            if self.p.arrival == "infinite":
                # unlimited supply: the unit exists in the system once the first node accepts it
                target = self.next_node()
                yield from target.enter(e, on_accept=self._admit)  # type: ignore[call-arg]
            else:
                yield self.ctx.env.timeout(self.p.interarrival.sample_seconds(self.rng))  # type: ignore[union-attr]
                self._admit(e)
                self.ctx.env.process(self._push(e))


class IndustrialSink(IndustrialNode):
    def enter(self, entity: Entity, on_accept=None) -> Proc:
        if on_accept:
            on_accept(entity)
        release_all_carriers(self.ctx, entity)
        self.ctx.wip.change(-1)
        if self.ctx.counting:
            self.ctx.record.completions.append((entity.id, entity.created, self.ctx.now))
        self.ctx.log("completed", entity, self.id)
        return
        yield  # pragma: no cover - makes this a generator


class IndustrialBuffer(IndustrialNode):
    def __init__(self, ctx: SimContext, cn: CompiledNode):
        super().__init__(ctx, cn)
        self.p: BufferParams = cn.params  # type: ignore[assignment]
        self.space = simpy.Resource(ctx.env, self.p.capacity) if self.p.capacity else None
        self.items: list[tuple[Entity, simpy.resources.resource.Request | None]] = []
        self._wake: simpy.Event | None = None
        self.level = LevelTracker(ctx, f"buffer:{self.id}")
        ctx.env.process(self._forward())

    def enter(self, entity: Entity, on_accept=None) -> Proc:
        req = None
        if self.space is not None:
            req = self.space.request()
            yield req
        if on_accept:
            on_accept(entity)
        entity.node_entered = self.ctx.now
        self.items.append((entity, req))
        self.level.change(+1)
        self.ctx.log("enter_buffer", entity, self.id, content=self.level.level)
        if self._wake is not None and not self._wake.triggered:
            self._wake.succeed()

    def _forward(self) -> Proc:
        while True:
            while not self.items:
                self._wake = self.ctx.env.event()
                yield self._wake
            entity, req = self.items.pop(0 if self.p.discipline == "fifo" else -1)
            # the unit keeps its buffer space until the downstream node accepts it
            yield from self.next_node().enter(entity)
            self.record_wait(entity)
            self.level.change(-1)
            if req is not None:
                self.space.release(req)  # type: ignore[union-attr]

    def finalize(self) -> None:
        self.level.finalize()


class IndustrialServer(IndustrialNode):
    """Machine / manual station / inspection / test... (behaviour 'server')."""

    def __init__(self, ctx: SimContext, cn: CompiledNode):
        super().__init__(ctx, cn)
        self.p: ServerParams = cn.params  # type: ignore[assignment]
        self.slots = simpy.Resource(ctx.env, self.p.capacity)
        self.free_slots = list(range(self.p.capacity))
        self.logical = [NodeState.STARVED] * self.p.capacity
        self.trackers = [StateTracker(ctx, NodeState.STARVED) for _ in range(self.p.capacity)]
        self.rng_time = ctx.rng(self.id, "process_time")
        self.rng_yield = ctx.rng(self.id, "yield")
        self.down = False
        self.up_event = ctx.env.event()
        self.processing: dict[int, simpy.Process] = {}
        ctx.record.node_processed[self.id] = 0
        ctx.record.node_rejects[self.id] = 0
        ctx.record.node_failures[self.id] = 0
        if self.p.failures:
            ctx.env.process(self._breakdowns())

    # ---- state helpers ----
    def _set(self, slot: int, state: str) -> None:
        self.logical[slot] = state
        self.trackers[slot].set(NodeState.DOWN if self.down else state)

    def _refresh(self) -> None:
        for i, t in enumerate(self.trackers):
            t.set(NodeState.DOWN if self.down else self.logical[i])

    # ---- flow ----
    def enter(self, entity: Entity, on_accept=None) -> Proc:
        req = self.slots.request()
        yield req
        if on_accept:
            on_accept(entity)
        slot = self.free_slots.pop(0)
        entity.node_entered = self.ctx.now
        self.ctx.log("enter", entity, self.id, slot=slot)
        self.ctx.env.process(self._work(entity, req, slot))

    def _work(self, e: Entity, req, slot: int) -> Proc:
        ctx, node = self.ctx, self.cn.node
        # 1) carriers (racks, pallets...) first, so an operator is never held while waiting for a rack
        for use in node.seize:
            self._set(slot, NodeState.WAITING_RESOURCE)
            units: list[Unit] = yield ctx.pools[use.resource].request(self.id, use.quantity, node.priority, e.id)
            e.carriers.append((use.resource, units))
            ctx.log("carrier_seized", e, self.id, resource=use.resource)
        # 2) operators / tools held during processing
        held: list[Unit] = []
        for use in self.p.resources:
            self._set(slot, NodeState.WAITING_RESOURCE)
            ctx.log("wait_resource", e, self.id, resource=use.resource)
            pool = ctx.pools[use.resource]
            units = yield pool.request(self.id, use.quantity, node.priority, e.id)
            walk = max(pool.travel_time(u, self.id) for u in units)
            for u in units:
                u.tracker.set("walking" if walk > 0 else "working")
            if walk > 0:
                ctx.log("operator_walking", e, self.id, resource=use.resource, seconds=round(walk, 3))
                yield ctx.env.timeout(walk)
            for u in units:
                u.location = self.id
                u.tracker.set("working")
            held.extend(units)
        self.record_wait(e)
        # 3) process (suspended during failures)
        self._set(slot, NodeState.BUSY)
        ctx.log("start_process", e, self.id)
        remaining = self.p.process_time.sample_seconds(self.rng_time)  # type: ignore[union-attr]
        while remaining > 1e-12:
            if self.down:
                yield self.up_event
                continue
            start = ctx.now
            self.processing[slot] = ctx.env.active_process  # type: ignore[assignment]
            try:
                yield ctx.env.timeout(remaining)
                remaining = 0.0
            except simpy.Interrupt:
                remaining -= ctx.now - start
            finally:
                self.processing.pop(slot, None)
        ctx.log("end_process", e, self.id)
        if ctx.counting:
            ctx.record.node_processed[self.id] += 1
        # 4) release operators/tools, then carriers released here
        by_pool: dict[str, list[Unit]] = {}
        for u in held:
            by_pool.setdefault(u.pool.id, []).append(u)
        for pid, units in by_pool.items():
            ctx.pools[pid].release(units)
        for rid in node.release:
            release_carrier(ctx, e, rid)
        # 5) quality
        target = None
        if self.p.yield_rate < 1 and self.rng_yield.random() >= self.p.yield_rate:
            if ctx.counting:
                ctx.record.node_rejects[self.id] += 1
            if self.p.on_reject == "scrap":
                release_all_carriers(ctx, e)
                ctx.wip.change(-1)
                if ctx.counting:
                    ctx.record.scrapped.append((e.id, self.id, ctx.now))
                ctx.log("scrapped", e, self.id)
            else:
                target = ctx.nodes[self.p.on_reject]
                ctx.log("rejected", e, self.id, to=self.p.on_reject)
        else:
            target = self.next_node()
        # 6) move downstream (blocked while downstream is full)
        if target is not None:
            self._set(slot, NodeState.BLOCKED)
            yield from target.enter(e)
            ctx.log("leave", e, self.id, to=target.id)
        self._set(slot, NodeState.STARVED)
        self.free_slots.append(slot)
        self.free_slots.sort()
        self.slots.release(req)

    def _breakdowns(self) -> Proc:
        f = self.p.failures
        rng = self.ctx.rng(self.id, "failures")
        while True:
            yield self.ctx.env.timeout(f.mtbf.sample_seconds(rng))  # type: ignore[union-attr]
            self.down = True
            if self.ctx.counting:
                self.ctx.record.node_failures[self.id] += 1
            self._refresh()
            self.ctx.log("down", None, self.id)
            for proc in list(self.processing.values()):
                if proc.is_alive:
                    proc.interrupt("failure")
            yield self.ctx.env.timeout(f.mttr.sample_seconds(rng))  # type: ignore[union-attr]
            self.down = False
            self._refresh()
            self.ctx.log("up", None, self.id)
            evt, self.up_event = self.up_event, self.ctx.env.event()
            evt.succeed()

    def finalize(self) -> None:
        tot: dict[str, float] = {}
        for t in self.trackers:
            for k, v in t.finalize().items():
                tot[k] = tot.get(k, 0.0) + v
        self.ctx.record.node_state_time[self.id] = tot
        self.ctx.record.node_slots[self.id] = self.p.capacity


def release_carrier(ctx: SimContext, e: Entity, resource: str) -> None:
    for i, (rid, units) in enumerate(e.carriers):
        if rid == resource:
            ctx.pools[rid].release(units)
            del e.carriers[i]
            ctx.log("carrier_released", e, None, resource=rid)
            return


def release_all_carriers(ctx: SimContext, e: Entity) -> None:
    for rid, units in e.carriers:
        ctx.pools[rid].release(units)
    e.carriers.clear()
