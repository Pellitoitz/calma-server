"""1.1-A physical run comparison: contracts of compare_physical_runs (pure, on stored results)."""

from __future__ import annotations

import copy
import json
import math

import pytest

from simforge.analytics.kpis import aggregate
from simforge.analytics.run_comparison import (
    DELTA_CONVENTION,
    PhysicalComparison,
    compare_physical_runs,
    experiment_deltas,
)
from simforge.analytics.stats import summarize
from simforge.experiments.runner import ExperimentResult, Scenario, SimulationResult


def R(per_rep: list[dict[str, float]], seeds: list[int] | None = None, horizon: float = 3600.0, warmup: float = 0.0,
      run_id: str = "r", engine_version: str = "0.9.0", model_hash: str = "h", availability: str | None = None) -> SimulationResult:
    seeds = seeds if seeds is not None else [100 + i for i in range(len(per_rep))]
    return SimulationResult(run_id=run_id, model_name="m", model_hash=model_hash, component_versions={"server": "1.0.0"},
                            engine="simforge-des", engine_version=engine_version, app_version="1.0.0rc1", seeds=seeds,
                            started_at="2026-01-01T00:00:00+00:00", wall_time_s=0.1, horizon_s=horizon, warmup_s=warmup,
                            kpis=aggregate(per_rep), per_replication=per_rep, findings=[], availability_hash=availability)


def reps(key: str, values: list[float]) -> list[dict[str, float]]:
    return [{key: v} for v in values]


# 1-3 -------------------------------------------------------------------------------------------- delta convention
def test_identical_runs_delta_zero():
    b = R(reps("units_completed", [10, 12, 11]), run_id="b")
    a = R(reps("units_completed", [10, 12, 11]), run_id="a")
    m = compare_physical_runs(b, a).metric("units_completed")
    assert m.status == "COMPARED" and m.delta.mean == 0.0 and m.delta.sign == "ZERO"
    assert m.delta.std == 0.0 and m.delta.ci95_low == m.delta.ci95_high == 0.0
    same = compare_physical_runs(b, b)
    assert same.metric("units_completed").delta.mean == 0.0
    assert any(c.check == "same_run" for c in same.checks)


def test_alt_greater_positive_delta_and_alt_lower_negative_for_every_metric():
    b = R([{"throughput_per_hour": 10.0, "avg_lead_time_s": 100.0}], run_id="b")
    a = R([{"throughput_per_hour": 12.0, "avg_lead_time_s": 80.0}], run_id="a")
    c = compare_physical_runs(b, a)
    assert c.metric("throughput_per_hour").delta.mean == 2.0
    assert c.metric("throughput_per_hour").delta.sign == "POSITIVE"
    # no silent inversion for "lower is better" metrics: alternative - baseline, always
    assert c.metric("avg_lead_time_s").delta.mean == -20.0
    assert c.metric("avg_lead_time_s").delta.sign == "NEGATIVE"
    assert c.delta_convention == DELTA_CONVENTION and "alternative - baseline" in DELTA_CONVENTION


# 4-5 -------------------------------------------------------------------------------------------- missing != zero
def test_missing_metric_is_not_zero():
    b = R([{"units_completed": 5.0, "total_setup_count": 3.0}], run_id="b")
    a = R([{"units_completed": 6.0}], run_id="a")
    m = compare_physical_runs(b, a).metric("total_setup_count")
    assert m.status == "NOT_AVAILABLE" and m.delta is None
    assert m.alternative_mean is None and "alternative" in m.reason and "not zero" in m.reason


def test_undefined_values_are_not_compared_silently():
    b = R(reps("avg_lead_time_s", [100.0, float("nan")]), run_id="b")
    a = R(reps("avg_lead_time_s", [90.0, 95.0]), run_id="a")
    m = compare_physical_runs(b, a).metric("avg_lead_time_s")
    assert m.status == "NOT_COMPARABLE" and m.delta is None and "NaN" in m.reason
    assert m.baseline_n == 1  # the defined value is still shown, with its count


# 6-8 -------------------------------------------------------------------------------------------- pairing (CRN)
def test_paired_only_with_crn_evidence_and_uses_per_replication_deltas():
    b = R(reps("units_completed", [10, 20, 30]), seeds=[1, 2, 3], run_id="b")
    a = R(reps("units_completed", [11, 22, 33]), seeds=[1, 2, 3], run_id="a")
    c = compare_physical_runs(b, a)
    assert c.comparison_mode == "PAIRED"
    d = c.metric("units_completed").delta
    ref = summarize([1, 2, 3])
    assert d.mode == "PAIRED" and d.n == 3 and d.mean == pytest.approx(2.0)
    assert d.std == pytest.approx(ref.std) and d.ci95_low == pytest.approx(ref.ci95_low)
    # the paired interval is much narrower than the spread of either run (that is the point of pairing)
    assert d.ci95_high - d.ci95_low < summarize([10, 20, 30]).ci95_high - summarize([10, 20, 30]).ci95_low


