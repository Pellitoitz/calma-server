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
        """Entity physically moves to node_id; the carriers it holds move with it."""
        old = e.location
        e.location = node_id
        for rid, units in e.carriers:
            self.carrier_move(rid, len(units), old or AVAILABLE, node_id)
        if e.carriers:
            self.check_carriers()

    def carrier_level(self, rid: str, loc: str) -> "LevelTracker":
        locs = self.carrier_locs.setdefault(rid, {})
        if loc not in locs:
            locs[loc] = LevelTracker(self, f"carrier_at:{rid}:{loc}", record_series=False, owner=self)
        return locs[loc]

    def carrier_move(self, rid: str, n: int, frm: str, to: str) -> None:
        if frm == to or n == 0:
            return
        self.carrier_level(rid, frm).change(-n)
        self.carrier_level(rid, to).change(+n)  # callers run check_carriers() once the operation is complete

    def check_carriers(self, rid: str | None = None) -> None:
        """AVAILABLE + held by entities (by location) + in return transports == TOTAL, never negative,
        cross-checked against an independent count of the pool's units."""
        if not self.check_invariants:
            return
        self.invariant_checks += 1
        for r, pool in self.pools.items():
            if rid and r != rid or pool.spec.kind.value != "carrier":
                continue
            locs = self.carrier_locs.get(r, {})
            total = pool.total
            s = sum(t.level for t in locs.values())
            if s != total:
                self.violation(f"rack conservation broken for '{r}': sum over locations {s} != total {total} "
                               f"({ {k: v.level for k, v in locs.items() if v.level} })")
            held = sum(len(u) for e in self.live.values() for x, u in e.carriers if x == r)
            in_transport = sum(n.carriers_in_transit(r) for n in self.nodes.values() if hasattr(n, "carriers_in_transit"))
            idle = sum(1 for u in pool.units if not u.busy)
            if held + in_transport + idle + pool.pending != total:
                self.violation(f"rack conservation broken for '{r}': held {held} + in transport {in_transport} "
                               f"+ available {idle} + granted {pool.pending} != total {total}")
            if idle != locs.get(AVAILABLE, _Zero).level:
                self.violation(f"'{r}': {idle} idle units but location 'available' says {locs.get(AVAILABLE, _Zero).level}")

    def check_end(self) -> None:
        if not self.check_invariants:
            return
        t = self.totals
        if t["created"] != t["completed"] + t["scrapped"] + len(self.live):
            self.violation(f"entity conservation: created {t['created']} != completed {t['completed']} + "
                           f"scrapped {t['scrapped']} + in system {len(self.live)}")
        if self.wip.level != len(self.live):
            self.violation(f"WIP counter {self.wip.level} != entities in system {len(self.live)}")
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


class ResourcePool:
    """Operators, tools or carriers. Units are individually tracked (state, location).

    Allocation happens at the end of the time step (see SimContext.at_end_of_timestep)
    with the configured dispatch rule; every contested decision is logged in trace mode.
    """

    def __init__(self, ctx: SimContext, spec: Resource, positions: dict[str, tuple[float, float]]):
        self.ctx = ctx
        self.spec = spec
        self.id = spec.id
        self.units = [Unit(self, i, StateTracker(ctx, ResourceState.IDLE), spec.home) for i in range(spec.quantity)]
        self.waiting: list[_Request] = []
        self._seq = 0
        self._dispatch_pending = False
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
        self.waiting.append(_Request(self._seq, node, qty, priority, self.ctx.now, evt, entity, resume, location or node))
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
            u.tracker.set(ResourceState.IDLE)
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

    # ---- dispatching ----
    def _schedule_dispatch(self) -> None:
        if self.ctx.dispatch_timing == "immediate":
            # decide right now, in event order (sensitivity check vs. end-of-time-step decisions)
            if not self._dispatching:
                self._dispatching = True
                try:
                    self._dispatch()
                finally:
                    self._dispatching = False
            return
        if not self._dispatch_pending:
            self._dispatch_pending = True
            self.ctx.at_end_of_timestep(self._dispatch)

    def _dispatch(self) -> None:
        self._dispatch_pending = False
        while self.waiting:
            free = [u for u in self.units if not u.busy]
            feasible = [r for r in self.waiting if r.qty <= len(free)]
            if not feasible:
                cand = self.strategy.preempt_candidate(self)
                if cand is not None:
                    unit, reason, state = cand
                    unit.preemptible = False
                    self.preemptions += int(self.ctx.counting)
                    self._log("preempt", unit.task, None, [unit], self.waiting, reason, state)
                    unit.preempt()  # type: ignore[operator]  # holder suspends its task and releases the unit
                return
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
                self.ctx.carrier_move(self.id, len(units), AVAILABLE, f"granted:{chosen.node}")
            self.waiting.remove(chosen)
            self.tasks[chosen.node] = self.tasks.get(chosen.node, 0) + 1
            self._log("assign", chosen.node, chosen, units, [chosen, *self.waiting], reason, state)
            chosen.event.succeed(units)

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
