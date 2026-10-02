"""Engine 0.4.0 distributions: gamma/weibull, explicit truncation, no silent negative resampling, data provenance link.

The example models must keep the content hash and the serialisation they had with engine 0.3.0 (the new optional
fields are omitted when empty), so approvals and caches of existing projects stay valid.
"""

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from simforge.domain.io import load_model
from simforge.domain.values import (
    DataLink,
    Empirical,
    Exponential,
    Gamma,
    LogNormal,
    NegativeSampleError,
    Normal,
    Provenance,
    Triangular,
    Truncation,
    Uniform,
    ValueStatus,
    Weibull,
)

from .conftest import EXAMPLES

HASHES = json.loads((Path(__file__).parent / "data" / "model_hashes_engine_0_3_0.json").read_text())


@pytest.mark.parametrize("name", sorted(HASHES))
def test_engine_0_4_0_keeps_model_hashes(name):
    m = load_model(EXAMPLES / name)
    assert m.content_hash() == HASHES[name]["content_hash"]
    assert hashlib.sha256(m.model_dump_json().encode()).hexdigest()[:16] == HASHES[name]["dump_sha"]


def test_empty_optional_fields_are_not_serialised():
    d = Normal(mean=10, std=1).model_dump()
    assert "truncation" not in d
    assert "data" not in Provenance().model_dump()


def test_normal_with_negative_mass_requires_explicit_truncation():
    with pytest.raises(ValidationError, match="explicit truncation"):
        Normal(mean=10, std=6)
    Normal(mean=50, std=5)  # P(t<0) ~ 1e-23: accepted
    n = Normal(mean=10, std=6, truncation={"lower": 0, "reason": "times cannot be negative", "bound_type": "MODELLING_BOUND"})
    assert "truncated[0,]" in n.describe()


def test_truncation_needs_reason_and_valid_bounds():
    with pytest.raises(ValidationError):
        Truncation(lower=0, reason="", bound_type="MODELLING_BOUND")
    with pytest.raises(ValidationError):
        Truncation(reason="no bounds", bound_type="MODELLING_BOUND")
    with pytest.raises(ValidationError):
        Truncation(lower=5, upper=5, reason="empty window", bound_type="MODELLING_BOUND")
    with pytest.raises(ValidationError):
        Truncation(lower=-1, reason="negative lower", bound_type="MODELLING_BOUND")
    with pytest.raises(ValidationError):
        Truncation(lower=0, reason="bound type is mandatory")  # never defaulted
    t = Truncation(lower=8, reason="nunca menos de 8 s (husillo)", bound_type="PHYSICAL_BOUND")
    assert t.method == "DECLARED"


def test_truncated_samples_stay_in_window_and_mean_is_conditional():
    d = Normal(mean=10, std=6, truncation={"lower": 0, "upper": 20, "reason": "observed range", "bound_type": "MODELLING_BOUND"})
    rng = random.Random(3)
    xs = [d.sample_seconds(rng) for _ in range(20000)]
    assert 0 <= min(xs) and max(xs) <= 20
    # analytic mean of N(10,6) truncated to [0,20] is 10 (symmetric window)
    assert d.mean_seconds() == pytest.approx(10, abs=1e-6)
    assert sum(xs) / len(xs) == pytest.approx(10, abs=0.15)
    one_sided = Normal(mean=10, std=6, truncation={"lower": 0, "reason": "non-negative", "bound_type": "MODELLING_BOUND"})
    assert one_sided.mean_seconds() > 10  # truncating the left tail raises the mean


def test_negative_raw_sample_raises_instead_of_silent_resampling():
    class Shifted(Uniform):  # a distribution that can go negative if validation were bypassed
        def _raw(self, rng):
            return -1.0
    d = Shifted(low=0, high=1)
    with pytest.raises(NegativeSampleError):
        d.sample_seconds(random.Random(1))


def test_impossible_truncation_window_raises():
    d = Uniform(low=0, high=1, truncation={"lower": 5, "upper": 6, "reason": "outside support", "bound_type": "MODELLING_BOUND"})
    with pytest.raises(ValueError, match="zero probability"):
        d.sample_seconds(random.Random(1))


@pytest.mark.parametrize("d,mean", [
    (Gamma(shape=4, scale=2.5), 10.0),
    (Weibull(shape=2, scale=10), 10 * math.gamma(1.5)),
    (LogNormal(mean=10, std=3), 10.0),
    (Exponential(mean=10), 10.0),
    (Triangular(low=5, mode=8, high=17), 10.0),
])
def test_sampling_matches_mean_and_is_non_negative(d, mean):
    assert d.mean_seconds() == pytest.approx(mean)
    rng = random.Random(42)
    xs = [d.sample_seconds(rng) for _ in range(40000)]
    assert min(xs) >= 0
    assert sum(xs) / len(xs) == pytest.approx(mean, rel=0.03)


def test_units_apply_to_new_distributions():
    assert Gamma(shape=2, scale=1, unit="min").mean_seconds() == pytest.approx(120)
    assert Weibull(shape=1, scale=500, unit="ms").mean_seconds() == pytest.approx(0.5)


@pytest.mark.parametrize("d", [Gamma(shape=2, scale=3), Weibull(shape=1.5, scale=4), Empirical(values=[1, 2, 3, 9]),
                               Normal(mean=3, std=2, truncation={"lower": 0, "reason": "non-negative", "bound_type": "MODELLING_BOUND"})])
def test_same_seed_same_sequence(d):
    a, b = random.Random(7), random.Random(7)
    assert [d.sample_seconds(a) for _ in range(200)] == [d.sample_seconds(b) for _ in range(200)]


def test_scipy_equivalents_have_the_same_mean():
    pytest.importorskip("scipy")
    for d in [Gamma(shape=3, scale=2), Weibull(shape=1.7, scale=9), LogNormal(mean=12, std=4), Exponential(mean=5),
              Normal(mean=20, std=2), Uniform(low=1, high=4), Triangular(low=1, mode=2, high=6)]:
        assert d.scipy().mean() == pytest.approx(d.mean_seconds(), rel=1e-9)


def test_new_distributions_roundtrip_in_a_model_parameter():
    from simforge.domain.behaviors import ServerParams

    link = DataLink(dataset_id="ds_x", dataset_version=1, content_hash="abc", source_file="t.xlsx", column="tiempo",
                    original_unit="min", basis="PER_PANEL", n_used=40, decision="FITTED", fit_id="fit_1",
                    decided_by="engineer", decided_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    p = ServerParams.model_validate({"process_time": {
        "dist": "weibull", "shape": 2.1, "scale": 3.0, "unit": "min",
        "provenance": {"status": "measured", "data": link.model_dump(mode="json")}}})
    again = ServerParams.model_validate(p.model_dump(mode="json"))
    assert again == p
    assert again.process_time.provenance.status == ValueStatus.MEASURED
    assert again.process_time.provenance.data.fit_id == "fit_1"
