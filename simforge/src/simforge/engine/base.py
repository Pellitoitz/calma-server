"""Engine-agnostic interface and RAW run data (layer 1 of 3: raw -> KPIs -> interpretation).

Any engine adapter (our SimPy kernel, a future AnyLogic runner...) must return
a `RunRecord`. KPIs are computed from it by `simforge.analytics`, never by the
engine and never by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..validation.verifier import CompiledModel


class NodeState:
    STARVED = "starved"  # idle, nothing to process
    WAITING_RESOURCE = "waiting_resource"  # has a unit, waiting for operator/tool/carrier
    BUSY = "busy"
    BLOCKED = "blocked"  # finished, downstream full
    DOWN = "down"
    ALL = (STARVED, WAITING_RESOURCE, BUSY, BLOCKED, DOWN)


class ResourceState:
    IDLE = "idle"
    WALKING = "walking"
    WORKING = "working"
    ALL = (IDLE, WALKING, WORKING)


@dataclass
class TimeSeries:
    t: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)


@dataclass
class RunRecord:
    """Raw facts produced by one replication. Times in seconds."""

    seed: int
    horizon_s: float
    warmup_s: float
    engine: str
    engine_version: str
    # entities
    completions: list[tuple[int, float, float]] = field(default_factory=list)  # (entity, created, done) done >= warmup
    scrapped: list[tuple[int, str, float]] = field(default_factory=list)  # (entity, node, t)
    created: int = 0
    wip_end: int = 0
    # nodes
    node_behavior: dict[str, str] = field(default_factory=dict)
    node_slots: dict[str, int] = field(default_factory=dict)
    node_state_time: dict[str, dict[str, float]] = field(default_factory=dict)  # summed over slots
    node_processed: dict[str, int] = field(default_factory=dict)  # finished processing (post-warmup)
    node_rejects: dict[str, int] = field(default_factory=dict)
    node_wait: dict[str, list[float]] = field(default_factory=dict)  # time from entering node to start/leave
    node_failures: dict[str, int] = field(default_factory=dict)
    # levels (time-weighted, post-warmup)
    level_avg: dict[str, float] = field(default_factory=dict)  # "wip", "buffer:<id>", "carriers_in_use:<id>"
    level_max: dict[str, float] = field(default_factory=dict)
    series: dict[str, TimeSeries] = field(default_factory=dict)
    # resources
    resource_units: dict[str, int] = field(default_factory=dict)
    resource_state_time: dict[str, dict[str, float]] = field(default_factory=dict)  # summed over units
    resource_tasks: dict[str, dict[str, int]] = field(default_factory=dict)  # resource -> node -> tasks
    resource_preemptions: dict[str, int] = field(default_factory=dict)
    node_trips: dict[str, int] = field(default_factory=dict)  # transports: trips started (post-warmup)
    node_units_moved: dict[str, int] = field(default_factory=dict)  # transports: units delivered
    node_preemptions: dict[str, int] = field(default_factory=dict)  # tasks suspended by pre-emption
    invariant_checks: int = 0
    completion_times: list[float] = field(default_factory=list)
    # debug
    events: list[dict[str, Any]] | None = None
    decisions: list[dict[str, Any]] | None = None

    @property
    def measured_s(self) -> float:
        return self.horizon_s - self.warmup_s


class SimulationEngine(Protocol):
    name: str
    version: str

    def run(self, model: CompiledModel, seed: int, trace: bool = False) -> RunRecord: ...
