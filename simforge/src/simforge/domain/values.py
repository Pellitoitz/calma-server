"""Traceable values: quantities, provenance and statistical distributions.

Every number that drives the simulation can carry *where it came from*
(``provenance``). Distributions validate their own parameters and can never
produce negative durations.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .units import Dimension, UnitError, dimension_of, to_base


class ValueStatus(str, Enum):
    MEASURED = "measured"
    PROVIDED_BY_CLIENT = "provided_by_client"
    ESTIMATED = "estimated"
    ASSUMED = "assumed"
    CALCULATED = "calculated"
    IMPORTED = "imported"
    DEFAULT = "default"  # library default, never confirmed by anyone


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValueStatus = ValueStatus.PROVIDED_BY_CLIENT
    source: str | None = None  # e.g. "time_study_2026_09_20.xlsx", "user_chat"
    note: str | None = None
    timestamp: datetime | None = None

    @classmethod
    def assumed(cls, note: str) -> "Provenance":
        return cls(status=ValueStatus.ASSUMED, note=note, timestamp=datetime.now(timezone.utc))


class Quantity(BaseModel):
    """A scalar with a unit, e.g. {"value": 8, "unit": "h"}."""

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    provenance: Provenance | None = None

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, v: str) -> str:
        dimension_of(v)
        return v

    def to_base(self, expected: Dimension | None = None) -> float:
        return to_base(self.value, self.unit, expected)

    def seconds(self) -> float:
        return self.to_base(Dimension.TIME)


def _time_unit(v: str) -> str:
    if dimension_of(v) is not Dimension.TIME:
        raise UnitError(f"'{v}' no es una unidad de tiempo")
    return v


# --------------------------------------------------------------------------
# Distributions (all durations). Parameters are expressed in `unit`.
# --------------------------------------------------------------------------


class _Dist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = "s"
    provenance: Provenance | None = None

    @field_validator("unit")
    @classmethod
    def _unit_is_time(cls, v: str) -> str:
        return _time_unit(v)

    @property
    def _k(self) -> float:
        return to_base(1.0, self.unit, Dimension.TIME)

    # Subclasses implement these in *base seconds*.
    def mean_seconds(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def sample_seconds(self, rng: random.Random) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def is_deterministic(self) -> bool:
        return False

    def describe(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class Constant(_Dist):
    dist: Literal["constant"] = "constant"
    value: float = Field(ge=0)

    def mean_seconds(self) -> float:
        return self.value * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        return self.value * self._k

    @property
    def is_deterministic(self) -> bool:
        return True

    def describe(self) -> str:
        return f"{self.value:g} {self.unit}"


class Uniform(_Dist):
    dist: Literal["uniform"] = "uniform"
    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def _order(self) -> "Uniform":
        if self.high < self.low:
            raise ValueError(f"uniform: high ({self.high}) < low ({self.low})")
        return self

    def mean_seconds(self) -> float:
        return (self.low + self.high) / 2 * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        return rng.uniform(self.low, self.high) * self._k

    def describe(self) -> str:
        return f"U({self.low:g}, {self.high:g}) {self.unit}"


class Triangular(_Dist):
    dist: Literal["triangular"] = "triangular"
    low: float = Field(ge=0)
    mode: float = Field(ge=0)
    high: float = Field(ge=0)

    @model_validator(mode="after")
    def _order(self) -> "Triangular":
        if not (self.low <= self.mode <= self.high):
            raise ValueError(f"triangular: se requiere low <= mode <= high (recibido {self.low}, {self.mode}, {self.high})")
        return self

    def mean_seconds(self) -> float:
        return (self.low + self.mode + self.high) / 3 * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        return rng.triangular(self.low, self.high, self.mode) * self._k

    def describe(self) -> str:
        return f"Tri({self.low:g}, {self.mode:g}, {self.high:g}) {self.unit}"


class Normal(_Dist):
    """Normal truncated at 0 by resampling (never negative times)."""

    dist: Literal["normal"] = "normal"
    mean: float = Field(gt=0)
    std: float = Field(ge=0)

    def mean_seconds(self) -> float:
        return self.mean * self._k  # truncation effect ignored (flagged by verifier if relevant)

    def sample_seconds(self, rng: random.Random) -> float:
        for _ in range(1000):
            x = rng.gauss(self.mean, self.std)
            if x >= 0:
                return x * self._k
        return 0.0

    def describe(self) -> str:
        return f"N({self.mean:g}, {self.std:g}) {self.unit}"


class LogNormal(_Dist):
    """Parameterised by the mean and std of the variable itself (not of log)."""

    dist: Literal["lognormal"] = "lognormal"
    mean: float = Field(gt=0)
    std: float = Field(gt=0)

    def _mu_sigma(self) -> tuple[float, float]:
        s2 = math.log(1 + (self.std / self.mean) ** 2)
        return math.log(self.mean) - s2 / 2, math.sqrt(s2)

    def mean_seconds(self) -> float:
        return self.mean * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        mu, sigma = self._mu_sigma()
        return rng.lognormvariate(mu, sigma) * self._k

    def describe(self) -> str:
        return f"LogN(mean={self.mean:g}, sd={self.std:g}) {self.unit}"


class Exponential(_Dist):
    dist: Literal["exponential"] = "exponential"
    mean: float = Field(gt=0)

    def mean_seconds(self) -> float:
        return self.mean * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        return rng.expovariate(1.0 / self.mean) * self._k

    def describe(self) -> str:
        return f"Exp(mean={self.mean:g}) {self.unit}"


class Empirical(_Dist):
    """Resamples uniformly from observed values (e.g. a time study)."""

    dist: Literal["empirical"] = "empirical"
    values: list[Annotated[float, Field(ge=0)]] = Field(min_length=1)

    def mean_seconds(self) -> float:
        return sum(self.values) / len(self.values) * self._k

    def sample_seconds(self, rng: random.Random) -> float:
        return rng.choice(self.values) * self._k

    @property
    def is_deterministic(self) -> bool:
        return len(set(self.values)) == 1

    def describe(self) -> str:
        return f"Empirical(n={len(self.values)}, mean={self.mean_seconds() / self._k:.3g}) {self.unit}"


Duration = Annotated[
    Union[Constant, Uniform, Triangular, Normal, LogNormal, Exponential, Empirical],
    Field(discriminator="dist"),
]

DISTRIBUTION_TYPES = ["constant", "uniform", "triangular", "normal", "lognormal", "exponential", "empirical"]


def const(value: float, unit: str = "s", provenance: Provenance | None = None) -> Constant:
    return Constant(value=value, unit=unit, provenance=provenance)
