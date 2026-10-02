"""Engine behaviours: the small set of primitives the simulation kernel executes.

Library components (Machine, ManualAssembly, SelectiveSoldering, AOI, ...) are
*specialisations* of these behaviours: same executable semantics, different
defaults, documentation, tags and KPIs. This keeps the engine tiny and
verifiable while the library grows without new engine code.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .units import Dimension
from .values import Duration, Quantity


class Behavior(str, Enum):
    SOURCE = "source"
    SINK = "sink"
    BUFFER = "buffer"
    SERVER = "server"  # machines, manual stations, inspection, test...
    TRANSPORT = "transport"  # physical move origin -> destination (racks, pallets, AGV, forklift...)


class ResourceUse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str
    quantity: int = Field(default=1, ge=1)


class FailureSpec(BaseModel):
    """Time-based (calendar) failures. Processing is suspended while down and resumed after repair."""

    model_config = ConfigDict(extra="forbid")

    mtbf: Duration  # time between failures
    mttr: Duration  # time to repair


class SourceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arrival: Literal["infinite", "interarrival"] = "infinite"
    interarrival: Duration | None = None
    max_entities: int | None = Field(default=None, ge=1)
    entity_type: str | None = None


class SinkParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BufferParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int | None = Field(default=None, ge=1, description="None = unlimited")
    discipline: Literal["fifo", "lifo"] = "fifo"


# How `process_time` combines with `work_units` = k (engine >= 0.5.0). Declared explicitly in the model; part of its hash.
#   sum_iid       T = X1 + ... + Xk   one independent sample per work unit (e.g. time measured per circuit, k circuits)
#   scale_sample  T = k * X           ONE sample multiplied: perfectly correlated units (Var = k^2 Var(X))
#   single_sample T = X               one sample is already the whole entity: work_units does not multiply the time
# Undeclared (None) keeps the historical behaviour (k * X) so existing models do not change; it is reported as
# WORK_UNITS_AGGREGATION_UNDECLARED whenever k != 1 and the time is random (simforge.validation.semantics).
WorkUnitsAggregation = Literal["sum_iid", "scale_sample", "single_sample"]
LEGACY_AGGREGATION = "scale_sample"


class ServerParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int = Field(default=1, ge=1, description="Parallel slots (identical stations)")
    process_time: Duration | None = None  # None -> model INCOMPLETE
    work_units: float = Field(default=1, gt=0, description="process_time is per work unit (e.g. per circuit); "
                              "how samples combine is work_units_aggregation. Use '$circuits_per_rack'.")
    work_units_aggregation: WorkUnitsAggregation | None = Field(
        default=None, description="sum_iid (X1+..+Xk) | scale_sample (k*X) | single_sample (X); undeclared = legacy k*X")
    resources: list[ResourceUse] = Field(default_factory=list, description="Held during processing")
    yield_rate: float = Field(default=1.0, gt=0, le=1)
    on_reject: str = Field(default="scrap", description="'scrap' or id of a rework node")
    failures: FailureSpec | None = None
    ideal_cycle_time: Duration | None = None  # for OEE performance; mean process time if absent (flagged)

    @model_validator(mode="after")
    def _check(self) -> "ServerParams":
        ids = [r.resource for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("un mismo recurso aparece dos veces en 'resources'")
        if self.work_units_aggregation == "sum_iid" and not float(self.work_units).is_integer():
            raise ValueError(f"work_units_aggregation 'sum_iid' necesita un número entero de unidades (work_units = {self.work_units})")
        return self

    @property
    def aggregation(self) -> str:
        """Effective aggregation (legacy k*X when undeclared)."""
        return self.work_units_aggregation or LEGACY_AGGREGATION

    def sample_entity_seconds(self, rng, process_time=None) -> float:
        """Processing time of one entity. All samples come from the node's own stream `rng` (reproducible).
        `process_time` = product-specific time (engine >= 0.7.0); None = the node's own process_time."""
        pt = self.process_time if process_time is None else process_time
        agg = self.aggregation
        if agg == "single_sample":
            return pt.sample_seconds(rng)  # type: ignore[union-attr]
        if agg == "sum_iid":
            return sum(pt.sample_seconds(rng) for _ in range(int(self.work_units)))  # type: ignore[union-attr]
        return pt.sample_seconds(rng) * self.work_units  # type: ignore[union-attr]

    def entity_time_factor(self) -> float:
        """Mean entity time = mean(process_time) x this factor (same for sum_iid and scale_sample)."""
        return 1.0 if self.aggregation == "single_sample" else float(self.work_units)


class TransportParams(BaseModel):
    """Physical transport. Distance, speed, load and unload times are REQUIRED (None -> INCOMPLETE):
    they are never defaulted because they drive walking/transport time directly."""

    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(default=None, description="node id; required for carrier-return transports")
    destination: str | None = Field(default=None, description="node id; required for carrier-return transports")
    distance: Quantity | None = None
    speed: Quantity | None = None
    capacity: int = Field(default=1, ge=1, description="units carried per trip")
    fleet: int = Field(default=1, ge=1, description="trips that can run in parallel (vehicles)")
    load_time: Duration | None = None  # per trip
    unload_time: Duration | None = None  # per trip
    resources: list[ResourceUse] = Field(default_factory=list, description="held for the whole trip (incl. empty return)")
    return_empty: bool = Field(default=True, description="the transporter travels back empty (resource held)")
    batch: Literal["immediate", "full"] = Field(default="immediate", description="leave with what is waiting / wait for a full load")
    reserve_destination: bool = Field(default=False, description="True: a trip starts (resource requested) only once a place "
                                      "at the destination is reserved; False: the transporter may wait at a full destination holding the load")
    loading_area: int = Field(default=0, ge=0, description="places at the pickup point. 0 = the unit stays in the upstream "
                              "node (keeping its place) until it is physically loaded")

    @model_validator(mode="after")
    def _batch(self) -> "TransportParams":
        if self.batch == "full" and self.capacity > 1 and self.loading_area < self.capacity:
            raise ValueError("batch 'full' con capacity > 1 requiere loading_area >= capacity (si no, nunca se completa la carga)")
        return self

    @model_validator(mode="after")
    def _check(self) -> "TransportParams":
        if self.distance is not None:
            if isinstance(self.distance.value, str):
                raise ValueError("distance sin resolver")
            self.distance.to_base(Dimension.LENGTH)
            if self.distance.value < 0:
                raise ValueError("distance no puede ser negativa")
        if self.speed is not None:
            self.speed.to_base(Dimension.SPEED)
            if self.speed.value <= 0:
                raise ValueError("speed debe ser > 0")
        return self

    def travel_seconds(self) -> float:
        return self.distance.to_base() / self.speed.to_base()  # type: ignore[union-attr]


BEHAVIOR_PARAMS: dict[Behavior, type[BaseModel]] = {
    Behavior.SOURCE: SourceParams,
    Behavior.SINK: SinkParams,
    Behavior.BUFFER: BufferParams,
    Behavior.SERVER: ServerParams,
    Behavior.TRANSPORT: TransportParams,
}
