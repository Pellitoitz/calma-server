"""work_units aggregation (engine 0.5.0): sum_iid (X1+..+Xk), scale_sample (k*X), single_sample (X).

Undeclared keeps the historical k*X so existing models do not change; it is reported, never silently "fixed"."""

from __future__ import annotations

import random
import statistics
from pathlib import Path

import pytest
from pydantic import ValidationError

from simforge.domain.behaviors import ServerParams
from simforge.domain.io import load_model
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import semantic_issues, verify_model

ROOT = Path(__file__).parents[1]
E2E = ROOT / "examples" / "data" / "e2e_selective_per_circuit.yaml"
GAMMA = {"dist": "gamma", "shape": 4, "scale": 2.5}  # mean 10, var 25
N = 20000


def _p(agg=None, k=4, pt=None):
    d = {"process_time": pt or GAMMA, "work_units": k}
    if agg:
        d["work_units_aggregation"] = agg
    return ServerParams.model_validate(d)


def _draws(p, seed=11, n=N):
    rng = random.Random(seed)
    return [p.sample_entity_seconds(rng) for _ in range(n)]


def test_k1_all_policies_identical():
    ref = _draws(_p(None, k=1), n=500)
    for agg in ("sum_iid", "scale_sample", "single_sample"):
        assert _draws(_p(agg, k=1), n=500) == ref


@pytest.mark.parametrize("agg,mean,var", [("sum_iid", 40, 100), ("scale_sample", 40, 400), ("single_sample", 10, 25)])
def test_k4_mean_and_variance(agg, mean, var):
    x = _draws(_p(agg))
    assert statistics.fmean(x) == pytest.approx(mean, rel=0.03)
    assert statistics.variance(x) == pytest.approx(var, rel=0.08)


def test_sum_iid_and_scale_sample_have_different_variance():
    v_sum, v_scale = statistics.variance(_draws(_p("sum_iid"))), statistics.variance(_draws(_p("scale_sample")))
    assert v_scale / v_sum == pytest.approx(4.0, rel=0.12)  # Var(4X) = 16 Var(X) vs Var(X1+..+X4) = 4 Var(X)


def test_undeclared_is_legacy_scale_sample_exactly():
    legacy = [GAMMA_sample * 4 for GAMMA_sample in _draws(_p(None, k=1), n=300)]  # pre-0.5.0 formula: sample * work_units
    assert _draws(_p(None), n=300) == legacy == _draws(_p("scale_sample"), n=300)


def test_same_seed_same_result():
    for agg in ("sum_iid", "scale_sample", "single_sample"):
        assert _draws(_p(agg), seed=3, n=200) == _draws(_p(agg), seed=3, n=200)


def test_deterministic_time_is_coherent():
    c = {"dist": "constant", "value": 30}
    rng = random.Random(1)
    assert _p("sum_iid", pt=c).sample_entity_seconds(rng) == 120
    assert _p("scale_sample", pt=c).sample_entity_seconds(rng) == 120
    assert _p("single_sample", pt=c).sample_entity_seconds(rng) == 30
    assert _p("single_sample", pt=c).entity_time_factor() == 1 and _p("sum_iid", pt=c).entity_time_factor() == 4


def test_empirical_sum_iid():
    emp = {"dist": "empirical", "values": [10, 20, 60]}
    x = _draws(_p("sum_iid", pt=emp))
    assert min(x) >= 40 and max(x) <= 240 and statistics.fmean(x) == pytest.approx(4 * 30, rel=0.02)
    assert len(set(x)) > 3  # combinations of independent draws, not just 4 * observed value


def test_truncated_sum_iid():
    tn = {"dist": "normal", "mean": 10, "std": 6, "truncation": {"lower": 2, "upper": 20, "reason": "observed range",
                                                                  "bound_type": "MODELLING_BOUND"}}
    x = _draws(_p("sum_iid", pt=tn), n=5000)
    assert min(x) >= 8 and max(x) <= 80


def test_sum_iid_requires_integer_units():
    with pytest.raises(ValidationError, match="entero"):
        _p("sum_iid", k=2.5)
    _p("scale_sample", k=2.5)  # a fractional factor is only meaningful as a scale


# ------------------------------------------------------------------------------------- model level
def _model(agg=None):
    m = load_model(E2E)
    m = set_value(m, "nodes.assembly.params.process_time", GAMMA)
    if agg:
        m = set_value(m, "nodes.assembly.params.work_units_aggregation", agg)
    return m


def test_policy_is_part_of_the_hash_and_invalidates_approval():
    from datetime import datetime, timezone

    from simforge.domain.isms import Approval
    base = _model("sum_iid")
    approved = base.model_copy(update={"approval": Approval(approved=True, by="ana", at=datetime.now(timezone.utc),
                                                            model_hash=base.content_hash())})
    assert approved.is_approved
    changed = set_value(approved, "nodes.assembly.params.work_units_aggregation", "scale_sample")
    assert changed.content_hash() != base.content_hash() and not changed.is_approved
    assert _model().content_hash() != base.content_hash()  # declaring it is a change too


def test_policy_persists_in_yaml(tmp_path):
    from simforge.domain.io import dump_model
    p = tmp_path / "m.yaml"
    p.write_text(dump_model(_model("single_sample")))
    assert load_model(p).nodes[1].params["work_units_aggregation"] == "single_sample"


def test_engine_runs_policies_reproducibly_and_legacy_unchanged():
    reg = ComponentRegistry.load_default(None)
    runs = {a: run_simulation(_model(a), reg, replications=3) for a in (None, "scale_sample", "sum_iid", "single_sample")}
    k = {a: r.kpis.mean("units_completed") for a, r in runs.items()}
    assert k[None] == k["scale_sample"]  # undeclared == historical k*X
    assert runs["sum_iid"].kpis.mean("avg_lead_time_s") != runs["scale_sample"].kpis.mean("avg_lead_time_s")
    lt = {a: r.kpis.mean("avg_lead_time_s") for a, r in runs.items()}
    assert lt["single_sample"] < lt["sum_iid"]  # 10 s per rack instead of ~40 s (throughput is capped by the selective)
    again = run_simulation(_model("sum_iid"), reg, replications=3)
    assert again.kpis.mean("units_completed") == k["sum_iid"] and again.seeds == runs["sum_iid"].seeds


def test_undeclared_random_time_is_reported_not_fixed():
    reg = ComponentRegistry.load_default(None)
    codes = [i.code for i in semantic_issues(_model(), reg)]
    assert codes == ["WORK_UNITS_AGGREGATION_UNDECLARED"]
    assert semantic_issues(_model("sum_iid"), reg) == []
    assert semantic_issues(load_model(E2E), reg) == []  # constant time: all policies but single_sample coincide (k*c)
    rep, _ = verify_model(_model(), reg)
    assert rep.ok and any(w.code == "WORK_UNITS_AGGREGATION_UNDECLARED" for w in rep.warnings)


def test_report_shows_policy():
    from simforge.reporting.report import build_markdown
    reg = ComponentRegistry.load_default(None)
    md = build_markdown(_model(), verify_model(_model(), reg)[0], None)
    assert "UNDECLARED: legacy scale_sample" in md and "WORK_UNITS_AGGREGATION_UNDECLARED" in md
    m = _model("sum_iid")
    assert "4 units (sum_iid)" in build_markdown(m, verify_model(m, reg)[0], None)