def test_different_seeds_not_paired():
    b = R(reps("units_completed", [10, 20]), seeds=[1, 2], run_id="b")
    a = R(reps("units_completed", [11, 22]), seeds=[5, 6], run_id="a")
    c = compare_physical_runs(b, a)
    assert c.comparison_mode == "UNPAIRED" and "seeds differ" in c.pairing_evidence
    d = c.metric("units_completed").delta
    assert d.mode == "UNPAIRED" and d.mean == pytest.approx(1.5) and d.ci95_low is None and d.std is None


def test_different_replication_count_not_paired_even_with_shared_prefix():
    b = R(reps("units_completed", [10, 20]), seeds=[1, 2], run_id="b")
    a = R(reps("units_completed", [10, 20, 30]), seeds=[1, 2, 3], run_id="a")
    c = compare_physical_runs(b, a)
    assert c.comparison_mode == "UNPAIRED"
    assert any("replications differ" in e for e in c.pairing_evidence)


def test_same_replication_count_alone_is_not_crn_evidence():
    b = R(reps("units_completed", [1, 2]), seeds=[1, 2], run_id="b")
    a = R(reps("units_completed", [1, 2]), seeds=[2, 1], run_id="a")
    assert compare_physical_runs(b, a).comparison_mode == "UNPAIRED"


def test_different_engine_version_not_paired_and_warned():
    b = R(reps("units_completed", [1, 2]), seeds=[1, 2], run_id="b")
    a = R(reps("units_completed", [1, 2]), seeds=[1, 2], run_id="a", engine_version="0.8.0")
    c = compare_physical_runs(b, a)
    assert c.comparison_mode == "UNPAIRED" and c.status == "COMPARABLE_WITH_WARNINGS"
    assert any(x.check == "engine" and x.level == "WARNING" for x in c.checks)


def test_pairing_not_determinable_without_seed_evidence():
    b = R(reps("units_completed", [1, 2]), seeds=[], run_id="b")
    a = R(reps("units_completed", [1, 2]), seeds=[1, 2], run_id="a")
    c = compare_physical_runs(b, a)
    assert c.comparison_mode == "NOT_DETERMINABLE"
    assert c.metric("units_completed").delta.mode == "UNPAIRED"
    assert any(x.check == "pairing" and x.level == "WARNING" for x in c.checks)


# 9 ---------------------------------------------------------------------------------------------- hard incompatibility
@pytest.mark.parametrize("kw", [{"horizon": 7200.0}, {"warmup": 600.0}])
def test_different_measured_window_is_not_comparable_and_never_normalised(kw):
    b = R(reps("units_completed", [10]), run_id="b")
    a = R(reps("units_completed", [20]), run_id="a", **kw)
    c = compare_physical_runs(b, a)
    assert c.status == "NOT_COMPARABLE" and c.errors
    m = c.metric("units_completed")
    assert m.status == "NOT_COMPARABLE" and m.delta is None
    assert m.baseline_mean == 10 and m.alternative_mean == 20  # absolute values stay visible, no per-hour rescaling


def test_calendar_difference_is_a_warning_not_a_block():
    b = R(reps("units_completed", [10]), run_id="b", availability="cal1")
    a = R(reps("units_completed", [8]), run_id="a", availability="cal2")
    c = compare_physical_runs(b, a)
    assert c.status == "COMPARABLE_WITH_WARNINGS" and c.metric("units_completed").delta.mean == -2


# 10 --------------------------------------------------------------------------------------------- n = 1
def test_single_replication_has_no_fake_std_or_ci():
    b = R(reps("units_completed", [10]), seeds=[1], run_id="b")
    a = R(reps("units_completed", [13]), seeds=[1], run_id="a")
    d = compare_physical_runs(b, a).metric("units_completed").delta
    assert d.mode == "PAIRED" and d.n == 1 and d.mean == 3
    assert d.std is None and d.ci95_low is None and d.ci95_high is None


