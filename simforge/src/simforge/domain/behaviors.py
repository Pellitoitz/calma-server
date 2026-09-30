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

from .values import Duration


class Behavior(str, Enum):
    SOURCE = "source"
    SINK = "sink"
    BUFFER = "buffer"
    SERVER = "server"  # machines, manual stations, inspection, test...


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


class ServerParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity: int = Field(default=1, ge=1, description="Parallel slots (identical stations)")
    process_time: Duration | None = None  # None -> model INCOMPLETE
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
        return self


BEHAVIOR_PARAMS: dict[Behavior, type[BaseModel]] = {
    Behavior.SOURCE: SourceParams,
    Behavior.SINK: SinkParams,
    Behavior.BUFFER: BufferParams,
    Behavior.SERVER: ServerParams,
}
