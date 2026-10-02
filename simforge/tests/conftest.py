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


# ------------------------------------------------------------------------------------------------ 1.0 test classes
# Files are classified, not rewritten:  pytest -m "not release" (fast) · pytest -m release · pytest (full suite)
_CLASSES = {
    "release": ("test_release_",),
    "validation": ("test_real_calendar_validation", "test_real_economic_validation"),
    "regression": ("test_engine_golden", "test_selective_benchmark", "test_llm_semantic_harness"),
    "integration": ("test_cli_report_ui", "test_ai_and_app", "test_ai_platform", "test_data_workflow", "test_nl_"),
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = Path(str(item.fspath)).stem
        for marker, prefixes in _CLASSES.items():
            if name.startswith(prefixes):
                item.add_marker(getattr(pytest.mark, marker))
                break
        else:
            item.add_marker(pytest.mark.unit)
