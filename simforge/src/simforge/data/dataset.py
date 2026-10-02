"""Traceable dataset model.

A dataset VERSION is immutable: original file bytes + import settings + parsed observations. Everything the engineer
does afterwards (exclusions, restorations, accepted reviews, fits, decisions, applications) is an APPEND-ONLY event
log next to it (store.py). The "current state" of a dataset is always recomputed from version + events.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .quantities import Basis, QuantityType


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class RowStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"  # usable; something was interpreted (recorded in issues)
    INVALID = "INVALID"  # never used (missing, not a number, negative, unknown unit...)
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # not used until the engineer accepts it (zero, formula value...)


GROUP_ROLES = ["operator", "product", "shift", "machine", "batch"]


class ColumnMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    unit: str | None = None  # one unit for the whole column ...
    unit_column: str | None = None  # ... or a column with the unit of each row
    timestamp: str | None = None
    operator: str | None = None
    product: str | None = None
    shift: str | None = None
    machine: str | None = None
    batch: str | None = None

    @model_validator(mode="after")
    def _one_unit_source(self) -> "ColumnMapping":
        if (self.unit is None) == (self.unit_column is None):
            raise ValueError("indica la unidad: o bien 'unit' (toda la columna) o bien 'unit_column' (una por fila), "
                             "nunca se asume")
        return self

    def group_columns(self) -> dict[str, str]:
        return {role: col for role in GROUP_ROLES if (col := getattr(self, role))}


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int  # position in the dataset (0-based), stable id used by exclusions
    row: int  # row number in the source file
    original_value: str  # exactly as read (text)
    original_unit: str | None = None
    value: float | None = None  # in the dataset analysis unit
    normalized_value: float | None = None  # in the SI base unit (s, m)
    status: RowStatus
    issues: list[str] = Field(default_factory=list)
    timestamp: str | None = None
    groups: dict[str, str] = Field(default_factory=dict)


class DatasetMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str  # "<name>@v<version>"
    name: str
    version: int
    created_at: datetime = Field(default_factory=now_utc)
    imported_by: str = "engineer"
    description: str = ""
    synthetic: bool = False  # SYNTHETIC TEST DATA (never presented as plant measurements)
    measurement_status: Literal["measured", "imported"] = "measured"  # measured by the plant vs imported from a system
    # source
    source_file: str
    stored_file: str  # path of the untouched copy inside the dataset folder
    file_sha256: str
    file_bytes: int
    file_format: str
    sheet: str | None = None
    encoding: str | None = None
    delimiter: str | None = None
    decimal: str | None = None
    header_row: int = 1
    # meaning
    mapping: ColumnMapping
    quantity_type: QuantityType
    basis: Basis
    basis_note: str = ""
    analysis_unit: str
    normalized_unit: str
    # counts
    n_rows: int
    counts: dict[str, int]
    import_notes: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)  # every interpretation applied at import
    content_hash: str  # hash of file bytes + import settings + parsed observations

    @property
    def label(self) -> str:
        return ("[SYNTHETIC TEST DATA] " if self.synthetic else "") + self.dataset_id


def content_hash(file_sha256: str, settings: dict[str, Any], observations: list[Observation]) -> str:
    payload = json.dumps({"file": file_sha256, "settings": settings,
                          "obs": [o.model_dump(mode="json") for o in observations]}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ------------------------------------------------------------------------------------------- event log
RowAction = Literal["EXCLUDE_FROM_FIT", "MARK_INVALID", "KEEP", "RESTORED", "ACCEPT_REVIEWED"]


class RowEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["row"] = "row"
    action: RowAction
    rows: list[int]  # observation indexes
    reason: str = Field(min_length=3)
    method: str | None = None  # e.g. "IQR 1.5", "MAD 3.5", "manual"
    by: str
    at: datetime = Field(default_factory=now_utc)


class Decision(str, Enum):
    USE_DETERMINISTIC = "USE_DETERMINISTIC"
    USE_EMPIRICAL = "USE_EMPIRICAL"
    USE_FITTED = "USE_FITTED"
    KEEP_WITHOUT_APPLYING = "KEEP_WITHOUT_APPLYING"
    REJECT = "REJECT"


class DecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["decision"] = "decision"
    decision_id: str
    decision: Decision
    by: str
    at: datetime = Field(default_factory=now_utc)
    reason: str = ""
    group: dict[str, str] = Field(default_factory=dict)  # subset the decision refers to ({} = all rows)
    pooled: bool = False  # engineer explicitly accepted mixing groups
    derivation: Literal["MEAN", "MEDIAN", "ENGINEER_VALUE"] | None = None  # USE_DETERMINISTIC
    engineer_value: float | None = None  # USE_DETERMINISTIC + ENGINEER_VALUE, in analysis unit
    fit_id: str | None = None  # USE_FITTED
    candidate: str | None = None  # USE_FITTED: distribution name
    truncation: dict | None = None  # explicit truncation accepted by the engineer (analysis unit)
    accepted_warnings: list[str] = Field(default_factory=list)  # plausibility warnings explicitly accepted
    distribution: dict | None = None  # resulting simforge Duration/Quantity (without provenance)
    rows_used: list[int] = Field(default_factory=list)
    n_used: int = 0
    n_excluded: int = 0
    state_hash: str = ""  # hash of (dataset content + exclusions) the decision was made on
    warnings: list[str] = Field(default_factory=list)  # warnings shown and recorded (not blocking)


class FitEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fit"] = "fit"
    fit_id: str
    at: datetime = Field(default_factory=now_utc)
    by: str
    group: dict[str, str] = Field(default_factory=dict)
    pooled: bool = False
    state_hash: str
    result: dict  # FitReport as JSON


class ApplyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["apply"] = "apply"
    decision_id: str
    project_model_version: int  # new model version created
    parent_model_version: int | None
    target: str
    target_basis: str
    conversion: dict | None = None
    by: str
    at: datetime = Field(default_factory=now_utc)
    warnings_acknowledged: list[str] = Field(default_factory=list)  # kept for logs written before engine 0.5.0
    work_units_aggregation: str | None = None  # aggregation set on the target node by this application, if changed


Event = RowEvent | DecisionEvent | FitEvent | ApplyEvent


def parse_event(d: dict) -> Event:
    return {"row": RowEvent, "decision": DecisionEvent, "fit": FitEvent, "apply": ApplyEvent}[d["kind"]].model_validate(d)
