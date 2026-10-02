"""Runtime infrastructure for the DES kernel: context, RNG streams, statistics
trackers, entities and shared resource pools (operators, tools, carriers).

SimPy is an implementation detail confined to `simforge.engine.des`.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import simpy

from ...domain.isms import Resource
from ..base import ResourceState, RunRecord, TimeSeries

LOW_PRIORITY = 2  # SimPy: 0 urgent, 1 normal. 2 = "end of current time step"
MAX_SERIES_POINTS = 50_000
AVAILABLE = "available"  # location of carriers idle in their pool
SETUP_TASK = "#setup"  # resource task id of a node's setup: '<node>#setup' (engine >= 0.7.0)
MAX_DECISIONS_PER_INSTANT = 100_000  # guard: a same-instant resolution that never reaches a fixed point is an error


class SameInstantLoopError(RuntimeError):
    """Resource decisions at one instant did not converge (zero-duration cycle in the model)."""


class InvariantViolation(RuntimeError):
    """A physical conservation law was broken (racks appearing/disappearing, negative WIP...).
    Always an ERROR: results of a run that violates an invariant are never reported."""


class TravelDataError(RuntimeError):
    pass


def fmt_hms(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


class SimContext:
    """Shared state of one replication."""

    def __init__(self, env: simpy.Environment, seed: int, warmup: float, horizon: float, record: RunRecord, trace: bool,
                 dispatch_timing: str = "end_of_timestep", check_invariants: bool = True):
        self.env = env
        self.dispatch_timing = dispatch_timing
        self.check_invariants = check_invariants
        self.live: dict[int, "Entity"] = {}  # entities currently in the system
        self.totals = {"created": 0, "completed": 0, "scrapped": 0}  # whole run, incl. warm-up (conservation)
        self.carrier_locs: dict[str, dict[str, "LevelTracker"]] = {}
        self.invariant_checks = 0
        self.seed = seed
        self.warmup = warmup
        self.horizon = horizon
        self.record = record
        self.trace = trace
        self._next_entity = 0
        self.nodes: dict[str, Any] = {}
        self.pools: dict[str, "ResourcePool"] = {}
        self.watchers: dict[str, list["ResourcePool"]] = {}  # node id -> pools whose strategy watches it
        self.wip = LevelTracker(self, "wip")
        self.node_rank: dict[str, int] = {}  # node id -> declaration index in the ISMS (technical tie-break)
        # same-instant resolution (dispatch_timing = end_of_timestep)
        self._dirty: set["ResourcePool"] = set()
        self._resolver_scheduled = False
        self._instant = -1.0
        self._instant_decisions = 0
        self.calendar = None  # CalendarClock when the model has an `availability` block (engine >= 0.6.0)
        self.production = None  # ProductionRuntime when the model has a `production` block (engine >= 0.7.0)
        self.maintenance = None  # MaintenanceRuntime when the model has a `maintenance` block (engine >= 0.8.0)
        self.product_totals: dict[str, dict[str, int]] = {}  # product -> created/completed/scrapped (whole run)
        self.product_wip: dict[str, "LevelTracker"] = {}

    def node_can_work(self, node_id: str) -> bool:
        """Calendars: a request from a node whose own/gating calendars are unavailable is not granted (it keeps its
        place in the queue and is re-evaluated when the node becomes available). Always True without calendars."""
        if self.calendar is None:
            return True
        if "#" in node_id:  # '<node>#setup' (>= 0.7.0), '<node>#pm', '<node>#repair' (>= 0.8.0): the node decides
            base, task = node_id.split("#", 1)
            return self.nodes[base].task_can_work(task)
        gating = self.calendar.rt.gating.get(node_id)
        return not gating or self.calendar.ok(gating)

    # ---- products (engine >= 0.7.0); never called for models without a `production` block ----
    def product_in(self, e: "Entity") -> None:
        t = self.product_totals.setdefault(e.etype, {"created": 0, "completed": 0, "scrapped": 0})
        t["created"] += 1
        if e.etype not in self.product_wip:
            self.product_wip[e.etype] = LevelTracker(self, f"wip:{e.etype}", record_series=False)
        self.product_wip[e.etype].change(+1)
        self.record.created_by_product[e.etype] = self.record.created_by_product.get(e.etype, 0) + 1
        self.record.entity_product[e.id] = e.etype

    def product_out(self, e: "Entity", how: str) -> None:
        self.product_totals[e.etype][how] += 1
        self.product_wip[e.etype].change(-1)

    def rng(self, *key: str) -> random.Random:
        """Independent, reproducible stream per (seed, purpose). Same stream across scenarios
        -> common random numbers, i.e. fairer scenario comparisons."""
        h = hashlib.sha256(("|".join([str(self.seed), *key])).encode()).digest()
        return random.Random(int.from_bytes(h[:8], "big"))

    def changed(self, node_id: str) -> None:
        """A node's occupancy/state changed: strategies watching it re-evaluate (end of time step)."""
        for pool in self.watchers.get(node_id, ()):
            pool._schedule_dispatch()

    # ---- entity / carrier bookkeeping (conservation invariants) ----
    def violation(self, msg: str) -> None:
        raise InvariantViolation(f"t={self.env.now:.3f}s: {msg}")

    def admit(self, e: "Entity", location: str) -> None:
        self.live[e.id] = e
        self.totals["created"] += 1
        e.location = location

    def retire(self, e: "Entity", how: str) -> None:
        if self.live.pop(e.id, None) is None:
            self.violation(f"entity {e.id} left the system twice")
        self.totals[how] += 1
        if e.carriers:
            self.violation(f"entity {e.id} left the system still holding {[r for r, _ in e.carriers]}")

    def place(self, e: "Entity", node_id: str) -> None:
        """Entity physically moves to node_id (or to a state such as 'reserved:<transport>'); its carriers move with it."""
        old = e.location
        e.location = node_id
        for rid, units in e.carriers:
            self.carrier_move(rid, units, old or AVAILABLE, node_id)
        if e.carriers:
            self.check_carriers()

    def carrier_level(self, rid: str, loc: str) -> "LevelTracker":
        locs = self.carrier_locs.setdefault(rid, {})
        if loc not in locs:
            locs[loc] = LevelTracker(self, f"carrier_at:{rid}:{loc}", record_series=False, owner=self)
        return locs[loc]

    def carrier_move(self, rid: str, units: list["Unit"], frm: str, to: str) -> None:
        """Move carrier units from one physical state to another. Each unit has exactly ONE state (Unit.cstate);
        moving a unit from a state it is not in is a conservation error (double membership / lost carrier)."""
        if frm == to or not units:
            return
        for u in units:
            if u.cstate != frm:
                self.violation(f"carrier '{u.name}' moved from '{frm}' but its state is '{u.cstate}'")
            u.cstate = to
        self.carrier_level(rid, frm).change(-len(units))
        self.carrier_level(rid, to).change(+len(units))  # callers run check_carriers() once the operation is complete

    def check_carriers(self, rid: str | None = None) -> None:
        """Strong carrier invariant, checked unit by unit (identity, not only counts):
        every carrier unit belongs to EXACTLY ONE owner - the pool (available), a pending grant (granted:<node>,
        only within the instant of the grant), an entity (its location: node, buffer, 'reserved:<transport>',
        on board '<transport>'), or an empty-return transport ('return:<transport>') - and its recorded state
        (Unit.cstate) matches that owner. Detects duplication, disappearance, double membership, carriers left
        granted beyond their instant and carriers without owner. Level trackers must agree with the states."""
        if not self.check_invariants:
            return
        self.invariant_checks += 1
        for r, pool in self.pools.items():
            if rid and r != rid or pool.spec.kind.value != "carrier":
                continue
            owners: dict[int, list[str]] = {u.index: [] for u in pool.units}
            expected: dict[int, str] = {}
            for u in pool.units:
                if not u.busy:
                    owners[u.index].append("pool")
                    expected[u.index] = AVAILABLE
                elif u.granted_at is not None:
                    owners[u.index].append("grant")
                    expected[u.index] = u.cstate if u.cstate.startswith("granted:") else "granted:?"
                    if u.granted_at < self.env.now:
                        self.violation(f"carrier '{u.name}' granted at t={u.granted_at:.3f}s never collected")
            for e in self.live.values():
                for x, units in e.carriers:
                    if x != r:
                        continue
                    for u in units:
                        owners[u.index].append(f"entity {e.id}")
                        expected[u.index] = e.location or "?"
            for n in self.nodes.values():
                for tid, units in (n.carrier_returns(r) if hasattr(n, "carrier_returns") else []):
                    for u in units:
                        owners[u.index].append(f"return {tid}")
                        expected[u.index] = f"return:{tid}"
            for u in pool.units:
                own = owners[u.index]
                if len(own) != 1:
                    self.violation(f"carrier '{u.name}' has {len(own)} owners {own} (must be exactly 1)")
                if u.cstate != expected[u.index]:
                    self.violation(f"carrier '{u.name}' state '{u.cstate}' != owner state '{expected[u.index]}' ({own[0]})")
            locs = self.carrier_locs.get(r, {})
            by_state: dict[str, int] = {}
            for u in pool.units:
                by_state[u.cstate] = by_state.get(u.cstate, 0) + 1
            levels = {k: t.level for k, t in locs.items() if t.level}
            if levels != by_state:
                self.violation(f"carrier level trackers {levels} != unit states {by_state} for '{r}'")
            if sum(by_state.values()) != pool.total:
                self.violation(f"rack conservation broken for '{r}': {sum(by_state.values())} != total {pool.total}")

    def check_end(self) -> None:
        if not self.check_invariants:
            return
        t = self.totals
        if t["created"] != t["completed"] + t["scrapped"] + len(self.live):
            self.violation(f"entity conservation: created {t['created']} != completed {t['completed']} + "
                           f"scrapped {t['scrapped']} + in system {len(self.live)}")
        if self.wip.level != len(self.live):
            self.violation(f"WIP counter {self.wip.level} != entities in system {len(self.live)}")
        if self.production is not None:  # conservation per product, and products add up to the totals
            for p, c in self.product_totals.items():
                live = sum(1 for e in self.live.values() if e.etype == p)
                if c["created"] != c["completed"] + c["scrapped"] + live:
                    self.violation(f"product conservation '{p}': created {c['created']} != completed {c['completed']} + "
                                   f"scrapped {c['scrapped']} + in system {live}")
                if self.product_wip[p].level != live:
                    self.violation(f"WIP counter of '{p}' {self.product_wip[p].level} != {live} in system")
            for k in ("created", "completed", "scrapped"):
                if sum(c[k] for c in self.product_totals.values()) != t[k]:
                    self.violation(f"sum over products of '{k}' != total {t[k]}")
        self.check_carriers()

    def snapshot(self) -> dict[str, Any]:
        """System state for the decision log (generic: works for any model)."""
        snap: dict[str, Any] = {"wip": self.wip.level, "buffers": {}, "stations": {}, "transports": {}, "carriers_available": {}}
        for nid, n in self.nodes.items():
            kind = getattr(n, "kind", "")
            if kind == "buffer":
                snap["buffers"][nid] = n.occupancy()
            elif kind == "server":
                snap["stations"][nid] = {k: v for k, v in n.state_counts().items() if v}
            elif kind == "transport":
                snap["transports"][nid] = n.occupancy()
        for rid, pool in self.pools.items():
            if pool.spec.kind.value == "carrier":
                snap["carriers_available"][rid] = sum(1 for u in pool.units if not u.busy)
        return snap

    def new_entity(self, etype: str) -> "Entity":
        self._next_entity += 1
        return Entity(self._next_entity, etype)

    @property
    def now(self) -> float:
        return self.env.now

    @property
    def counting(self) -> bool:
        """Statistics window is (warmup, horizon]."""
        return self.env.now > self.warmup or self.warmup == 0

    def log(self, event: str, entity: "Entity | None" = None, node: str | None = None, **extra: Any) -> None:
        if self.trace and self.record.events is not None:
            self.record.events.append({"t": round(self.env.now, 6), "entity": entity.id if entity else None,
                                       "event": event, "node": node, **extra})

    # ---- same-instant resolution ------------------------------------------------------------
    def request_resolution(self, pool: "ResourcePool") -> None:
        """A pool has something to decide at this instant (new request, released unit, watched state change)."""
        self._dirty.add(pool)
        if not self._resolver_scheduled:
            self._resolver_scheduled = True
            self.at_end_of_timestep(self._resolve)

    def _resolve(self) -> None:
        """Resolve the resource decisions of the current instant to a fixed point.

        Runs at the end of the instant, i.e. after every ordinary event at time t. Takes ONE decision (assignment
        or pre-emption) from the first pool in EVENT RESOLUTION ORDER that has one, then yields so that the
        consequences of that decision (ordinary events at the same t, e.g. an entity that received a rack now asks
        for its operator) are processed before the next decision; then fires again. Stops when no pool can decide.
        Resolution order is technical, not an industrial priority: carriers first (a carrier grant only ENABLES a
        task to request its operator/tool, so operator decisions must see every task enabled at this instant),
        then the other pools; ties by declaration order in the ISMS.
        """
        self._resolver_scheduled = False
        if self.env.now != self._instant:
            self._instant, self._instant_decisions = self.env.now, 0
        for pool in sorted(self._dirty, key=lambda p: p.resolution_key):
            self._dirty.discard(pool)
            if pool._decide_one():
                self._instant_decisions += 1
                if self._instant_decisions > MAX_DECISIONS_PER_INSTANT:
                    raise SameInstantLoopError(f"t={self.env.now:.3f}s: more than {MAX_DECISIONS_PER_INSTANT} resource "
                                               f"decisions at the same instant (zero-duration cycle?)")
                self.request_resolution(pool)  # it may have more requests / free units; re-ordered next round
                return

    def at_end_of_timestep(self, callback: Callable[[], None]) -> None:
        """Run callback after every other event scheduled at the current time.
        Used for dispatching decisions so that all simultaneous requests compete."""
        evt = self.env.event()
        evt.callbacks.append(lambda _e: callback())
        evt._ok = True  # noqa: SLF001 - SimPy has no public API for custom-priority scheduling
        evt._value = None  # noqa: SLF001
        self.env.schedule(evt, priority=LOW_PRIORITY)


