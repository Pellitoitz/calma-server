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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from .units import Dimension, UnitError, dimension_of, to_base


class ValueStatus(str, Enum):
    MEASURED = "measured"
    PROVIDED_BY_CLIENT = "provided_by_client"
    ESTIMATED = "estimated"
    ASSUMED = "assumed"
    CALCULATED = "calculated"
    IMPORTED = "imported"
    DEFAULT = "default"  # library default, never confirmed by anyone


class DataLink(BaseModel):
    """Where a value derived from imported data comes from (dataset + engineer decision). See simforge.data."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    dataset_version: int
    content_hash: str  # hash of the imported observations (the file may change later; this does not)
    source_file: str
    column: str
    original_unit: str
    basis: str  # PER_CIRCUIT, PER_RACK, ... (never converted silently)
    n_used: int
    n_excluded: int = 0
    decision: Literal["DETERMINISTIC", "EMPIRICAL", "FITTED"]
    derivation: str | None = None  # DETERMINISTIC: MEAN | MEDIAN | ENGINEER_VALUE
    fit_id: str | None = None
    fit_summary: str | None = None
    parameter_sources: dict | None = None  # per parameter: ESTIMATED_FROM_DATA / CALCULATED_BOUNDS / ENGINEER_BOUNDS...
    conversion: dict | None = None  # explicit basis/unit conversion: {"formula": ..., "inputs": {...}}
    decided_by: str
    decided_at: datetime


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValueStatus = ValueStatus.PROVIDED_BY_CLIENT
    source: str | None = None  # e.g. "time_study_2026_09_20.xlsx", "user_chat"
    note: str | None = None
    timestamp: datetime | None = None
    data: DataLink | None = None  # only for values derived from an imported dataset

    @model_serializer(mode="wrap")
    def _omit_empty_link(self, handler):
        # 'data' is serialised only when present, so models saved before it existed keep their content hash
        d = handler(self)
        if isinstance(d, dict) and d.get("data") is None:
            d.pop("data", None)
        return d

    @classmethod
    def assumed(cls, note: str) -> "Provenance":
        return cls(status=ValueStatus.ASSUMED, note=note, timestamp=datetime.now(timezone.utc))


class Quantity(BaseModel):
    """A scalar with a unit, e.g. {"value": 8, "unit": "h"}."""

    model_config = ConfigDict(extra="forbid")

    value: float | str  # str only for parameter expressions ('$operator_speed'), resolved before simulation
    unit: str
    provenance: Provenance | None = None

    @field_validator("value")
    @classmethod
    def _expr(cls, v):
        if isinstance(v, str) and "$" not in v:
            raise ValueError(f"valor no numérico '{v}' (sólo se admiten expresiones con $parametro)")
        return v

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


class NegativeSampleError(ValueError):
    """A duration distribution produced a negative value and no explicit truncation was declared."""


class Truncation(BaseModel):
    """EXPLICIT truncation of a duration distribution (rejection sampling inside [lower, upper], in the
    distribution's unit). Never applied implicitly: it changes the distribution and is part of its provenance."""

    model_config = ConfigDict(extra="forbid")

    lower: float | None = Field(default=None, ge=0)
    upper: float | None = None
    reason: str = Field(min_length=3)
    # PHYSICAL_BOUND: the process physically cannot go beyond it ("never under 8 s").
    # MODELLING_BOUND: a modelling device (e.g. a normal truncated at 0 to avoid impossible times).
    bound_type: Literal["PHYSICAL_BOUND", "MODELLING_BOUND"]
    # DECLARED: written by the engineer. FIT_THEN_TRUNCATE: parameters were fitted WITHOUT truncation and the fitted
    # distribution was truncated afterwards (NOT a truncated-distribution fit; that method is not implemented).
    method: Literal["DECLARED", "FIT_THEN_TRUNCATE"] = "DECLARED"
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _bounds(self) -> "Truncation":
        if self.lower is None and self.upper is None:
            raise ValueError("truncation needs a lower and/or an upper bound")
        if self.lower is not None and self.upper is not None and self.upper <= self.lower:
            raise ValueError(f"truncation: upper ({self.upper}) <= lower ({self.lower})")
        return self


_MAX_REJECTIONS = 10_000


class _Dist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = "s"
    provenance: Provenance | None = None
    truncation: Truncation | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_truncation(self, handler):
        d = handler(self)
        if isinstance(d, dict) and d.get("truncation") is None:
            d.pop("truncation", None)  # keeps content hashes of models saved before truncation existed
        return d

    @field_validator("unit")
    @classmethod
    def _unit_is_time(cls, v: str) -> str:
        return _time_unit(v)

    @property
    def _k(self) -> float:
        return to_base(1.0, self.unit, Dimension.TIME)

    # ---- implemented by subclasses, in the distribution's own unit ----
    def _raw(self, rng: random.Random) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def _mean(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError

    def scipy(self):
        """Frozen scipy.stats distribution in the distribution's unit (requires the optional 'data' extra)."""
        raise NotImplementedError(f"{type(self).__name__}: no scipy equivalent")

    # ---- common behaviour ----
    def sample_seconds(self, rng: random.Random) -> float:
        t = self.truncation
        if t is None:
            x = self._raw(rng)
            if x < 0:
                raise NegativeSampleError(f"{self.describe()} produced {x:.4g} < 0 and has no explicit truncation")
            return x * self._k
        lo = t.lower if t.lower is not None else -math.inf
        hi = t.upper if t.upper is not None else math.inf
        for _ in range(_MAX_REJECTIONS):
            x = self._raw(rng)
            if lo <= x <= hi:
                if x < 0:
                    raise NegativeSampleError(f"{self.describe()}: truncation window allows negative durations")
                return x * self._k
        raise ValueError(f"{self.describe()}: truncation [{t.lower}, {t.upper}] has (almost) zero probability")

    def mean_seconds(self) -> float:
        if self.truncation is None:
            return self._mean() * self._k
        return self._truncated_mean() * self._k

    def _truncated_mean(self) -> float:
        t = self.truncation
        lo = t.lower if t.lower is not None else -math.inf
        hi = t.upper if t.upper is not None else math.inf
        try:
            d = self.scipy()
            return float(d.expect(lambda x: x, lb=lo, ub=hi, conditional=True))
        except (ImportError, NotImplementedError):
            r = random.Random(20260101)  # deterministic fallback without scipy
            xs = [x for x in (self._raw(r) for _ in range(200_000)) if lo <= x <= hi]
            return sum(xs) / len(xs)

    @property
    def is_deterministic(self) -> bool:
        return False

    def describe(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def _trunc_txt(self) -> str:
        t = self.truncation
        return "" if t is None else f" truncated[{'' if t.lower is None else f'{t.lower:g}'},{'' if t.upper is None else f'{t.upper:g}'}]"


class Constant(_Dist):
    dist: Literal["constant"] = "constant"
    value: float = Field(ge=0)

    def _mean(self) -> float:
        return self.value

    def _raw(self, rng: random.Random) -> float:
        return self.value

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

    def _mean(self) -> float:
        return (self.low + self.high) / 2

    def _raw(self, rng: random.Random) -> float:
        return rng.uniform(self.low, self.high)

    def scipy(self):
        from scipy import stats
        return stats.uniform(loc=self.low, scale=self.high - self.low)

    def describe(self) -> str:
        return f"U({self.low:g}, {self.high:g}) {self.unit}{self._trunc_txt()}"


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

    def _mean(self) -> float:
        return (self.low + self.mode + self.high) / 3

    def _raw(self, rng: random.Random) -> float:
        return rng.triangular(self.low, self.high, self.mode)

    def scipy(self):
        from scipy import stats
        w = self.high - self.low
        return stats.triang(c=(self.mode - self.low) / w if w else 0.5, loc=self.low, scale=w or 1e-12)

    def describe(self) -> str:
        return f"Tri({self.low:g}, {self.mode:g}, {self.high:g}) {self.unit}{self._trunc_txt()}"


class Normal(_Dist):
    """Normal duration. If its mass below 0 is not negligible (> 1e-9), an EXPLICIT truncation is required
    (engine >= 0.4.0; before, negatives were silently re-sampled)."""

    dist: Literal["normal"] = "normal"
    mean: float = Field(gt=0)
    std: float = Field(ge=0)

    @model_validator(mode="after")
    def _negative_mass(self) -> "Normal":
        p_neg = self.p_negative()
        lower_ok = self.truncation is not None and self.truncation.lower is not None and self.truncation.lower >= 0
        if p_neg > 1e-9 and not lower_ok:
            raise ValueError(f"normal N({self.mean:g}, {self.std:g}) gives P(t < 0) = {p_neg:.2g}: durations cannot be negative. "
                             "Use a positive distribution (lognormal, gamma, weibull) or declare an explicit truncation, "
                             "e.g. truncation: {lower: 0, reason: '...', bound_type: MODELLING_BOUND}")
        return self

    def p_negative(self) -> float:
        if self.std == 0:
            return 0.0
        return 0.5 * math.erfc(self.mean / (self.std * math.sqrt(2)))

    def _mean(self) -> float:
        return self.mean

    def _raw(self, rng: random.Random) -> float:
        return rng.gauss(self.mean, self.std)

    def scipy(self):
        from scipy import stats
        return stats.norm(loc=self.mean, scale=self.std)

    def describe(self) -> str:
        return f"N({self.mean:g}, {self.std:g}) {self.unit}{self._trunc_txt()}"


class LogNormal(_Dist):
    """Parameterised by the mean and std of the variable itself (not of log)."""

    dist: Literal["lognormal"] = "lognormal"
    mean: float = Field(gt=0)
    std: float = Field(gt=0)

    def _mu_sigma(self) -> tuple[float, float]:
        s2 = math.log(1 + (self.std / self.mean) ** 2)
        return math.log(self.mean) - s2 / 2, math.sqrt(s2)

    def _mean(self) -> float:
        return self.mean

    def _raw(self, rng: random.Random) -> float:
        mu, sigma = self._mu_sigma()
        return rng.lognormvariate(mu, sigma)

    def scipy(self):
        from scipy import stats
        mu, sigma = self._mu_sigma()
        return stats.lognorm(s=sigma, scale=math.exp(mu))

    def describe(self) -> str:
        return f"LogN(mean={self.mean:g}, sd={self.std:g}) {self.unit}{self._trunc_txt()}"


class Exponential(_Dist):
    dist: Literal["exponential"] = "exponential"
    mean: float = Field(gt=0)

    def _mean(self) -> float:
        return self.mean

    def _raw(self, rng: random.Random) -> float:
        return rng.expovariate(1.0 / self.mean)

    def scipy(self):
        from scipy import stats
        return stats.expon(scale=self.mean)

    def describe(self) -> str:
        return f"Exp(mean={self.mean:g}) {self.unit}{self._trunc_txt()}"


class Gamma(_Dist):
    """Gamma(shape k, scale theta), in `unit`. Mean = k * theta."""

    dist: Literal["gamma"] = "gamma"
    shape: float = Field(gt=0)
    scale: float = Field(gt=0)

    def _mean(self) -> float:
        return self.shape * self.scale

    def _raw(self, rng: random.Random) -> float:
        return rng.gammavariate(self.shape, self.scale)

    def scipy(self):
        from scipy import stats
        return stats.gamma(a=self.shape, scale=self.scale)

    def describe(self) -> str:
        return f"Gamma(k={self.shape:.4g}, θ={self.scale:.4g}) {self.unit}{self._trunc_txt()}"


class Weibull(_Dist):
    """Weibull(shape k, scale lambda), in `unit`. Mean = lambda * Gamma(1 + 1/k)."""

    dist: Literal["weibull"] = "weibull"
    shape: float = Field(gt=0)
    scale: float = Field(gt=0)

    def _mean(self) -> float:
        return self.scale * math.gamma(1 + 1 / self.shape)

    def _raw(self, rng: random.Random) -> float:
        return rng.weibullvariate(self.scale, self.shape)

    def scipy(self):
        from scipy import stats
        return stats.weibull_min(c=self.shape, scale=self.scale)

    def describe(self) -> str:
        return f"Weibull(k={self.shape:.4g}, λ={self.scale:.4g}) {self.unit}{self._trunc_txt()}"


class Empirical(_Dist):
    """Resamples uniformly from observed values (e.g. a time study)."""

    dist: Literal["empirical"] = "empirical"
    values: list[Annotated[float, Field(ge=0)]] = Field(min_length=1)

    def _mean(self) -> float:
        return sum(self.values) / len(self.values)

    def _raw(self, rng: random.Random) -> float:
        return rng.choice(self.values)

    @property
    def is_deterministic(self) -> bool:
        return len(set(self.values)) == 1

    def describe(self) -> str:
        return f"Empirical(n={len(self.values)}, mean={self._mean():.3g}) {self.unit}{self._trunc_txt()}"


Duration = Annotated[
    Union[Constant, Uniform, Triangular, Normal, LogNormal, Exponential, Gamma, Weibull, Empirical],
    Field(discriminator="dist"),
]

DISTRIBUTION_TYPES = ["constant", "uniform", "triangular", "normal", "lognormal", "exponential", "gamma", "weibull", "empirical"]


def const(value: float, unit: str = "s", provenance: Provenance | None = None) -> Constant:
    return Constant(value=value, unit=unit, provenance=provenance)
