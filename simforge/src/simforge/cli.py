"""SimForge command line. Works fully offline; no UI needed.

    simforge validate examples/02_shared_operator.yaml
    simforge run examples/02_shared_operator.yaml --reps 10
    simforge experiment examples/05_selective_soldering.yaml
    simforge report examples/02_shared_operator.yaml -o report.html
    simforge parse "Fuente infinita. Un operario monta 60 s..." -o model.yaml
    simforge library list | show <id> | docs
    simforge ai new "Linea MVP" "Fuente infinita. Un operario monta..."   (AI orchestration, see `simforge ai --help`)
    simforge data import <project> tiempos.xlsx ...   (measured data -> distributions, see `simforge data --help`)
    simforge ui
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

from .domain.io import ModelFormatError, dump_model, load_model
from .domain.isms import ExperimentSpec, Factor
from .experiments.runner import ExperimentError, run_experiment, run_simulation
from .library.registry import ComponentRegistry
from .validation.semantics import verify_model as verify
from .validation.verifier import ModelError

app = typer.Typer(add_completion=False, help="SimForge - AI-assisted industrial simulation (local).", no_args_is_help=True)
lib_app = typer.Typer(help="Component library", no_args_is_help=True)
app.add_typer(lib_app, name="library")
bench_app = typer.Typer(help="Benchmark against a reference model (e.g. AnyLogic)", no_args_is_help=True)
app.add_typer(bench_app, name="benchmark")
ai_app = typer.Typer(help="AI orchestration on workspace projects: describe -> match -> ask -> approve -> run", no_args_is_help=True)
app.add_typer(ai_app, name="ai")
from .cli_data import data_app, project_app  # noqa: E402

app.add_typer(data_app, name="data")
app.add_typer(project_app, name="project")
from .cli_calendar import calendar_app  # noqa: E402

app.add_typer(calendar_app, name="calendar")
from .cli_products import products_app  # noqa: E402

app.add_typer(products_app, name="products")


def _registry() -> ComponentRegistry:
    from .services.app import default_library_dir
    return ComponentRegistry.load_default(default_library_dir())


def _load(path: Path):
    try:
        return load_model(path)
    except (ModelFormatError, FileNotFoundError) as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(2) from None


@app.command()
def validate(model_file: Path):
    """Verify a model (errors, warnings, assumptions, readiness)."""
    rep, _ = verify(_load(model_file), _registry())
    color = "green" if rep.ok else "red"
    for i in rep.issues:
        typer.secho(str(i), fg={"error": "red", "warning": "yellow"}.get(i.level.value, None))
    typer.secho(rep.summary(), fg=color, bold=True)
    raise typer.Exit(0 if rep.ok else 1)


@app.command()
def run(model_file: Path, reps: Optional[int] = typer.Option(None, help="Replications (default: model setting)"),
        seed: Optional[int] = None, trace_dir: Optional[Path] = typer.Option(None, help="Write event/decision logs here"),
        as_json: bool = typer.Option(False, "--json", help="Print full result as JSON")):
    """Run a simulation and print KPIs."""
    from .reporting.report import HEADLINE, fmt, kpi_rows
    model = _load(model_file)
    try:
        res = run_simulation(model, _registry(), replications=reps, base_seed=seed, trace=bool(trace_dir))
    except ModelError as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1) from None
    if as_json:
        typer.echo(json.dumps(res.to_dict(), indent=2, default=str))
        return
    typer.secho(f"{model.meta.name} | run {res.run_id} | {len(res.seeds)} rep(s) | model {res.model_hash} | {res.wall_time_s}s", bold=True)
    for r in kpi_rows(res, HEADLINE):
        ci = f"  ± {fmt(r['metric'], (r['ci95_high'] - r['ci95_low']) / 2)}" if r["n"] > 1 else ""
        typer.echo(f"  {r['label']:<22} {fmt(r['metric'], r['mean']):>14}{ci}")
    for k, st in res.kpis.stats.items():
        if k.endswith(".utilization"):
            typer.echo(f"  {k:<40} {fmt(k, st.mean):>8}")
    typer.secho("Diagnostics:", bold=True)
    for f in res.findings:
        typer.secho(f"  [{f.severity}] {f.message}", fg={"flag": "red", "warning": "yellow"}.get(f.severity))
    if trace_dir:
        from .persistence.project import _write_csv
        trace_dir.mkdir(parents=True, exist_ok=True)
        for rec in res.records:
            if rec.events:
                _write_csv(trace_dir / f"events_seed{rec.seed}.csv", rec.events)
            if rec.decisions:
                _write_csv(trace_dir / f"decisions_seed{rec.seed}.csv",
                           [{**d, "candidates": json.dumps(d["candidates"]), "units": ",".join(d["units"])} for d in rec.decisions])
        typer.echo(f"Traces written to {trace_dir}")


@app.command()
def experiment(model_file: Path, index: int = typer.Option(0, help="Which experiment in the model file"),
               factor: list[str] = typer.Option([], help="path=v1,v2,... (overrides the model's experiment)"),
               reps: Optional[int] = None, csv_out: Optional[Path] = typer.Option(None, "--csv")):
    """Run a grid experiment defined in the model (or via --factor)."""
    from .reporting.report import experiment_csv
    model = _load(model_file)
    if factor:
        facs = []
        for f in factor:
            path, vals = f.split("=", 1)
            facs.append(Factor(path=path, values=[json.loads(v) for v in vals.split(",")]))
        spec = ExperimentSpec(name="cli", factors=facs, replications=reps)
    elif model.experiments:
        spec = model.experiments[index]
        if reps:
            spec = spec.model_copy(update={"replications": reps})
    else:
        typer.secho("El modelo no define experimentos; usa --factor path=v1,v2", fg="red")
        raise typer.Exit(2)
    try:
        exp = run_experiment(model, spec, _registry(), progress=lambda i, n: typer.echo(f"\r  scenario {i}/{n}", nl=False))
    except (ExperimentError, ModelError) as e:
        typer.secho(f"\n{e}", fg="red")
        raise typer.Exit(1) from None
    typer.echo("")
    text = experiment_csv(exp)
    typer.echo(text)
    if csv_out:
        csv_out.write_text(text, encoding="utf-8")


@app.command()
def report(model_file: Path, output: Path = typer.Option(Path("report.html"), "-o"), reps: Optional[int] = None,
           with_experiment: bool = typer.Option(False, "--experiment", help="Also run the model's first experiment")):
    """Simulate and write an HTML (+ .md) report."""
    from .reporting.report import build_markdown, markdown_to_html
    model = _load(model_file)
    reg = _registry()
    rep, _ = verify(model, reg)
    res = run_simulation(model, reg, replications=reps) if rep.ok else None
    exp = run_experiment(model, model.experiments[0], reg) if with_experiment and model.experiments and rep.ok else None
    md = build_markdown(model, rep, res, exp)
    output.with_suffix(".md").write_text(md, encoding="utf-8")
    output.write_text(markdown_to_html(md, model.meta.name), encoding="utf-8")
    typer.echo(f"Report: {output} (+ {output.with_suffix('.md')})")


@app.command()
def parse(text: str, output: Optional[Path] = typer.Option(None, "-o"), offline: bool = typer.Option(False, help="Force the offline rule-based parser")):
    """Natural language -> ISMS model (prints assumptions and missing data)."""
    from .ai.compiler import compile_draft
    from .ai.interpreter import LLMInterpreter, RuleBasedInterpreter
    from .ai.provider import provider_from_env
    reg = _registry()
    prov = None if offline else provider_from_env()
    interp = LLMInterpreter(prov, reg) if prov else RuleBasedInterpreter(reg)
    out = compile_draft(interp.parse(text), reg, text)
    rep, _ = verify(out.model, reg)
    typer.secho(f"Interpreter: {interp.name} | reuse {out.reuse_ratio:.0%} | {rep.summary()}", bold=True)
    for m in out.component_matches:
        typer.echo(f"  {m['step']:<24} -> {m['component']}@{m['version']} ({m['how']})")
    for a in out.model.assumptions:
        typer.secho(f"  ASSUMED: {a.text}", fg="yellow")
    for m in out.model.missing:
        typer.secho(f"  MISSING{'' if m.required else ' (optional)'}: {m.question}", fg="red" if m.required else "yellow")
    if output:
        output.write_text(dump_model(out.model), encoding="utf-8")
        typer.echo(f"Model written to {output}")
    else:
        typer.echo(dump_model(out.model))


@lib_app.command("list")
def lib_list(query: str = typer.Argument("", help="search text"), category: Optional[str] = None):
    """List/search components."""
    reg = _registry()
    comps = reg.search(query, category=category) if query else [c for c in reg.all() if not category or c.category == category]
    for c in comps:
        typer.echo(f"{c.id:<22} v{c.version:<7} {c.category:<14} {c.behavior.value:<7} {c.validation_status.value:<9} {c.name}")


@lib_app.command("show")
def lib_show(component_id: str):
    """Show component documentation (generated from its schema)."""
    typer.echo(_registry().get(component_id).to_markdown())


@lib_app.command("docs")
def lib_docs(output: Path = typer.Option(Path("component_library.md"), "-o")):
    """Generate Markdown docs for the whole library."""
    reg = _registry()
    output.write_text("# Component library\n\n" + "\n\n".join(c.to_markdown() for c in reg.all()), encoding="utf-8")
    typer.echo(f"Written {output}")


@bench_app.command("selective-soldering")
def bench_selective(bench_dir: Path = typer.Option(Path("benchmark"), "--dir"),
                    no_sensitivity: bool = typer.Option(False, help="Skip the simultaneous-event sensitivity run"),
                    no_charts: bool = False):
    """Run racks 1..10, compare with AnyLogic results (if imported), write report + charts."""
    from .benchmark.run_selective_soldering import run_benchmark
    run = run_benchmark(bench_dir, _registry(), sensitivity=not no_sensitivity, charts=not no_charts)
    color = "red" if run.status.startswith(("BLOCKED", "NOT")) else "yellow" if run.status.startswith("PRELIMINARY") else "green"
    typer.secho(f"Status: {run.status}", fg=color, bold=True)
    if run.check.missing:
        typer.secho(f"{len(run.check.missing)} inputs missing (REQUIRED_FROM_ANYLOGIC):", fg="red")
        for k in run.check.missing:
            typer.echo(f"  - {k}")
    for x in run.check.invalid:
        typer.secho(f"  invalid: {x}", fg="red")
    for k, pth in run.files.items():
        typer.echo(f"{k}: {pth}")
    raise typer.Exit(0 if run.check.runnable else 2)


@bench_app.command("inputs")
def bench_inputs(bench_dir: Path = typer.Option(Path("benchmark"), "--dir")):
    """Regenerate required_inputs.md from the configuration."""
    from .benchmark.selective_soldering import Config, check_inputs, required_inputs_markdown
    cfg = Config.load(bench_dir / "selective_soldering_config.yaml")
    (bench_dir / "required_inputs.md").write_text(required_inputs_markdown(cfg), encoding="utf-8")
    chk = check_inputs(cfg)
    typer.echo(f"missing {len(chk.missing)} · to confirm {len(chk.unconfirmed)} · invalid {len(chk.invalid)} -> {bench_dir / 'required_inputs.md'}")


@bench_app.command("trace")
def bench_trace(racks: int = typer.Option(..., help="number of racks"), minutes: float = typer.Option(15.0),
                bench_dir: Path = typer.Option(Path("benchmark"), "--dir"), show: int = typer.Option(60, help="lines to print")):
    """Short detailed trace (first N minutes) for event-by-event comparison with AnyLogic."""
    from .benchmark.run_selective_soldering import run_trace
    from .benchmark.selective_soldering import BenchmarkBlocked
    from .engine.des.runtime import fmt_hms
    try:
        events, decisions, stem = run_trace(bench_dir, _registry(), racks, minutes)
    except BenchmarkBlocked as e:
        typer.secho(f"Blocked: {len(e.missing)} inputs missing, {len(e.invalid)} invalid. Run 'simforge benchmark inputs'.", fg="red")
        raise typer.Exit(2) from None
    merged = sorted([("E", ev["t"], ev) for ev in events] + [("D", d["t"], d) for d in decisions], key=lambda x: (x[1], x[0] != "D"))
    for kind, t, x in merged[:show]:
        if kind == "E":
            extra = {k: v for k, v in x.items() if k not in ("t", "entity", "event", "node")}
            typer.echo(f"{fmt_hms(t)}  rack/unit {x.get('entity') or '-':>4}  {x['event']:<22} {x.get('node') or '':<24} {extra if extra else ''}")
        else:
            typer.secho(f"{fmt_hms(t)}  DECISION {x['resource']}: {x['chosen_node']} [{x['reason_code']}] candidates="
                        f"{[c['node'] for c in x['candidates']]} feed_wip={x['state'].get('feed_wip')} "
                        f"racks_available={x['system']['carriers_available']}", fg="cyan")
    typer.echo(f"{len(events)} events, {len(decisions)} decisions -> {stem}_events.csv / _decisions.csv")


# --------------------------------------------------------------------------- ai orchestration
def _app(offline: bool = False):
    from .services.app import SimForgeApp
    return SimForgeApp(provider=None if offline else "auto")


def _project(sf, slug: str):
    try:
        return sf.open_project(slug)
    except Exception as e:  # noqa: BLE001
        typer.secho(f"Proyecto '{slug}' no encontrado: {e}", fg="red")
        raise typer.Exit(2) from None


def _show_parse(pr) -> None:
    o = pr.outcome
    typer.secho(f"Model v{pr.version} | {pr.interpreter} | {pr.report.summary()}", bold=True)
    typer.echo(o.matching_report())
    if o.plan:
        typer.echo("\n" + o.plan.to_text())
    for a in o.model.assumptions:
        typer.secho(f"ASSUMED: {a.text}", fg="yellow")
    for c in o.model.custom_rule_candidates:
        typer.secho(f"CUSTOM RULE CANDIDATE [{c.id}] ({c.status}): {c.description}", fg="magenta")
    typer.echo("\n" + o.questions_text())


@ai_app.command("new")
def ai_new(name: str, description: str, offline: bool = typer.Option(False, help="offline rule-based interpreter"),
           prototype: bool = typer.Option(False, help="fill missing values with library defaults (explicit assumptions)")):
    """Create a project and build its model from a description (library components only)."""
    sf = _app(offline)
    p = sf.create_project(name)
    _show_parse(sf.parse_process(p, description, prototype=prototype))
    typer.echo(f"\nProject: {p.meta.slug}")


@ai_app.command("answer")
def ai_answer(slug: str, answers: list[str] = typer.Argument(..., help="param:<id>=<value> or return_mode:<carrier>=immediate|transport")):
    """Answer the grouped questions; the stored interpretation is recompiled deterministically."""
    sf = _app(True)
    parsed = {}
    for a in answers:
        k, _, v = a.partition("=")
        try:
            parsed[k] = json.loads(v)
        except json.JSONDecodeError:
            parsed[k] = v
    _show_parse(sf.answer_questions(_project(sf, slug), parsed))


@ai_app.command("approve")
def ai_approve(slug: str, by: str = typer.Option(..., help="engineer name")):
    """Engineer approval (required before the first run of an AI-generated model)."""
    sf = _app(True)
    v = sf.approve_model(_project(sf, slug), by)
    typer.secho(f"v{v} approved by {by}", fg="green")


@ai_app.command("say")
def ai_say(slug: str, request: str, yes: bool = typer.Option(False, "--yes", help="confirm important changes")):
    """Chat request -> structured ISMS change / experiment / analysis."""
    sf = _app()
    r = sf.command(_project(sf, slug), request, confirm=yes)
    typer.echo(r.message)
    if r.experiment:
        for row in r.experiment.table(["units_completed", "throughput_per_hour", "avg_wip"]):
            typer.echo("  " + json.dumps(row, default=str))
    if r.needs_confirmation:
        typer.secho("Repite con --yes para confirmar.", fg="yellow")


@ai_app.command("run")
def ai_run(slug: str):
    """Run the current model of a project (refused if approval is pending)."""
    from .services.app import ApprovalRequired
    sf = _app(True)
    try:
        res = sf.run_simulation(_project(sf, slug))
    except ApprovalRequired as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1) from None
    for k in ["units_completed", "throughput_per_hour", "avg_wip", "avg_lead_time_s"]:
        typer.echo(f"{k:<22}{res.kpis.mean(k):>12.4g}")


@ai_app.command("custom-rule")
def ai_custom_rule(slug: str, candidate_id: str, decision: str = typer.Argument(..., help="deferred | rejected"),
                   by: str = typer.Option(...)):
    """Engineer decision on a CustomRuleCandidate (deferred = run WITHOUT it, reported)."""
    sf = _app(True)
    v = sf.decide_custom_rule(_project(sf, slug), candidate_id, decision, by)
    typer.echo(f"v{v}: {candidate_id} -> {decision}")


@ai_app.command("compare")
def ai_compare(a: str = typer.Argument(..., help="model file or <project-slug>@<version>"), b: str = typer.Argument(...),
               run: bool = typer.Option(True, help="run both when structurally equivalent")):
    """compare_model_specs(A, B): textual vs structural equivalence, then result equivalence."""
    sf = _app(True)

    def load(ref: str):
        if "@" in ref and not Path(ref).exists():
            slug, ver = ref.rsplit("@", 1)
            return _project(sf, slug).load_version(int(ver))
        return Path(ref).read_text(encoding="utf-8")
    spec, res = sf.compare_models(load(a), load(b), run=run)
    typer.echo(spec.to_text())
    if res:
        typer.echo("\n" + res.to_text())
    raise typer.Exit(0 if spec.structurally_equivalent and (res is None or res.equivalent) else 1)


@ai_app.command("corrections")
def ai_corrections(slug: str):
    """Engineer corrections of AI values (AI value -> engineer value, reason)."""
    sf = _app(True)
    for c in _project(sf, slug).corrections():
        typer.echo(f"v{c['model_version']} {c['parameter']} ({c['component'] or '-'}): AI {c['ai_value']} -> engineer "
                   f"{c['engineer_value']}  reason: {c['reason'] or '—'}")


@ai_app.command("candidates")
def ai_candidates(min_occurrences: int = typer.Option(2)):
    """CANDIDATE_FOR_LIBRARY_IMPROVEMENT across all projects (the library is never changed automatically)."""
    sf = _app(True)
    cands = sf.library_improvement_candidates(min_occurrences)
    if not cands:
        typer.echo("No repeated patterns yet.")
    for c in cands:
        typer.echo(f"{c['status']} [{c['kind']}] x{c['occurrences']} in {', '.join(c['projects'])}: {c['suggestion']}")


@ai_app.command("productivity")
def ai_productivity(slug: str, manual_min: Optional[float] = typer.Option(None, help="manual model build time (min)"),
                    review_min: Optional[float] = typer.Option(None), correction_min: Optional[float] = typer.Option(None)):
    """Time saved vs manual model building (each figure with its source)."""
    from .services.productivity import productivity, record_engineer_time
    sf = _app(True)
    p = _project(sf, slug)
    for key, val in (("manual_model_build_min", manual_min), ("engineer_review_min", review_min), ("correction_min", correction_min)):
        if val is not None:
            record_engineer_time(p, key, val)
    typer.echo(productivity(p).to_text())


@ai_app.command("audit")
def ai_audit(slug: str):
    """AI audit log: provider, model, prompt version, repairs, validation errors, tokens, cost, latency."""
    sf = _app(True)
    for a in _project(sf, slug).audit_log():
        cost = f"${a['est_cost_usd']:.4f}" if a["est_cost_usd"] is not None else "-"
        typer.echo(f"{a['ts']} {a['purpose']:<14} {a['provider']}/{a['model']} {a['prompt_version']} accepted={bool(a['accepted'])} "
                   f"repairs={a['repairs']} tokens={a['input_tokens']}+{a['output_tokens']} cost={cost} "
                   f"latency={a['latency_ms'] or 0:.0f}ms")


@app.command()
def ui(port: int = 8501):
    """Launch the local web UI (Streamlit)."""
    target = Path(__file__).parent / "ui" / "app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(target), "--server.port", str(port),
                                      "--browser.gatherUsageStats", "false",
                                      "--theme.primaryColor", "#2a78d6"]))


if __name__ == "__main__":
    app()