@dataclass
class Entity:
    id: int
    etype: str
    created: float = 0.0
    carriers: list[tuple[str, list["Unit"]]] = field(default_factory=list)
    node_entered: float = 0.0
    location: str | None = None
    route: tuple[str, ...] | None = None  # product route (engine >= 0.7.0); None = legacy edge routing
    route_pos: int = 0  # index of the entity's current node in `route`


class StateTracker:
    """Accumulates time spent in each state, clipped to [warmup, horizon]."""

    def __init__(self, ctx: SimContext, initial: str):
        self.ctx = ctx
        self.state = initial
        self.since = ctx.now
        self.acc: dict[str, float] = {}

    def set(self, state: str) -> None:
        if state == self.state:
            return
        self._flush(self.ctx.now)
        self.state = state

    def _flush(self, t: float) -> None:
        a = max(self.since, self.ctx.warmup)
        b = min(t, self.ctx.horizon)
        if b > a:
            self.acc[self.state] = self.acc.get(self.state, 0.0) + (b - a)
        self.since = t

    def finalize(self) -> dict[str, float]:
        self._flush(self.ctx.horizon)
        return self.acc


class LevelTracker:
    """Time-weighted average of an integer level (WIP, buffer content...)."""

    def __init__(self, ctx: SimContext, name: str, record_series: bool = True, owner=None, upper: int | None = None):
        self.ctx = ctx
        self.name = name
        self.upper = upper
        self.level = 0
        self.since = ctx.now
        self.integral = 0.0
        self.max = 0
        self.series = TimeSeries() if record_series else None
        if self.series is not None:
            self.series.t.append(0.0)
            self.series.v.append(0)

    def change(self, delta: int) -> None:
        now = self.ctx.now
        a, b = max(self.since, self.ctx.warmup), min(now, self.ctx.horizon)
        if b > a:
            self.integral += self.level * (b - a)
        if now >= self.ctx.warmup:
            self.max = max(self.max, self.level)  # level held when crossing the warm-up
        self.since = now
        self.level += delta
        if self.ctx.check_invariants and (self.level < 0 or (self.upper is not None and self.level > self.upper)):
            self.ctx.violation(f"level '{self.name}' = {self.level} outside [0, {self.upper if self.upper is not None else 'inf'}]")
        if now >= self.ctx.warmup:
            self.max = max(self.max, self.level)
        if self.series is not None and len(self.series.t) < MAX_SERIES_POINTS and now <= self.ctx.horizon:
            self.series.t.append(now)
            self.series.v.append(self.level)

    def finalize(self) -> None:
        self.change(0)
        span = self.ctx.horizon - self.ctx.warmup
        self.ctx.record.level_avg[self.name] = self.integral / span if span > 0 else 0.0
        self.ctx.record.level_max[self.name] = self.max
        if self.series is not None:
            self.ctx.record.series[self.name] = self.series


