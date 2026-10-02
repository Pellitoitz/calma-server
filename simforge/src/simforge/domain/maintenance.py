"""Maintenance & reliability (engine >= 0.8.0): failures with explicit clocks, corrective repair with resources,
preventive maintenance (calendar- or usage-based). Extension block `maintenance` of SimModel.

Legacy failures (`nodes.<id>.params.failures: {mtbf, mttr}`) are NOT touched: they keep their historical contract
(elapsed clock from t = 0, MTBF counted from the end of the previous repair, repair = pure delay). A node uses either
the legacy block or this one, never both.

    maintenance:
      nodes:
        machine_a:
          failure:
            clock: OPERATING_TIME              # ELAPSED_TIME | OPERATING_TIME
            exposure: [PROCESSING]             # OPERATING_TIME only: PROCESSING and/or SETUP (explicit, never assumed)
            time_to_failure: {dist: weibull, shape: 1.5, scale: 120, unit: h}
            repair_time: {dist: lognormal, mean: 45, std: 15, unit: min}
            repair_resources: [{resource: technician}]   # at most one in 0.8
            repair_age_effect: RESET           # only RESET in 0.8 (as legacy)
          preventive:
            - id: pm_weekly
              trigger: CALENDAR_BASED          # first_due + every (simulation time)
              first_due: {dist: constant, value: 6, unit: h}
              every: {dist: constant, value: 168, unit: h}
              duration: {dist: constant, value: 2, unit: h}
              resources: [{resource: technician}]
              start_policy: AFTER_CURRENT_ACTIVITY
              failure_age_effect: RESET        # RESET | NO_RESET (explicit)
            - id: pm_usage
              trigger: USAGE_BASED
              usage_states: [PROCESSING]
              usage_threshold: {dist: constant, value: 100, unit: h}
              duration: {dist: constant, value: 30, unit: min}
              start_policy: AFTER_CURRENT_ACTIVITY
              failure_age_effect: NO_RESET
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .behaviors import ResourceUse
from .values import Duration, Provenance

EXPOSURE_STATES = ("PROCESSING", "SETUP")  # what can age a machine / accumulate PM usage in 0.8


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FailureModel(_Strict):
    clock: Literal["ELAPSED_TIME", "OPERATING_TIME"]
    exposure: list[str] = Field(default_factory=list)  # OPERATING_TIME: subset of EXPOSURE_STATES, required
    time_to_failure: Duration
    repair_time: Duration
    repair_resources: list[ResourceUse] = Field(default_factory=list)
    repair_age_effect: Literal["RESET", "NO_RESET"]
    resource_unavailability_policy: Literal["FINISH_CURRENT"] | None = None  # repair resources with calendars
    provenance: Provenance | None = None


class PreventiveTask(_Strict):
    id: str
    trigger: Literal["CALENDAR_BASED", "USAGE_BASED"]
    first_due: Duration | None = None  # CALENDAR_BASED: first due time (simulation time from t = 0)
    every: Duration | None = None  # CALENDAR_BASED: interval between due times (None = once)
    usage_states: list[str] = Field(default_factory=list)  # USAGE_BASED: subset of EXPOSURE_STATES, required
    usage_threshold: Duration | None = None  # USAGE_BASED: usage since the end of the last execution of this PM
    duration: Duration
    resources: list[ResourceUse] = Field(default_factory=list)
    start_policy: Literal["AFTER_CURRENT_ACTIVITY"]
    failure_age_effect: Literal["RESET", "NO_RESET"]
    at_unavailability: Literal["FINISH_CURRENT"] | None = None  # PM on calendar-gated machines/resources
    provenance: Provenance | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(f"id de PM inválido '{v}' (minúsculas, dígitos, '_')")
        return v

    @model_validator(mode="after")
    def _shape(self) -> "PreventiveTask":
        if self.trigger == "CALENDAR_BASED":
            if self.first_due is None:
                raise ValueError(f"PM '{self.id}': CALENDAR_BASED necesita first_due")
            if self.usage_states or self.usage_threshold is not None:
                raise ValueError(f"PM '{self.id}': usage_states/usage_threshold sólo con USAGE_BASED")
        else:
            if self.usage_threshold is None or not self.usage_states:
                raise ValueError(f"PM '{self.id}': USAGE_BASED necesita usage_states y usage_threshold")
            if self.first_due is not None or self.every is not None:
                raise ValueError(f"PM '{self.id}': first_due/every sólo con CALENDAR_BASED")
        return self


class NodeMaintenance(_Strict):
    failure: FailureModel | None = None
    preventive: list[PreventiveTask] = Field(default_factory=list)


class MaintenanceSpec(_Strict):
    nodes: dict[str, NodeMaintenance] = Field(min_length=1)

    def maintenance_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]
