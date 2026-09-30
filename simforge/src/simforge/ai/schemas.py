"""Structured-output schemas for the AI layer.

The LLM never produces an ISMS model directly and never produces results.
It fills these small, strongly-typed drafts; deterministic code (compiler.py)
turns them into ISMS, checks every number against the user's text and
records assumptions/missing data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DraftTime(BaseModel):
    dist: Literal["constant", "uniform", "triangular", "normal", "lognormal", "exponential"] = "constant"
    value: float | None = None  # constant
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    mean: float | None = None
    std: float | None = None
    unit: Literal["s", "min", "h"] = "s"


class DraftResource(BaseModel):
    id: str = Field(description="snake_case id, e.g. operator_1, racks")
    name: str
    kind: Literal["operator", "carrier", "tool"] = "operator"
    quantity: int | None = Field(default=None, description="null if the text does not say how many")


class DraftStep(BaseModel):
    id: str = Field(description="snake_case id, unique")
    name: str
    component: str = Field(description="component id from the provided library catalog; 'buffer' for queues/buffers")
    time: DraftTime | None = Field(default=None, description="processing time; null if not stated (never invent)")
    capacity: int | None = Field(default=None, description="buffers: max units; stations: parallel slots. null if not stated")
    resources: list[str] = Field(default_factory=list, description="ids of resources (operators/tools) needed during the step")
    yield_rate: float | None = None


class DraftPolicy(BaseModel):
    resource: str
    rule: Literal["fifo", "priority"]
    priority_order: list[str] = Field(default_factory=list, description="step ids, most urgent first")


class DraftCarrierLoop(BaseModel):
    resource: str = Field(description="carrier resource id (racks, pallets...)")
    seize_at: str = Field(description="step id where a unit takes a carrier")
    release_at: str = Field(description="step id where the carrier is freed")


class DraftQuestion(BaseModel):
    question: str
    required: bool = True


class DraftExperiment(BaseModel):
    target: str = Field(description="what to vary, e.g. 'buffer capacity', 'racks', 'operators'")
    values: list[float]


class ProcessDraft(BaseModel):
    """Linear process description (steps in flow order). Branching is not supported by the V1 parser."""

    model_name: str
    horizon_value: float | None = None
    horizon_unit: Literal["s", "min", "h"] = "h"
    supply: Literal["infinite", "interarrival", "unknown"] = "unknown"
    interarrival: DraftTime | None = None
    resources: list[DraftResource] = Field(default_factory=list)
    steps: list[DraftStep] = Field(default_factory=list)
    policies: list[DraftPolicy] = Field(default_factory=list)
    carrier_loops: list[DraftCarrierLoop] = Field(default_factory=list)
    experiments: list[DraftExperiment] = Field(default_factory=list)
    missing_information: list[DraftQuestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)


Intent = Literal["set", "experiment", "run", "revert", "compare_baseline", "explain_bottleneck",
                 "explain_waiting", "none"]


class EditOp(BaseModel):
    intent: Intent
    path: str | None = Field(default=None, description="ISMS parameter path for 'set', e.g. nodes.buffer_1.params.capacity")
    value_json: str | None = Field(default=None, description="JSON-encoded new value for 'set'")
    factor_path: str | None = Field(default=None, description="path varied by 'experiment'")
    values_json: str | None = Field(default=None, description="JSON list of levels for 'experiment'")


class EditPlan(BaseModel):
    operations: list[EditOp] = Field(default_factory=list)
    explanation: str = ""
    question: str | None = Field(default=None, description="ask the engineer when the request is ambiguous")