# ---------------------------------------------------------------------------
# Shared resource pools
# ---------------------------------------------------------------------------


@dataclass
class Unit:
    pool: "ResourcePool"
    index: int
    tracker: StateTracker
    location: str | None = None
    busy: bool = False
    last_task: str | None = None  # task finished most recently (decision log: 'current task' of the operator)
    task: str | None = None  # node currently served
    preemptible: bool = False  # True only while processing a task that may be suspended
    preempt: object = None  # callable set by the holder: suspends the task and frees this unit
    cstate: str = AVAILABLE  # carriers only: the ONE physical state of this unit (see SimContext.check_carriers)
    granted_at: float | None = None  # carriers only: time it was granted and not yet collected
    base: str = ResourceState.IDLE  # what the unit is doing (idle / walking / working:<node> / transporting:<node>)
    cal: str = "available"  # calendar label of its resource: available / break / off_shift (always 'available' if none)

    def set_state(self, base: str) -> None:
        self.base = base
        self.tracker.set(self.effective())

    def effective(self) -> str:
        """Tracked state. Without a calendar it is exactly `base` (legacy). Outside planned time: the calendar
        label if idle, 'outside_planned:<base>' if still doing something (FINISH_CURRENT overrun, walking)."""
        if self.cal == "available":
            return self.base
        return self.cal if self.base == ResourceState.IDLE else f"outside_planned:{self.base}"

    @property
    def name(self) -> str:
        return f"{self.pool.id}#{self.index + 1}"


