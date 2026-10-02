"""Engine-ready availability (calendars expanded to simulation seconds) attached to the compiled model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.calendar import DAY_S, OperationPolicy, Timeline, expand, intersect_timelines
from ..library.registry import ComponentRegistry
from ..validation.verifier import CompiledModel


@dataclass
class AvailabilityRuntime:
    spec_hash: str
    end_s: float  # timelines are expanded beyond the horizon (window ends near the horizon stay correct)
    timelines: dict[str, Timeline]  # calendar id -> timeline
    resource_calendar: dict[str, str]  # resource id -> calendar id
    node_calendar: dict[str, str]  # node id (server/source) -> calendar id
    gating: dict[str, list[str]]  # node id -> calendars that must ALL be available (own + its operators/tools)
    policies: dict[str, OperationPolicy] = field(default_factory=dict)

    def node_timeline(self, node_id: str) -> Timeline:
        return intersect_timelines([self.timelines[c] for c in dict.fromkeys(self.gating.get(node_id, []))], self.end_s)


@dataclass
class CalendarCompiledModel(CompiledModel):
    availability: AvailabilityRuntime | None = None


def compile_availability(cm: CompiledModel, model, registry: ComponentRegistry) -> CalendarCompiledModel:
    from ..validation.availability import calendared_requirements
    spec = model.availability
    end = cm.horizon_s + 2 * DAY_S
    rt = AvailabilityRuntime(
        spec_hash=spec.calendar_hash(), end_s=end,
        timelines={c.id: expand(spec, c, end) for c in spec.calendars},
        resource_calendar=dict(spec.resources), node_calendar=dict(spec.nodes),
        gating={nid: list(dict.fromkeys(cals)) for nid, cals in calendared_requirements(model, spec, registry).items()},
        policies=dict(spec.operations))
    return CalendarCompiledModel(model=cm.model, nodes=cm.nodes, horizon_s=cm.horizon_s, warmup_s=cm.warmup_s,
                                 component_versions=cm.component_versions, availability=rt)
