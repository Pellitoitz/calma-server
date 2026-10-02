"""Industrial building blocks executed by the DES kernel.

Flow protocol: every receiving node exposes `enter(entity)` (a generator).
It completes when the node has *accepted* the entity (space available). The
upstream node keeps its own slot until then -> blocking-after-service, so
buffer capacities and WIP limits genuinely constrain the flow.
"""

from __future__ import annotations

from typing import Generator

import simpy

from collections import Counter

from ...domain.behaviors import BufferParams, ServerParams, SourceParams, TransportParams
from ...validation.verifier import CompiledNode
from ..base import NodeState
from ..production_compile import SetupTransitionMissing
from .runtime import AVAILABLE, SETUP_TASK, Entity, LevelTracker, ResourcePool, SimContext, StateTracker, Unit

Proc = Generator[simpy.Event, object, object]

# trace event names of the shared timed-operation loop (processing names are the historical ones)
_PROCESS_EVENTS = {"restart": "restart_lost_work", "pause": "paused_by_calendar", "resume": "resume_process",
                   "preempted": "preempted", "paused_state": NodeState.PAUSED}
_SETUP_PAUSED = "setup_paused"  # logical slot state: setup paused by its calendar (tracked as PAUSED or WAITING_RESOURCE)
_SETUP_EVENTS = {"restart": "setup_restart_lost_work", "pause": "setup_paused_by_calendar", "resume": "setup_resume",
                 "preempted": "setup_preempted", "paused_state": _SETUP_PAUSED}


class IndustrialNode:
    def __init__(self, ctx: SimContext, cn: CompiledNode):
        self.ctx = ctx
        self.cn = cn
        self.id = cn.node.id
        self.kind = cn.behavior.value
        self.route_rng = ctx.rng(self.id, "routing")
        ctx.record.node_behavior[self.id] = cn.behavior.value
        ctx.record.node_wait[self.id] = []

    def enter(self, entity: Entity, on_accept=None) -> Proc:  # pragma: no cover - abstract
        raise NotImplementedError

    def next_node(self, entity: Entity | None = None) -> "IndustrialNode":
        if entity is not None and entity.route is not None:  # product route (engine >= 0.7.0): no random draw
            r = entity.route
            try:
                i = r.index(self.id, entity.route_pos)
            except ValueError:
                self.ctx.violation(f"entity {entity.id} ({entity.etype}) at '{self.id}', which is not on its route {list(r)}")
            entity.route_pos = i + 1
            return self.ctx.nodes[r[i + 1]]
        succ = self.cn.successors
        if len(succ) == 1:
            return self.ctx.nodes[succ[0][0]]
        r, acc = self.route_rng.random(), 0.0
        for target, p in succ:
            acc += p
            if r < acc:
                return self.ctx.nodes[target]
        return self.ctx.nodes[succ[-1][0]]

    def reserve(self) -> Proc:
        """Reserve a place for a future `enter(..., reservation=token)`; default: nothing to reserve."""
        return None
        yield  # pragma: no cover

    # generic probes used by dispatch strategies (process-agnostic)
    def occupancy(self) -> int:
        return 0

    def state_counts(self) -> dict[str, int]:
        return {}

    def held_entities(self) -> set[int]:
        """Entities physically held by this node (counted by occupancy())."""
        return set()

    def in_process_entities(self) -> set[int]:
        """Entities in a slot/vehicle that is BUSY or BLOCKED (the 'in process' notion of WIP_TARGET_PRIORITY)."""
        return set()

    def on_calendar_change(self) -> None:
        """A gating calendar changed (CalendarClock). Default: nothing (waiters re-check on the change event)."""

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
        # product generation (engine >= 0.7.0). Legacy sources create no product stream: no extra random numbers
        self.gen = ctx.production.generation(self.id) if ctx.production is not None else None
        if self.gen is not None:
            self.seq_i = 0
            if self.gen.mode == "PROBABILISTIC_MIX":  # fixed order (sorted ids): the same hash gives the same sequence
                self.rng_product = ctx.rng(self.id, "product_mix")
                self.mix = sorted((p, w) for p, w in self.gen.mix.items() if w > 0)
        # own calendar (engine >= 0.6.0): arrivals only in available time (the interarrival clock pauses outside it)
        self.gating = ctx.calendar.rt.gating.get(self.id, []) if ctx.calendar else []
        ctx.env.process(self._run())

    def _admit(self, e: Entity) -> None:
        e.created = self.ctx.now
        self.ctx.admit(e, self.id)
        self.ctx.record.created += 1
        self.ctx.wip.change(+1)
        if self.ctx.production is not None:
            self.ctx.product_in(e)
            self.ctx.log("created", e, self.id, product=e.etype)
        else:
            self.ctx.log("created", e, self.id)

    def _push(self, e: Entity) -> Proc:
        yield from self.next_node(e).enter(e)

    def _new(self) -> Entity | None:
        """Next entity. Products: PROBABILISTIC_MIX draws from this source's own 'product_mix' stream;
        EXPLICIT_SEQUENCE takes the next element (None when a non-repeating sequence is exhausted)."""
        if self.gen is None:
            return self.ctx.new_entity(self.etype)
        if self.gen.mode == "EXPLICIT_SEQUENCE":
            seq = self.gen.sequence
            if self.seq_i >= len(seq) and not self.gen.repeat:
                return None
            product = seq[self.seq_i % len(seq)]
            self.seq_i += 1
        else:
            r, acc, product = self.rng_product.random(), 0.0, self.mix[-1][0]
            for p, w in self.mix:
                acc += w
                if r < acc:
                    product = p
                    break
        e = self.ctx.new_entity(product)
        e.route = self.ctx.production.routes.get(product)
        return e

    def _run(self) -> Proc:
        n = 0
        while self.p.max_entities is None or n < self.p.max_entities:
            n += 1
            e = self._new()
            if e is None:
                return  # explicit sequence finished (repeat: false)
            if self.p.arrival == "infinite":
                # unlimited supply: the unit exists in the system once the first node accepts it
                target = self.next_node(e)
                if self.gating:
                    # place first, then wait for the source's own availability: never admitted outside it
                    res = yield from target.reserve()
                    yield from self.ctx.calendar.wait_until_ok(self.gating)
                    yield from target.enter(e, on_accept=self._admit, reservation=res)  # type: ignore[call-arg]
                else:
                    yield from target.enter(e, on_accept=self._admit)  # type: ignore[call-arg]
            else:
                d = self.p.interarrival.sample_seconds(self.rng)  # type: ignore[union-attr]
                if self.gating:
                    yield from self.ctx.calendar.consume_available(self.gating, d)
                else:
                    yield self.ctx.env.timeout(d)
                self._admit(e)
                self.ctx.env.process(self._push(e))