@dataclass
class _Request:
    seq: int
    node: str
    qty: int
    priority: int
    t: float
    event: simpy.Event
    entity: int | None
    resume: bool = False  # re-request of a task suspended by pre-emption
    location: str | None = None  # where the unit is needed (defaults to the requesting node)
    node_rank: int = 0  # declaration index of the requesting node (technical tie-break, see dispatch.tie_key)


class ResourcePool:
    """Operators, tools or carriers. Units are individually tracked (state, location).

    Allocation happens at the end of the time step (see SimContext.at_end_of_timestep)
    with the configured dispatch rule; every contested decision is logged in trace mode.
    """

    def __init__(self, ctx: SimContext, spec: Resource, positions: dict[str, tuple[float, float]], index: int = 0):
        self.ctx = ctx
        self.spec = spec
        self.id = spec.id
        # EVENT RESOLUTION ORDER within an instant (technical, see SimContext._resolve): carriers, then the rest;
        # then declaration order in the ISMS
        self.resolution_key = (0 if spec.kind.value == "carrier" else 1, index)
        self.units = [Unit(self, i, StateTracker(ctx, ResourceState.IDLE), spec.home) for i in range(spec.quantity)]
        self.waiting: list[_Request] = []
        self._seq = 0
        self.positions = positions
        self.speed = spec.travel.speed.to_base() if spec.travel else None
        self.metric = spec.travel.metric if spec.travel else "euclidean"
        self.matrix: dict[frozenset, float] = {}
        self.locations = dict(spec.travel.locations) if spec.travel else {}
        self.pending = 0  # carrier units granted to a node but not yet collected by the entity
        if spec.travel:
            for d in spec.travel.distances:
                self.matrix[frozenset((d.a, d.b))] = d.distance.to_base()
        self.total = spec.quantity
        self.in_use = LevelTracker(ctx, f"in_use:{spec.id}", record_series=spec.kind.value == "carrier", upper=spec.quantity)
        self._dispatching = False
        if spec.kind.value == "carrier":
            ctx.carrier_level(spec.id, AVAILABLE).change(spec.quantity)
        self.tasks: dict[str, int] = {}
        self.preemptions = 0
        from .dispatch import make_strategy

        self.strategy = make_strategy(spec)
        for nid in self.strategy.watched_nodes():
            ctx.watchers.setdefault(nid, []).append(self)

    # ---- API used by nodes ----
    def request(self, node: str, qty: int, priority: int, entity: int | None, resume: bool = False,
                location: str | None = None) -> simpy.Event:
        self._seq += 1
        evt = self.ctx.env.event()
        base = node.split("#", 1)[0]  # a setup / pm / repair task ranks as its node
        self.waiting.append(_Request(self._seq, node, qty, priority, self.ctx.now, evt, entity, resume, location or node,
                                     self.ctx.node_rank.get(base, len(self.ctx.node_rank))))
        self._schedule_dispatch()
        return evt

    def release(self, units: list[Unit]) -> None:
        for u in units:
            if not u.busy:
                self.ctx.violation(f"'{u.name}' released but it was not in use")
            u.busy = False
            u.last_task = u.task
            u.task = None
            u.preemptible = False
            u.preempt = None
            u.set_state(ResourceState.IDLE)
        self.in_use.change(-len(units))
        self._schedule_dispatch()

    def point(self, node: str) -> str:
        return self.locations.get(node, node)

    def distance(self, a: str, b: str) -> float:
        """Path distance a->b: explicit distance table first (e.g. AnyLogic network path lengths),
        then node positions. Never silently 0: missing data is an error."""
        if a == b or self.point(a) == self.point(b):
            return 0.0
        d = self.matrix.get(frozenset((self.point(a), self.point(b))))
        if d is not None:
            return d
        pa, pb = self.positions.get(a), self.positions.get(b)
        if pa is None or pb is None:
            raise TravelDataError(f"'{self.id}' needs the distance between '{a}' and '{b}' (no distance entry, no positions)")
        dx, dy = pa[0] - pb[0], pa[1] - pb[1]
        return abs(dx) + abs(dy) if self.metric == "manhattan" else math.hypot(dx, dy)

    def travel_time(self, unit: Unit, node: str) -> float:
        if self.speed is None or unit.location is None or unit.location == node:
            return 0.0
        return self.distance(unit.location, node) / self.speed

    def set_calendar_label(self, label: str) -> None:
        """Calendar transition of this resource (all its units share the calendar). Busy units keep their task: what
        happens to the operation is decided by the node's policy (FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART)."""
        for u in self.units:
            u.cal = label
            u.tracker.set(u.effective())
        if label == "available":
            self._schedule_dispatch()

    # ---- dispatching ----
    def _schedule_dispatch(self) -> None:
        if self.ctx.dispatch_timing == "immediate":
            # sensitivity mode: decide right now, in event order (first come, first decided)
            if not self._dispatching:
                self._dispatching = True
                try:
                    self._dispatch()
                finally:
                    self._dispatching = False
            return
        self.ctx.request_resolution(self)  # end_of_timestep: same-instant fixed-point resolution

    def _dispatch(self) -> None:
        """Take every decision possible now (immediate mode)."""
        while self._decide_one():
            pass

    def _decide_one(self) -> bool:
        """Take at most ONE decision (assignment or pre-emption). True if one was taken."""
        if not self.waiting:
            return False
        free = [u for u in self.units if not u.busy and u.cal == "available"]  # off-shift units take no new task
        feasible = [r for r in self.waiting if r.qty <= len(free) and self.ctx.node_can_work(r.node)]
        if not feasible:
            if self.units and self.units[0].cal != "available":
                return False  # off-shift: nothing to grant, and pre-empting would hand work to an unavailable unit
            cand = self.strategy.preempt_candidate(self)
            if cand is None:
                return False
            unit, reason, state = cand
            unit.preemptible = False
            self.preemptions += int(self.ctx.counting)
            self._log("preempt", unit.task, None, [unit], self.waiting, reason, state)
            unit.preempt()  # type: ignore[operator]  # holder suspends its task and releases the unit
            return True
        chosen, reason, state = self.strategy.choose(self, feasible)
        # nearest free units first (walking time), then lowest index
        free.sort(key=lambda u: (self.travel_time(u, chosen.location or chosen.node), u.index))
        units = free[: chosen.qty]
        for u in units:
            u.busy = True
            u.task = chosen.node
        self.in_use.change(len(units))
        if self.spec.kind.value == "carrier":
            self.pending += len(units)
            for u in units:
                u.granted_at = self.ctx.now
            self.ctx.carrier_move(self.id, units, AVAILABLE, f"granted:{chosen.node}")
        self.waiting.remove(chosen)
        self.tasks[chosen.node] = self.tasks.get(chosen.node, 0) + 1
        self._log("assign", chosen.node, chosen, units, [chosen, *self.waiting], reason, state)
        chosen.event.succeed(units)
        return True

    def _log(self, kind: str, node: str | None, chosen: "_Request | None", units: list["Unit"],
             candidates: list["_Request"], reason: str, state: dict) -> None:
        if not (self.ctx.trace and self.ctx.record.decisions is not None):
            return
        m = re.match(r"([A-Z_]+): (.*)", reason)
        code, text = (m.group(1), m.group(2)) if m else ("", reason)
        self.ctx.record.decisions.append({
            "t": round(self.ctx.now, 6),
            "time": fmt_hms(self.ctx.now),
            "resource": self.id,
            "kind": kind,
            "units": [u.name for u in units],
            "current_task": {u.name: (u.task if kind == "preempt" else u.last_task) for u in units},
            "chosen_node": node,
            "chosen_entity": chosen.entity if chosen else None,
            "contested": len({r.node for r in candidates}) > 1,
            "candidates": [{"node": r.node, "entity": r.entity, "priority": r.priority, "resume": r.resume,
                            "waiting_s": round(self.ctx.now - r.t, 3)} for r in candidates],
            "rule": self.strategy.rule,
            "reason_code": code or self.strategy.rule.upper(),
            "reason": text or reason,
            "state": state,
            "system": self.ctx.snapshot(),
        })

    def finalize(self) -> None:
        rec = self.ctx.record
        tot: dict[str, float] = {}
        for u in self.units:
            for k, v in u.tracker.finalize().items():
                tot[k] = tot.get(k, 0.0) + v
        rec.resource_units[self.id] = len(self.units)
        rec.resource_state_time[self.id] = tot
        rec.resource_tasks[self.id] = dict(self.tasks)
        rec.resource_preemptions[self.id] = self.preemptions
        self.in_use.finalize()


class _ZeroLevel:
    level = 0


_Zero = _ZeroLevel()
