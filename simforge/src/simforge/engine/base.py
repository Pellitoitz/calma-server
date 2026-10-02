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
    # calendars (engine >= 0.6.0), only outside PLANNED time of the node (its own calendar ∩ its resources' calendars)
    PAUSED = "paused_by_calendar"  # operation interrupted (PAUSE_RESUME / STOP_RESTART), entity kept in the slot
    BUSY_OUTSIDE = "busy_outside_planned"  # FINISH_CURRENT: operation started in planned time, finishing after it
    BREAK = "break"
    OFF_SHIFT = "off_shift"
    # setups / changeovers (engine >= 0.7.0); only on nodes with setups (never in legacy KPIs: not part of ALL)
    SETUP = "setup"
    SETUP_OUTSIDE = "setup_outside_planned"  # setup running outside the node's planned time
    PLANNED = (*ALL, SETUP)
    UNPLANNED = (PAUSED, BUSY_OUTSIDE, BREAK, OFF_SHIFT, SETUP_OUTSIDE)


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
    availability: dict[str, Any] | None = None  # calendars: planned/break/off-shift time per resource/node (engine >= 0.6.0)
    # products and setups (engine >= 0.7.0); empty for models without a `production` block
    created_by_product: dict[str, int] = field(default_factory=dict)  # whole run
    entity_product: dict[int, str] = field(default_factory=dict)  # entity id -> product
    node_setups: dict[str, int] = field(default_factory=dict)  # setups completed (post-warmup)
    setups: list[dict[str, Any]] = field(default_factory=list)  # one audit row per setup (whole run)
    wip_end_by_product: dict[str, int] = field(default_factory=dict)
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