class IndustrialSink(IndustrialNode):
    def enter(self, entity: Entity, on_accept=None, reservation=None) -> Proc:
        if on_accept:
            on_accept(entity)
        self.ctx.place(entity, self.id)
        release_all_carriers(self.ctx, entity)
        self.ctx.retire(entity, "completed")
        self.ctx.wip.change(-1)
        if self.ctx.production is not None:
            self.ctx.product_out(entity, "completed")
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
        self.level = LevelTracker(ctx, f"buffer:{self.id}", upper=self.p.capacity)
        self._forwarding: Entity | None = None  # popped, still in the buffer until the next node accepts it
        ctx.env.process(self._forward())

    def reserve(self) -> Proc:
        if self.space is None:
            return None
        req = self.space.request()
        yield req
        return req

    def enter(self, entity: Entity, on_accept=None, reservation=None) -> Proc:
        req = reservation
        if req is None and self.space is not None:
            req = self.space.request()
            yield req
        if on_accept:
            on_accept(entity)
        entity.node_entered = self.ctx.now
        self.ctx.place(entity, self.id)
        self.items.append((entity, req))
        self.level.change(+1)
        self.ctx.changed(self.id)
        self.ctx.log("enter_buffer", entity, self.id, content=self.level.level)
        if self._wake is not None and not self._wake.triggered:
            self._wake.succeed()

    def _forward(self) -> Proc:
        while True:
            while not self.items:
                self._wake = self.ctx.env.event()
                yield self._wake
            entity, req = self.items.pop(0 if self.p.discipline == "fifo" else -1)
            self._forwarding = entity
            # the unit keeps its buffer space until the downstream node accepts it
            yield from self.next_node(entity).enter(entity)
            self._forwarding = None
            self.record_wait(entity)
            self.level.change(-1)
            self.ctx.changed(self.id)
            if req is not None:
                self.space.release(req)  # type: ignore[union-attr]

    def occupancy(self) -> int:
        return self.level.level

    def held_entities(self) -> set[int]:
        ids = {e.id for e, _ in self.items}
        if self._forwarding is not None:
            ids.add(self._forwarding.id)
        return ids

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
        self.slot_entity: list[Entity | None] = [None] * self.p.capacity
        self.trackers = [StateTracker(ctx, NodeState.STARVED) for _ in range(self.p.capacity)]
        self.rng_time = ctx.rng(self.id, "process_time")
        self.rng_yield = ctx.rng(self.id, "yield")
        self.down = False
        self.up_event = ctx.env.event()
        self.processing: dict[int, simpy.Process] = {}
        # calendars (engine >= 0.6.0): calendars that must ALL be available for this node to work (own + resources)
        rt = ctx.calendar.rt if ctx.calendar else None
        self.gating: list[str] = rt.gating.get(self.id, []) if rt else []
        pol = rt.policies.get(self.id) if rt else None
        self.policy = pol.at_unavailability if pol else None
        self.start_rule = pol.start_rule if pol else None
        ctx.record.node_processed[self.id] = 0
        ctx.record.node_rejects[self.id] = 0
        ctx.record.node_failures[self.id] = 0
        ctx.record.node_preemptions[self.id] = 0
        # products and setups (engine >= 0.7.0); legacy nodes: no table, no setup, no extra random stream
        prod = ctx.production
        self.prod_times = prod.processing.get(self.id) if prod is not None else None
        self.setup = prod.setups.get(self.id) if prod is not None else None
        self.phase: dict[int, str] = {}  # slot -> "setup" | "process" (what an interruption applies to)
        if self.setup is not None:
            self.setup_state = self.setup.initial_state  # changes ONLY when a setup completes
            self.rng_setup = ctx.rng(self.id, "setup")
            self.setup_gating: list[str] = prod.setup_gating.get(self.id, [])
            self.setup_policy = self.setup.at_unavailability
            self.setup_uses = self.setup.resources
            ctx.record.node_setups[self.id] = 0
        if self.p.failures:
            ctx.env.process(self._breakdowns())
        if self.gating:
            self._refresh()  # initial calendar state at t=0

    # ---- state helpers ----
    def _cal_ok(self) -> bool:
        return not self.gating or self.ctx.calendar.ok(self.gating)

    def _eff(self, state: str) -> str:
        """Tracked state. Without calendars: logical state or DOWN (legacy). Outside planned time: paused /
        busy (FINISH_CURRENT overrun) / break / off_shift, so planned and unplanned time are never mixed."""
        if self.gating and not self.ctx.calendar.ok(self.gating):
            if state == NodeState.BUSY:
                return NodeState.BUSY_OUTSIDE
            if state == NodeState.SETUP:
                return NodeState.SETUP_OUTSIDE
            if state in (NodeState.PAUSED, _SETUP_PAUSED):
                return NodeState.PAUSED
            return self.ctx.calendar.off_label(self.gating)
        if state == _SETUP_PAUSED:  # setup paused by ITS calendar inside the node's planned time: waits for a resource
            return NodeState.DOWN if self.down else NodeState.WAITING_RESOURCE
        return NodeState.DOWN if self.down else state

    def _set(self, slot: int, state: str) -> None:
        self.logical[slot] = state
        self.trackers[slot].set(self._eff(state))
        self.ctx.changed(self.id)

    def occupancy(self) -> int:
        return self.p.capacity - len(self.free_slots)

    def state_counts(self) -> dict[str, int]:
        return dict(Counter(NodeState.DOWN if self.down else st for st in self.logical))

    def held_entities(self) -> set[int]:
        return {e.id for e in self.slot_entity if e is not None}

    def in_process_entities(self) -> set[int]:
        return {e.id for e, st in zip(self.slot_entity, self.logical)
                if e is not None and not self.down and st in (NodeState.BUSY, NodeState.BLOCKED)}

    def _refresh(self) -> None:
        for i, t in enumerate(self.trackers):
            t.set(self._eff(self.logical[i]))

    def _interrupt(self, slot: int, cause: str) -> bool:
        """The ONLY way an operation in progress is interrupted (failure, calendar, pre-emption). The process is removed
        from `processing` BEFORE the interrupt is sent, so a second cause at the same instant, or while the process is
        handling the first one (e.g. waiting to re-acquire its operator after a pre-emption), finds nothing to
        interrupt: one interruption, one remaining-work update, one release."""
        proc = self.processing.pop(slot, None)
        if proc is None or not proc.is_alive:
            return False
        proc.interrupt(cause)
        return True

    def on_calendar_change(self) -> None:
        """Calendar transition of one of the gating calendars (called by the CalendarClock, URGENT)."""
        cal = self.ctx.calendar
        for slot in sorted(self.processing):
            if self.phase.get(slot) == "setup":
                gating, policy = self.setup_gating, self.setup_policy
            else:
                gating, policy = self.gating, self.policy
            if gating and not cal.ok(gating) and policy in ("PAUSE_RESUME", "STOP_RESTART"):
                self._interrupt(slot, "calendar")
        if self._cal_ok():
            for use in self.p.resources:  # requests left pending while this node was unavailable compete again
                self.ctx.pools[use.resource]._schedule_dispatch()
        if self.setup is not None and (not self.setup_gating or cal.ok(self.setup_gating)):
            for use in self.setup_uses:
                self.ctx.pools[use.resource]._schedule_dispatch()
        self._refresh()
        self.ctx.changed(self.id)

    def _release_for_calendar(self, e: Entity, slot: int, held: list[Unit], state: str, gating: list[str] | None = None) -> Proc:
        """Free operators/tools (not carriers, not the slot) until every gating calendar is available again AND the
        machine is not down: resources are re-requested only when the operation can really continue (a machine still
        under repair when the shift starts does not pull its operator back until it is repaired)."""
        release_units(self.ctx, held)
        self._set(slot, state)
        while True:
            yield from self.ctx.calendar.wait_until_ok(self.gating if gating is None else gating)
            if not self.down:
                return []
            yield self.up_event

    def _ready_to_start(self, e: Entity, slot: int, held: list[Unit], gating: list[str] | None = None,
                        uses=None, task: str | None = None, full_window: bool = True) -> Proc:
        """Before STARTING an operation: every gating calendar available, and (REQUIRE_FULL_WINDOW, deterministic times
        only, processing only) the whole operation fits before the common availability ends. Returns the held units."""
        cal = self.ctx.calendar
        gating = self.gating if gating is None else gating
        while True:
            if not cal.ok(gating):
                held = yield from self._release_for_calendar(e, slot, held, NodeState.WAITING_RESOURCE, gating)
                held = yield from self._acquire(e, slot, uses=uses, task=task)
                continue
            if full_window and self.start_rule == "REQUIRE_FULL_WINDOW":
                need = self._pt(e).mean_seconds() * self.p.entity_time_factor()  # type: ignore[union-attr]
                end = cal.window_end(self.gating, self.ctx.now)
                if self.ctx.now + need > end + 1e-9:
                    self.ctx.log("start_deferred", e, self.id, needs_s=round(need, 3), window_left_s=round(end - self.ctx.now, 3))
                    release_units(self.ctx, held)
                    self._set(slot, NodeState.WAITING_RESOURCE)
                    yield self.ctx.env.timeout(end - self.ctx.now)
                    held = []
                    yield from cal.wait_until_ok(self.gating)
                    held = yield from self._acquire(e, slot)
                    continue
            return held

    def _pt(self, e: Entity):
        """Processing time distribution for this entity: the product's own (engine >= 0.7.0) or the node's."""
        if self.prod_times is None:
            return self.p.process_time
        pt = self.prod_times.get(e.etype)
        if pt is None:  # the verifier makes this impossible; never fall back to another product's time
            raise RuntimeError(f"'{self.id}': no processing time for product '{e.etype}'")
        return pt

    # ---- flow ----
    def reserve(self) -> Proc:
        req = self.slots.request()
        yield req
        return req

    def enter(self, entity: Entity, on_accept=None, reservation=None) -> Proc:
        req = reservation
        if req is None:
            req = self.slots.request()
            yield req
        if on_accept:
            on_accept(entity)
        slot = self.free_slots.pop(0)
        self.slot_entity[slot] = entity
        entity.node_entered = self.ctx.now
        self.ctx.place(entity, self.id)
        self.ctx.log("enter", entity, self.id, slot=slot)
        self.ctx.env.process(self._work(entity, req, slot))

    def _acquire(self, e: Entity, slot: int, resume: bool = False, uses=None, task: str | None = None) -> Proc:
        """Operators/tools held during processing (walking to this node if they have travel). Setups (engine >= 0.7.0)
        pass their own `uses` and the task id '<node>#setup' (units walk to this node)."""
        ctx, held = self.ctx, []
        for use in (self.p.resources if uses is None else uses):
            self._set(slot, NodeState.WAITING_RESOURCE)
            if task is None:
                ctx.log("wait_resource", e, self.id, resource=use.resource, resume=resume)
            else:
                ctx.log("wait_resource", e, self.id, resource=use.resource, resume=resume, task=task)
            held.extend((yield from acquire_units(ctx, ctx.pools[use.resource], task or self.id, use.quantity,
                                                  self.cn.node.priority, e, resume, walk_to=self.id if task else None)))
        return held

    def _work(self, e: Entity, req, slot: int) -> Proc:
        ctx, node = self.ctx, self.cn.node
        # 1) carriers (racks, pallets...) first, so an operator is never held while waiting for a rack
        for use in node.seize:
            self._set(slot, NodeState.WAITING_RESOURCE)
            pool = ctx.pools[use.resource]
            units: list[Unit] = yield pool.request(self.id, use.quantity, node.priority, e.id)
            e.carriers.append((use.resource, units))
            pool.pending -= len(units)
            for u in units:
                u.granted_at = None
            ctx.carrier_move(use.resource, units, f"granted:{self.id}", e.location or self.id)
            ctx.check_carriers(use.resource)
            ctx.log("carrier_seized", e, self.id, resource=use.resource, available=sum(1 for u in pool.units if not u.busy))
        # 1b) setup / changeover (engine >= 0.7.0): its own resources, before the processing resources
        if self.setup is not None:
            yield from self._do_setup(e, slot)
        # 2) operators / tools
        held = yield from self._acquire(e, slot)
        if self.gating:
            held = yield from self._ready_to_start(e, slot, held)
        self.record_wait(e)
        # 3) process: suspended during failures; pre-emptible by the resource's dispatch strategy;
        #    calendars: FINISH_CURRENT continues, PAUSE_RESUME keeps the remaining work, STOP_RESTART loses it
        self.phase[slot] = "process"
        self._set(slot, NodeState.BUSY)
        ctx.log("start_process", e, self.id)
        remaining = self.p.sample_entity_seconds(self.rng_time, None if self.prod_times is None else self._pt(e))
        held = yield from self._timed(e, slot, held, remaining, self.policy, self.gating, None, None, NodeState.BUSY,
                                      _PROCESS_EVENTS)
        ctx.log("end_process", e, self.id)
        if ctx.counting:
            ctx.record.node_processed[self.id] += 1
        # 4) release operators/tools, then carriers released here (optionally via a return transport)
        release_units(ctx, held)
        for rid in node.release:
            release_carrier(ctx, e, rid, node.release_via.get(rid))
        # 5) quality
        target = None
        if self.p.yield_rate < 1 and self.rng_yield.random() >= self.p.yield_rate:
            if ctx.counting:
                ctx.record.node_rejects[self.id] += 1
            if self.p.on_reject == "scrap":
                release_all_carriers(ctx, e)
                ctx.retire(e, "scrapped")
                ctx.wip.change(-1)
                if ctx.production is not None:
                    ctx.product_out(e, "scrapped")
                if ctx.counting:
                    ctx.record.scrapped.append((e.id, self.id, ctx.now))
                ctx.log("scrapped", e, self.id)
            else:
                target = ctx.nodes[self.p.on_reject]
                ctx.log("rejected", e, self.id, to=self.p.on_reject)
        else:
            target = self.next_node(e)
        # 6) move downstream (blocked while downstream is full)
        if target is not None:
            self._set(slot, NodeState.BLOCKED)
            yield from target.enter(e)
            ctx.log("leave", e, self.id, to=target.id)
        self.free_slots.append(slot)
        self.free_slots.sort()
        self.slot_entity[slot] = None
        self._set(slot, NodeState.STARVED)
        self.slots.release(req)

    def _timed(self, e: Entity, slot: int, held: list[Unit], full: float, policy, gating: list[str], uses, task,
               busy: str, names: dict, interruptions: list | None = None) -> Proc:
        """Run `full` seconds of work (processing or setup) in this slot. The single implementation of: suspension
        while DOWN (failure clock unchanged: remaining work kept), calendar policy (PAUSE_RESUME keeps the remaining,
        STOP_RESTART repeats the SAME sample), pre-emption by the dispatch strategy. Returns the held units."""
        ctx = self.ctx
        remaining = full
        proc = ctx.env.active_process
        while remaining > 1e-12:
            if self.down:
                yield self.up_event
                continue
            if gating and policy in ("PAUSE_RESUME", "STOP_RESTART") and not ctx.calendar.ok(gating):
                if policy == "STOP_RESTART":
                    ctx.log(names["restart"], e, self.id, lost_s=round(full - remaining, 3))
                    remaining = full  # REUSE_ORIGINAL_SAMPLE: no new random number
                ctx.log(names["pause"], e, self.id, remaining_s=round(remaining, 3), policy=policy)
                held = yield from self._release_for_calendar(e, slot, held, names["paused_state"], gating)
                held = yield from self._acquire(e, slot, resume=True, uses=uses, task=task)
                if policy == "STOP_RESTART":
                    held = yield from self._ready_to_start(e, slot, held, gating, uses, task, full_window=task is None)
                self._set(slot, busy)
                ctx.log(names["resume"], e, self.id, remaining_s=round(remaining, 3))
                continue
            start = ctx.now
            self.processing[slot] = proc  # type: ignore[assignment]
            for u in held:
                u.preemptible = True
                u.preempt = lambda s=slot: self._interrupt(s, "preempt")
            try:
                yield ctx.env.timeout(remaining)
                remaining = 0.0
            except simpy.Interrupt as intr:
                remaining -= ctx.now - start
                if intr.cause == "calendar" and remaining <= 1e-9:
                    remaining = 0.0  # finished exactly when availability ended: complete, never paused/restarted
                if interruptions is not None:
                    interruptions.append({"t": ctx.now, "cause": intr.cause, "remaining_s": round(remaining, 6)})
                if intr.cause == "preempt":
                    if ctx.counting:
                        ctx.record.node_preemptions[self.id] += 1
                    ctx.log(names["preempted"], e, self.id, remaining_s=round(remaining, 3))
                    release_units(ctx, held)
                    held = yield from self._acquire(e, slot, resume=True, uses=uses, task=task)
                    self._set(slot, busy)
                    ctx.log(names["resume"], e, self.id)
            finally:
                self.processing.pop(slot, None)
                for u in held:
                    u.preemptible = False
                    u.preempt = None
        return held

    def _do_setup(self, e: Entity, slot: int) -> Proc:
        """Changeover before processing `e` (engine >= 0.7.0). Required iff the node's CURRENT setup state differs from
        the entity's setup key; the state changes only when the setup COMPLETES. An undefined change stops the run."""
        ctx = self.ctx
        key = ctx.production.setup_key.get(e.etype)
        frm = self.setup_state
        if key is None or key == frm:
            if key is None:
                raise SetupTransitionMissing(f"t={ctx.now:.3f}s: product '{e.etype}' has no setup_key at '{self.id}'")
            return
        dur = self.setup.duration(frm, key)
        if dur is None:
            raise SetupTransitionMissing(f"t={ctx.now:.3f}s: '{self.id}' needs setup {frm}->{key} for entity {e.id} "
                                         f"({e.etype}) but the model does not define it (never defaulted)")
        task = self.id + SETUP_TASK
        held = yield from self._acquire(e, slot, uses=self.setup_uses, task=task)
        if self.setup_gating:
            held = yield from self._ready_to_start(e, slot, held, self.setup_gating, self.setup_uses, task, full_window=False)
        sample = dur.sample_seconds(self.rng_setup)
        row = {"node": self.id, "slot": slot, "entity": e.id, "product": e.etype, "from": frm, "to": key,
               "start": ctx.now, "sampled_s": sample, "resources": [u.name for u in held], "interruptions": []}
        self.phase[slot] = "setup"
        self._set(slot, NodeState.SETUP)
        ctx.log("setup_start", e, self.id, frm=frm, to=key, duration_s=round(sample, 6), resources=row["resources"])
        held = yield from self._timed(e, slot, held, sample, self.setup_policy, self.setup_gating, self.setup_uses, task,
                                      NodeState.SETUP, _SETUP_EVENTS, row["interruptions"])
        self.setup_state = key  # only now: an interrupted/paused setup never counts as done
        row["end"] = ctx.now
        row["elapsed_s"] = ctx.now - row["start"]
        row["counted"] = ctx.counting
        ctx.record.setups.append(row)
        if ctx.counting:
            ctx.record.node_setups[self.id] += 1
        ctx.log("setup_end", e, self.id, frm=frm, to=key)
        release_units(ctx, held)

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
            for slot in sorted(self.processing):
                self._interrupt(slot, "failure")
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


