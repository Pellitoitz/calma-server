"""Dispatching strategies for shared resources (operators, tools...).

A strategy only DECIDES; the pool executes. Strategies are process-agnostic: they
see nodes through two generic probes every node implements:
    node.occupancy()     -> units currently inside the node
    node.state_counts()  -> {state: slots} (stations only)
so WIP_TARGET_PRIORITY works for selective soldering, a press line or a packing cell.
Every decision returns (reason, system-state snapshot) for the decision log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ...domain.isms import DispatchRule, Resource, WipTargetParams
from ..base import NodeState

if TYPE_CHECKING:  # pragma: no cover
    from .runtime import ResourcePool, Unit, _Request


class DispatchStrategy(Protocol):
    rule: str

    def choose(self, pool: "ResourcePool", feasible: list["_Request"]) -> tuple["_Request", str, dict]: ...

    def preempt_candidate(self, pool: "ResourcePool") -> tuple["Unit", str, dict] | None: ...

    def watched_nodes(self) -> list[str]: ...


class FifoStrategy:
    rule = "fifo"

    def choose(self, pool, feasible):
        r = min(feasible, key=lambda x: x.seq)
        return r, f"FIFO: oldest request (waiting since t={r.t:.1f}s)", {}

    def preempt_candidate(self, pool):
        return None

    def watched_nodes(self):
        return []


class PriorityStrategy(FifoStrategy):
    rule = "priority"

    def choose(self, pool, feasible):
        r = min(feasible, key=lambda x: (x.priority, x.seq))
        return r, f"PRIORITY: static priority: '{r.node}' has priority {r.priority} (lower = more urgent)", {}


class WipTargetPriority:
    """WIP_TARGET_PRIORITY - see domain.isms.WipTargetParams for the rule set."""

    rule = "wip_target"

    def __init__(self, params: WipTargetParams):
        self.p = params
        self.feeders = set(params.feeder_nodes)
        self.target = int(params.target)  # resolved & verified int
        self.preempt_below = None if params.preempt_below is None else int(params.preempt_below)

    # ---- system probes -------------------------------------------------
    def feed_wip(self, pool) -> tuple[int, dict]:
        nodes = pool.ctx.nodes
        detail = {nid: nodes[nid].occupancy() for nid in self.p.feed_nodes}
        total = sum(detail.values())
        if self.p.count_feeder_in_process:
            for nid in self.p.feeder_nodes:
                c = nodes[nid].state_counts()
                n = c.get(NodeState.BUSY, 0) + c.get(NodeState.BLOCKED, 0)
                detail[f"{nid}(in process)"] = n
                total += n
        return total, detail

    def _state(self, pool) -> tuple[int, bool, dict]:
        feed, detail = self.feed_wip(pool)
        prot = pool.ctx.nodes[self.p.protected_node].state_counts()
        blocked = prot.get(NodeState.BLOCKED, 0) > 0
        state = {"feed_wip": feed, "target": self.target, "feed_detail": detail,
                 f"{self.p.protected_node}_state": {k: v for k, v in prot.items() if v}}
        return feed, blocked, state

    # ---- decisions -------------------------------------------------------
    def choose(self, pool, feasible):
        feed, blocked, state = self._state(pool)
        feeders = [r for r in feasible if r.node in self.feeders]
        others = [r for r in feasible if r.node not in self.feeders]
        first = lambda rs: min(rs, key=lambda x: x.seq)  # noqa: E731 - FIFO within a class
        if blocked and others and self.p.unblock_protected:
            return first(others), (f"PROTECTED_BLOCKED: '{self.p.protected_node}' is BLOCKED (output full) -> downstream task first "
                                   f"to unblock it (feed WIP {feed}, target {self.target})"), state
        if feed < self.target and feeders:
            return first(feeders), f"WIP_BELOW_TARGET: feed WIP {feed} < target {self.target} -> feeder task (keep '{self.p.protected_node}' fed)", state
        if others:
            why = (f"WIP_AT_OR_ABOVE_TARGET: feed WIP {feed} >= target {self.target}" if feed >= self.target
                   else f"NO_FEEDER_WAITING: feed WIP {feed} < target but no feeder task waiting")
            return first(others), f"{why} -> non-feeder task", state
        return first(feeders), f"ONLY_FEEDER_WAITING: only feeder tasks waiting (feed WIP {feed}, target {self.target})", state

    def preempt_candidate(self, pool):
        if self.preempt_below is None:
            return None
        if not any(r.node in self.feeders for r in pool.waiting):
            return None
        feed, blocked, state = self._state(pool)
        if feed >= self.preempt_below or (blocked and self.p.unblock_protected):
            return None
        for u in pool.units:
            if u.busy and u.preemptible and u.task not in self.feeders:
                state["preempted_task"] = u.task
                return u, (f"PREEMPT_WIP_BELOW_THRESHOLD: feed WIP {feed} < preempt_below {self.preempt_below} while working on non-feeder "
                           f"'{u.task}' -> suspend it and serve the feeder task"), state
        return None

    def watched_nodes(self):
        return list(dict.fromkeys([*self.p.feed_nodes, *self.p.feeder_nodes, self.p.protected_node]))


def make_strategy(spec: Resource) -> DispatchStrategy:
    if spec.dispatch is DispatchRule.WIP_TARGET:
        return WipTargetPriority(spec.wip_target)  # type: ignore[arg-type]
    if spec.dispatch is DispatchRule.PRIORITY:
        return PriorityStrategy()
    return FifoStrategy()
