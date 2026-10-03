"""`simforge data ...` and `simforge project ...`: measured data -> engineer decision -> model parameter, offline.

    simforge project new "Linea selectiva" --model examples/05_selective_soldering.yaml
    simforge data preview tiempos_montaje.xlsx
    simforge data import linea_selectiva tiempos_montaje.xlsx --name montaje --sheet Hoja1 --column Tiempo \
        --unit s --quantity PROCESSING_TIME --basis PER_CIRCUIT --timestamp Fecha
    simforge data inspect linea_selectiva montaje@v1
    simforge data rows linea_selectiva montaje@v1 KEEP 20 61 --reason "ciclos largos reales" --by ana
    simforge data fit linea_selectiva montaje@v1 --by ana
    simforge data decide linea_selectiva montaje@v1 USE_FITTED --fit fit_... --candidate lognormal --by ana
    simforge data apply linea_selectiva montaje@v1 dec_... --target nodes.assembly.params.process_time --target-basis PER_CIRCUIT \
        --aggregation sum_iid --by ana
    simforge project approve linea_selectiva --by ana
    simforge project run linea_selectiva
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

data_app = typer.Typer(help="Measured data: import CSV/XLSX -> validate -> analyse -> fit -> engineer decision -> apply (offline)",
                       no_args_is_help=True)
project_app = typer.Typer(help="Workspace projects (versions, approval, runs) without AI", no_args_is_help=True)


def _sf():
    from .services.app import SimForgeApp
    return SimForgeApp(provider=None)  # the data workflow never calls an LLM


def _proj(sf, slug: str):
    try:
        return sf.open_project(slug)
    except Exception as e:  # noqa: BLE001
        typer.secho(f"Proyecto '{slug}' no encontrado: {e}", fg="red")
        raise typer.Exit(2) from None


def _pairs(items: list[str] | None, what: str) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep:
            typer.secho(f"{what}: usa clave=valor (recibido '{it}')", fg="red")
            raise typer.Exit(2)
        out[k.strip()] = v.strip()
    return out


def _run(fn):
    """Show domain errors (decisions required, invalid data) as messages, not tracebacks."""
    from .data.importers import ImportError_
    from .data.store import DatasetError
    from .domain.units import UnitError
    try:
        return fn()
    except (DatasetError, ImportError_, UnitError, ValueError, KeyError) as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1) from None


# ======================================================================================== data
@data_app.command("quantities")
def quantities():
    """Quantity types: DATA_IMPORT_SUPPORTED vs SIMULATION_USE (what the engine can consume)."""
    from .data.quantities import support_table
    for r in support_table():
        typer.echo(f"{r['quantity']:<18} {r['dimension']:<7} {r['simulation']:<34} targets={r['targets'] or '-'}  {r['note']}")


@data_app.command("preview")
def preview(file: Path, sheet: Optional[str] = None, delimiter: Optional[str] = None, decimal: Optional[str] = None,
            header_row: int = 1, rows: int = 10):
    """Look at a file BEFORE importing it: sheets, columns, first rows, detected format, unit hints."""
    from .data.importers import preview as pv
    p = _run(lambda: pv(file, sheet=sheet, n=rows, delimiter=delimiter, decimal=decimal, header_row=header_row))
    if "sheets" in p:
        typer.echo(f"Sheets: {p['sheets']}")
        if p.get("needs") == "sheet":
            typer.secho("Varias hojas: indica --sheet.", fg="yellow")
            return
    typer.echo(f"Sheet: {p.get('sheet')}  delimiter: {p.get('delimiter')!r}  decimal: {p.get('decimal')!r}  encoding: {p.get('encoding')}")
    typer.echo(f"Columns: {p['columns']}   rows: {p['rows']}")
    for c, t in p["column_types"].items():
        typer.echo(f"  {c:<24} {t}")
    for n in p["notes"]:
        typer.echo(f"  note: {n}")
    if p["unit_hints"]:
        typer.secho(f"Unit hints from headers (NOT applied; pass --unit): {p['unit_hints']}", fg="yellow")
    for r in p["first_rows"]:
        typer.echo("  " + " | ".join("" if v is None else str(v) for v in r))


@data_app.command("import")
def import_(slug: str, file: Path, name: str = typer.Option(..., help="dataset name (versions: name@v1, name@v2...)"),
            column: str = typer.Option(..., help="VALUE column"),
            quantity: str = typer.Option(..., help="PROCESSING_TIME, ARRIVAL_INTERVAL, REPAIR_TIME... (see `data quantities`)"),
            basis: str = typer.Option(..., help="PER_CIRCUIT, PER_RACK, PER_PANEL, PER_UNIT, PER_BATCH, PER_CYCLE, PER_OPERATION, PER_TRIP, UNKNOWN"),
            unit: Optional[str] = typer.Option(None, help="unit of the whole column (ms, s, min, h, mm, cm, m, km, UNKNOWN)"),
            unit_column: Optional[str] = typer.Option(None, help="column with the unit of each row"),
            sheet: Optional[str] = None, delimiter: Optional[str] = None, decimal: Optional[str] = None, header_row: int = 1,
            timestamp: Optional[str] = typer.Option(None, help="TIMESTAMP column (keeps time order)"),
            group: Optional[list[str]] = typer.Option(None, help="role=column, roles: operator, product, shift, machine, batch"),
            synthetic: bool = typer.Option(False, help="SYNTHETIC TEST DATA (never presented as measured)"),
            imported: bool = typer.Option(False, help="values exported from a system (IMPORTED) rather than measured by a study"),
            description: str = "", basis_note: str = "", by: str = "engineer",
            force_new_version: bool = typer.Option(False, help="import again even if the same file+settings already exists")):
    """Import a CSV/XLSX column as an immutable, hashed dataset version."""
    sf = _sf()
    p = _proj(sf, slug)
    r = _run(lambda: sf.data(p).import_file(file, name, column, quantity, basis, unit=unit, unit_column=unit_column, sheet=sheet,
                                            delimiter=delimiter, decimal=decimal, header_row=header_row, timestamp=timestamp,
                                            groups=_pairs(group, "--group"), by=by, description=description, synthetic=synthetic,
                                            measurement_status="imported" if imported else "measured", basis_note=basis_note,
                                            force_new_version=force_new_version))
    if r.duplicate_of:
        typer.secho(f"DUPLICATE: el mismo archivo con la misma configuración ya es {r.duplicate_of} (usa --force-new-version "
                    "para crear otra versión).", fg="yellow")
    m = r.meta
    typer.secho(f"{m.label}: {m.n_rows} filas {m.counts} | {m.quantity_type.value} | {m.basis.value} | unidad {m.analysis_unit} "
                f"| hash {m.content_hash}", bold=True)
    for n in m.import_notes + m.transformations:
        typer.echo(f"  {n}")
    typer.echo(f"Siguiente: simforge data inspect {slug} {m.dataset_id}")


@data_app.command("list")
def list_(slug: str):
    """Datasets of a project (all versions)."""
    sf = _sf()
    for m in sf.data(_proj(sf, slug)).list():
        typer.echo(f"{m.label:<40} {m.source_file:<30} {m.quantity_type.value:<17} {m.basis.value:<14} n={m.n_rows:<6} "
                   f"{m.created_at:%Y-%m-%d %H:%M} hash {m.content_hash}")


@data_app.command("inspect")
def inspect(slug: str, dataset: str, group: Optional[list[str]] = typer.Option(None, help="role=value subset"),
            pooled: bool = typer.Option(False, help="explicitly mix all groups"), seed: int = 12345,
            as_json: bool = typer.Option(False, "--json"), output: Optional[Path] = typer.Option(None, "-o", help="write DATA PROFILE (.md/.txt/.json)")):
    """DATA PROFILE: validation, statistics, serial dependence, outlier candidates, latest fit, status."""
    from .data.report import profile_text
    sf = _sf()
    ds = sf.data(_proj(sf, slug))
    prof = _run(lambda: ds.profile(dataset, group=_pairs(group, "--group"), pooled=pooled, seed=seed))
    st = ds.state(dataset)
    fit = next((f.result for f in reversed(st.fits) if f.state_hash == st.state_hash and f.group == prof["group"]
                and f.pooled == pooled), None)
    if as_json:
        typer.echo(json.dumps({"profile": prof, "fit": fit}, indent=1, ensure_ascii=False, default=str))
        return
    text = profile_text(prof, fit)
    if output:
        output.write_text(json.dumps({"profile": prof, "fit": fit}, indent=1, ensure_ascii=False, default=str)
                          if output.suffix == ".json" else ("```\n" + text + "\n```\n" if output.suffix == ".md" else text),
                          encoding="utf-8")
        typer.echo(f"written {output}")
    typer.echo(text)


@data_app.command("rows")
def rows(slug: str, dataset: str, action: str = typer.Argument(..., help="KEEP | EXCLUDE_FROM_FIT | MARK_INVALID | RESTORED | ACCEPT_REVIEWED"),
         indexes: list[int] = typer.Argument(..., help="observation indexes (idx shown by inspect)"),
         reason: str = typer.Option(...), by: str = typer.Option(...), method: Optional[str] = None):
    """Engineer action on rows. Nothing is deleted: every action is logged and EXCLUDE/MARK_INVALID can be RESTORED."""
    sf = _sf()
    ev = _run(lambda: sf.data(_proj(sf, slug)).act_rows(dataset, action.upper(), indexes, reason, by, method))
    typer.secho(f"{ev.action} {ev.rows} by {ev.by}: {ev.reason}", fg="green")


@data_app.command("fit")
def fit(slug: str, dataset: str, by: str = typer.Option(...), group: Optional[list[str]] = typer.Option(None),
        pooled: bool = False, physical_min: Optional[float] = typer.Option(None, help="physically impossible below (dataset unit)"),
        physical_max: Optional[float] = None, as_json: bool = typer.Option(False, "--json"),
        bound_low: Optional[float] = typer.Option(None, help="uniform/triangular lower bound (needs --bound-source)"),
        bound_high: Optional[float] = typer.Option(None, help="uniform/triangular upper bound (needs --bound-source)"),
        bound_source: Optional[str] = typer.Option(None, help="ENGINEER_BOUNDS | PROCESS_SPECIFICATION")):
    """Fit candidate distributions: ranking (AIC), GOF evidence, industrial plausibility, SUGGESTED candidate."""
    from .data.report import fit_text
    sf = _sf()
    r = _run(lambda: sf.data(_proj(sf, slug)).fit(dataset, by=by, group=_pairs(group, "--group"), pooled=pooled,
                                                  physical_min=physical_min, physical_max=physical_max,
                                                  bounds=({"low": bound_low, "high": bound_high, "source": bound_source}
                                                          if bound_source else None)))
    typer.echo(json.dumps(r, indent=1, ensure_ascii=False, default=str) if as_json else fit_text(r))
    if not as_json:
        typer.echo(f"\nNada se ha aplicado. Decide: simforge data decide {slug} {dataset} USE_FITTED --fit {r['fit_id']} "
                   "--candidate <familia> --by <ingeniero>  (o USE_EMPIRICAL / USE_DETERMINISTIC --derivation MEAN|MEDIAN|ENGINEER_VALUE)")


@data_app.command("holdout")
def holdout(slug: str, dataset: str, train: float = typer.Option(0.7, help="fraction used to fit (time order); 0.7 is a proposal"),
            group: Optional[list[str]] = typer.Option(None), pooled: bool = False, by: str = "engineer"):
    """Temporal holdout: fit on the first part, check against later observations the fit never saw (changes nothing)."""
    from .data.report import holdout_text
    sf = _sf()
    h = _run(lambda: sf.data(_proj(sf, slug)).holdout(dataset, train, group=_pairs(group, "--group"), pooled=pooled, by=by))
    typer.echo(holdout_text(h))


@data_app.command("decide")
def decide(slug: str, dataset: str,
           decision: str = typer.Argument(..., help="USE_DETERMINISTIC | USE_EMPIRICAL | USE_FITTED | KEEP_WITHOUT_APPLYING | REJECT"),
           by: str = typer.Option(...), reason: str = "", group: Optional[list[str]] = typer.Option(None), pooled: bool = False,
           derivation: Optional[str] = typer.Option(None, help="USE_DETERMINISTIC: MEAN | MEDIAN | ENGINEER_VALUE"),
           value: Optional[float] = typer.Option(None, help="ENGINEER_VALUE in the dataset unit"),
           fit_id: Optional[str] = typer.Option(None, "--fit"), candidate: Optional[str] = None,
           trunc_lower: Optional[float] = None, trunc_upper: Optional[float] = None, trunc_reason: Optional[str] = None,
           trunc_bound_type: Optional[str] = typer.Option(None, help="PHYSICAL_BOUND | MODELLING_BOUND (mandatory with truncation)"),
           accept: Optional[list[str]] = typer.Option(None, help="plausibility warning codes explicitly accepted")):
    """Record the ENGINEER DECISION (nothing reaches the model until `data apply`)."""
    trunc = None
    if trunc_lower is not None or trunc_upper is not None:
        if not trunc_reason:
            typer.secho("El truncamiento necesita --trunc-reason.", fg="red")
            raise typer.Exit(2)
        trunc = {"lower": trunc_lower, "upper": trunc_upper, "reason": trunc_reason, "bound_type": trunc_bound_type}
    sf = _sf()
    ev = _run(lambda: sf.data(_proj(sf, slug)).decide(dataset, decision.upper(), by, reason=reason, group=_pairs(group, "--group"),
                                                      pooled=pooled, derivation=derivation.upper() if derivation else None,
                                                      engineer_value=value, fit_id=fit_id, candidate=candidate, truncation=trunc,
                                                      accept_warnings=accept))
    typer.secho(f"{ev.decision_id}: {ev.decision.value} by {ev.by} (n={ev.n_used}) -> {ev.distribution or 'nada que aplicar'}", fg="green")
    for w in ev.warnings:
        typer.secho(f"  {w}", fg="yellow")
    if ev.distribution:
        typer.echo(f"Aplicar: simforge data apply {slug} {dataset} {ev.decision_id} --target nodes.<id>.params.<param> "
                   "--target-basis <BASIS> --by <ingeniero>")


@data_app.command("apply")
def apply(slug: str, dataset: str, decision_id: str, target: str = typer.Option(..., help="e.g. nodes.assembly.params.process_time"),
          target_basis: str = typer.Option(..., help="what ONE sample of the target represents (PER_CIRCUIT, PER_RACK...)"),
          by: str = typer.Option(...), factor: Optional[float] = typer.Option(None, help="explicit basis conversion factor"),
          formula: Optional[str] = None, inputs: Optional[str] = typer.Option(None, help='JSON, e.g. {"circuits_per_rack": 4}'),
          conversion_mode: Optional[str] = typer.Option(None, help="scale_sample: the ONLY way a factor converts a distribution (k·X)"),
          aggregation: Optional[str] = typer.Option(None, help="target node work_units_aggregation: sum_iid | scale_sample | single_sample")):
    """Write the decided value into the current model -> NEW model version, approval invalidated."""
    conv = None
    if factor is not None:
        conv = {"factor": factor, "formula": formula or "", "inputs": json.loads(inputs) if inputs else None}
        if conversion_mode:
            conv["aggregation"] = conversion_mode
    sf = _sf()
    r = _run(lambda: sf.data(_proj(sf, slug)).apply(dataset, decision_id, target, target_basis, by, conversion=conv, aggregation=aggregation))
    typer.secho(f"Model v{r['version']} (from v{r['parent']}): {r['target']}", bold=True)
    typer.echo(f"  before: {r['previous']}\n  after:  {r['new']}\n  provenance: {r['provenance']}")
    for w in r["warnings"]:
        typer.secho(f"  {w}", fg="yellow")
    typer.secho(f"  approval: {r['approval']} -> simforge project approve {slug} --by <ingeniero>", fg="yellow")


@data_app.command("trace")
def trace(slug: str, path: str, version: Optional[int] = None):
    """Where did this parameter come from? dataset version + hash + fit + decision (reproducibility)."""
    sf = _sf()
    p = _proj(sf, slug)
    t = _run(lambda: sf.data(p).trace_parameter(p.load_version(version), path))
    typer.echo(json.dumps(t, indent=1, ensure_ascii=False, default=str))


# ===================================================================================== project
@project_app.command("new")
def project_new(name: str, model: Optional[Path] = typer.Option(None, help="initial model YAML (saved as v1)"), by: str = "engineer"):
    """Create a workspace project, optionally from a model file."""
    from .domain.io import load_model
    sf = _sf()
    p = sf.create_project(name)
    if model:
        v = sf.save_model(p, load_model(model), f"imported from {model.name}", actor="user")
        typer.echo(f"v{v} <- {model}")
    typer.echo(f"Project: {p.meta.slug}")


@project_app.command("versions")
def project_versions(slug: str):
    """Model versions with approval state."""
    sf = _sf()
    p = _proj(sf, slug)
    for v in p.versions():
        m = p.load_version(v.version)
        cur = "*" if v.version == p.meta.current_version else " "
        typer.echo(f"{cur} v{v.version:<4} {v.created_at} {v.author or '':<12} approved={m.is_approved!s:<5} {v.content_hash}  {v.message or ''}")


@project_app.command("approve")
def project_approve(slug: str, by: str = typer.Option(..., help="engineer name"), note: str = ""):
    """Engineer approval of the CURRENT model version (bound to its exact content hash)."""
    sf = _sf()
    v = _run(lambda: sf.approve_model(_proj(sf, slug), by, note))
    typer.secho(f"v{v} approved by {by}", fg="green")


@project_app.command("run")
def project_run(slug: str, reps: Optional[int] = None):
    """Run the current model (refused if it needs approval). Records seeds, engine version, model hash."""
    from .reporting.report import HEADLINE, fmt, fmt_unit, kpi_rows
    from .services.app import ApprovalRequired
    sf = _sf()
    p = _proj(sf, slug)
    try:
        res = sf.run_simulation(p, replications=reps)
    except ApprovalRequired as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1) from None
    typer.secho(f"run {res.run_id} | model v{p.meta.current_version} {res.model_hash} | engine {res.engine_version} | seeds {res.seeds}",
                bold=True)
    for r in kpi_rows(res, HEADLINE):
        ci = f"  ± {fmt(r['metric'], (r['ci95_high'] - r['ci95_low']) / 2)}" if r["n"] > 1 else ""
        typer.echo(f"  {r['label']:<22} {fmt_unit(r['metric'], r['mean']):>20}{ci}")


# ------------------------------------------------------------------------------------------------ 1.0 workflow commands
# Thin wrappers of existing services (no new capability): they make the golden workflow possible from the CLI.
@project_app.command("save")
def project_save(slug: str, model: Path, message: str = typer.Option("", "-m", help="version message"), by: str = "engineer"):
    """Save a model file as a NEW immutable version of the project (becomes current; approval is not carried over)."""
    from .domain.io import load_model
    sf = _sf()
    v = sf.save_model(_proj(sf, slug), load_model(model), message or f"from {model.name}", actor="user")
    typer.echo(f"v{v} <- {model}")


@project_app.command("checkout")
def project_checkout(slug: str, version: int):
    """Make an existing version current (nothing is lost: versions are immutable)."""
    sf = _sf()
    _proj(sf, slug).checkout(version)
    typer.echo(f"current version -> v{version}")


@project_app.command("baseline")
def project_baseline(slug: str, version: Optional[int] = typer.Option(None, help="default: current version")):
    """Mark a version as the baseline (scenarios are derived from it)."""
    sf = _sf()
    p = _proj(sf, slug)
    v = version or p.meta.current_version
    p.set_baseline(v)
    typer.echo(f"baseline = v{v}")


@project_app.command("scenario")
def project_scenario(slug: str, name: str, model: Path, message: str = typer.Option("", "-m")):
    """Create a named scenario (a new version, derived from the baseline) from a model file; it becomes current."""
    from .domain.io import load_model
    sf = _sf()
    v = _proj(sf, slug).create_scenario(name, load_model(model), message)
    typer.echo(f"scenario '{name}' = v{v}")


# ------------------------------------------------------------------------------------------------ 1.1-A scenarios & comparison
def _sets(items: list[str] | None) -> dict[str, object]:
    """--set path=value (value parsed as JSON when possible: 2, 1.5, null, {"dist": ...}; otherwise a string)."""
    out: dict[str, object] = {}
    for k, v in _pairs(items, "--set").items():
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


@project_app.command("scenarios")
def project_scenarios(slug: str):
    """Baseline and named scenarios (version, approval, parent)."""
    sf = _sf()
    p = _proj(sf, slug)
    parents = {v.version: v.parent for v in p.versions()}
    b = p.meta.baseline_version
    typer.echo(f"baseline: v{b}" if b is not None else "baseline: — (set one with 'project baseline')")
    for name, v in sorted(p.meta.scenarios.items()):
        typer.echo(f"  {name:<24} v{v:<4} parent v{parents.get(v)}  approved={p.load_version(v).is_approved}")


@project_app.command("scenario-clone")
def project_scenario_clone(slug: str, name: str,
                           set_: Optional[list[str]] = typer.Option(None, "--set", help="path=value (repeatable)"),
                           from_version: Optional[int] = typer.Option(None, help="default: the baseline"),
                           message: str = typer.Option("", "-m"), by: str = "engineer"):
    """Clone the baseline (or --from-version) into a named scenario, applying --set changes. It becomes current;
    approval is bound to the content, so a changed clone is NOT approved."""
    sf = _sf()
    p = _proj(sf, slug)
    v = sf.clone_scenario(p, name, _sets(set_), from_version=from_version, message=message, by=by)
    m = p.load_version(v)
    typer.echo(f"scenario '{name}' = v{v} (from v{from_version if from_version is not None else p.meta.baseline_version}) "
               f"hash {m.content_hash()} approved={m.is_approved}")
    for path, a, b in sf.compare_versions(p, from_version if from_version is not None else p.meta.baseline_version, v):
        typer.echo(f"  {path}: {json.dumps(a, default=str)} -> {json.dumps(b, default=str)}")


@project_app.command("scenario-set")
def project_scenario_set(slug: str, name: str, set_: list[str] = typer.Option(..., "--set", help="path=value (repeatable)"),
                         message: str = typer.Option("", "-m"), by: str = "engineer"):
    """Modify an existing scenario: a new version (parent = its previous version); the scenario name moves to it."""
    sf = _sf()
    v = sf.modify_scenario(_proj(sf, slug), name, _sets(set_), message=message, by=by)
    typer.echo(f"scenario '{name}' = v{v}")


def _num_txt(v: float | None) -> str:
    return "—" if v is None else f"{v:.6g}"


def print_comparison(c, show_all: bool = False) -> None:
    for side, i in (("baseline   ", c.baseline), ("alternative", c.alternative)):
        tag = f"v{i.model_version}" if i.model_version is not None else "unsaved model"
        tag += f" scenario '{i.scenario}'" if i.scenario else (" (baseline version)" if i.is_baseline_version else "")
        typer.echo(f"{side} run {i.run_id} · {tag} · hash {i.model_hash} · {i.engine} {i.engine_version} · "
                   f"horizon {i.horizon_s:g} s warm-up {i.warmup_s:g} s · {i.replications} rep · seeds {i.seeds}")
    color = {"COMPARABLE": "green", "COMPARABLE_WITH_WARNINGS": "yellow", "NOT_COMPARABLE": "red"}[c.status]
    typer.secho(f"status: {c.status} · mode: {c.comparison_mode} · {c.delta_convention}", fg=color, bold=True)
    for e in c.pairing_evidence:
        typer.echo(f"  pairing: {e}")
    for ch in c.checks:
        typer.secho(f"  [{ch.level}] {ch.check}: {ch.detail}",
                    fg={"HARD_INCOMPATIBILITY": "red", "WARNING": "yellow"}.get(ch.level))
    from .analytics.run_comparison import HEADLINE_METRICS
    rows = [m for m in c.metrics if show_all or m.metric in HEADLINE_METRICS or m.metric.endswith(".utilization")]
    typer.echo(f"  {'metric':<40} {'baseline':>12} {'alternative':>12} {'delta':>12} {'ci95':>25}  status")
    for m in rows:
        d = m.delta
        ci = f"[{_num_txt(d.ci95_low)}, {_num_txt(d.ci95_high)}]" if d and d.ci95_low is not None else "—"
        typer.echo(f"  {m.metric:<40} {_num_txt(m.baseline_mean):>12} {_num_txt(m.alternative_mean):>12} "
                   f"{(f'{d.mean:+.6g}' if d else '—'):>12} {ci:>25}  {m.status}{(' — ' + m.reason) if m.reason else ''}")
    hidden = len(c.metrics) - len(rows)
    if hidden:
        typer.echo(f"  ... {hidden} more metric(s): use --all or --metric")
    typer.echo(c.note)


@project_app.command("compare-runs")
def project_compare_runs(slug: str, baseline_run: str, alternative_run: str,
                         metric: Optional[list[str]] = typer.Option(None, help="metric key (repeatable); default: all"),
                         show_all: bool = typer.Option(False, "--all", help="print every metric (default: headline + utilizations)"),
                         as_json: bool = typer.Option(False, "--json")):
    """Physical comparison of two STORED runs: delta = alternative - baseline, paired only with common-random-numbers
    evidence, comparability checks. Facts only (no ranking, no recommendation); nothing is simulated or stored.
    Exit code 1 when the runs are NOT_COMPARABLE."""
    sf = _sf()
    c = sf.compare_runs(_proj(sf, slug), baseline_run, alternative_run, metrics=metric or None)
    if as_json:
        typer.echo(c.model_dump_json(indent=2))
    else:
        print_comparison(c, show_all=show_all or bool(metric))
    raise typer.Exit(1 if c.status == "NOT_COMPARABLE" else 0)


@project_app.command("experiment")
def project_experiment(slug: str, factor: list[str] = typer.Option(..., help="path=v1,v2,... (repeatable)"),
                       reps: Optional[int] = None, reference: int = typer.Option(0, help="reference scenario index for deltas"),
                       metric: Optional[list[str]] = typer.Option(None, help="metric key (repeatable)")):
    """Run a grid experiment on the project's CURRENT model (approval gate applies; stored in the project) and print each
    scenario with its delta vs the reference scenario (same seeds -> paired). Scenario order is kept: no ranking."""
    from .domain.isms import ExperimentSpec, Factor
    sf = _sf()
    p = _proj(sf, slug)
    facs = []
    for f in factor:
        path, sep, vals = f.partition("=")
        if not sep:
            typer.secho(f"--factor: usa path=v1,v2 (recibido '{f}')", fg="red")
            raise typer.Exit(2)
        facs.append(Factor(path=path, values=[json.loads(v) for v in vals.split(",")]))
    exp = sf.run_experiment(p, ExperimentSpec(name="cli: " + ", ".join(x.path for x in facs), factors=facs, replications=reps))
    keys = list(metric or ["units_completed", "throughput_per_hour", "avg_wip", "avg_lead_time_s"])
    deltas = sf.experiment_deltas(p, exp.experiment_id, reference, keys)
    typer.secho(f"experiment {exp.experiment_id} · {len(exp.scenarios)} scenarios · {deltas.delta_convention}", bold=True)
    for s in deltas.scenarios:
        head = f"  #{s.index}{' (reference)' if s.is_reference else ''} {json.dumps(s.factors, default=str)}"
        if s.comparison is None:
            typer.secho(f"{head}  FAILED: {s.error}", fg="red")
            continue
        cells = []
        for k in keys:
            m = s.comparison.metric(k)
            if m is None or m.status != "COMPARED":
                cells.append(f"{k}={_num_txt(m.alternative_mean if m else None)} (Δ {m.status if m else 'NOT_AVAILABLE'})")
            else:
                cells.append(f"{k}={_num_txt(m.alternative_mean)} (Δ {m.delta.mean:+.6g})")
        typer.echo(f"{head}  [{s.comparison.status}] " + " · ".join(cells))
    typer.echo(deltas.note)


@project_app.command("runs")
def project_runs(slug: str, limit: int = 20):
    """Stored runs (only COMPLETED runs are stored; failed / interrupted runs are in the history)."""
    sf = _sf()
    for r in _proj(sf, slug).runs(limit):
        typer.echo(f"{r['run_id']}  model v{r['model_version']}  {r['created_at']}  reps {r['replications']}  COMPLETED")


@project_app.command("evaluate")
def project_evaluate(slug: str, run_id: str,
                     economics: Optional[Path] = typer.Option(None, help="economics YAML file"),
                     from_run: bool = typer.Option(False, "--from-run", help="use the economics block of the run's own model "
                                                   "version (default: the CURRENT version's block, as in the UI)")):
    """Economic evaluation of a STORED run (no simulation is executed). Always prints which assumptions were used."""
    from .cli_economics import _spec, print_evaluation
    sf = _sf()
    p = _proj(sf, slug)
    if economics:
        spec, source = _spec(str(economics)), f"file {economics}"
    elif from_run:
        spec, source = getattr(sf.run_model_of(p, run_id), "economics", None), "the run's own model version"
    else:
        spec, source = getattr(p.current_model(), "economics", None), f"current model v{p.meta.current_version}"
    if spec is None:
        typer.secho(f"ECONOMICS_ERROR: no economic assumptions in {source}", fg="red")
        raise typer.Exit(1)
    typer.echo(f"assumptions: {source} · economic_hash {spec.economic_hash()}")
    print_evaluation(sf.evaluate_economics(p, run_id, spec))


@project_app.command("compare")
def project_compare(slug: str, baseline_eval: str, alternative_eval: str):
    """Compare two stored economic evaluations (facts only: deltas, savings, payback; no ranking or recommendation)."""
    sf = _sf()
    c = sf.compare_economics(_proj(sf, slug), baseline_eval, alternative_eval)
    typer.echo(json.dumps(c.to_dict(), indent=2, default=str))


@project_app.command("report")
def project_report(slug: str, run_id: Optional[str] = typer.Option(None, help="default: latest run")):
    """Markdown + HTML + KPI CSV report of a run (describes the model version of THAT run)."""
    sf = _sf()
    for k, path in sf.generate_report(_proj(sf, slug), run_id=run_id).items():
        typer.echo(f"{k}: {path}")


@project_app.command("engineering-report")
def project_engineering_report(slug: str, run_id: str, output: Optional[Path] = typer.Option(None, "-o", help="output directory")):
    """1.1-D run engineering report (Markdown + HTML + JSON model) from stored evidence; nothing is simulated."""
    sf = _sf()
    p = _proj(sf, slug)
    for k, path in sf.export_engineering_report(p, sf.engineering_report(p, run_id), output).items():
        typer.echo(f"{k}: {path}")


@project_app.command("comparison-report")
def project_comparison_report(slug: str, baseline_run: str, alternative_run: str,
                              baseline_eval: Optional[str] = typer.Option(None, help="economic evaluation of the baseline run"),
                              alternative_eval: Optional[str] = typer.Option(None, help="economic evaluation of the alternative run"),
                              output: Optional[Path] = typer.Option(None, "-o", help="output directory")):
    """1.1-D scenario comparison report: compare-runs + existing economics comparison (if evaluated). Facts only."""
    sf = _sf()
    p = _proj(sf, slug)
    rep = sf.comparison_report(p, baseline_run, alternative_run, baseline_eval, alternative_eval)
    for k, path in sf.export_engineering_report(p, rep, output).items():
        typer.echo(f"{k}: {path}")
    typer.echo(f"physical: {rep.physical.status} ({rep.physical.comparison_mode}) · economics: {rep.economics.status}")


@project_app.command("manifest")
def project_manifest(slug: str, run_id: str, output: Optional[Path] = typer.Option(None, "-o")):
    """Reproducibility manifest of a stored run (versions, hashes, seeds, approval, datasets, economic evaluations)."""
    from .reporting.manifest import build_manifest
    sf = _sf()
    text = json.dumps(build_manifest(_proj(sf, slug), run_id), indent=2, allow_nan=False)
    if output:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"manifest: {output}")
    else:
        typer.echo(text)


@project_app.command("export")
def project_export(slug: str, dest: Path, attachments: bool = typer.Option(False, help="include attachments/")):
    """Portable .simproject archive (model versions, database, runs, reports; never secrets)."""
    sf = _sf()
    typer.echo(f"exported: {sf.workspace.export_project(slug, dest, include_attachments=attachments)}")


@project_app.command("import")
def project_import(archive: Path):
    """Import a .simproject archive into the workspace (a new slug if it already exists)."""
    sf = _sf()
    typer.echo(f"Project: {sf.workspace.import_project(archive).meta.slug}")
