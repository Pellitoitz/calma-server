"""Simulation & experiment runners.

* Replication i always uses seed = base_seed + i  -> full reproducibility and
  common random numbers across scenarios (fairer comparisons).
* Results are cached by (model content hash, engine version, seed).
* Experiments: grid search over factors with an explicit scenario cap.
  The design is pluggable (random search / Optuna later).
"""

from __future__ import annotations

import hashlib
import itertools
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .. import ENGINE_NAME, ENGINE_VERSION, __version__
from ..analytics.diagnostics import Finding, diagnose
from ..analytics.kpis import ReplicatedKPIs, aggregate, compute_run_kpis
from ..domain.isms import ExperimentSpec, ISMSModel
from ..domain.paths import get_value, set_value
from ..engine.base import RunRecord, SimulationEngine
from ..engine.des.engine import DesEngine
from ..library.registry import ComponentRegistry
from ..validation.verifier import compile_model


class ResultCache(Protocol):
    def get(self, key: str) -> dict[str, float] | None: ...
    def put(self, key: str, kpis: dict[str, float]) -> None: ...


def cache_key(model_hash: str, seed: int) -> str:
    return hashlib.sha256(f"{model_hash}|{ENGINE_NAME}|{ENGINE_VERSION}|{seed}".encode()).hexdigest()[:24]


@dataclass
class SimulationResult:
    run_id: str
    model_name: str
    model_hash: str
    component_versions: dict[str, str]
    engine: str
    engine_version: str
    app_version: str
    seeds: list[int]
    started_at: str
    wall_time_s: float
    horizon_s: float
    warmup_s: float
    kpis: ReplicatedKPIs
    per_replication: list[dict[str, float]]
    findings: list[Finding]
    cache_hits: int = 0
    records: list[RunRecord] = field(default_factory=list)  # raw data; kept in memory only (trace/debug)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "model_name": self.model_name, "model_hash": self.model_hash,
            "component_versions": self.component_versions, "engine": self.engine,
            "engine_version": self.engine_version, "app_version": self.app_version, "seeds": self.seeds,
            "started_at": self.started_at, "wall_time_s": self.wall_time_s, "horizon_s": self.horizon_s,
            "warmup_s": self.warmup_s, "kpis": self.kpis.to_dict(), "per_replication": self.per_replication,
            "findings": [f.to_dict() for f in self.findings], "cache_hits": self.cache_hits,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SimulationResult":
        return cls(**{**d, "kpis": ReplicatedKPIs.from_dict(d["kpis"]),
                      "findings": [Finding(**f) for f in d["findings"]], "records": []})