# 11-13 ------------------------------------------------------------------------------------------ determinism, no ranking, no mutation
def test_deterministic_serialised_output_and_metric_order():
    b = R([{"z.metric": 1.0, "units_completed": 2.0, "a.metric": 3.0, "avg_wip": 1.0}], run_id="b")
    a = R([{"a.metric": 4.0, "avg_wip": 2.0, "units_completed": 1.0, "z.metric": 0.0}], run_id="a")
    c1, c2 = compare_physical_runs(b, a), compare_physical_runs(b, a)
    assert c1.model_dump_json() == c2.model_dump_json()
    assert [m.metric for m in c1.metrics] == ["units_completed", "avg_wip", "a.metric", "z.metric"]
    PhysicalComparison.model_validate_json(c1.model_dump_json())  # round trip, extra="forbid"


FORBIDDEN = ("best", "winner", "rank", "recommend", "optimal", "superior", "score", "better")


def _keys(x, out):
    if isinstance(x, dict):
        for k, v in x.items():
            out.add(k.lower())
            _keys(v, out)
    elif isinstance(x, list):
        for v in x:
            _keys(v, out)
    return out


def test_no_ranking_or_recommendation_fields_or_wording():
    b = R(reps("units_completed", [10, 11]), run_id="b")
    a = R(reps("units_completed", [12, 13]), run_id="a", availability="x")
    c = compare_physical_runs(b, a)
    keys = _keys(json.loads(c.model_dump_json()), set())
    assert not [k for k in keys if any(w in k for w in FORBIDDEN)]
    texts = [x.detail for x in c.checks] + c.pairing_evidence + [m.reason or "" for m in c.metrics] + [c.delta_convention]
    assert not [t for t in texts if any(w in t.lower() for w in FORBIDDEN)]
    assert "does not rank" in c.note


def test_comparison_does_not_mutate_runs():
    b = R(reps("units_completed", [10, float("nan")]), run_id="b")
    a = R(reps("units_completed", [11, 12]), run_id="a")
    before = (copy.deepcopy(b.to_dict()), copy.deepcopy(a.to_dict()))
    compare_physical_runs(b, a)
    after = (b.to_dict(), a.to_dict())
    assert json.dumps(before, default=str) == json.dumps(after, default=str)
    assert math.isnan(b.per_replication[1]["units_completed"])


def test_metric_filter_keeps_requested_order_and_reports_unknown_as_not_available():
    b = R([{"units_completed": 1.0, "avg_wip": 1.0}], run_id="b")
    a = R([{"units_completed": 2.0, "avg_wip": 1.0}], run_id="a")
    c = compare_physical_runs(b, a, metrics=["avg_wip", "nope", "units_completed"])
    assert [m.metric for m in c.metrics] == ["avg_wip", "nope", "units_completed"]
    assert c.metric("nope").status == "NOT_AVAILABLE"


# experiments ------------------------------------------------------------------------------------- deltas vs reference scenario
def _exp() -> ExperimentResult:
    from simforge.domain.isms import ExperimentSpec, Factor
    spec = ExperimentSpec(name="e", factors=[Factor(path="resources.op.quantity", values=[1, 2, 3])])
    s = [Scenario(0, {"resources.op.quantity": 1}, R(reps("units_completed", [10, 12]), seeds=[1, 2], run_id="s0")),
         Scenario(1, {"resources.op.quantity": 2}, R(reps("units_completed", [15, 16]), seeds=[1, 2], run_id="s1")),
         Scenario(2, {"resources.op.quantity": 3}, None, "boom")]
    return ExperimentResult("exp1", spec, "h", s, "2026-01-01T00:00:00+00:00", 0.1)


def test_experiment_deltas_vs_reference_keep_order_and_failed_scenarios():
    d = experiment_deltas(_exp(), 0, ["units_completed"])
    assert [s.index for s in d.scenarios] == [0, 1, 2]
    assert d.scenarios[0].is_reference and d.scenarios[0].comparison.metric("units_completed").delta.mean == 0
    m = d.scenarios[1].comparison.metric("units_completed")
    assert m.delta.mode == "PAIRED" and m.delta.mean == pytest.approx(4.5)
    assert d.scenarios[2].comparison is None and d.scenarios[2].error == "boom"
    d1 = experiment_deltas(_exp(), 1, ["units_completed"])
    assert d1.scenarios[0].comparison.metric("units_completed").delta.mean == pytest.approx(-4.5)
    assert [s.index for s in d1.scenarios] == [0, 1, 2]  # never re-ordered by a KPI


def test_experiment_deltas_invalid_reference():
    with pytest.raises(ValueError):
        experiment_deltas(_exp(), 7)
    with pytest.raises(ValueError, match="falló"):
        experiment_deltas(_exp(), 2)
