"""Calendar clock of one replication (engine >= 0.6.0).

Precedence inside one simulation instant t (documented in docs/calendars_and_shifts.md):
  1. CALENDAR TRANSITIONS at t (URGENT priority, before any other event at t, independent of creation order):
     every calendar takes its label for [t, ...); resource pools switch units on/off; nodes whose gating calendars
     became unavailable interrupt operations whose policy is PAUSE_RESUME / STOP_RESTART. Within the instant the
     transitions are applied in a fixed order: resources in ISMS declaration order, then nodes in declaration order.
  2. Ordinary events at t (completions, arrivals, ...) in their usual order. An operation whose remaining work is 0
     at t is COMPLETE (never paused nor restarted), whatever the order of its completion and the transition.
  3. Resource decisions at the end of the instant (same-instant resolver, engine 0.3.0): they see the calendar
     state of [t, ...), so a resource that goes off at t gets no new task at t and one that comes on at t competes
     for tasks at t through the normal dispatch rule (no priority for 'returning from a break').
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import simpy

from ...domain.calendar import AVAILABLE, BREAK, OFF_SHIFT
from ..calendar_compile import AvailabilityRuntime

if TYPE_CHECKING:  # pragma: no cover
    from .runtime import SimContext

URGENT = 0  # simpy.events.URGENT


class CalendarClock:
    def __init__(self, ctx: "SimContext", rt: AvailabilityRuntime):
        self.ctx = ctx
        self.rt = rt
        self.labels = {cid: tl.label_at(0.0) for cid, tl in rt.timelines.items()}
        self.change_event: simpy.Event = ctx.env.event()
        self.points = sorted({p for tl in rt.timelines.values() for p in tl.change_points() if p <= ctx.horizon})
        self._i = 0
        self._schedule_next()
        # the run must reach the horizon even if nothing else can happen (resources off until the end)
        self._at(ctx.horizon, lambda: None)

    # ---- queries ----
    def label(self, cal: str) -> str:
        return self.labels[cal]

    def ok(self, cals: list[str]) -> bool:
        return all(self.labels[c] == AVAILABLE for c in cals)

    def off_label(self, cals: list[str]) -> str:
        labs = [self.labels[c] for c in cals]
        return BREAK if BREAK in labs else OFF_SHIFT

    def window_end(self, cals: list[str], t: float) -> float:
        """Time at which the current common availability of `cals` ends (t if not available now)."""
        if not self.ok(cals):
            return t
        return min(self.rt.timelines[c].next_unavailable(t) for c in cals)

    def wait_until_ok(self, cals: list[str]):
        """Generator: wait (in simulation time) until every calendar in `cals` is available."""
        while not self.ok(cals):
            yield self.change_event

    def consume_available(self, cals: list[str], seconds: float):
        """Generator: let `seconds` of AVAILABLE time pass (the clock pauses while unavailable)."""
        left = seconds
        while left > 1e-9:
            if not self.ok(cals):
                yield self.change_event
                continue
            now = self.ctx.now
            end = self.window_end(cals, now)
            step = min(left, end - now)
            yield self.ctx.env.timeout(step)
            left -= step

    # ---- transitions ----
    def _at(self, t: float, callback) -> None:
        evt = self.ctx.env.event()
        evt.callbacks.append(lambda _e: callback())
        evt._ok = True  # noqa: SLF001 - SimPy has no public API for custom-priority scheduling
        evt._value = None  # noqa: SLF001
        self.ctx.env.schedule(evt, priority=URGENT, delay=max(0.0, t - self.ctx.now))

    def _schedule_next(self) -> None:
        if self._i < len(self.points):
            t = self.points[self._i]
            self._i += 1
            self._at(t, self._transition)

    def _transition(self) -> None:
        ctx, t = self.ctx, self.ctx.now
        old = dict(self.labels)
        for cid, tl in self.rt.timelines.items():
            self.labels[cid] = tl.label_at(t)
        changed = {cid for cid in self.labels if self.labels[cid] != old[cid]}
        if changed:
            ctx.log("calendar", None, None, changed={c: f"{old[c]}->{self.labels[c]}" for c in sorted(changed)})
            for pool in ctx.pools.values():  # declaration order
                cid = self.rt.resource_calendar.get(pool.id)
                if cid in changed:
                    pool.set_calendar_label(self.labels[cid])
            setup_gating = ctx.production.setup_gating if ctx.production is not None else {}
            for nid in ctx.node_rank:  # declaration order
                node = ctx.nodes.get(nid)
                if node is not None and changed & (set(self.rt.gating.get(nid, [])) | set(setup_gating.get(nid, []))):
                    node.on_calendar_change()
            evt, self.change_event = self.change_event, ctx.env.event()
            evt.succeed()
        self._schedule_next()
