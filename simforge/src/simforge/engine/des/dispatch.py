"""Dispatching strategies for shared resources (operators, tools...).

A strategy only DECIDES; the pool executes. Strategies are process-agnostic: they
see nodes through two generic probes every node implements:
    node.occupancy()     -> units currently inside the node
    node.state_counts()  -> {state: slots} (stations only)
so WIP_TARGET_PRIORITY works for selective soldering, a press line or a packing cell.
Every decision returns (reason, system-state snapshot) for the decision log.
"""

from __future__ import annotations

import math
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


def tie_key(r: "_Request") -> tuple:
    """Deterministic order among requests the strategy considers equivalent (documented in docs/simulation_engine.md):
    1) logical request time (older request first)
    2) older unit first (lower entity id = entered the system earlier; requests without a unit go last)
    3) declaration order of the requesting node in the ISMS
    4) request sequence number (last resort; only reached by two requests of the same node and unit)
    Never Python iteration order, hashes or SimPy's internal event order."""
    return (r.t, r.entity if r.entity is not None else math.inf, r.node_rank, r.seq)


def tie_note(chosen: "_Request", rivals: list["_Request"]) -> str:
    """Explain which tie-break criterion decided among `rivals` (same strategy class), for the decision log."""
    same_t = [r for r in rivals if r is not chosen and r.t == chosen.t]
    if not same_t:
        return ""
    if all((r.entity if r.entity is not None else math.inf) != (chosen.entity if chosen.entity is not None else math.inf)
           for r in same_t):
        return f" [tie at t={chosen.t:.3f}s resolved by older unit]"
    if all(r.node_rank != chosen.node_rank for r in same_t):
        return f" [tie at t={chosen.t:.3f}s resolved by node declaration order]"
    return f" [tie at t={chosen.t:.3f}s resolved by request sequence]"


class FifoStrategy:
    rule = "fifo"

    def choose(self, pool, feasible):
        r = min(feasible, key=tie_key)
        return r, f"FIFO: oldest request (waiting since t={r.t:.1f}s){tie_note(r, feasible)}", {}

    def preempt_candidate(self, pool):
        return None

    def watched_nodes(self):
        return []


class PriorityStrategy(FifoStrategy):
    rule = "priority"

    def choose(self, pool, feasible):
        r = min(feasible, key=lambda x: (x.priority, *tie_key(x)))
        same = [x for x in feasible if x.priority == r.priority]
        return r, f"PRIORITY: static priority: '{r.node}' has priority {r.priority} (lower = more urgent){tie_note(r, same)}", {}


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
        """Number of DISTINCT units that are: held by a feed node, or (count_feeder_in_process) in a BUSY/BLOCKED
        slot or vehicle of a feeder node. Inclusion is the contract of WipTargetParams; a unit satisfying several
        conditions (e.g. a rack still occupying the assembly place while the transport that reserved it is loading)
        is counted ONCE. `detail` lists each source; 'shared' = units seen by more than one source."""
        nodes = pool.ctx.nodes
        seen: dict[int, int] = {}
        detail: dict[str, int] = {}
        for nid in self.p.feed_nodes:
            ids = nodes[nid].held_entities()
            detail[nid] = len(ids)
            for i in ids:
                seen[i] = seen.get(i, 0) + 1
        if self.p.count_feeder_in_process:
            for nid in self.p.feeder_nodes:
                ids = nodes[nid].in_process_entities()
                detail[f"{nid}(in process)"] = len(ids)
                for i in ids:
                    seen[i] = seen.get(i, 0) + 1
        detail["shared"] = sum(1 for c in seen.values() if c > 1)
        return len(seen), detail

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
        def first(rs):  # FIFO within a class, deterministic tie-break (tie_key)
            r = min(rs, key=tie_key)
            return r, tie_note(r, rs)
        if blocked and others and self.p.unblock_protected:
            r, tie = first(others)
            return r, (f"PROTECTED_BLOCKED: '{self.p.protected_node}' is BLOCKED (output full) -> downstream task first "
                       f"to unblock it (feed WIP {feed}, target {self.target}){tie}"), state
        if feed < self.target and feeders:
            r, tie = first(feeders)
            return r, f"WIP_BELOW_TARGET: feed WIP {feed} < target {self.target} -> feeder task (keep '{self.p.protected_node}' fed){tie}", state
        if others:
            why = (f"WIP_AT_OR_ABOVE_TARGET: feed WIP {feed} >= target {self.target}" if feed >= self.target
                   else f"NO_FEEDER_WAITING: feed WIP {feed} < target but no feeder task waiting")
            r, tie = first(others)
            return r, f"{why} -> non-feeder task{tie}", state
        r, tie = first(feeders)
        return r, f"ONLY_FEEDER_WAITING: only feeder tasks waiting (feed WIP {feed}, target {self.target}){tie}", state

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
