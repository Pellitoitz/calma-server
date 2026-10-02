"""`simforge economics ...` (engine >= 0.9.0): economic assumptions, post-run evaluation, scenario comparison.

    simforge economics show model.yaml [--economics econ.yaml]
    simforge economics evaluate model.yaml [--economics a.yaml --economics b.yaml] [--seed N] [--replications R]
        -> ONE physical run, one evaluation per economics file (same physics, different economics)
    simforge economics compare baseline.yaml alternative.yaml [--seed N] [--replications R]
        -> same seeds (paired), facts and deltas; never a recommendation
An economics file contains the `economics` block (currency, labor, machine, energy, ..., capex, annualization).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml

economics_app = typer.Typer(help="Economic assumptions, evaluation and comparison (engine >= 0.9.0)", no_args_is_help=True)


def _spec(path: str):
    from .domain.economics import EconomicsSpec
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return EconomicsSpec.model_validate(data.get("economics", data))


def _model(path: str):
    from .domain.io import load_model
    return load_model(path)


def _fmt(s, ccy="") -> str:
    if s is None:
        return "—"
    if isinstance(s, str):
        return s
    m = s["mean"]
    ci = "" if s.get("ci95_low") is None or s["ci95_low"] != s["ci95_low"] else f" [{s['ci95_low']:.2f}, {s['ci95_high']:.2f}]"
    return f"{m:,.2f} {ccy}{ci}".strip()


def print_evaluation(ev) -> None:
    c = ev.currency
    typer.echo(f"evaluation {ev.evaluation_id} · run {ev.run_id} · physical {ev.physical_model_hash} · economic "
               f"{ev.economic_hash} · economics {ev.economics_engine_version} · status {ev.status}")
    typer.echo("Coverage: " + ", ".join(f"{k}={v}" for k, v in ev.coverage.items()) + f" · out of scope: {', '.join(ev.out_of_scope)}")
    typer.echo(f"{'line':<26}{'status':<28}{'basis':<30}{'quantity':>14}{'cost':>16}  formula")
    for ln in ev.lines:
        q = f"{ln.quantity['mean']:.3f} {ln.unit}" if ln.quantity else "—"
        v = f"{ln.value['mean']:,.2f}" if ln.value else "—"
        typer.echo(f"{ln.line_id:<26}{ln.status:<28}{ln.basis:<30}{q:>14}{v:>16}  {ln.formula_id}")
    typer.echo(f"evaluated_total_cost: {_fmt(ev.totals['evaluated_total_cost'], c)} = sum of INCLUDED lines (complete categories "
               f"{ev.totals['included_categories']}; evaluated categories only, NOT a full production cost)")
    typer.echo("  breakdown: " + ", ".join(f"{k} {_fmt(v, c)} [{ev.totals['by_category_coverage'][k]}]"
                                           for k, v in ev.totals["by_category"].items()))
    typer.echo(f"cost_per_produced_unit: {_fmt(ev.unit_costs['cost_per_produced_unit'], c)} · cost_per_good_unit: "
               f"{_fmt(ev.unit_costs['cost_per_good_unit'], c)} (mean of per-replication ratios)")
    if ev.revenue["status"] == "AVAILABLE":
        typer.echo(f"revenue: {_fmt(ev.revenue['revenue'], c)} · evaluated_net_result: {_fmt(ev.revenue['evaluated_net_result'], c)} "
                   f"(revenue - cost of {ev.revenue['cost_categories_in_net_result']}; NOT a profit)")
    a = ev.annualized
    typer.echo("annualized: " + (f"{_fmt(a['evaluated_total_cost'], c)}/year (x{a['runs_per_year']} runs)" if a["status"] == "AVAILABLE"
                                 else f"MISSING ({a['reason']})"))
    k = ev.capex
    typer.echo(f"CAPEX: {k['status']}" + (f" total {k['total']:,.2f} {c}" if k["total"] is not None else "") +
               (f" missing {k['missing']}" if k["missing"] else ""))
    typer.echo(f"uncertainty: {ev.uncertainty_label} ({ev.replications} replication(s))")


@economics_app.command("show")
def show(model: str, economics: Optional[str] = typer.Option(None, help="economics YAML (default: the model's block)")):
    from .library.registry import ComponentRegistry
    from .validation.economics import economics_issues
    m = _model(model)
    spec = _spec(economics) if economics else getattr(m, "economics", None)
    if spec is None:
        typer.echo("Sin supuestos económicos.")
        raise typer.Exit(0)
    typer.echo(yaml.safe_dump(spec.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True))
    typer.echo(f"economic_hash {spec.economic_hash()} · physical hash {m.content_hash()}")
    for i in economics_issues(spec, m, ComponentRegistry.load_default(None)):
        typer.secho(f"  {i}", fg="red" if i.level.value == "error" else "yellow")


@economics_app.command("evaluate")
def evaluate(model: str, economics: list[str] = typer.Option(None, help="one or more economics YAML files"),
             seed: Optional[int] = typer.Option(None), replications: Optional[int] = typer.Option(None)):
    from .economics import evaluate_run
    from .experiments.runner import run_simulation
    from .library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default(None)
    m = _model(model)
    kw = {k: v for k, v in (("base_seed", seed), ("replications", replications)) if v is not None}
    run = run_simulation(m, reg, **kw)  # ONE physical run
    specs = [_spec(p) for p in economics] if economics else [getattr(m, "economics", None)]
    for spec in specs:
        try:
            print_evaluation(evaluate_run(run, m, spec, reg))
        except ValueError as e:
            typer.secho(str(e), fg="red")
            raise typer.Exit(1) from None
        typer.echo("")


@economics_app.command("compare")
def compare(baseline: str, alternative: str, seed: Optional[int] = typer.Option(None),
            replications: Optional[int] = typer.Option(None)):
    from .economics import compare_evaluations, evaluate_run
    from .experiments.runner import run_simulation
    from .library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default(None)
    mb, ma = _model(baseline), _model(alternative)
    kw = {k: v for k, v in (("base_seed", seed), ("replications", replications)) if v is not None}
    eb = evaluate_run(run_simulation(mb, reg, **kw), mb, None, reg)
    ea = evaluate_run(run_simulation(ma, reg, **kw), ma, None, reg)
    c = compare_evaluations(eb, ea, mb, ma)
    ccy = eb.currency
    typer.echo(f"comparison {c.status} · paired={c.paired} (delta = alternative - baseline; savings = baseline - alternative)")
    for x in c.checks:
        typer.secho(f"  {x['level']} [{x['check']}] {x['detail']}", fg={"HARD_INCOMPATIBILITY": "red", "WARNING": "yellow"}.get(x["level"]))
    for k, d in c.physical_deltas.items():
        pct = f" ({d['delta_pct']:+.1f}%)" if d["delta_pct"] is not None else ""
        typer.echo(f"  {k}: {d['baseline']:.3f} -> {d['alternative']:.3f}  delta {d['delta']:+.3f}{pct}")
    for k, d in c.cost_deltas.items():
        typer.echo(f"  cost {k}: delta {d['mean']:+,.2f} {ccy}")
    typer.echo(f"  evaluated savings (run): {c.savings['mean']:+,.2f} {ccy} ({c.savings['definition']})")
    if c.annual["status"] == "AVAILABLE":
        typer.echo(f"  evaluated savings (year): {c.annual['savings_per_year']['mean']:+,.2f} {ccy}")
    else:
        typer.echo(f"  annual: {c.annual['status']} ({c.annual.get('reason', '')})")
    if c.capex["status"] == "AVAILABLE":
        typer.echo(f"  incremental CAPEX: {c.capex['incremental']:,.2f} {ccy}")
    else:
        typer.echo(f"  incremental CAPEX: {c.capex['status']} (never assumed 0)")
    p = c.payback
    typer.echo("  simple payback: " + (f"{p['years']:.2f} years" if p["status"] == "AVAILABLE" else f"{p['status']} ({p.get('reason', '')})")
               + f"  [{p['formula']}]")
    r = c.annual_return_on_incremental_capex
    typer.echo("  annual return on incremental CAPEX: " + (f"{r['value']:.3f}" if r["status"] == "AVAILABLE" else r["status"]))
    typer.echo(f"  {c.note}")


@economics_app.command("validate-real")
def validate_real(case_dir: Path):
    """Real-data economic validation of one case (protocol: docs/validation/economic_real_data_validation.md).
    Thin wrapper of scripts/validation/economic_validation.py (a validation tool, not engine logic)."""
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "scripts" / "validation" / "economic_validation.py"
    if not script.exists():
        typer.secho("Validator not found (source checkout needed): run python scripts/validation/economic_validation.py <CASE>",
                    fg="red")
        raise typer.Exit(2)
    spec = importlib.util.spec_from_file_location("economic_validation", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    code = mod.main([str(case_dir)])
    typer.echo(f"Report: {case_dir / 'VALIDATION_REPORT.md'} · matrix: {case_dir / 'comparison' / 'capabilities.csv'}")
    raise typer.Exit(code)
