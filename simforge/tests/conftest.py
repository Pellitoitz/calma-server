from __future__ import annotations

from pathlib import Path

import pytest

from simforge.domain.isms import Edge, ISMSModel, ModelMeta, Node, Resource, SimulationSettings
from simforge.library.registry import ComponentRegistry

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="session")
def registry() -> ComponentRegistry:
    return ComponentRegistry.load_default()


def C(v: float, unit: str = "s") -> dict:
    return {"dist": "constant", "value": v, "unit": unit}


def line(steps: list[tuple[str, str, dict]], horizon_h: float = 1, resources: list[Resource] | None = None,
         **sim) -> ISMSModel:
    """Build a linear model: src -> steps... -> out. steps = [(id, component, params)]."""
    nodes = [Node(id="src", component="source")]
    nodes += [Node(id=i, component=c, params=p) for i, c, p in steps]
    nodes.append(Node(id="out", component="sink"))
    ids = [n.id for n in nodes]
    return ISMSModel(meta=ModelMeta(name="test"),
                     simulation=SimulationSettings(horizon={"value": horizon_h, "unit": "h"}, **sim),
                     resources=resources or [], nodes=nodes,
                     edges=[Edge(source=a, target=b) for a, b in zip(ids, ids[1:])])
