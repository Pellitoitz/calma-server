"""Maintenance controller of one station (engine >= 0.8.0): failure clock, corrective repair, preventive maintenance.

Orthogonal state (see docs/maintenance_and_reliability.md):
  * machine CONDITION (node level, `condition_time`): up / down_waiting_repair_resource / repair / pm_waiting /
    preventive_maintenance;
  * slot ACTIVITY (processing / setup / ...), untouched; an activity interrupted by a failure keeps its remaining work;
  * CALENDAR label (0.6), untouched: the slot accounting maps any condition to the calendar label outside planned time.

Contracts:
  * failure age = accumulated EXPOSURE since the last reset; failure when age reaches the sampled time-to-failure
    (sample != age: nothing is re-sampled by idle, breaks, off-shift or pauses). ELAPSED_TIME exposure = all time except
    DOWN (failure until repair end) and active PM; OPERATING_TIME exposure = the declared states (PROCESSING / SETUP).
  * corrective repair: FAILURE -> DOWN (waiting for the repair resource, if any) -> REPAIR (sampled repair time) -> UP;
    not gated by the machine calendar (as legacy); age RESET at repair end with a new sample.
  * preventive maintenance: PM_DUE (calendar-based: fixed schedule; usage-based: usage since the end of the last
    execution) -> PENDING -> AFTER_CURRENT_ACTIVITY: the activity in progress (incl. an interrupted/paused one) finishes,
    no new activity starts, the machine is reserved -> needs: not DOWN, PM calendars available, resource -> PM -> UP.
    The start decision is taken at the END of the instant (after failures, calendar transitions and activity ends of
    that instant). A due PM already pending is merged (not stacked). PM never changes setup_state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..base import NodeState

if TYPE_CHECKING:  # pragma: no cover
    from .nodes import IndustrialServer

URGENT = 0
UP = "up"
COND_DOWN_WAITING = NodeState.DOWN_WAITING_REPAIR
COND_REPAIR = NodeState.REPAIR
COND_PM_WAITING = NodeState.PM_WAITING
COND_PM = NodeState.PM


class Integrator:
    """Accumulates time while `active()` holds; calls `on_reach` once when the value reaches `threshold`."""

    def __init__(self, ctrl: "MaintenanceController", active: Callable[[], bool], threshold: float | None,
                 on_reach: Callable[[], None]):
        self.c, self.active, self.threshold, self.on_reach = ctrl, active, threshold, on_reach
        self.value = 0.0
        self.window_value = 0.0  # part inside [warm-up, horizon] (observed MTBF basis)
        self.since = ctrl.ctx.now
        self.running = False
        self.gen = 0

    def sync(self, until: float | None = None) -> None:
        ctx = self.c.ctx
        now = ctx.now if until is None else until  # finalize: close the window at the horizon (not the last event)
        if self.running:
            self.value += now - self.since
            a, b = max(self.since, ctx.warmup), min(now, ctx.horizon)
            if b > a:
                self.window_value += b - a
        self.since = now

    def refresh(self) -> None:
        self.sync()
        self.running = self.active()
        self.gen += 1
        if not self.running or self.threshold is None:
            return
        left = self.threshold - self.value
        if left <= 1e-9:
            self._reach()
            return
        gen = self.gen
        evt = self.c.ctx.env.timeout(left)
        evt.callbacks.append(lambda _e: self._timer(gen))

    def _timer(self, gen: int) -> None:
        if gen != self.gen:
            return
        self.sync()
        if self.threshold is not None and self.value >= self.threshold - 1e-9:
            self._reach()

    def _reach(self) -> None:
        self.threshold = None  # fires once; re-armed by reset()
        self.gen += 1
        self.on_reach()

    def reset(self, threshold: float | None) -> None:
        self.sync()
        self.value = 0.0
        self.threshold = threshold
        self.refresh()


class MaintenanceController:
    def __init__(self, node: "IndustrialServer", nm, pm_gating: dict[str, list[str]]):
        self.node, self.ctx, self.nm = node, node.ctx, nm
        ctx = self.ctx
        self.exposed: set[str] = set()  # PROCESSING / SETUP segments running now
        self.activities = 0  # activities in progress (started, not finished; paused/interrupted ones included)
        self.pending: list = []  # due PM tasks, in due order
        self.pm_active = None
        self.pm_gating = pm_gating
        self.failing = False
        self.condition = UP
        from .runtime import StateTracker
        self.tracker = StateTracker(ctx, UP)
        self._change = ctx.env.event()
        self.rows: list[dict] = []
        f = nm.failure
        self.failure = None
        if f is not None:
            self.rng_ttf = ctx.rng(node.id, "failure_ttf")
            self.rng_repair = ctx.rng(node.id, "repair")
            if f.clock == "ELAPSED_TIME":
                active = lambda: not node.down and self.pm_active is None  # noqa: E731
            else:
                states = set(f.exposure)
                active = lambda: not node.down and bool(self.exposed & states)  # noqa: E731
            self.ttf = f.time_to_failure.sample_seconds(self.rng_ttf)
            self.failure = Integrator(self, active, self.ttf, self._on_failure_due)
        self.usage: dict[str, Integrator] = {}
        self.rng_pm = {}
        for t in nm.preventive:
            self.rng_pm[t.id] = ctx.rng(node.id, "pm", t.id)
            if t.trigger == "USAGE_BASED":
                states = set(t.usage_states)
                self.usage[t.id] = Integrator(self, lambda s=states: not node.down and bool(self.exposed & s),
                                              t.usage_threshold.mean_seconds(), lambda t=t: self._due(t))
            else:
                self._schedule_calendar_pm(t, t.first_due.mean_seconds())
        if nm.preventive:
            ctx.env.process(self._pm_executor())
        self._refresh_integrators()

    # ------------------------------------------------------------------ hooks called by the station
    def activity(self, on: bool) -> None:
        self.activities += 1 if on else -1
        self._notify()

    def exposure(self, kind: str, on: bool) -> None:
        (self.exposed.add if on else self.exposed.discard)(kind)
        self._refresh_integrators()
        if not on:
            self._notify()

    def blocks(self) -> bool:
        """Gate for NEW activities (setup / processing): none starts while the machine is DOWN or a PM is pending or
        running (AFTER_CURRENT_ACTIVITY). Activities already started finish first (an interrupted one keeps its
        resources and remaining work, as legacy)."""
        return self.node.down or bool(self.pending) or self.pm_active is not None

    def gate(self):
        while self.blocks():
            yield self.wait_change()

    def task_can_work(self) -> bool:
        cal = self.ctx.calendar
        if not self.pending or cal is None:
            return True
        g = self.pm_gating.get(self.pending[0].id, [])
        return not g or cal.ok(g)

    def notify(self) -> None:
        self._notify()

    # ------------------------------------------------------------------ internals
    def wait_change(self):
        return self._change

    def _notify(self) -> None:
        self._set_condition()
        evt, self._change = self._change, self.ctx.env.event()
        evt.succeed()

    def _set_condition(self) -> None:
        if self.node.down:
            cond = self.condition if self.condition in (COND_DOWN_WAITING, COND_REPAIR) else COND_DOWN_WAITING
        elif self.pm_active is not None:
            cond = COND_PM
        elif self.pending and self.activities == 0:
            cond = COND_PM_WAITING
        else:
            cond = UP
        self._condition(cond)

    def _condition(self, cond: str) -> None:
        if cond != self.condition:
            self.condition = cond
            self.tracker.set(cond)
            self.node._refresh()
            self.ctx.changed(self.node.id)

    def _refresh_integrators(self) -> None:
        if self.failure is not None:
            self.failure.refresh()
        for it in self.usage.values():
            it.refresh()

    def _at_urgent(self, t: float, cb) -> None:
        env = self.ctx.env
        evt = env.event()
        evt.callbacks.append(lambda _e: cb())
        evt._ok = True  # noqa: SLF001 - same mechanism as the calendar clock (URGENT = start of the instant)
        evt._value = None  # noqa: SLF001
        env.schedule(evt, priority=URGENT, delay=max(0.0, t - env.now))

    def _schedule_calendar_pm(self, t, due: float) -> None:
        if due > self.ctx.horizon:
            return

        def fire():
            self._due(t)
            if t.every is not None:
                self._schedule_calendar_pm(t, due + t.every.mean_seconds())
        self._at_urgent(due, fire)

    def _state_info(self) -> dict:
        node, ctx = self.node, self.ctx
        info: dict = {"condition": self.condition}
        if ctx.calendar is not None and node.gating:
            info["calendar"] = "available" if ctx.calendar.ok(node.gating) else ctx.calendar.off_label(node.gating)
        if node.setup is not None:
            info["setup_state"] = node.setup_state
        return info

    def _due(self, t) -> None:
        ctx = self.ctx
        if any(p.id == t.id for p in self.pending) or (self.pm_active is not None and self.pm_active.id == t.id):
            ctx.log("pm_due_merged", None, self.node.id, pm=t.id, **self._state_info())
            return
        self.pending.append(t)
        self.rows.append({"type": "pm", "node": self.node.id, "pm": t.id, "trigger": t.trigger, "due": ctx.now})
        ctx.log("pm_due", None, self.node.id, pm=t.id, trigger=t.trigger, activity_in_progress=self.activities > 0,
                **self._state_info())
        self._notify()

    # ---- corrective maintenance
    def _on_failure_due(self) -> None:
        if not self.failing:
            self.failing = True
            self.ctx.env.process(self._fail())

    def _fail(self):
        node, ctx, f = self.node, self.ctx, self.nm.failure
        self.failure.sync()
        age = self.failure.value
        interrupted = [{"slot": s, "activity": node.phase.get(s), "remaining_s": round(node.seg_remaining(s), 6)}
                       for s in sorted(node.processing)]
        row = {"type": "failure", "node": node.id, "t_fail": ctx.now, "clock": f.clock, "ttf_s": self.ttf, "age_s": age,
               "interrupted": interrupted, "counted": ctx.counting}
        self.rows.append(row)  # open until the repair ends (a repair still open at the horizon stays visible)
        node.down = True
        self._condition(COND_DOWN_WAITING)
        self._refresh_integrators()
        if ctx.counting:
            ctx.record.node_failures[node.id] += 1
        ctx.log("failure", None, node.id, clock=f.clock, ttf_s=round(self.ttf, 6), age_s=round(age, 6),
                interrupted=interrupted, **self._state_info())
        for slot in sorted(node.processing):
            node._interrupt(slot, "failure")
        held = []
        for use in f.repair_resources:
            from .nodes import acquire_units
            ctx.log("repair_resource_request", None, node.id, resource=use.resource)
            held.extend((yield from acquire_units(ctx, ctx.pools[use.resource], node.id + REPAIR_TASK, use.quantity,
                                                  node.cn.node.priority, None, walk_to=node.id)))
        row["t_repair_start"] = ctx.now
        d = f.repair_time.sample_seconds(self.rng_repair)
        row["repair_sampled_s"] = d
        row["repair_resources"] = [u.name for u in held]
        self._condition(COND_REPAIR)
        ctx.log("repair_start", None, node.id, duration_s=round(d, 6), resources=row["repair_resources"], **self._state_info())
        yield ctx.env.timeout(d)
        _release(ctx, held)
        row["t_repair_end"] = ctx.now
        ctx.log("repair_end", None, node.id)
        # repair_age_effect RESET (the only one supported in 0.8, as legacy): new time-to-failure from now
        self.ttf = f.time_to_failure.sample_seconds(self.rng_ttf)
        node.down = False
        self.failing = False
        self.failure.reset(self.ttf)
        self._set_condition()
        node._refresh()
        ctx.log("up", None, node.id, **self._state_info())
        evt, node.up_event = node.up_event, ctx.env.event()
        evt.succeed()
        self._refresh_integrators()
        self._notify()

    # ---- preventive maintenance
    def _end_of_instant(self):
        evt = self.ctx.env.event()
        self.ctx.at_end_of_timestep(lambda: evt.succeed())
        return evt

    def _can_start(self, t) -> bool:
        cal = self.ctx.calendar
        g = self.pm_gating.get(t.id, [])
        return not self.node.down and self.activities == 0 and (not g or cal is None or cal.ok(g))

    def _pm_executor(self):
        node, ctx = self.node, self.ctx
        while True:
            while not self.pending:
                yield self.wait_change()
            t = self.pending[0]
            if not self._can_start(t):
                yield self.wait_change()
                continue
            yield self._end_of_instant()  # failures / calendar / activity ends of this instant first
            if not self.pending or not self._can_start(self.pending[0]):
                continue
            t = self.pending[0]
            held = []
            for use in t.resources:
                from .nodes import acquire_units
                ctx.log("pm_resource_request", None, node.id, pm=t.id, resource=use.resource)
                held.extend((yield from acquire_units(ctx, ctx.pools[use.resource], node.id + PM_TASK, use.quantity,
                                                      node.cn.node.priority, None, walk_to=node.id)))
            if not self._can_start(t):  # failed (ELAPSED) or calendar closed while waiting: never PM on a DOWN machine
                _release(ctx, held)
                ctx.log("pm_resource_returned", None, node.id, pm=t.id, **self._state_info())
                continue
            row = next(r for r in reversed(self.rows) if r["type"] == "pm" and r["pm"] == t.id and "start" not in r)
            row["start"] = ctx.now
            if self.failure is not None:
                self.failure.sync()
                row["age_before_s"] = self.failure.value
            d = t.duration.sample_seconds(self.rng_pm[t.id])
            row["sampled_s"] = d
            row["resources"] = [u.name for u in held]
            self.pm_active = t
            self._refresh_integrators()
            self._set_condition()
            ctx.log("pm_start", None, node.id, pm=t.id, duration_s=round(d, 6), resources=row["resources"],
                    **self._state_info())
            yield ctx.env.timeout(d)
            _release(ctx, held)
            self.pm_active = None
            self.pending.pop(0)
            if self.failure is not None and t.failure_age_effect == "RESET":
                self.ttf = self.nm.failure.time_to_failure.sample_seconds(self.rng_ttf)
                self.failure.reset(self.ttf)
            if t.id in self.usage:
                self.usage[t.id].reset(t.usage_threshold.mean_seconds())
            row["end"] = ctx.now
            row["counted"] = ctx.counting
            row["age_effect"] = t.failure_age_effect
            if self.failure is not None:
                self.failure.sync()
                row["age_after_s"] = self.failure.value
            self._refresh_integrators()
            ctx.log("pm_end", None, node.id, pm=t.id, age_effect=t.failure_age_effect, **self._state_info())
            self._notify()

    def finalize(self) -> None:
        rec = self.ctx.record
        rec.node_condition_time[self.node.id] = self.tracker.finalize()
        if self.failure is not None:
            self.failure.sync(max(self.ctx.now, self.ctx.horizon))
            rec.failure_exposure_s[self.node.id] = self.failure.window_value
        rec.maintenance.extend(self.rows)


REPAIR_TASK = "#repair"
PM_TASK = "#pm"


def _release(ctx, held) -> None:
    from .nodes import release_units
    release_units(ctx, held)
