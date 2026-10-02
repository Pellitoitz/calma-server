"""Engine-ready maintenance runtime (failure models, preventive tasks, calendars gating PM)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.maintenance import MaintenanceSpec, NodeMaintenance


@dataclass
class MaintenanceRuntime:
    spec_hash: str
    nodes: dict[str, NodeMaintenance]
    pm_gating: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # node -> pm id -> calendars


def compile_maintenance(model, spec: MaintenanceSpec) -> MaintenanceRuntime:
    av = getattr(model, "availability", None)
    gating: dict[str, dict[str, list[str]]] = {}
    for nid, nm in spec.nodes.items():
        for t in nm.preventive:
            cals = []
            if av is not None:
                cals = ([av.nodes[nid]] if nid in av.nodes else []) + [av.resources[u.resource] for u in t.resources
                                                                       if u.resource in av.resources]
            gating.setdefault(nid, {})[t.id] = list(dict.fromkeys(cals))
    return MaintenanceRuntime(spec_hash=spec.maintenance_hash(), nodes=dict(spec.nodes), pm_gating=gating)
