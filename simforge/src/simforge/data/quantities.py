"""What a measured column IS: quantity type, physical dimension, basis, and where (if anywhere) the engine can use it.

Two independent notions:
  DATA_IMPORT_SUPPORTED            the data can be imported, cleaned, described and fitted
  SIMULATION_USE_NOT_YET_SUPPORTED the engine has no parameter that can consume it (yet) -> it can never be applied
"""

from __future__ import annotations

import re
from enum import Enum

from ..domain.units import Dimension, UnitError, dimension_of, to_base


class QuantityType(str, Enum):
    PROCESSING_TIME = "PROCESSING_TIME"
    TRANSPORT_TIME = "TRANSPORT_TIME"
    LOAD_TIME = "LOAD_TIME"  # extension: handling time at the start of a transport trip
    UNLOAD_TIME = "UNLOAD_TIME"  # extension: handling time at the end of a transport trip
    DISTANCE = "DISTANCE"
    ARRIVAL_INTERVAL = "ARRIVAL_INTERVAL"
    SETUP_TIME = "SETUP_TIME"
    REPAIR_TIME = "REPAIR_TIME"
    FAILURE_INTERVAL = "FAILURE_INTERVAL"


class Basis(str, Enum):
    """What ONE observation refers to. Never converted silently (see apply.py: explicit CALCULATED conversion)."""

    PER_CIRCUIT = "PER_CIRCUIT"
    PER_RACK = "PER_RACK"
    PER_PANEL = "PER_PANEL"
    PER_UNIT = "PER_UNIT"
    PER_BATCH = "PER_BATCH"
    PER_CYCLE = "PER_CYCLE"
    PER_OPERATION = "PER_OPERATION"
    PER_TRIP = "PER_TRIP"  # extension for transport handling times
    UNKNOWN = "UNKNOWN"


# quantity -> (dimension, engine targets as path templates relative to a node, accepts distributions, note)
# A target template "{node}.params.process_time" is filled with a node id by the apply step.
SUPPORT: dict[QuantityType, dict] = {
    QuantityType.PROCESSING_TIME: {"dimension": Dimension.TIME, "targets": ["params.process_time"], "distributions": True,
                                   "behaviors": ["server"], "note": "time per entity, or per work unit if the node has work_units != 1"},
    QuantityType.LOAD_TIME: {"dimension": Dimension.TIME, "targets": ["params.load_time"], "distributions": True,
                             "behaviors": ["transport"], "note": "per trip"},
    QuantityType.UNLOAD_TIME: {"dimension": Dimension.TIME, "targets": ["params.unload_time"], "distributions": True,
                               "behaviors": ["transport"], "note": "per trip"},
    QuantityType.ARRIVAL_INTERVAL: {"dimension": Dimension.TIME, "targets": ["params.interarrival"], "distributions": True,
                                    "behaviors": ["source"], "note": "source must use arrival: interarrival"},
    QuantityType.REPAIR_TIME: {"dimension": Dimension.TIME, "targets": ["params.failures.mttr"], "distributions": True,
                               "behaviors": ["server"], "note": "the node must already declare failures"},
    QuantityType.FAILURE_INTERVAL: {"dimension": Dimension.TIME, "targets": ["params.failures.mtbf"], "distributions": True,
                                    "behaviors": ["server"], "note": "calendar time between failures; the node must already declare failures"},
    QuantityType.DISTANCE: {"dimension": Dimension.LENGTH, "targets": ["params.distance"], "distributions": False,
                            "behaviors": ["transport"],
                            "note": "the engine takes a single distance (Quantity): only a DETERMINISTIC value can be applied"},
    QuantityType.TRANSPORT_TIME: {"dimension": Dimension.TIME, "targets": [], "distributions": False, "behaviors": [],
                                  "note": "the engine computes travel time from distance/speed + load/unload; a measured "
                                          "door-to-door time cannot replace it. Split it (LOAD_TIME/UNLOAD_TIME/DISTANCE) instead"},
    QuantityType.SETUP_TIME: {"dimension": Dimension.TIME, "targets": [], "distributions": False, "behaviors": [],
                              "note": "setups / product changeovers are not modelled by the engine"},
}


def simulation_support(q: QuantityType) -> str:
    return "SIMULATION_USE_SUPPORTED" if SUPPORT[q]["targets"] else "SIMULATION_USE_NOT_YET_SUPPORTED"


def support_table() -> list[dict]:
    return [{"quantity": q.value, "dimension": s["dimension"].value, "data_import": "DATA_IMPORT_SUPPORTED",
             "simulation": simulation_support(q), "distributions_in_engine": s["distributions"] and bool(s["targets"]),
             "targets": s["targets"], "note": s["note"]} for q, s in SUPPORT.items()]


UNKNOWN_UNIT = "UNKNOWN"


def base_unit(dim: Dimension) -> str:
    return {Dimension.TIME: "s", Dimension.LENGTH: "m"}[dim]


# aliases accepted in unit columns / headers; anything else must be a known simforge unit or is rejected
UNIT_ALIASES = {"seg": "s", "sec": "s", "secs": "s", "segundos": "s", "segundo": "s", "seconds": "s", "second": "s",
                "mins": "min", "minutos": "min", "minuto": "min", "minutes": "min", "minute": "min",
                "horas": "h", "hora": "h", "hours": "h", "hour": "h", "hr": "h", "hrs": "h",
                "milisegundos": "ms", "milliseconds": "ms", "msec": "ms",
                "metros": "m", "metro": "m", "meters": "m", "metres": "m", "milimetros": "mm", "milímetros": "mm",
                "centimetros": "cm", "centímetros": "cm", "kilometros": "km", "kilómetros": "km"}


def normalize_unit(u: str, dim: Dimension) -> str:
    """Map a written unit to a simforge unit of the expected dimension; raises UnitError if unknown or wrong dimension.
    'm' is metres for LENGTH; for TIME 'm' is ambiguous (minutes? metres?) and is rejected."""
    key = u.strip().lower()
    if key == "unknown":
        return UNKNOWN_UNIT  # explicitly unknown: analysable, never applicable to a model
    if dim is Dimension.TIME and key == "m":
        raise UnitError("'m' es ambiguo para un tiempo (¿minutos?). Usa 'min'.")
    key = UNIT_ALIASES.get(key, key)
    d = dimension_of(key)
    if d is not dim:
        raise UnitError(f"'{u}' es una unidad de {d.value}, se esperaba {dim.value}")
    return key


def to_base_value(x: float, unit: str, dim: Dimension) -> float:
    return to_base(x, unit, dim)


_HEADER_UNIT = re.compile(r"[\(\[]\s*([A-Za-zµ\.]+)\s*[\)\]]\s*$")


def unit_from_header(header: str) -> str | None:
    """'tiempo (min)' -> 'min'. Only used as a SUGGESTION shown to the engineer, never applied silently."""
    m = _HEADER_UNIT.search(header or "")
    return m.group(1) if m else None
