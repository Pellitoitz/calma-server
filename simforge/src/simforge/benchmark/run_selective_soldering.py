"""Selective-soldering benchmark runner.

    python -m simforge.benchmark.run_selective_soldering [--dir benchmark] [--no-sensitivity]
    simforge benchmark selective-soldering

1. load configuration  2. check inputs (stop if anything is missing)  3. run racks 1..10
4. save engine results  5. import AnyLogic results (if any)  6. compare  7. report  8. charts
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import ENGINE_NAME, ENGINE_VERSION, __version__
from ..analytics.diagnostics import capacity_bounds
from ..domain.paths import set_value
from ..experiments.runner import SimulationResult, run_simulation
from ..library.registry import ComponentRegistry
from ..validation.verifier import compile_model
from .compare import KPI_COLUMNS, compare, load_reference, load_tolerances, reference_template, write_csv
from .selective_soldering import Config, InputCheck, build_model, check_inputs, required_inputs_markdown

CONFIG = "selective_soldering_config.yaml"
REFERENCE = "anylogic_results.csv"
KPI_DEFS = "anylogic_kpi_definitions.yaml"
EXPLANATIONS = "difference_explanations.yaml"

INVESTIGATION_ORDER = [
    ("kpi_definition", "KPI definition mismatch (formula, period, included states)"),
    ("initial_conditions", "Initial conditions (rack location, empty system, operator location)"),
    ("event_ordering", "Event ordering"),
    ("simultaneous_events", "Simultaneous events (who gets the operator at the same timestamp)"),
    ("seize_release", "Resource seize/release semantics (order carriers/operator, release before moving)"),
    ("buffer_capacity", "Buffer capacity semantics (does a unit keep its place until picked up?)"),
    ("blocking", "Blocking behaviour (blocking-after-service)"),
    ("starvation", "Starvation behaviour"),
    ("operator_priority", "Operator priority / WIP_TARGET_PRIORITY rule"),
    ("transport_timing", "Transport timing (walk to origin, load, travel, unload, return)"),
    ("rack_conservation", "Rack conservation"),
    ("second_branch", "Second branch routing"),
    ("warmup", "Warm-up / statistics reset"),
    ("end_of_simulation", "End-of-simulation behaviour (units finishing exactly at 8 h, partial work)"),
    ("randomness", "Random seed / distributions"),
    ("time_resolution", "Floating point / time resolution"),
]


@dataclass
class BenchmarkRun:
    check: InputCheck
    engine: dict[int, dict[str, Any]] = field(default_factory=dict)
    comparison: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, Path] = field(default_factory=dict)
    status: str = "BLOCKED"


# ------------------------------------------------------------------------------------------ KPIs
def _transport_ids(model) -> list[str]:
    return [n.id for n in model.nodes if n.component in ("rack_transport", "transport")]


def extract(res: SimulationResult, model, cfg: Config) -> dict[str, Any]:
    k = res.kpis.mean
    horizon_h = float(cfg.v("simulation.horizon")) - float(cfg.v("simulation.warmup"))
    exclusive = cfg.v("simulation.production_definition") == "completions_strictly_before_stop"
    prod = k("units_completed_before_horizon") if exclusive else k("units_completed")
    tids = _transport_ids(model)
    stats = res.kpis.stats
    row: dict[str, Any] = {
        "production": prod,
        "throughput": prod / horizon_h if horizon_h > 0 else None,
        "avg_wip": k("avg_wip"),
        "max_wip": k("max_wip"),
        "lead_time": k("avg_lead_time_s"),
        "operator_utilization": k("resource.operator.utilization"),
        "selective_utilization": k("node.selective_1.utilization"),
        "selective_starvation": k("node.selective_1.starved"),
        "selective_blocking": k("node.selective_1.blocked"),
        "trips": sum(k(f"node.{t}.trips") for t in tids) if tids else 0,
        "racks_transported": sum(k(f"node.{t}.units_transported") for t in tids) if tids else 0,
        "walking_time": k("resource.operator.walking_h"),
        # engine-only detail (not in the AnyLogic template)
        "production_inclusive": k("units_completed"),
        "production_strictly_before_horizon": k("units_completed_before_horizon"),
        "assembly_time_h": k("resource.operator.working_h.assembly") if "resource.operator.working_h.assembly" in stats else 0.0,
        "review_time_h": k("resource.operator.working_h.review") if "resource.operator.working_h.review" in stats else 0.0,
        "transport_time_h": sum(k(key) for key in stats if key.startswith(("resource.operator.working_h.", "resource.operator.transporting_h."))
                                and key.split(".")[-1] in tids),
        "idle_time_h": k("resource.operator.idle_h"),
        "preemptions": k("resource.operator.preemptions"),
        "avg_racks_per_trip": (sum(k(f"node.{t}.units_transported") for t in tids) / max(1, sum(k(f"node.{t}.trips") for t in tids))) if tids else None,
        "avg_queue_assembly_conveyor": k("node.assembly_conveyor.avg_content") if "node.assembly_conveyor.avg_content" in stats else None,
        "avg_queue_selective_entry": k("node.selective_entry.avg_content"),
        "avg_queue_selective_out": k("node.selective_out.avg_content"),
        "selective2_utilization": k("node.selective_2.utilization") if "node.selective_2.utilization" in stats else None,
        "racks_available_avg": k("resource.racks.avg_at.available") if "resource.racks.avg_at.available" in stats else None,
        "assembly_blocking": k("node.assembly.blocked"),
    }
    return row


# ------------------------------------------------------------------------------------------ run
def run_benchmark(bench_dir: Path, registry: ComponentRegistry, sensitivity: bool = True, charts: bool = True) -> BenchmarkRun:
    cfg = Config.load(bench_dir / CONFIG)
    chk = check_inputs(cfg)
    run = BenchmarkRun(check=chk)
    (bench_dir / "required_inputs.md").write_text(required_inputs_markdown(cfg), encoding="utf-8")
    run.files["required_inputs"] = bench_dir / "required_inputs.md"
    ref_path = bench_dir / REFERENCE
    if not ref_path.exists():
        ref_path.write_text(reference_template(list(cfg.v("experiment.racks") or range(1, 11))), encoding="utf-8")
    if not chk.runnable:
        run.status = "BLOCKED"
        run.files["report"] = _write_report(bench_dir, cfg, run, {}, {}, {})
        return run

    racks_values = [int(x) for x in cfg.v("experiment.racks")]
    manifest: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION, "app_version": __version__, "config_file": CONFIG, "config_hash": cfg.hash,
        "base_seed": cfg.v("simulation.base_seed"), "replications": cfg.v("simulation.replications"),
        "dispatch_timing": cfg.v("simulation.dispatch_timing"), "python": platform.python_version(), "git_commit": _git_commit(),
        "official_inputs": chk.official, "scenarios": {},
    }
    gen_dir = bench_dir / "generated_models"
    gen_dir.mkdir(exist_ok=True)
    timeseries: list[dict[str, Any]] = []
    extra: dict[int, dict[str, Any]] = {}
    for racks in racks_values:
        model = build_model(cfg, racks)
        (gen_dir / f"racks_{racks:02d}.yaml").write_text(yaml.safe_dump(model.model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
        try:
            res = run_simulation(model, registry, keep_records=True)
        except Exception as e:  # noqa: BLE001 - a failing scenario is reported, never hidden
            run.engine[racks] = {"error": f"{type(e).__name__}: {e}"}
            continue
        row = extract(res, model, cfg)
        cm = compile_model(model, registry)
        bounds = capacity_bounds(cm)
        row["theoretical_max_throughput"] = bounds[0].units_per_hour if bounds else None
        row["theoretical_bound_subject"] = bounds[0].subject if bounds else None
        row["sanity_throughput_le_bound"] = (row["throughput"] <= row["theoretical_max_throughput"] * 1.0001 + 1e-9) if bounds else None
        row["invariant_checks"] = sum(r.invariant_checks for r in res.records)
        if sensitivity:
            alt_timing = "immediate" if cfg.v("simulation.dispatch_timing") == "end_of_timestep" else "end_of_timestep"
            alt = run_simulation(set_value(model, "simulation.dispatch_timing", alt_timing), registry)
            alt_row = extract(alt, model, cfg)
            row["sensitivity_timing"] = alt_timing
            row["sensitivity_production"] = alt_row["production"]
            row["sensitivity_production_delta"] = alt_row["production"] - row["production"]
            row["sensitivity_operator_utilization_delta"] = alt_row["operator_utilization"] - row["operator_utilization"]
        run.engine[racks] = row
        manifest["scenarios"][racks] = {"model_hash": res.model_hash, "seeds": res.seeds, "component_versions": res.component_versions,
                                        "run_id": res.run_id, "generated_model": f"generated_models/racks_{racks:02d}.yaml"}
        if res.records:
            times = sorted(res.records[0].completion_times)
            for hour in range(1, int(float(cfg.v("simulation.horizon"))) + 1):
                timeseries.append({"racks": racks, "hour": hour, "cumulative_production": sum(1 for t in times if t <= hour * 3600)})
        extra[racks] = row

    columns = ["racks", *[c for c, _, _ in KPI_COLUMNS]]
    rows = [{"racks": sc, **r} for sc, r in sorted(run.engine.items())]
    write_csv(bench_dir / "engine_results.csv", rows, columns + ["error"])
    write_csv(bench_dir / "engine_results_detail.csv", rows)
    write_csv(bench_dir / "engine_production_timeseries.csv", timeseries, ["racks", "hour", "cumulative_production"])
    reference = load_reference(ref_path)
    tolerances = load_tolerances(cfg.raw.get("tolerances", {}))
    run.comparison = compare(run.engine, reference, tolerances)
    write_csv(bench_dir / "comparison.csv", run.comparison)
    (bench_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    run.files.update({k: bench_dir / f for k, f in [("engine_results", "engine_results.csv"), ("engine_detail", "engine_results_detail.csv"),
                                                     ("timeseries", "engine_production_timeseries.csv"), ("comparison", "comparison.csv"),
                                                     ("manifest", "run_manifest.json")]})
    if charts:
        run.files.update(_charts(bench_dir, run.engine, reference))
    run.status = _status(chk, cfg, reference, run.comparison, _explanations(bench_dir), run.engine)
    run.files["report"] = _write_report(bench_dir, cfg, run, reference, tolerances, manifest)
    return run


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def _explanations(bench_dir: Path) -> list[dict]:
    p = bench_dir / EXPLANATIONS
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("explanations", []) if p.exists() else []


def _status(chk: InputCheck, cfg: Config, reference, comparison, explanations, engine) -> str:
    if not chk.runnable:
        return "BLOCKED — missing inputs"
    if any(r.get("error") for r in engine.values()) or any(r.get("sanity_throughput_le_bound") is False for r in engine.values()):
        return "NOT VALIDATED — engine errors or sanity-check failures"
    has_ref = any(v is not None for row in reference.values() for v in row.values())
    if not has_ref:
        return "PRELIMINARY — no AnyLogic results imported yet"
    explained = {(e.get("racks"), e.get("kpi")) for e in explanations if e.get("status") == "explained"}
    fails = [r for r in comparison if r["status"] and r["status"].startswith("FAIL")]
    unexplained = [r for r in fails if (r["racks"], r["kpi"]) not in explained]
    tol_agreed = all(t.get("status") == "AGREED" for t in cfg.raw.get("tolerances", {}).values())
    if unexplained:
        return f"NOT VALIDATED — {len(unexplained)} differences outside tolerance without explanation"
    if not chk.official or not tol_agreed or any(r["status"] == "NO_REFERENCE" for r in comparison):
        return "PRELIMINARY — inputs to confirm / tolerances not agreed / incomplete reference"
    return "CANDIDATE FOR ENGINEER APPROVAL — all KPIs within tolerance or explained (approval is the engineer's decision)"


# ------------------------------------------------------------------------------------------ charts
def _charts(bench_dir: Path, engine: dict, reference: dict) -> dict[str, Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {}
    out = bench_dir / "charts"
    out.mkdir(exist_ok=True)
    files = {}
    specs = [("production", "Production (racks in 8 h)"), ("throughput", "Throughput (racks/h)"), ("avg_wip", "Average WIP (racks)"),
             ("operator_utilization", "Operator utilization"), ("selective_utilization", "Selective utilization")]
    for col, title in specs:
        xs = [sc for sc, r in sorted(engine.items()) if r.get(col) is not None]
        ys = [engine[sc][col] for sc in xs]
        rx = [sc for sc in sorted(reference) if reference[sc].get(col) is not None]
        ry = [reference[sc][col] for sc in rx]
        fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=120)
        ax.plot(xs, ys, color="#2a78d6", linewidth=2, marker="o", markersize=6, label="SimForge engine")
        if rx:
            ax.plot(rx, ry, color="#eb6834", linewidth=2, linestyle="--", marker="s", markersize=6, label="AnyLogic")
        ax.set_xlabel("Number of racks")
        ax.set_title(title + ("" if rx else "  (no AnyLogic data yet)"), fontsize=10, loc="left")
        ax.set_xticks(sorted(set(xs) | set(rx)) or [1])
        ax.grid(alpha=0.25)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        if col.endswith("utilization"):
            ax.set_ylim(0, 1.05)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        p = out / f"{col}.png"
        fig.savefig(p)
        plt.close(fig)
        files[f"chart_{col}"] = p
    return files


# ------------------------------------------------------------------------------------------ report
def _f(x: Any, nd: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "yes" if x else "NO"
    if isinstance(x, float):
        return f"{x:.{nd}f}".rstrip("0").rstrip(".") if abs(x) < 1e6 else f"{x:.3g}"
    return str(x)


def _write_report(bench_dir: Path, cfg: Config, run: BenchmarkRun, reference: dict, tolerances: dict, manifest: dict) -> Path:
    chk = run.check
    defs_p = bench_dir / KPI_DEFS
    defs = (yaml.safe_load(defs_p.read_text(encoding="utf-8")) or {}) if defs_p.exists() else {}
    L = ["# Benchmark report — selective soldering (SimForge vs. AnyLogic)", "",
         f"*Generated:* {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · *engine* {ENGINE_NAME} {ENGINE_VERSION} · "
         f"*config hash* `{cfg.hash}` · *git* `{manifest.get('git_commit') or _git_commit()}`", "",
         f"## Validation status: **{run.status}**", "",
         "> Parameters are never tuned to match AnyLogic. Every difference must be explained (section 8) before any claim of equivalence.", ""]
    # 1
    L += ["## 1. Model configuration", "", "| Parameter | Value | Unit | Status |", "|---|---|---|---|"]
    for key, e in cfg.entries():
        if key.startswith(("benchmark.",)):
            continue
        L.append(f"| `{key}` | {_f(e.get('value'))} | {e.get('unit', '')} | {e.get('status')} |")
    L += ["", "Structure built from generic library components (see `generated_models/`); SimForge engine semantics in "
          "`docs/simulation_engine.md`, operator rule in `docs/benchmark_operator_logic.md`.", ""]
    # 2
    L += ["## 2. AnyLogic configuration", "",
          f"- Model file: {_f(cfg.v('benchmark.anylogic_model_file'))} · version: {_f(cfg.v('benchmark.anylogic_version'))}",
          f"- Simultaneous events: {_f(cfg.v('simulation.simultaneous_events'))} · randomness: {_f(cfg.v('simulation.randomness'))} · "
          f"warm-up: {_f(cfg.v('simulation.warmup'))} h · production definition: {_f(cfg.v('simulation.production_definition'))}",
          f"- KPI definitions file (`{KPI_DEFS}`): {'present' if defs else '**missing**'}", ""]
    # 3
    L += ["## 3. KPI definitions", "", "Full SimForge definitions: `docs/benchmark_kpi_definitions.md`.", "",
          "| KPI | Unit | AnyLogic definition |", "|---|---|---|"]
    for col, unit, _ in KPI_COLUMNS:
        L.append(f"| {col} | {unit} | {_f((defs.get('kpis') or {}).get(col)) if defs else '**NOT PROVIDED**'} |")
    L.append("")
    if not chk.runnable:
        L += ["## 4–8. Results", "", "Not run: the benchmark is **BLOCKED** until the missing inputs are provided.", ""]
    else:
        # 4
        cols = [c for c, _, _ in KPI_COLUMNS]
        L += ["## 4. Results (engine | AnyLogic)", "", "| racks | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
        for sc, r in sorted(run.engine.items()):
            if r.get("error"):
                L.append(f"| {sc} | ENGINE ERROR: {r['error']} |")
                continue
            ref = reference.get(sc, {})
            L.append(f"| {sc} | " + " | ".join(f"{_f(r.get(c))} \\| {_f(ref.get(c))}" for c in cols) + " |")
        L += ["", "Engine detail (operator time split, queues, sanity bound, event-ordering sensitivity): `engine_results_detail.csv`.", "",
              "| racks | assembly h | review h | transport h | walking h | idle h | trips | racks/trip | max throughput bound | ≤ bound | "
              "Δ production if decisions taken immediately |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for sc, r in sorted(run.engine.items()):
            if r.get("error"):
                continue
            L.append(f"| {sc} | {_f(r['assembly_time_h'])} | {_f(r['review_time_h'])} | {_f(r['transport_time_h'])} | {_f(r['walking_time'])} | "
                     f"{_f(r['idle_time_h'])} | {_f(r['trips'])} | {_f(r['avg_racks_per_trip'])} | {_f(r['theoretical_max_throughput'])} "
                     f"({r['theoretical_bound_subject']}) | {_f(r['sanity_throughput_le_bound'])} | {_f(r.get('sensitivity_production_delta'))} |")
        L.append("")
        # 5
        L += ["## 5. Differences", "", "absolute_difference = engine − AnyLogic · relative_error_% = |engine − AnyLogic| / |AnyLogic| × 100 "
              "· pp = percentage points (fractions)", "",
              "| racks | KPI | AnyLogic | engine | abs diff | rel % | pp | tolerance | status |", "|---|---|---|---|---|---|---|---|---|"]
        for r in run.comparison:
            L.append(f"| {r['racks']} | {r['kpi']} | {_f(r['anylogic'])} | {_f(r['engine'])} | {_f(r['absolute_difference'])} | "
                     f"{_f(r['relative_error_percent'], 2)} | {_f(r['pp_difference'], 2)} | {_f(r['tolerance'])} | {r['status']} |")
        passed = [r for r in run.comparison if r["status"] == "PASS"]
        failed = [r for r in run.comparison if (r["status"] or "").startswith("FAIL")]
        L += ["", "## 6. Passed tolerances", "", f"{len(passed)} KPI×scenario checks passed."]
        L += [f"- racks {r['racks']} · {r['kpi']}" for r in passed[:200]]
        L += ["", "## 7. Failed tolerances", "", f"{len(failed)} KPI×scenario checks failed." if failed else "None (or no reference values yet)."]
        L += [f"- racks {r['racks']} · {r['kpi']}: engine {_f(r['engine'])} vs AnyLogic {_f(r['anylogic'])} (tolerance {r['tolerance']})" for r in failed]
        L += ["", "Tolerances (all must be AGREED before a final verdict):", "", "| KPI | type | value | status | justification |", "|---|---|---|---|---|"]
        L += [f"| {k} | {t.type} | {t.value:g} | {t.status} | {t.justification} |" for k, t in tolerances.items()]
        # 8
        expl = _explanations(bench_dir)
        L += ["", "## 8. Possible explanations (investigate in this order; never tune parameters)", ""]
        if not failed:
            L.append("No failed checks to investigate yet.")
        for r in failed:
            e = run.engine.get(r["racks"], {})
            done = [x for x in expl if x.get("racks") == r["racks"] and x.get("kpi") == r["kpi"]]
            L.append(f"### racks {r['racks']} · {r['kpi']}")
            if done:
                L += [f"- **{x.get('status')}** ({x.get('cause')}): {x.get('explanation')}" for x in done]
            L += ["", "Automatic evidence:",
                  f"- model is deterministic ({cfg.v('simulation.randomness')}): randomness {'excluded' if cfg.v('simulation.randomness') == 'deterministic' else 'possible'}",
                  f"- simultaneous-event sensitivity: production changes by {_f(e.get('sensitivity_production_delta'))} when decisions are taken immediately",
                  f"- end of simulation: production inclusive {_f(e.get('production_inclusive'))} vs strictly before 8 h {_f(e.get('production_strictly_before_horizon'))}",
                  f"- rack conservation invariant checks passed: {_f(e.get('invariant_checks'))}",
                  f"- theoretical bound {_f(e.get('theoretical_max_throughput'))} ({e.get('theoretical_bound_subject')}); throughput ≤ bound: {_f(e.get('sanity_throughput_le_bound'))}",
                  f"- short trace for manual comparison: `simforge benchmark trace --racks {r['racks']} --minutes 15`", "",
                  "Checklist: " + " → ".join(f"{i + 1}. {label}" for i, (_, label) in enumerate(INVESTIGATION_ORDER)), ""]
    # 9
    L += ["## 9. Outstanding questions", "", f"Missing inputs ({len(chk.missing)}):"]
    L += [f"- `{k}` — {cfg.entry(k).get('note') or ''} *Where:* {cfg.entry(k).get('anylogic') or '—'}" for k in chk.missing] or ["- none"]
    L += ["", f"Stated in conversation, to confirm against AnyLogic ({len(chk.unconfirmed)}):"]
    L += [f"- `{k}` = {_f(cfg.v(k))}" for k in chk.unconfirmed] or ["- none"]
    if chk.invalid:
        L += ["", "Invalid / not implemented:"] + [f"- {x}" for x in chk.invalid]
    L += ["", "Full list with where to look in AnyLogic: `required_inputs.md`.", "",
          "## 10. Validation status", "", f"**{run.status}**", "",
          "Rules: BLOCKED (inputs missing) → PRELIMINARY (runs, but inputs unconfirmed / tolerances not agreed / no reference) → "
          "NOT VALIDATED (unexplained differences or engine/sanity errors) → CANDIDATE FOR ENGINEER APPROVAL (every KPI within an agreed "
          "tolerance or explained). SimForge never marks the model as validated by itself.", ""]
    p = bench_dir / "benchmark_report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------ short trace
def run_trace(bench_dir: Path, registry: ComponentRegistry, racks: int, minutes: float) -> tuple[list[dict], list[dict], Path]:
    cfg = Config.load(bench_dir / CONFIG)
    model = build_model(cfg, racks)
    model = set_value(model, "simulation.horizon", {"value": minutes, "unit": "min"})
    model = set_value(model, "simulation.warmup", {"value": 0, "unit": "s"})
    res = run_simulation(model, registry, replications=1, trace=True)
    rec = res.records[0]
    out = bench_dir / "traces"
    out.mkdir(exist_ok=True)
    stem = f"racks_{racks:02d}_{minutes:g}min"
    write_csv(out / f"{stem}_events.csv", rec.events or [])
    write_csv(out / f"{stem}_decisions.csv", [{**d, "candidates": json.dumps(d["candidates"]), "state": json.dumps(d["state"]),
                                                "system": json.dumps(d["system"]), "current_task": json.dumps(d["current_task"]),
                                                "units": ",".join(d["units"])} for d in rec.decisions or []])
    return rec.events or [], rec.decisions or [], out / stem


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="benchmark", type=Path)
    ap.add_argument("--no-sensitivity", action="store_true")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args(argv)
    run = run_benchmark(a.dir, ComponentRegistry.load_default(), sensitivity=not a.no_sensitivity, charts=not a.no_charts)
    print(f"Status: {run.status}")
    if run.check.missing:
        print(f"{len(run.check.missing)} inputs missing -> see {a.dir / 'required_inputs.md'}")
    for k, p in run.files.items():
        print(f"  {k}: {p}")
    return 0 if run.check.runnable else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
