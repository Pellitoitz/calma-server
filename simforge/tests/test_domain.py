import random

import pytest
from pydantic import ValidationError

from simforge.domain.io import dump_model, load_model, model_from_dict
from simforge.domain.isms import ISMSModel, ModelMeta, Node
from simforge.domain.paths import diff, get_value, set_value
from simforge.domain.units import UnitError, seconds
from simforge.domain.values import Constant, Exponential, LogNormal, Normal, Triangular, Uniform

from .conftest import EXAMPLES


def test_units_convert():
    assert seconds(2, "min") == 120
    assert seconds(8, "h") == 28800
    with pytest.raises(UnitError):
        seconds(1, "m")  # length is not time
    with pytest.raises(UnitError):
        seconds(1, "fortnight")


def test_distribution_units_and_means():
    assert Constant(value=2, unit="min").mean_seconds() == 120
    assert Uniform(low=10, high=20).mean_seconds() == 15
    assert Triangular(low=1, mode=2, high=6).mean_seconds() == 3


@pytest.mark.parametrize("bad", [
    {"dist": "constant", "value": -1},
    {"dist": "uniform", "low": 5, "high": 1},
    {"dist": "triangular", "low": 1, "mode": 9, "high": 5},
    {"dist": "normal", "mean": 10, "std": -1},
    {"dist": "exponential", "mean": 0},
    {"dist": "empirical", "values": []},
    {"dist": "constant", "value": 5, "unit": "m"},
])
def test_invalid_distributions_rejected(bad):
    from simforge.domain.behaviors import ServerParams

    with pytest.raises(ValidationError):
        ServerParams.model_validate({"process_time": bad})


def test_no_negative_samples():
    rng = random.Random(1)
    for d in [Normal(mean=1, std=5), LogNormal(mean=5, std=10), Exponential(mean=3), Uniform(low=0, high=1)]:
        assert min(d.sample_seconds(rng) for _ in range(5000)) >= 0


def test_ids_validated():
    with pytest.raises(ValidationError):
        Node(id="Bad Id", component="machine")


def test_yaml_roundtrip():
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    import yaml
    m2 = model_from_dict(yaml.safe_load(dump_model(m)))
    assert m2.content_hash() == m.content_hash()


def test_paths_get_set_diff():
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    assert get_value(m, "nodes.buffer_1.params.capacity") == 5
    m2 = set_value(m, "nodes.buffer_1.params.capacity", 8)
    assert get_value(m2, "nodes.buffer_1.params.capacity") == 8
    assert get_value(m, "nodes.buffer_1.params.capacity") == 5  # original untouched
    m3 = set_value(m2, "resources.operator_1.quantity", 2)
    changes = {p: (a, b) for p, a, b in diff(m, m3)}
    assert changes == {"nodes.buffer_1.params.capacity": (5, 8), "resources.operator_1.quantity": (1, 2)}
    with pytest.raises(KeyError):
        get_value(m, "nodes.nope.params.capacity")
    with pytest.raises(KeyError):
        set_value(m, "resources.operator_1.not_a_field", 3)


def test_content_hash_ignores_meta_but_not_params():
    m = load_model(EXAMPLES / "01_simple_line.yaml")
    m2 = m.model_copy(update={"meta": ModelMeta(name="renamed")})
    assert m.content_hash() == m2.content_hash()
    assert set_value(m, "nodes.buf.params.capacity", 4).content_hash() != m.content_hash()


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ISMSModel.model_validate({"meta": {"name": "x"}, "shifts": []})  # unsupported -> rejected, never ignored
