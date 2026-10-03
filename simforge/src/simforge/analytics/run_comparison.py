"""Physical run comparison (1.1-A): baseline run vs alternative run, from STORED results. Facts only.

The comparator never simulates, never re-computes KPIs, never touches RNG, traces or hashes: it reads two
SimulationResult objects (their per-replication KPIs) and describes the differences.

Conventions (fixed, tested):
  delta = alternative - baseline, for EVERY metric (no per-KPI sign inversion; a positive delta is not "better").
  PAIRED   (evidence of common random numbers): same engine + engine version, same ordered seeds (hence the same number of
           replications) and the same horizon and warm-up. Per-replication deltas delta_i = alt_i - base_i are
           summarised (mean, std, 95 % CI with Student t; n = 1 -> no std / CI).
  UNPAIRED: difference of the replication means; no interval is computed (no new statistical method is introduced).
  NOT_DETERMINABLE: the runs lack the seed / replication evidence needed to decide.
Missing is never zero: a metric absent in a run is NOT_AVAILABLE; a metric undefined (NaN) in some replication is
NOT_COMPARABLE. Checks are HARD_INCOMPATIBILITY (-> NOT_COMPARABLE, no delta shown) | WARNING | INFORMATIONAL.
A different measured window (horizon / warm-up) is a hard incompatibility: no per-hour normalisation is applied.
The result has no ranking, winner, score or recommendation: the engineer decides.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..experiments.runner import SimulationResult
from .kpis import metric_info
from .stats import summarize

DELTA_CONVENTION = "delta = alternative - baseline (all metrics; the sign describes the difference, it is not a judgement)"
NOTE = "Facts only: SimForge compares and traces; it does not rank, choose or recommend. The engineer decides."
HEADLINE_METRICS = ("units_completed", "throughput_per_hour", "avg_wip", "max_wip", "avg_lead_time_s", "p90_lead_time_s",
                    "units_scrapped", "yield")

Mode = Literal["PAIRED", "UNPAIRED", "NOT_DETERMINABLE"]
Level = Literal["HARD_INCOMPATIBILITY", "WARNING", "INFORMATIONAL"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunIdentity(_Strict):
    run_id: str
    model_name: str
    model_hash: str
    model_version: int | None = None  # None = run of a model never saved as a project version
    scenario: str | None = None  # scenario name of that version, when the project maps one
    is_baseline_version: bool | None = None
    engine: str
    engine_version: str
    app_version: str
    horizon_s: float
    warmup_s: float
    replications: int
    seeds: list[int]
    availability_hash: str | None = None
    started_at: str


class Check(_Strict):
    check: str
    level: Level
    detail: str


class DeltaSummary(_Strict):
    mode: Literal["PAIRED", "UNPAIRED"]
    n: int  # paired: number of replication pairs; unpaired: min(n_base, n_alt) (informative only)
    mean: float
    std: float | None = None  # paired and n > 1 only
    ci95_low: float | None = None
    ci95_high: float | None = None
    sign: Literal["POSITIVE", "NEGATIVE", "ZERO"]  # sign of the mean delta: a mathematical fact, not a judgement


class MetricComparison(_Strict):
    metric: str
    label: str
    unit: str
    status: Literal["COMPARED", "NOT_AVAILABLE", "NOT_COMPARABLE"]
    reason: str | None = None
    baseline_mean: float | None = None
    alternative_mean: float | None = None
    baseline_n: int = 0
    alternative_n: int = 0
    delta: DeltaSummary | None = None


class PhysicalComparison(_Strict):
    baseline: RunIdentity
    alternative: RunIdentity
    status: Literal["COMPARABLE", "COMPARABLE_WITH_WARNINGS", "NOT_COMPARABLE"]
    comparison_mode: Mode
    pairing_evidence: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    metrics: list[MetricComparison] = Field(default_factory=list)
    delta_convention: str = DELTA_CONVENTION
    note: str = NOTE

    def metric(self, key: str) -> MetricComparison | None:
        return next((m for m in self.metrics if m.metric == key), None)

    @property
    def errors(self) -> list[str]:
        return [c.detail for c in self.checks if c.level == "HARD_INCOMPATIBILITY"]

    @property
    def warnings(self) -> list[str]:
        return [c.detail for c in self.checks if c.level == "WARNING"]


# ------------------------------------------------------------------------------------------------ helpers
def _clean(x: float) -> float:
    return x + 0.0  # no "-0.0"


def _sign(x: float) -> Literal["POSITIVE", "NEGATIVE", "ZERO"]:
    return "POSITIVE" if x > 0 else "NEGATIVE" if x < 0 else "ZERO"


def _defined(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v)


def identity(run: SimulationResult, model_version: int | None = None, scenario: str | None = None,
             is_baseline_version: bool | None = None) -> RunIdentity:
    return RunIdentity(run_id=run.run_id, model_name=run.model_name, model_hash=run.model_hash, model_version=model_version,
                       scenario=scenario, is_baseline_version=is_baseline_version, engine=run.engine,
                       engine_version=run.engine_version, app_version=run.app_version, horizon_s=run.horizon_s,
                       warmup_s=run.warmup_s, replications=len(run.per_replication), seeds=list(run.seeds),
                       availability_hash=run.availability_hash, started_at=run.started_at)


def pairing(b: SimulationResult, a: SimulationResult) -> tuple[Mode, list[str]]:
    """Conservative CRN evidence. Equal replication counts alone are never enough."""
    if not b.seeds or not a.seeds or len(b.seeds) != len(b.per_replication) or len(a.seeds) != len(a.per_replication):
        return "NOT_DETERMINABLE", ["seed list missing or inconsistent with the stored replications"]
    reasons = []
    if (b.engine, b.engine_version) != (a.engine, a.engine_version):
        reasons.append(f"engine differs ({b.engine} {b.engine_version} vs {a.engine} {a.engine_version})")
    if b.seeds != a.seeds:
        reasons.append("seeds differ" if len(b.seeds) == len(a.seeds) else
                       f"replications differ ({len(b.seeds)} vs {len(a.seeds)})")
    if (b.horizon_s, b.warmup_s) != (a.horizon_s, a.warmup_s):
        reasons.append("horizon / warm-up differ")
    if reasons:
        return "UNPAIRED", reasons
    return "PAIRED", [f"same engine {b.engine} {b.engine_version}", f"same seeds {b.seeds}",
                      f"same horizon {b.horizon_s:g} s and warm-up {b.warmup_s:g} s"]


def _model_checks(base_model, alt_model, registry) -> list[Check]:
    """Scenario-level differences derived from the two model versions (when both are known). Intended differences are
    what is being compared: they are flagged, never blocking."""
    out: list[Check] = []
    if registry is not None:
        def sources(m) -> dict[str, Any]:
            res = {}
            for n in m.nodes:
                try:
                    if registry.get(n.component).behavior.value == "source":
                        res[n.id] = n.params
                except Exception:  # noqa: BLE001 - an unknown component is reported by the verifier, not here
                    pass
            return res
        if sources(base_model) != sources(alt_model):
            out.append(Check(check="demand", level="WARNING",
                             detail="arrival / demand assumptions (sources) differ: output deltas include the demand change"))
    pb, pa = getattr(base_model, "production", None), getattr(alt_model, "production", None)
    gb = pb.model_dump(mode="json")["generation"] if pb else None
    ga = pa.model_dump(mode="json")["generation"] if pa else None
    if gb != ga:
        out.append(Check(check="product_mix", level="WARNING",
                         detail="product mix / sequence differs: no normalisation or weighting is applied"))
    return out


def comparability(b: SimulationResult, a: SimulationResult, mode: Mode, base_model=None, alt_model=None,
                  registry=None, version_known: tuple[bool, bool] = (True, True)) -> list[Check]:
    checks: list[Check] = []

    def add(check: str, level: Level, detail: str) -> None:
        checks.append(Check(check=check, level=level, detail=detail))
    if not b.per_replication or not a.per_replication:
        add("results", "HARD_INCOMPATIBILITY", "a run has no stored replication results")
    if (b.horizon_s, b.warmup_s) != (a.horizon_s, a.warmup_s):
        add("measured_window", "HARD_INCOMPATIBILITY",
            f"measured window differs (horizon/warm-up {b.horizon_s:g}/{b.warmup_s:g} s vs {a.horizon_s:g}/{a.warmup_s:g} s): "
            "counts and time totals cover different windows; no normalisation is applied in 1.1")
    if (b.engine, b.engine_version) != (a.engine, a.engine_version):
        add("engine", "WARNING", f"different engine versions ({b.engine_version} vs {a.engine_version}): differences may "
            "come from engine semantics, not from the scenario")
    if b.component_versions != a.component_versions:
        add("components", "WARNING", "library component versions differ between the two runs")
    if b.availability_hash != a.availability_hash:
        add("calendars", "WARNING", "calendars differ (fine if the calendar IS the alternative; check it is intended)")
    if b.run_id == a.run_id:
        add("same_run", "INFORMATIONAL", "the same run is compared with itself: every delta is 0")
    elif b.model_hash == a.model_hash:
        add("model", "INFORMATIONAL", "same physical model (same content hash): differences can only come from seeds / "
            "replications")
    else:
        add("model", "INFORMATIONAL", f"physical models differ ({b.model_hash} vs {a.model_hash}): this is what is compared")
    if not all(version_known):
        which = [n for n, k in zip(("baseline", "alternative"), version_known) if not k]
        add("lineage", "WARNING", f"{' and '.join(which)} run: model not saved as a project version; lineage not traceable")
    if mode == "UNPAIRED":
        add("pairing", "INFORMATIONAL", "no common-random-numbers evidence: difference of means only, no interval")
    elif mode == "NOT_DETERMINABLE":
        add("pairing", "WARNING", "pairing cannot be determined from the stored runs: difference of means only")
    if base_model is not None and alt_model is not None:
        checks.extend(_model_checks(base_model, alt_model, registry))
    return checks


def _metric_keys(b: SimulationResult, a: SimulationResult, metrics: list[str] | None) -> list[str]:
    if metrics is not None:
        return list(dict.fromkeys(metrics))
    keys = set(b.kpis.stats) | set(a.kpis.stats)
    head = [k for k in HEADLINE_METRICS if k in keys]
    return head + sorted(keys - set(head))


def _values(run: SimulationResult, key: str) -> list[Any]:
    return [rep.get(key) for rep in run.per_replication]


def _compare_metric(key: str, b: SimulationResult, a: SimulationResult, mode: Mode, blocked: bool) -> MetricComparison:
    label, unit, _ = metric_info(key)
    in_b, in_a = key in b.kpis.stats, key in a.kpis.stats
    base = MetricComparison(metric=key, label=label, unit=unit, status="NOT_AVAILABLE")
    if not in_b or not in_a:
        where = "baseline and alternative" if not in_b and not in_a else "baseline" if not in_b else "alternative"
        base.reason = f"metric not available in {where} (missing is not zero)"
        return base
    vb, va = _values(b, key), _values(a, key)
    sb, sa = summarize([v for v in vb if _defined(v)]), summarize([v for v in va if _defined(v)])
    base.baseline_n, base.alternative_n = sb.n, sa.n
    base.baseline_mean = _clean(sb.mean) if sb.n else None
    base.alternative_mean = _clean(sa.mean) if sa.n else None
    undefined = sum(not _defined(v) for v in vb) + sum(not _defined(v) for v in va)
    if blocked:
        base.status, base.reason = "NOT_COMPARABLE", "hard incompatibility between the runs (see checks)"
        return base
    if undefined:
        base.status = "NOT_COMPARABLE"
        base.reason = f"undefined (NaN) or absent in {undefined} replication value(s): no delta is computed"
        return base
    base.status = "COMPARED"
    if mode == "PAIRED":
        d = summarize([y - x for x, y in zip(vb, va)])
        multi = d.n > 1
        base.delta = DeltaSummary(mode="PAIRED", n=d.n, mean=_clean(d.mean), std=_clean(d.std) if multi else None,
                                  ci95_low=_clean(d.ci95_low) if multi else None,
                                  ci95_high=_clean(d.ci95_high) if multi else None, sign=_sign(d.mean))
    else:
        m = sa.mean - sb.mean
        base.delta = DeltaSummary(mode="UNPAIRED", n=min(sb.n, sa.n), mean=_clean(m), sign=_sign(m))
    return base


def compare_physical_runs(baseline: SimulationResult, alternative: SimulationResult, *, metrics: list[str] | None = None,
                          base_model=None, alt_model=None, registry=None,
                          baseline_identity: RunIdentity | None = None,
                          alternative_identity: RunIdentity | None = None) -> PhysicalComparison:
    """Compare two stored runs. Pure: no simulation, no I/O, inputs are not mutated."""
    mode, evidence = pairing(baseline, alternative)
    bid = baseline_identity or identity(baseline)
    aid = alternative_identity or identity(alternative)
    known = (baseline_identity is None or bid.model_version is not None, alternative_identity is None or aid.model_version is not None)
    checks = comparability(baseline, alternative, mode, base_model, alt_model, registry, version_known=known)
    blocked = any(c.level == "HARD_INCOMPATIBILITY" for c in checks)
    rows = [_compare_metric(k, baseline, alternative, mode, blocked) for k in _metric_keys(baseline, alternative, metrics)]
    status = "NOT_COMPARABLE" if blocked else "COMPARABLE_WITH_WARNINGS" if any(c.level == "WARNING" for c in checks) else "COMPARABLE"
    return PhysicalComparison(baseline=bid, alternative=aid, status=status, comparison_mode=mode, pairing_evidence=evidence,
                              checks=checks, metrics=rows)


# ------------------------------------------------------------------------------------------------ experiments
class ScenarioDelta(_Strict):
    index: int
    factors: dict[str, Any]
    is_reference: bool
    error: str | None = None
    comparison: PhysicalComparison | None = None


class ExperimentDeltas(_Strict):
    experiment_id: str
    reference_index: int
    scenarios: list[ScenarioDelta]  # in the experiment's own order (never sorted by a KPI)
    delta_convention: str = "delta = scenario - reference scenario (same experiment, same seeds)"
    note: str = NOTE


def experiment_deltas(exp, reference_index: int = 0, metrics: list[str] | None = None) -> ExperimentDeltas:
    """Deltas of every scenario of a stored experiment against an engineer-chosen reference scenario (default: the
    first one). Uses compare_physical_runs; the scenario order of the experiment is kept."""
    ref = next((s for s in exp.scenarios if s.index == reference_index), None)
    if ref is None:
        raise ValueError(f"El experimento no tiene el escenario {reference_index}.")
    if ref.result is None:
        raise ValueError(f"El escenario de referencia {reference_index} falló ({ref.error}): no hay resultados con los que comparar.")
    rows = []
    for s in exp.scenarios:
        cmp = compare_physical_runs(ref.result, s.result, metrics=metrics) if s.result is not None else None
        rows.append(ScenarioDelta(index=s.index, factors=s.factors, is_reference=s.index == reference_index,
                                  error=s.error, comparison=cmp))
    return ExperimentDeltas(experiment_id=exp.experiment_id, reference_index=reference_index, scenarios=rows)
