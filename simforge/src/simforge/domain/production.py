"""Product mix, product-specific processing/routing and setups / changeovers (engine >= 0.7.0).

Extension block `production` of SimModel (domain/isms_ext.py). A model without it is a legacy model: one entity type,
no setups, same hash, same results, same random streams.

    production:
      products:                       # keys = ids of the ISMS `entities` (the ProductType of each entity)
        pcb_a: {setup_key: FAMILY_A}
        pcb_b: {setup_key: FAMILY_B}
      generation:                     # one entry per source: what each created entity is
        src: {mode: PROBABILISTIC_MIX, mix: {pcb_a: 0.6, pcb_b: 0.4}}
        # src: {mode: EXPLICIT_SEQUENCE, sequence: [pcb_a, pcb_a, pcb_b], repeat: false}
      routes:                         # optional; if present, EVERY product needs one (node sequence along edges)
        pcb_a: {nodes: [src, m1, m2, out]}
      processing:                     # node -> product -> time (replaces the node's process_time; never mixed)
        m1: {pcb_a: {dist: constant, value: 30, unit: s}, pcb_b: {dist: constant, value: 45, unit: s}}
      setups:                         # node -> changeover configuration
        m1:
          mode: SEQUENCE_DEPENDENT    # CONSTANT_CHANGEOVER | TARGET_DEPENDENT | SEQUENCE_DEPENDENT
          initial_state: FAMILY_A     # a setup key or UNCONFIGURED (explicit, never assumed)
          matrix: {FAMILY_A: {FAMILY_B: {dist: constant, value: 600, unit: s}}}
          from_unconfigured: {}       # UNCONFIGURED -> key times (required when initial_state = UNCONFIGURED)
          resources: [{resource: setup_tech}]   # only what is declared (never the processing operator implicitly)
          at_unavailability: PAUSE_RESUME       # required on calendar-gated nodes; independent of processing

Nothing is completed, normalised, mirrored or defaulted: a missing time, transition or route is an ERROR/MISSING.
SimForge represents a sequence; it never chooses or optimises one.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .behaviors import ResourceUse
from .values import Duration, Provenance

UNCONFIGURED = "UNCONFIGURED"
MIX_SUM_TOLERANCE = 1e-9  # |sum(mix) - 1| above this is an ERROR (never normalised)
SETUP_MODES = ("CONSTANT_CHANGEOVER", "TARGET_DEPENDENT", "SEQUENCE_DEPENDENT")
SETUP_POLICIES = ("FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART")
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_key(v: str) -> str:
    if not _KEY.fullmatch(v):
        raise ValueError(f"setup key inválida '{v}' (letras, dígitos, '_' o '-', empezando por letra)")
    if v == UNCONFIGURED:
        raise ValueError(f"'{UNCONFIGURED}' es un estado reservado de la máquina, no una setup key de producto")
    return v


class ProductSpec(_Strict):
    """Production attributes of a ProductType (the ISMS EntityType with the same id)."""

    setup_key: str | None = None  # setup family; products with the same key need no changeover between them
    provenance: Provenance | None = None

    @field_validator("setup_key")
    @classmethod
    def _key(cls, v):
        return None if v is None else _check_key(v)


class ProbabilisticMix(_Strict):
    mode: Literal["PROBABILISTIC_MIX"]
    mix: dict[str, float] = Field(min_length=1)  # product -> probability (sum must be 1; never normalised)
    provenance: Provenance | None = None


class ExplicitSequence(_Strict):
    mode: Literal["EXPLICIT_SEQUENCE"]
    sequence: list[str] = Field(min_length=1)  # product ids, in creation order
    repeat: bool = False  # False: the source stops after the last element; True: starts again from the first
    provenance: Provenance | None = None


Generation = Annotated[Union[ProbabilisticMix, ExplicitSequence], Field(discriminator="mode")]


class Route(_Strict):
    nodes: list[str] = Field(min_length=2)  # source ... sink, every consecutive pair must be an edge
    provenance: Provenance | None = None


class SetupSpec(_Strict):
    mode: Literal["CONSTANT_CHANGEOVER", "TARGET_DEPENDENT", "SEQUENCE_DEPENDENT"]
    initial_state: str  # setup key or UNCONFIGURED; REQUIRED
    constant: Duration | None = None  # CONSTANT_CHANGEOVER: any change of setup key
    by_target: dict[str, Duration] = Field(default_factory=dict)  # TARGET_DEPENDENT: -> key
    matrix: dict[str, dict[str, Duration]] = Field(default_factory=dict)  # SEQUENCE_DEPENDENT: from -> to (asymmetric)
    from_unconfigured: dict[str, Duration] = Field(default_factory=dict)  # UNCONFIGURED -> key (all modes)
    resources: list[ResourceUse] = Field(default_factory=list)  # held during the setup only
    at_unavailability: Literal["FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART"] | None = None
    provenance: Provenance | None = None

    @field_validator("initial_state")
    @classmethod
    def _initial(cls, v: str) -> str:
        return v if v == UNCONFIGURED else _check_key(v)

    @model_validator(mode="after")
    def _shape(self) -> "SetupSpec":
        if self.mode == "CONSTANT_CHANGEOVER":
            if self.constant is None:
                raise ValueError("CONSTANT_CHANGEOVER necesita 'constant'")
            if self.by_target or self.matrix:
                raise ValueError("CONSTANT_CHANGEOVER sólo admite 'constant' (y from_unconfigured)")
        elif self.mode == "TARGET_DEPENDENT":
            if self.constant is not None or self.matrix:
                raise ValueError("TARGET_DEPENDENT sólo admite 'by_target' (y from_unconfigured)")
        elif self.constant is not None or self.by_target:
            raise ValueError("SEQUENCE_DEPENDENT sólo admite 'matrix' (y from_unconfigured)")
        for k in [*self.by_target, *self.matrix, *self.from_unconfigured, *(t for row in self.matrix.values() for t in row)]:
            _check_key(k)
        ids = [r.resource for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("un mismo recurso aparece dos veces en setups.resources")
        return self

    def duration(self, frm: str, to: str) -> Duration | None:
        """Setup time for the change frm -> to (frm != to). None = not defined (never completed or defaulted)."""
        if frm == UNCONFIGURED:
            return self.from_unconfigured.get(to)
        if self.mode == "CONSTANT_CHANGEOVER":
            return self.constant
        if self.mode == "TARGET_DEPENDENT":
            return self.by_target.get(to)
        return self.matrix.get(frm, {}).get(to)

    def durations(self) -> list[Duration]:
        out = [self.constant] if self.constant is not None else []
        return out + list(self.by_target.values()) + [d for r in self.matrix.values() for d in r.values()] \
            + list(self.from_unconfigured.values())


class ProductionSpec(_Strict):
    products: dict[str, ProductSpec] = Field(min_length=1)
    generation: dict[str, Generation] = Field(default_factory=dict)  # source id -> generation
    routes: dict[str, Route] = Field(default_factory=dict)  # product -> route (all or none)
    processing: dict[str, dict[str, Duration]] = Field(default_factory=dict)  # node -> product -> time
    setups: dict[str, SetupSpec] = Field(default_factory=dict)  # node -> setup configuration

    def production_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]

    def produced_by(self, source: str) -> list[str]:
        """Products a source can create (sorted ids)."""
        g = self.generation.get(source)
        if g is None:
            return []
        if isinstance(g, ProbabilisticMix):
            return sorted(p for p, w in g.mix.items() if w > 0)
        return sorted(set(g.sequence))