def acquire_units(ctx: SimContext, pool: ResourcePool, node_id: str, qty: int, priority: int, e: Entity | None,
                  resume: bool = False, walk_to: str | None = None) -> Proc:
    """Request units, walk them to `walk_to` (default: the requesting node), mark them working."""
    dest = walk_to or node_id
    units: list[Unit] = yield pool.request(node_id, qty, priority, e.id if e else None, resume, location=dest)
    walk = max(pool.travel_time(u, dest) for u in units)
    for u in units:
        u.set_state("walking" if walk > 0 else f"working:{node_id}")
    if walk > 0:
        ctx.log("operator_walking", e, node_id, resource=pool.id, seconds=round(walk, 3),
                frm=",".join(str(u.location) for u in units), to=dest)
        yield ctx.env.timeout(walk)
    for u in units:
        u.location = dest
        u.set_state(f"working:{node_id}")
    return units


def release_units(ctx: SimContext, units: list[Unit]) -> None:
    by_pool: dict[str, list[Unit]] = {}
    for u in units:
        by_pool.setdefault(u.pool.id, []).append(u)
    for pid, us in by_pool.items():
        ctx.pools[pid].release(us)


def release_carrier(ctx: SimContext, e: Entity, resource: str, via: str | None = None) -> None:
    for i, (rid, units) in enumerate(e.carriers):
        if rid == resource:
            del e.carriers[i]
            if via:
                # the empty carrier travels back physically before it can be reused
                ctx.carrier_move(rid, units, e.location or AVAILABLE, f"return:{via}")
                ctx.nodes[via].carry_back(rid, units)
                ctx.log("carrier_to_transport", e, via, resource=rid)
            else:
                ctx.carrier_move(rid, units, e.location or AVAILABLE, AVAILABLE)
                ctx.pools[rid].release(units)
                ctx.log("carrier_released", e, None, resource=rid)
            ctx.check_carriers(rid)
            return


