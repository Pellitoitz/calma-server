"""ISMS - Industrial Simulation Model Specification (v0.1).

Engine-independent description of a production system. It is the SINGLE
SOURCE OF TRUTH: the chat, the UI and the CLI all read and modify this object;
adapters (the SimPy engine today, AnyLogic/visualisers tomorrow) consume it.

Design rule: ISMS v0.1 only contains what the engine actually executes.
Anything the engine would silently ignore is a hallucination vector, so
unsupported concepts are added to the schema only together with their
implementation (see docs/domain_model.md for the roadmap of extensions).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .behaviors import ResourceUse
from .units import Dimension
from .values import Provenance, Quantity

ISMS_VERSION = "0.1"

_ID_HELP = "lowercase letters, digits and '_' (e.g. 'selective_1')"


def _check_id(v: str) -> str:
    import re

    if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
        raise ValueError(f"id inválido '{v}': usar {_ID_HELP}")
    return v


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _HasId(_Strict):
    id: str

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check_id(v)


class ModelMeta(_Strict):
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    domain: str | None = None  # e.g. "electronics", "automotive"


class SimulationSettings(_Strict):
    horizon: Quantity = Field(default_factory=lambda: Quantity(value=8, unit="h"))
    warmup: Quantity = Field(default_factory=lambda: Quantity(value=0, unit="s"))
    kind: Literal["terminating", "steady_state"] = "terminating"
    replications: int = Field(default=1, ge=1, le=1000)
    base_seed: int = 12345
    trace: bool = False  # event log + operator decision log (debug mode)

    @field_validator("horizon", "warmup")
    @classmethod
    def _time(cls, q: Quantity) -> Quantity:
        q.to_base(Dimension.TIME)
        if q.value < 0:
            raise ValueError("el tiempo no puede ser negativo")
        return q


class EntityType(_HasId):
    name: str
    description: str = ""


class ResourceKind(str, Enum):
    OPERATOR = "operator"  # people; can walk between nodes
    CARRIER = "carrier"  # racks, pallets, fixtures, kanban cards: held across several nodes
    TOOL = "tool"  # shared equipment / tooling held during processing


class DispatchRule(str, Enum):
    FIFO = "fifo"  # first request first served
    PRIORITY = "priority"  # lowest node.priority first, FIFO tie-break
    WIP_TARGET = "wip_target"  # WIP_TARGET_PRIORITY: keep a protected node fed (see WipTargetParams)


class WipTargetParams(_Strict):
    """WIP_TARGET_PRIORITY dispatching (reusable, process-agnostic).

    The resource serves FEEDER tasks while the WIP available to feed the PROTECTED node is below
    `target`; otherwise it serves the other tasks (e.g. review). Rules, in order:
      1. protected node BLOCKED (its output is full) and a downstream task waits -> downstream task
         (otherwise the resource itself would starve the protected node through blocking);
      2. feed WIP < target and a feeder task waits -> feeder task;
      3. feed WIP >= target -> non-feeder task if one waits, else feeder;
      FIFO among tasks of the same class.
    Re-evaluation while busy: if `preempt_below` is set and feed WIP drops below it while a unit is
    working on a non-feeder task and a feeder task waits, that task is suspended (remaining work kept)
    and the unit switches to the feeder task.
    """

    protected_node: str
    feed_nodes: list[str] = Field(min_length=1, description="nodes whose content is WIP ready to feed the protected node")
    feeder_nodes: list[str] = Field(min_length=1, description="tasks that create feed WIP (e.g. assembly)")
    target: int | str | None = Field(default=None, description="REQUIRED. units; may be an expression like '$wip_target'")
    count_feeder_in_process: bool = True  # units being worked on at feeder tasks count as feed WIP
    preempt_below: int | str | None = None  # None = no pre-emption (non-preemptive re-evaluation at each decision)


class Travel(_Strict):
    speed: Quantity  # m/s, m/min, km/h
    metric: Literal["euclidean", "manhattan"] = "euclidean"

    @field_validator("speed")
    @classmethod
    def _speed(cls, q: Quantity) -> Quantity:
        q.to_base(Dimension.SPEED)
        if q.value <= 0:
            raise ValueError("la velocidad debe ser > 0")
        return q


class Resource(_HasId):
    name: str = ""
    kind: ResourceKind = ResourceKind.OPERATOR
    quantity: int | str = Field(default=1, description="int >= 0 or expression, e.g. '$n_operators'")
    dispatch: DispatchRule = DispatchRule.FIFO
    wip_target: WipTargetParams | None = None  # required when dispatch = wip_target
    travel: Travel | None = None  # only meaningful for operators with node positions
    home: str | None = None  # node id where the operator starts
    cost_per_hour: float | None = Field(default=None, ge=0)  # economics layer only
    provenance: Provenance | None = None


class Position(_Strict):
    x: float  # metres
    y: float = 0.0


class Node(_HasId):
    name: str = ""
    component: str  # library component id, e.g. "machine", "selective_soldering"
    component_version: str | None = None  # pinned on save for reproducibility
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0  # for PRIORITY dispatching of shared resources (lower = more urgent)
    seize: list[ResourceUse] = Field(default_factory=list)  # carriers acquired before processing, kept downstream
    release: list[str] = Field(default_factory=list)  # carriers released after processing here
    release_via: dict[str, str] = Field(default_factory=dict)  # carrier -> transport node that returns it (empty trip)
    position: Position | None = None
    notes: str = ""


class Edge(_Strict):
    source: str
    target: str
    probability: float | str | None = Field(default=None, description="0<p<=1 or expression, e.g. '$branch2_share'")

    @field_validator("probability")
    @classmethod
    def _p(cls, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not 0 < v <= 1:
            raise ValueError("la probabilidad debe estar en (0, 1]")
        return v


class ModelParameter(_HasId):
    """Named, traceable model parameter. Referenced anywhere as '$id' (e.g. process-time multipliers,
    routing shares, capacities). value = None means REQUIRED and not yet provided (model INCOMPLETE)."""

    value: float | None = None
    unit: str = ""
    description: str = ""
    role: Literal["fixed", "decision_variable", "uncertain"] = "fixed"
    min: float | None = None
    max: float | None = None
    provenance: Provenance | None = None


class Assumption(_Strict):
    id: str
    text: str
    path: str | None = None  # parameter path it affects
    origin: Literal["ai", "library_default", "engineer", "system"] = "system"
    accepted: bool = False  # engineer explicitly accepted it


class MissingInfo(_Strict):
    question: str
    path: str | None = None
    required: bool = True


class Approval(_Strict):
    approved: bool = False
    by: str | None = None
    at: datetime | None = None
    model_hash: str | None = None  # approval is only valid for this exact content
    note: str = ""


class Factor(_Strict):
    path: str  # e.g. "nodes.buffer_1.params.capacity" or "resources.racks.quantity"
    values: list[Any] = Field(min_length=1)
    label: str | None = None


class ExperimentSpec(_Strict):
    name: str = "experiment"
    factors: list[Factor] = Field(min_length=1)
    replications: int | None = Field(default=None, ge=1)  # None -> simulation.replications
    max_scenarios: int = Field(default=500, ge=1)


class ISMSModel(_Strict):
    isms_version: str = ISMS_VERSION
    meta: ModelMeta
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)
    entities: list[EntityType] = Field(default_factory=lambda: [EntityType(id="unit", name="Unit")])
    parameters: list[ModelParameter] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    missing: list[MissingInfo] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)
    experiments: list[ExperimentSpec] = Field(default_factory=list)

    # ---------------- helpers ----------------
    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"El nodo '{node_id}' no existe en el modelo.")

    def resource(self, res_id: str) -> Resource:
        for r in self.resources:
            if r.id == res_id:
                return r
        raise KeyError(f"El recurso '{res_id}' no existe en el modelo.")

    def successors(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def predecessors(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def content_hash(self) -> str:
        """Hash of everything that affects simulation behaviour (not meta/approval/notes)."""
        d = self.model_dump(mode="json", exclude={"approval": True, "meta": True, "assumptions": True, "missing": True, "experiments": True})
        blob = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @property
    def is_approved(self) -> bool:
        return self.approval.approved and self.approval.model_hash == self.content_hash()
