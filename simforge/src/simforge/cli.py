"""SimForge command line. Works fully offline; no UI needed.

    simforge validate examples/02_shared_operator.yaml
    simforge run examples/02_shared_operator.yaml --reps 10
    simforge experiment examples/05_selective_soldering.yaml
    simforge report examples/02_shared_operator.yaml -o report.html
    simforge parse "Fuente infinita. Un operario monta 60 s..." -o model.yaml
    simforge library list | show <id> | docs
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
from .validation.verifier import ModelError, verify

app = typer.Typer(add_completion=False, help="SimForge - AI-assisted industrial simulation (local).", no_args_is_help=True)
lib_app = typer.Typer(help="Component library", no_args_is_help=True)
app.add_typer(lib_app, name="library")


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


@app.command()
def ui(port: int = 8501):
    """Launch the local web UI (Streamlit)."""
    target = Path(__file__).parent / "ui" / "app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(target), "--server.port", str(port),
                                      "--browser.gatherUsageStats", "false",
                                      "--theme.primaryColor", "#2a78d6"]))


if __name__ == "__main__":
    app()
