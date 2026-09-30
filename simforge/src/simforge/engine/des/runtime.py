"""Runtime infrastructure for the DES kernel: context, RNG streams, statistics
trackers, entities and shared resource pools (operators, tools, carriers).

SimPy is an implementation detail confined to `simforge.engine.des`.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

import simpy

from ...domain.isms import DispatchRule, Resource
from ..base import ResourceState, RunRecord, TimeSeries

LOW_PRIORITY = 2  # SimPy: 0 urgent, 1 normal. 2 = "end of current time step"
MAX_SERIES_POINTS = 50_000


class SimContext:
    """Shared state of one replication."""

    def __init__(self, env: simpy.Environment, seed: int, warmup: float, horizon: float, record: RunRecord, trace: bool):
        self.env = env
        self.seed = seed
        self.warmup = warmup
        self.horizon = horizon
        self.record = record
        self.trace = trace
        self._next_entity = 0
        self.nodes: dict[str, Any] = {}
        self.pools: dict[str, "ResourcePool"] = {}
        self.wip = LevelTracker(self, "wip")

    def rng(self, *key: str) -> random.Random:
        """Independent, reproducible stream per (seed, purpose). Same stream across scenarios
        -> common random numbers, i.e. fairer scenario comparisons."""
        h = hashlib.sha256(("|".join([str(self.seed), *key])).encode()).digest()
        return random.Random(int.from_bytes(h[:8], "big"))

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

    def __init__(self, ctx: SimContext, name: str, record_series: bool = True):
        self.ctx = ctx
        self.name = name
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
        self.in_use = LevelTracker(ctx, f"in_use:{spec.id}", record_series=spec.kind.value == "carrier")
        self.tasks: dict[str, int] = {}

    # ---- API used by nodes ----
    def request(self, node: str, qty: int, priority: int, entity: int | None) -> simpy.Event:
        self._seq += 1
        evt = self.ctx.env.event()
        self.waiting.append(_Request(self._seq, node, qty, priority, self.ctx.now, evt, entity))
        self._schedule_dispatch()
        return evt

    def release(self, units: list[Unit]) -> None:
        for u in units:
            u.busy = False
            u.tracker.set(ResourceState.IDLE)
        self.in_use.change(-len(units))
        self._schedule_dispatch()

    def travel_time(self, unit: Unit, node: str) -> float:
        if self.speed is None or unit.location is None or unit.location == node:
            return 0.0
        a, b = self.positions.get(unit.location), self.positions.get(node)
        if a is None or b is None:
            return 0.0
        dx, dy = a[0] - b[0], a[1] - b[1]
        dist = abs(dx) + abs(dy) if self.metric == "manhattan" else math.hypot(dx, dy)
        return dist / self.speed

    # ---- dispatching ----
    def _schedule_dispatch(self) -> None:
        if not self._dispatch_pending:
            self._dispatch_pending = True
            self.ctx.at_end_of_timestep(self._dispatch)

    def _dispatch(self) -> None:
        self._dispatch_pending = False
        while self.waiting:
            free = [u for u in self.units if not u.busy]
            feasible = [r for r in self.waiting if r.qty <= len(free)]
            if not feasible:
                return
            if self.spec.dispatch is DispatchRule.PRIORITY:
                chosen = min(feasible, key=lambda r: (r.priority, r.seq))
                reason = f"priority rule: node '{chosen.node}' has priority {chosen.priority} (lower = more urgent)"
            else:
                chosen = min(feasible, key=lambda r: r.seq)
                reason = f"FIFO: oldest request (waiting since t={chosen.t:.1f}s)"
            # nearest free units first (walking time), then lowest index
            free.sort(key=lambda u: (self.travel_time(u, chosen.node), u.index))
            units = free[: chosen.qty]
            for u in units:
                u.busy = True
            self.in_use.change(len(units))
            self.waiting.remove(chosen)
            self.tasks[chosen.node] = self.tasks.get(chosen.node, 0) + 1
            if self.ctx.trace and self.ctx.record.decisions is not None and (len(self.waiting) > 0 or len(feasible) > 1):
                self.ctx.record.decisions.append({
                    "t": round(self.ctx.now, 6),
                    "resource": self.id,
                    "units": [u.name for u in units],
                    "chosen_node": chosen.node,
                    "chosen_entity": chosen.entity,
                    "candidates": [{"node": r.node, "entity": r.entity, "priority": r.priority,
                                    "waiting_s": round(self.ctx.now - r.t, 3)} for r in [chosen, *self.waiting]],
                    "rule": self.spec.dispatch.value,
                    "reason": reason,
                })
            chosen.event.succeed(units)

    def finalize(self) -> None:
        rec = self.ctx.record
        tot: dict[str, float] = {}
        for u in self.units:
            for k, v in u.tracker.finalize().items():
                tot[k] = tot.get(k, 0.0) + v
        rec.resource_units[self.id] = len(self.units)
        rec.resource_state_time[self.id] = tot
        rec.resource_tasks[self.id] = dict(self.tasks)
        self.in_use.finalize()
