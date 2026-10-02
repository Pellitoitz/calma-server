"""Engine-ready production runtime (product mix, routes, product times, setups) attached to the compiled model."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.production import ProductionSpec, SetupSpec


class SetupTransitionMissing(RuntimeError):
    """A setup change occurred at run time that the model does not define. Never defaulted: the run stops."""


@dataclass
class ProductionRuntime:
    spec_hash: str
    spec: ProductionSpec
    setup_key: dict[str, str | None]  # product -> setup key
    routes: dict[str, tuple[str, ...]]  # product -> node sequence (empty dict = legacy edge routing)
    processing: dict[str, dict]  # node -> product -> Duration
    setups: dict[str, SetupSpec]
    setup_gating: dict[str, list[str]] = field(default_factory=dict)  # node -> calendars gating its SETUP

    def generation(self, source: str):
        return self.spec.generation.get(source)


def compile_production(model, spec: ProductionSpec, cm) -> ProductionRuntime:
    av = getattr(model, "availability", None)
    gating: dict[str, list[str]] = {}
    if av is not None:
        for nid, st in spec.setups.items():
            cals = [av.nodes[nid]] if nid in av.nodes else []
            cals += [av.resources[u.resource] for u in st.resources if u.resource in av.resources]
            if cals:
                gating[nid] = list(dict.fromkeys(cals))
    return ProductionRuntime(
        spec_hash=spec.production_hash(), spec=spec,
        setup_key={p: ps.setup_key for p, ps in spec.products.items()},
        routes={p: tuple(r.nodes) for p, r in spec.routes.items()},
        processing={n: dict(t) for n, t in spec.processing.items()},
        setups=dict(spec.setups), setup_gating=gating)