def release_all_carriers(ctx: SimContext, e: Entity) -> None:
    carriers, e.carriers = e.carriers, []
    for rid, units in carriers:
        ctx.carrier_move(rid, units, e.location or AVAILABLE, AVAILABLE)
        ctx.pools[rid].release(units)
    if carriers:
        ctx.check_carriers()


class IndustrialTransport(IndustrialNode):
    """Physical transport: origin -> destination, `capacity` units per trip, `fleet` parallel trips.

    Trip = resources walk to the origin -> load -> travel (distance/speed) -> unload -> hand over to the
    destination (blocked while it is full) -> optional empty return.
    Pickup semantics: with loading_area = 0 (default) a unit STAYS in the upstream node, keeping its place,
    until it is physically loaded (no phantom buffer place). With loading_area = N, N units may wait at the
    pickup point (belonging to this node).
    Two uses: in the product flow (edges) or returning EMPTY carriers (a node's `release_via`): the carrier
    becomes available only when it is unloaded at the destination.
    Resource states: load/unload = working:<this node>; loaded travel and empty return = transporting:<this node>;
    reaching the origin = walking.
    """

    def __init__(self, ctx: SimContext, cn: CompiledNode, carrier_mode: bool):
        super().__init__(ctx, cn)
        self.p: TransportParams = cn.params  # type: ignore[assignment]
        self.carrier_mode = carrier_mode
        preds = [e.source for e in ctx.model.edges if e.target == self.id]
        self.origin = self.p.origin or (preds[0] if preds else None)
        self.destination = self.p.destination or (cn.successors[0][0] if cn.successors else None)
        self.area = simpy.Resource(ctx.env, self.p.loading_area) if (self.p.loading_area and not carrier_mode) else None
        # queue items: ("unit", entity, picked_event, area_req) | ("carrier", resource_id, units)
        self.queue: list[tuple] = []
        self._wake: list[simpy.Event] = []
        self.aboard: list[tuple] = []  # physically on board (after loading)
        self.in_trip: list[tuple] = []  # assigned to a trip (from pickup request until delivery)
        self.trackers = [StateTracker(ctx, NodeState.STARVED) for _ in range(self.p.fleet)]
        self.logical = [NodeState.STARVED] * self.p.fleet
        self.vehicle_load: list[list[tuple]] = [[] for _ in range(self.p.fleet)]
        self.level = LevelTracker(ctx, f"transport:{self.id}")
        self.rng_load = ctx.rng(self.id, "load")
        self.rng_unload = ctx.rng(self.id, "unload")
        ctx.record.node_trips[self.id] = 0
        ctx.record.node_units_moved[self.id] = 0
        ctx.record.node_processed[self.id] = 0
        for v in range(self.p.fleet):
            ctx.env.process(self._vehicle(v))

    # ---- probes ----
    def occupancy(self) -> int:
        """Units physically in this node: aboard + waiting in the loading area (not those still upstream)."""
        waiting = sum(1 for q in self.queue if q[0] == "unit" and q[3] is not None)
        return waiting + sum(1 for q in self.aboard if q[0] == "unit")

    def carriers_in_transit(self, rid: str) -> int:
        return sum(len(q[2]) for q in [*self.queue, *self.in_trip] if q[0] == "carrier" and q[1] == rid)

    def carrier_returns(self, rid: str) -> list[tuple[str, list[Unit]]]:
        """Empty carriers owned by this transport (queued or travelling back), for the carrier invariant."""
        return [(self.id, q[2]) for q in [*self.queue, *self.in_trip] if q[0] == "carrier" and q[1] == rid]

    def state_counts(self) -> dict[str, int]:
        return dict(Counter(self.logical))

    def held_entities(self) -> set[int]:
        waiting = {q[1].id for q in self.queue if q[0] == "unit" and q[3] is not None}
        return waiting | {q[1].id for q in self.aboard if q[0] == "unit"}

    def in_process_entities(self) -> set[int]:
        return {q[1].id for v, load in enumerate(self.vehicle_load) if self.logical[v] in (NodeState.BUSY, NodeState.BLOCKED)
                for q in load if q[0] == "unit"}

    def _set(self, v: int, state: str) -> None:
        self.logical[v] = state
        self.trackers[v].set(state)
        self.ctx.changed(self.id)

    # ---- inputs ----
    def enter(self, entity: Entity, on_accept=None) -> Proc:
        area_req = None
        if self.area is not None:
            area_req = self.area.request()
            yield area_req
        if on_accept:
            on_accept(entity)
        picked = self.ctx.env.event()
        if area_req is not None:
            entity.node_entered = self.ctx.now
            self.ctx.place(entity, self.id)
        self._push(("unit", entity, picked, area_req))
        self.ctx.log("transport_requested", entity, self.id, origin=self.origin)
        if area_req is None:
            yield picked  # the unit keeps its upstream place until it is loaded

    def carry_back(self, resource: str, units: list[Unit]) -> None:
        self._push(("carrier", resource, units))

    def _push(self, item: tuple) -> None:
        self.queue.append(item)
        self.level.change(+1)
        self.ctx.changed(self.id)
        wake, self._wake = self._wake, []
        for w in wake:
            if not w.triggered:
                w.succeed()

    def _wait_items(self, n: int) -> Proc:
        while len(self.queue) < n:
            evt = self.ctx.env.event()
            self._wake.append(evt)
            yield evt

    # ---- trips ----
    def _vehicle(self, v: int) -> Proc:
        ctx, p = self.ctx, self.p
        trip = p.travel_seconds()
        tid = self.id
        while True:
            yield from self._wait_items(p.capacity if p.batch == "full" else 1)
            load = [self.queue.pop(0) for _ in range(min(p.capacity, len(self.queue)))]
            self.in_trip.extend(load)
            self.vehicle_load[v] = load
            for q in load:
                if q[0] == "unit":
                    # from now on the unit (and its carriers) belongs to this transport: RESERVED_FOR_TRANSPORT.
                    # It may still occupy its upstream place (pickup semantics) - that is station capacity, not its state.
                    ctx.place(q[1], f"reserved:{tid}")
            targets: dict[int, tuple] = {}
            for q in load:
                if q[0] == "unit":
                    target = self.next_node(q[1])
                    token = None
                    if p.reserve_destination:
                        self._set(v, NodeState.BLOCKED)  # waiting for room at the destination (resource not held)
                        token = yield from target.reserve()
                    targets[id(q)] = (target, token)
            held: list[Unit] = []
            for use in p.resources:
                self._set(v, NodeState.WAITING_RESOURCE)
                rep = next((q[1] for q in load if q[0] == "unit"), None)  # unit being moved (tie-break: older unit first)
                held.extend((yield from acquire_units(ctx, ctx.pools[use.resource], tid, use.quantity,
                                                      self.cn.node.priority, rep, walk_to=self.origin)))
            self._set(v, NodeState.BUSY)
            ctx.log("trip_start", None, tid, items=len(load), origin=self.origin, destination=self.destination,
                    resources=[u.name for u in held])
            yield ctx.env.timeout(p.load_time.sample_seconds(self.rng_load))  # type: ignore[union-attr]
            for q in load:  # physically on board now
                self.aboard.append(q)
                if q[0] == "unit":
                    e = q[1]
                    self.record_wait(e)
                    e.node_entered = ctx.now
                    ctx.place(e, tid)
                    if q[3] is not None:
                        self.area.release(q[3])  # type: ignore[union-attr]
                    if not q[2].triggered:
                        q[2].succeed()  # upstream node frees its place
            ctx.log("loaded", None, tid, items=len(load))
            for u in held:
                u.set_state(f"transporting:{tid}")
            yield ctx.env.timeout(trip)
            for u in held:
                u.set_state(f"working:{tid}")
                u.location = self.destination
            yield ctx.env.timeout(p.unload_time.sample_seconds(self.rng_unload))  # type: ignore[union-attr]
            for q in list(load):
                if q[0] == "unit":
                    self._set(v, NodeState.BLOCKED)
                    target, token = targets[id(q)]
                    yield from target.enter(q[1], reservation=token)
                else:
                    ctx.carrier_move(q[1], q[2], f"return:{tid}", AVAILABLE)
                    self.aboard.remove(q)
                    self.in_trip.remove(q)
                    ctx.pools[q[1]].release(q[2])
                    ctx.check_carriers(q[1])
                    ctx.log("carrier_released", None, tid, resource=q[1])
                if q in self.aboard:
                    self.aboard.remove(q)
                if q in self.in_trip:
                    self.in_trip.remove(q)
                self.level.change(-1)
                if ctx.counting:
                    ctx.record.node_units_moved[tid] += 1
                    ctx.record.node_processed[tid] += 1
            if ctx.counting:
                ctx.record.node_trips[tid] += 1  # delivered trips (avg load = units / trips is exact)
            ctx.changed(tid)
            if p.return_empty and trip > 0:
                self._set(v, NodeState.BUSY)
                for u in held:
                    u.set_state(f"transporting:{tid}")
                yield ctx.env.timeout(trip)
                for u in held:
                    u.location = self.origin
            release_units(ctx, held)
            ctx.log("trip_end", None, tid)
            self.vehicle_load[v] = []
            self._set(v, NodeState.STARVED)

    def finalize(self) -> None:
        tot: dict[str, float] = {}
        for t in self.trackers:
            for k, v in t.finalize().items():
                tot[k] = tot.get(k, 0.0) + v
        self.ctx.record.node_state_time[self.id] = tot
        self.ctx.record.node_slots[self.id] = self.p.fleet
        self.level.finalize()