def run_simulation(
    model: ISMSModel,
    registry: ComponentRegistry,
    replications: int | None = None,
    base_seed: int | None = None,
    trace: bool | None = None,
    engine: SimulationEngine | None = None,
    cache: ResultCache | None = None,
    keep_records: bool = False,
) -> SimulationResult:
    engine = engine or DesEngine()
    cm = compile_model(model, registry)  # raises ModelError with readable issues
    reps = replications or model.simulation.replications
    seed0 = model.simulation.base_seed if base_seed is None else base_seed
    trace = model.simulation.trace if trace is None else trace
    h = model.content_hash()
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    per_rep, records, hits = [], [], 0
    for i in range(reps):
        seed = seed0 + i
        key = cache_key(h, seed)
        cached = cache.get(key) if (cache and not trace and not keep_records) else None
        if cached is not None:
            per_rep.append(cached)
            hits += 1
            continue
        rec = engine.run(cm, seed, trace=trace)
        k = compute_run_kpis(rec, cm)
        per_rep.append(k)
        if cache:
            cache.put(key, k)
        if trace or keep_records:
            records.append(rec)
    agg = aggregate(per_rep)
    return SimulationResult(
        run_id=uuid.uuid4().hex[:10], model_name=model.meta.name, model_hash=h,
        component_versions=cm.component_versions, engine=engine.name, engine_version=engine.version,
        app_version=__version__, seeds=[seed0 + i for i in range(reps)], started_at=started,
        wall_time_s=round(time.perf_counter() - t0, 4), horizon_s=cm.horizon_s, warmup_s=cm.warmup_s,
        kpis=agg, per_replication=per_rep, findings=diagnose(cm, agg), cache_hits=hits, records=records,
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


class ExperimentError(ValueError):
    pass


@dataclass
class Scenario:
    index: int
    factors: dict[str, Any]
    result: SimulationResult | None = None
    error: str | None = None


@dataclass
class ExperimentResult:
    experiment_id: str
    spec: ExperimentSpec
    base_model_hash: str
    scenarios: list[Scenario]
    started_at: str
    wall_time_s: float

    def table(self, metrics: list[str]) -> list[dict[str, Any]]:
        rows = []
        for s in self.scenarios:
            row: dict[str, Any] = {"scenario": s.index, **{_short(p): v for p, v in s.factors.items()}}
            if s.result:
                for m in metrics:
                    st = s.result.kpis.stats.get(m)
                    row[m] = st.mean if st else None
                    if st and st.n > 1:
                        row[f"{m}_ci95"] = st.half_width
            else:
                row["error"] = s.error
            rows.append(row)
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {"experiment_id": self.experiment_id, "spec": self.spec.model_dump(mode="json"),
                "base_model_hash": self.base_model_hash, "started_at": self.started_at,
                "wall_time_s": self.wall_time_s,
                "scenarios": [{"index": s.index, "factors": s.factors, "error": s.error,
                               "result": s.result.to_dict() if s.result else None} for s in self.scenarios]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperimentResult":
        return cls(d["experiment_id"], ExperimentSpec.model_validate(d["spec"]), d["base_model_hash"],
                   [Scenario(s["index"], s["factors"], SimulationResult.from_dict(s["result"]) if s["result"] else None, s["error"])
                    for s in d["scenarios"]], d["started_at"], d["wall_time_s"])


def _short(path: str) -> str:
    parts = path.split(".")
    if parts[0] in ("nodes", "resources") and len(parts) >= 3:
        return f"{parts[1]}.{parts[-1]}" if parts[-1] != "value" else f"{parts[1]}.{parts[-2]}"
    return path


def grid(spec: ExperimentSpec) -> list[dict[str, Any]]:
    n = 1
    for f in spec.factors:
        n *= len(f.values)
    if n > spec.max_scenarios:
        raise ExperimentError(
            f"El experimento genera {n} escenarios (> límite {spec.max_scenarios}). "
            "Reduce niveles/factores o sube max_scenarios conscientemente.")
    return [dict(zip([f.path for f in spec.factors], combo)) for combo in itertools.product(*[f.values for f in spec.factors])]


def validate_experiment(model: ISMSModel, spec: ExperimentSpec) -> None:
    for f in spec.factors:
        try:
            get_value(model, f.path)
        except KeyError as e:
            raise ExperimentError(f"Factor inválido '{f.path}': {e}") from None
        try:
            set_value(model, f.path, f.values[0])
        except Exception as e:  # noqa: BLE001
            raise ExperimentError(f"El valor {f.values[0]!r} no es válido para '{f.path}': {e}") from None
    grid(spec)


def run_experiment(
    model: ISMSModel,
    spec: ExperimentSpec,
    registry: ComponentRegistry,
    cache: ResultCache | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExperimentResult:
    validate_experiment(model, spec)
    combos = grid(spec)
    t0 = time.perf_counter()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    scenarios = []
    for i, combo in enumerate(combos):
        m = model
        try:
            for path, val in combo.items():
                m = set_value(m, path, val)
            res = run_simulation(m, registry, replications=spec.replications, trace=False, cache=cache)
            scenarios.append(Scenario(i, combo, res))
        except Exception as e:  # noqa: BLE001 - one bad scenario must not kill the experiment
            scenarios.append(Scenario(i, combo, None, str(e)))
        if progress:
            progress(i + 1, len(combos))
    return ExperimentResult(uuid.uuid4().hex[:10], spec, model.content_hash(), scenarios, started,
                            round(time.perf_counter() - t0, 3))
