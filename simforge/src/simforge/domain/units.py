"""Minimal, strict unit system.

Why not Pint? We only need a handful of dimensions (time, length, speed, rate,
money, power). A small explicit table gives clear error messages, trivial
(de)serialisation and zero surprises. The engine works internally in SI base
units (seconds, metres); conversion happens once, at the model boundary.
"""

from __future__ import annotations

from enum import Enum


class Dimension(str, Enum):
    TIME = "time"
    LENGTH = "length"
    SPEED = "speed"
    RATE = "rate"  # units per time
    POWER = "power"
    DIMENSIONLESS = "dimensionless"


# unit -> (dimension, factor to SI base unit)
_UNITS: dict[str, tuple[Dimension, float]] = {
    # time -> seconds
    "s": (Dimension.TIME, 1.0),
    "second": (Dimension.TIME, 1.0),
    "seconds": (Dimension.TIME, 1.0),
    "min": (Dimension.TIME, 60.0),
    "minute": (Dimension.TIME, 60.0),
    "minutes": (Dimension.TIME, 60.0),
    "h": (Dimension.TIME, 3600.0),
    "hour": (Dimension.TIME, 3600.0),
    "hours": (Dimension.TIME, 3600.0),
    "day": (Dimension.TIME, 86400.0),
    "days": (Dimension.TIME, 86400.0),
    # length -> metres
    "m": (Dimension.LENGTH, 1.0),
    "cm": (Dimension.LENGTH, 0.01),
    "mm": (Dimension.LENGTH, 0.001),
    # speed -> m/s
    "m/s": (Dimension.SPEED, 1.0),
    "m/min": (Dimension.SPEED, 1 / 60.0),
    "km/h": (Dimension.SPEED, 1000 / 3600.0),
    # rate -> units per second
    "1/s": (Dimension.RATE, 1.0),
    "1/min": (Dimension.RATE, 1 / 60.0),
    "1/h": (Dimension.RATE, 1 / 3600.0),
    "units/h": (Dimension.RATE, 1 / 3600.0),
    "units/day": (Dimension.RATE, 1 / 86400.0),
    # power -> W
    "W": (Dimension.POWER, 1.0),
    "kW": (Dimension.POWER, 1000.0),
    # dimensionless
    "": (Dimension.DIMENSIONLESS, 1.0),
    "%": (Dimension.DIMENSIONLESS, 0.01),
}

TIME_UNITS = sorted(u for u, (d, _) in _UNITS.items() if d is Dimension.TIME)


class UnitError(ValueError):
    pass


def dimension_of(unit: str) -> Dimension:
    try:
        return _UNITS[unit][0]
    except KeyError:
        known = ", ".join(sorted(k for k in _UNITS if k))
        raise UnitError(f"Unidad desconocida '{unit}'. Unidades válidas: {known}") from None


def to_base(value: float, unit: str, expected: Dimension | None = None) -> float:
    """Convert value to the SI base unit of its dimension."""
    dim, factor = _UNITS.get(unit, (None, None))  # type: ignore[assignment]
    if dim is None:
        dimension_of(unit)  # raises with a helpful message
    if expected is not None and dim is not expected:
        raise UnitError(f"Se esperaba una unidad de {expected.value} pero se recibió '{unit}' ({dim.value}).")
    return value * factor


def from_base(value: float, unit: str) -> float:
    dim, factor = _UNITS[unit]
    return value / factor


def seconds(value: float, unit: str) -> float:
    return to_base(value, unit, Dimension.TIME)
