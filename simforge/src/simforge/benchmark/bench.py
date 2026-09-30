"""Benchmark: SimForge vs. a reference model (e.g. AnyLogic), scenario by scenario.

Rules (by design):
  * reference values are IMPORTED from a CSV filled by the engineer; nothing is ever estimated;
  * missing reference values are reported as NO_REFERENCE, never interpolated;
  * the comparison NEVER changes model parameters (no curve fitting): differences are investigated
    and classified by cause (logic, warm-up, KPI definition, simultaneous events, capacity,
    transport, operator rules, randomness).

    abs_error      = engine - reference
    rel_error_pct  = |engine - reference| / reference x 100   (n/a when reference = 0)
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..domain.io import load_model
from ..domain.isms import ExperimentSpec, Factor, ISMSModel
from ..domain.paths import set_value
from ..experiments.runner import ExperimentResult, run_experiment
from ..library.registry import ComponentRegistry
from ..validation.verifier import VerificationReport, verify

CAUSES = {
    "logic": "Flow/logic difference (routing, seize/release order, blocking semantics). Check the event log of the scenario.",
    "warmup": "Warm-up / initial state (empty system vs. pre-loaded, statistics window).",
    "kpi_definition": "KPI defined differently (e.g. utilization incl./excl. blocked or setup time; throughput per net vs. gross hour).",
    "simultaneous_events": "Order of simultaneous events (ties at the same timestamp: who gets the operator first).",
    "capacity": "Capacities (buffers, conveyor, stations, number of racks/operators) not equivalent.",
    "transport": "Transport/walking (distances, speeds, load/unload, empty returns, who transports).",
    "operator_rules": "Operator decision rule (WIP target, priorities, pre-emption) not equivalent.",
    "randomness": "Stochastic noise (compare the difference with the engine CI; check replications/seeds).",
}


class BenchMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str  # column name in the reference CSV
    label: str
    engine_key: str  # SimForge KPI key, e.g. node.selective_1.utilization
    unit: str = ""
    tolerance_rel_pct: float = Field(default=2.0, ge=0)
    tolerance_abs: float = Field(default=0.0, ge=0)  # difference also accepted if |abs_error| <= tolerance_abs
    likely_causes: list[str] = Field(default_factory=list)  # keys of CAUSES, investigation starting points


class BenchmarkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: str  # path relative to the spec file
    factor: Factor
    scenario_column: str = "scenario"
    replications: int | None = None
    metrics: list[BenchMetric]
    reference_csv: str = "anylogic_results.csv"
    reference_definitions: str = "anylogic_definitions.yaml"
    notes: str = ""

    @classmethod
    def load(cls, path: Path) -> "BenchmarkSpec":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class BenchmarkNotReady(Exception):
    def __init__(self, report: VerificationReport):
        self.report = report
        super().__init__("El modelo del benchmark no es ejecutable todavía.")


def _num(x: str | None) -> float | None:
    if x is None or str(x).strip() == "":
        return None
    return float(str(x).replace(",", "."))


def load_reference(path: Path, spec: BenchmarkSpec) -> dict[float, dict[str, float | None]]:
    """{scenario value: {metric id: value or None}}. Blank cells stay None (never filled in)."""
    if not path.exists():
        return {}
    out: dict[float, dict[str, float | None]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sc = _num(row.get(spec.scenario_column))
            if sc is None:
                continue
            out[sc] = {m.id: _num(row.get(m.id)) for m in spec.metrics}
    return out


def reference_template(spec: BenchmarkSpec) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([spec.scenario_column, *[m.id for m in spec.metrics]])
    for v in spec.factor.values:
        w.writerow([v, *[""] * len(spec.metrics)])
    return buf.getvalue()


def prepare_model(spec: BenchmarkSpec, base_dir: Path) -> ISMSModel:
    return load_model(base_dir / spec.model)


def run_engine(spec: BenchmarkSpec, base_dir: Path, registry: ComponentRegistry) -> ExperimentResult:
    model = prepare_model(spec, base_dir)
    rep, _ = verify(set_value(model, spec.factor.path, spec.factor.values[0]), registry)
    if not rep.ok:
        raise BenchmarkNotReady(rep)
    exp = ExperimentSpec(name=spec.name, factors=[spec.factor], replications=spec.replications, max_scenarios=len(spec.factor.values))
    return run_experiment(model, exp, registry)


def engine_rows(spec: BenchmarkSpec, exp: ExperimentResult) -> list[dict[str, Any]]:
    rows = []
    for s in exp.scenarios:
        row: dict[str, Any] = {spec.scenario_column: s.factors[spec.factor.path]}
        if s.result is None:
            row["error"] = s.error
        else:
            for m in spec.metrics:
                st = s.result.kpis.stats.get(m.engine_key)
                row[m.id] = st.mean if st else None
                row[f"{m.id}__ci95"] = st.half_width if st and st.n > 1 else None
        rows.append(row)
    return rows


def compare(spec: BenchmarkSpec, engine: list[dict[str, Any]], reference: dict[float, dict[str, float | None]],
            deterministic: bool) -> list[dict[str, Any]]:
    out = []
    for row in engine:
        sc = float(row[spec.scenario_column])
        ref_row = reference.get(sc, {})
        for m in spec.metrics:
            e, r, ci = row.get(m.id), ref_row.get(m.id), row.get(f"{m.id}__ci95")
            rec: dict[str, Any] = {"scenario": row[spec.scenario_column], "metric": m.id, "label": m.label, "unit": m.unit,
                                   "engine": e, "engine_ci95": ci, "reference": r, "abs_error": None, "rel_error_pct": None}
            if row.get("error"):
                rec["status"] = "ENGINE_ERROR"
                rec["note"] = row["error"]
            elif e is None:
                rec["status"] = "NO_ENGINE_VALUE"
            elif r is None:
                rec["status"] = "NO_REFERENCE"
            else:
                rec["abs_error"] = e - r
                rec["rel_error_pct"] = abs(e - r) / r * 100 if r != 0 else None
                ok_rel = rec["rel_error_pct"] is not None and rec["rel_error_pct"] <= m.tolerance_rel_pct
                ok_abs = abs(e - r) <= m.tolerance_abs
                rec["status"] = "OK" if (ok_rel or ok_abs) else "DIFF"
                if r == 0 and not ok_abs:
                    rec["status"] = "DIFF_REF_ZERO"
                if rec["status"] != "OK":
                    rec["noise_check"] = ("deterministic model: randomness excluded" if deterministic else
                                          ("difference within engine CI: may be noise" if ci and abs(e - r) <= 2 * ci
                                           else "difference larger than 2x engine CI half-width"))
                    rec["investigate"] = ", ".join(m.likely_causes or list(CAUSES))
            out.append(rec)
    return out


def comparison_csv(rows: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _f(x: Any, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:.2f}%" if pct else (f"{x:,.4g}" if isinstance(x, float) else str(x))


def comparison_markdown(spec: BenchmarkSpec, rows: list[dict[str, Any]], definitions: dict | None, model: ISMSModel) -> str:
    L = [f"# Benchmark: {spec.name}", "", f"*Generated:* {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · "
         f"*factor:* `{spec.factor.path}` = {spec.factor.values}", "",
         "abs_error = engine − reference · rel_error = |engine − reference| / reference × 100", "",
         "> Parameters were NOT tuned to match the reference. Differences must be explained, not fitted.", ""]
    statuses = [r["status"] for r in rows]
    L += [f"**Summary:** {statuses.count('OK')} OK · {sum(s.startswith('DIFF') for s in statuses)} DIFF · "
          f"{statuses.count('NO_REFERENCE')} without reference value · {statuses.count('ENGINE_ERROR')} engine errors", ""]
    for m in spec.metrics:
        mr = [r for r in rows if r["metric"] == m.id]
        rels = [r["rel_error_pct"] for r in mr if r["rel_error_pct"] is not None]
        L += [f"## {m.label} (`{m.engine_key}`; tolerance {m.tolerance_rel_pct}% / ±{m.tolerance_abs} {m.unit})", "",
              "| Scenario | Engine | ±CI95 | AnyLogic | Abs error | Rel error | Status |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['scenario']} | {_f(r['engine'])} | {_f(r['engine_ci95'])} | {_f(r['reference'])} | {_f(r['abs_error'])} | "
              f"{_f(r['rel_error_pct'], True)} | {r['status']} |" for r in mr]
        if rels:
            L += ["", f"Mean |rel error| {sum(rels) / len(rels):.2f}% · max {max(rels):.2f}%"]
        L.append("")
    diffs = [r for r in rows if r["status"].startswith("DIFF")]
    L += ["## Investigation of differences", ""]
    if not diffs:
        L.append("No differences outside tolerance (or no reference values yet).")
    for r in diffs:
        L.append(f"- **{r['label']} @ {spec.scenario_column}={r['scenario']}**: engine {_f(r['engine'])} vs "
                 f"{_f(r['reference'])} ({_f(r['rel_error_pct'], True)}). {r.get('noise_check', '')}. "
                 f"Start with: {r.get('investigate', '')}.")
    L += ["", "### Cause checklist (fill in the conclusion for every DIFF before approving the model)", "",
          "| Cause | What to check | Conclusion |", "|---|---|---|"]
    L += [f"| {k} | {v} | _pending_ |" for k, v in CAUSES.items()]
    L += ["", "### KPI definitions", "", "| Metric | SimForge definition | AnyLogic definition |", "|---|---|---|"]
    from ..analytics.kpis import metric_info
    for m in spec.metrics:
        ref_def = (definitions or {}).get("metrics", {}).get(m.id) or "**NOT PROVIDED**"
        L.append(f"| {m.id} | {metric_info(m.engine_key)[2]} | {ref_def} |")
    wu = (definitions or {}).get("warmup") or "**NOT PROVIDED**"
    L += ["", f"Warm-up — SimForge: {model.simulation.warmup.value:g} {model.simulation.warmup.unit} "
          f"({model.simulation.kind}); AnyLogic: {wu}"]
    return "\n".join(L) + "\n"


def write_outputs(spec: BenchmarkSpec, base_dir: Path, exp: ExperimentResult, registry: ComponentRegistry) -> dict[str, Path]:
    out_dir = base_dir / "results"
    out_dir.mkdir(exist_ok=True)
    model = prepare_model(spec, base_dir)
    rows = engine_rows(spec, exp)
    paths = {"engine": out_dir / "engine_results.csv"}
    paths["engine"].write_text(comparison_csv(rows), encoding="utf-8")
    reference = load_reference(base_dir / spec.reference_csv, spec)
    defs_path = base_dir / spec.reference_definitions
    definitions = yaml.safe_load(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else None
    deterministic = all(s.result is None or all(v.std == 0 for v in s.result.kpis.stats.values() if v.n > 1)
                        for s in exp.scenarios) and _is_deterministic(model, registry)
    cmp_rows = compare(spec, rows, reference, deterministic)
    paths["comparison_csv"] = out_dir / "comparison.csv"
    paths["comparison_csv"].write_text(comparison_csv(cmp_rows), encoding="utf-8")
    paths["comparison_md"] = out_dir / "comparison.md"
    paths["comparison_md"].write_text(comparison_markdown(spec, cmp_rows, definitions, model), encoding="utf-8")
    return paths


def _is_deterministic(model: ISMSModel, registry: ComponentRegistry) -> bool:
    rep, cm = verify(model, registry)
    if cm is None:
        return False
    for c in cm.nodes.values():
        for f in ("process_time", "load_time", "unload_time", "interarrival"):
            d = getattr(c.params, f, None)
            if d is not None and not d.is_deterministic:
                return False
        if getattr(c.params, "failures", None) or getattr(c.params, "yield_rate", 1) < 1 or len(c.successors) > 1:
            return False
    return True
