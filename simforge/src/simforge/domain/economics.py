"""Economic assumptions (engine >= 0.9.0): an explicit, post-run layer on top of physical simulation results.

Extension block `economics` of SimModel, EXCLUDED from the physical content hash: changing a salary, a tariff or a
CAPEX never changes the DES, never invalidates the physical approval and never requires a new physical run. Its own
hash (`economic_hash`) identifies an evaluation together with the physical run it is applied to.

Every monetary value carries value + currency + basis (+ provenance / reference / effective_date). `value: null` =
MISSING (shown as such, never replaced by a typical value). One currency per evaluation; no FX.

    economics:
      currency: EUR
      scope: [labor, machine, energy, material, maintenance]   # what the engineer wants evaluated (coverage)
      labor:
        - {resource: operator_1, paid_time: CALENDAR_WINDOW,
           rate: {value: 30, currency: EUR, basis: PER_PAID_HOUR, provenance: {status: provided_by_client}}}
      machine:
        - {node: m1, rate: {value: 12, currency: EUR, basis: PER_PROCESSING_HOUR}}
      energy:
        price: {value: 0.2, currency: EUR, basis: PER_KWH}
        power_kw: {m1: {PROCESSING: 5.5, SETUP: 1.2}}           # declared electrical power (post-run accounting)
      material:
        - {rate: {value: 5, currency: EUR, basis: PER_CONSUMED_UNIT}}
      scrap: []
      maintenance:
        - {kind: REPAIR_LABOR, node: m1, resource: technician, rate: {value: 40, currency: EUR, basis: PER_BUSY_HOUR}}
      downtime: []
      revenue: []
      capex:
        - {category: equipment, amount: {value: 42000, currency: EUR, basis: FIXED}}
      annualization: {mode: REPEAT_RUN, runs_per_year: 440}
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from .values import Provenance

ECONOMICS_ENGINE_VERSION = "0.9.0"
CATEGORIES = ("labor", "machine", "energy", "material", "scrap", "maintenance", "downtime")
OUT_OF_SCOPE = ("depreciation", "financing", "taxes", "overhead", "opportunity_cost", "lost_revenue")


class Basis(str, Enum):
    """What one unit of the rate is applied to. Each basis maps to ONE physical magnitude (economics/metrics.py)."""

    PER_PAID_HOUR = "PER_PAID_HOUR"  # labor: paid time per the declared paid_time rule
    PER_PLANNED_HOUR = "PER_PLANNED_HOUR"  # calendar planned-available time (always-available = measured window)
    PER_BUSY_HOUR = "PER_BUSY_HOUR"  # resource in use (working + walking + transporting, incl. outside planned)
    PER_PROCESSING_HOUR = "PER_PROCESSING_HOUR"  # node processing (busy) time
    PER_SETUP_HOUR = "PER_SETUP_HOUR"  # node setup time (engine >= 0.7.0)
    PER_OPERATING_HOUR = "PER_OPERATING_HOUR"  # node processing + setup time
    PER_CALENDAR_HOUR = "PER_CALENDAR_HOUR"  # measured window x units/slots
    PER_CYCLE = "PER_CYCLE"  # node processed count
    PER_GOOD_UNIT = "PER_GOOD_UNIT"  # units completed at a sink
    PER_SCRAP_UNIT = "PER_SCRAP_UNIT"  # units scrapped
    PER_CONSUMED_UNIT = "PER_CONSUMED_UNIT"  # good + scrapped units (units that consumed their material and left)
    PER_KWH = "PER_KWH"  # energy price
    PER_FAILURE = "PER_FAILURE"  # maintenance: fixed amount per failure
    PER_PM = "PER_PM"  # maintenance: fixed amount per preventive maintenance completed
    PER_CORRECTIVE_DOWNTIME_HOUR = "PER_CORRECTIVE_DOWNTIME_HOUR"  # declared downtime cost
    FIXED_PER_RUN = "FIXED_PER_RUN"  # fixed amount for the evaluated run
    FIXED = "FIXED"  # an amount (CAPEX items)
    # declared but NOT calculable in 0.9 (rejected by the verifier with the reason):
    PER_UNIT = "PER_UNIT"  # ambiguous (created? processed? good?) -> use PER_GOOD_UNIT / PER_CONSUMED_UNIT
    FIXED_PER_PERIOD = "FIXED_PER_PERIOD"  # needs a period model -> use FIXED_PER_RUN + annualization


UNSUPPORTED_BASES = {Basis.PER_UNIT: "ambiguo: usa PER_GOOD_UNIT o PER_CONSUMED_UNIT",
                     Basis.FIXED_PER_PERIOD: "no hay modelo de periodos en 0.9: usa FIXED_PER_RUN + annualization"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Money(_Strict):
    value: float | None  # None = MISSING
    currency: str
    basis: Basis
    provenance: Provenance | None = None
    reference: str | None = None
    effective_date: dt.date | None = None

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError(f"moneda '{v}' inválida: código ISO de 3 letras (p. ej. EUR)")
        return v

    @field_validator("value")
    @classmethod
    def _finite(cls, v):
        if v is not None and not math.isfinite(v):
            raise ValueError("el valor económico debe ser finito")
        return v

    @model_serializer(mode="wrap")
    def _keep_missing(self, handler):
        d = handler(self)
        d.setdefault("value", None)  # MISSING stays explicit even under exclude_none (saved models round-trip)
        return d

    @property
    def missing(self) -> bool:
        return self.value is None


class LaborLine(_Strict):
    resource: str
    rate: Money
    paid_time: Literal["CALENDAR_WINDOW", "PLANNED_AVAILABLE", "DECLARED"] | None = None  # PER_PAID_HOUR only
    declared_paid_hours_per_unit: float | None = None  # DECLARED: paid hours per resource unit for the run


class MachineLine(_Strict):
    node: str
    rate: Money


class EnergyModel(_Strict):
    price: Money
    power_kw: dict[str, dict[Literal["PROCESSING", "SETUP"], float]] = Field(default_factory=dict)  # node -> state -> kW


class UnitLine(_Strict):
    rate: Money
    product: str | None = None  # product-specific (PER_GOOD_UNIT only)


class MaintenanceLine(_Strict):
    kind: Literal["REPAIR_LABOR", "PM_LABOR", "PER_FAILURE", "PER_PM"]
    node: str
    resource: str | None = None  # *_LABOR
    rate: Money


class DowntimeLine(_Strict):
    node: str
    rate: Money


class CapexItem(_Strict):
    category: str
    amount: Money
    note: str = ""


class Annualization(_Strict):
    mode: Literal["REPEAT_RUN"]
    runs_per_year: float  # how many times per year the evaluated run represents the operation (explicit)
    provenance: Provenance | None = None


class EconomicsSpec(_Strict):
    currency: str
    scope: list[str] = Field(default_factory=list)  # categories the engineer wants evaluated (coverage / MISSING)
    labor: list[LaborLine] = Field(default_factory=list)
    machine: list[MachineLine] = Field(default_factory=list)
    energy: EnergyModel | None = None
    material: list[UnitLine] = Field(default_factory=list)
    scrap: list[UnitLine] = Field(default_factory=list)  # scrap material cost (PER_SCRAP_UNIT)
    maintenance: list[MaintenanceLine] = Field(default_factory=list)
    downtime: list[DowntimeLine] = Field(default_factory=list)
    revenue: list[UnitLine] = Field(default_factory=list)  # sale price PER_GOOD_UNIT
    capex: list[CapexItem] = Field(default_factory=list)
    annualization: Annualization | None = None
    allocation_policy: Literal["NONE"] = "NONE"  # shared costs are never spread over products in 0.9

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return Money._ccy(v)

    @model_validator(mode="after")
    def _scope(self) -> "EconomicsSpec":
        bad = [c for c in self.scope if c not in CATEGORIES]
        if bad:
            raise ValueError(f"scope {bad} desconocido; categorías: {list(CATEGORIES)}")
        return self

    def economic_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]

    def all_money(self) -> list[tuple[str, Money]]:
        out: list[tuple[str, Money]] = []
        out += [(f"labor.{i}", x.rate) for i, x in enumerate(self.labor)]
        out += [(f"machine.{i}", x.rate) for i, x in enumerate(self.machine)]
        if self.energy:
            out.append(("energy.price", self.energy.price))
        for cat in ("material", "scrap", "revenue"):
            out += [(f"{cat}.{i}", x.rate) for i, x in enumerate(getattr(self, cat))]
        out += [(f"maintenance.{i}", x.rate) for i, x in enumerate(self.maintenance)]
        out += [(f"downtime.{i}", x.rate) for i, x in enumerate(self.downtime)]
        out += [(f"capex.{i}", x.amount) for i, x in enumerate(self.capex)]
        return out
