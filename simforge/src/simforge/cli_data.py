"""`simforge data ...` and `simforge project ...`: measured data -> engineer decision -> model parameter, offline.

    simforge project new "Linea selectiva" --model examples/05_selective_soldering.yaml
    simforge data preview tiempos_montaje.xlsx
    simforge data import linea_selectiva tiempos_montaje.xlsx --name montaje --sheet Hoja1 --column Tiempo \
        --unit s --quantity PROCESSING_TIME --basis PER_CIRCUIT --timestamp Fecha
    simforge data inspect linea_selectiva montaje@v1
    simforge data rows linea_selectiva montaje@v1 KEEP 20 61 --reason "ciclos largos reales" --by ana
    simforge data fit linea_selectiva montaje@v1 --by ana
    simforge data decide linea_selectiva montaje@v1 USE_FITTED --fit fit_... --candidate lognormal --by ana
    simforge data apply linea_selectiva montaje@v1 dec_... --target nodes.assembly.params.process_time --target-basis PER_CIRCUIT --by ana
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
        physical_max: Optional[float] = None, as_json: bool = typer.Option(False, "--json")):
    """Fit candidate distributions: ranking (AIC), GOF evidence, industrial plausibility, SUGGESTED candidate."""
    from .data.report import fit_text
    sf = _sf()
    r = _run(lambda: sf.data(_proj(sf, slug)).fit(dataset, by=by, group=_pairs(group, "--group"), pooled=pooled,
                                                  physical_min=physical_min, physical_max=physical_max))
    typer.echo(json.dumps(r, indent=1, ensure_ascii=False, default=str) if as_json else fit_text(r))
    if not as_json:
        typer.echo(f"\nNada se ha aplicado. Decide: simforge data decide {slug} {dataset} USE_FITTED --fit {r['fit_id']} "
                   "--candidate <familia> --by <ingeniero>  (o USE_EMPIRICAL / USE_DETERMINISTIC --derivation MEAN|MEDIAN|ENGINEER_VALUE)")


@data_app.command("decide")
def decide(slug: str, dataset: str,
           decision: str = typer.Argument(..., help="USE_DETERMINISTIC | USE_EMPIRICAL | USE_FITTED | KEEP_WITHOUT_APPLYING | REJECT"),
           by: str = typer.Option(...), reason: str = "", group: Optional[list[str]] = typer.Option(None), pooled: bool = False,
           derivation: Optional[str] = typer.Option(None, help="USE_DETERMINISTIC: MEAN | MEDIAN | ENGINEER_VALUE"),
           value: Optional[float] = typer.Option(None, help="ENGINEER_VALUE in the dataset unit"),
           fit_id: Optional[str] = typer.Option(None, "--fit"), candidate: Optional[str] = None,
           trunc_lower: Optional[float] = None, trunc_upper: Optional[float] = None, trunc_reason: Optional[str] = None,
           accept: Optional[list[str]] = typer.Option(None, help="plausibility warning codes explicitly accepted")):
    """Record the ENGINEER DECISION (nothing reaches the model until `data apply`)."""
    trunc = None
    if trunc_lower is not None or trunc_upper is not None:
        if not trunc_reason:
            typer.secho("El truncamiento necesita --trunc-reason.", fg="red")
            raise typer.Exit(2)
        trunc = {"lower": trunc_lower, "upper": trunc_upper, "reason": trunc_reason}
    sf = _sf()
    ev = _run(lambda: sf.data(_proj(sf, slug)).decide(dataset, decision.upper(), by, reason=reason, group=_pairs(group, "--group"),
                                                      pooled=pooled, derivation=derivation.upper() if derivation else None,
                                                      engineer_value=value, fit_id=fit_id, candidate=candidate, truncation=trunc,
                                                      accept_warnings=accept))
    typer.secho(f"{ev.decision_id}: {ev.decision.value} by {ev.by} (n={ev.n_used}) -> {ev.distribution or 'nada que aplicar'}", fg="green")
    if ev.distribution:
        typer.echo(f"Aplicar: simforge data apply {slug} {dataset} {ev.decision_id} --target nodes.<id>.params.<param> "
                   "--target-basis <BASIS> --by <ingeniero>")


@data_app.command("apply")
def apply(slug: str, dataset: str, decision_id: str, target: str = typer.Option(..., help="e.g. nodes.assembly.params.process_time"),
          target_basis: str = typer.Option(..., help="what ONE sample of the target represents (PER_CIRCUIT, PER_RACK...)"),
          by: str = typer.Option(...), factor: Optional[float] = typer.Option(None, help="explicit basis conversion factor"),
          formula: Optional[str] = None, inputs: Optional[str] = typer.Option(None, help='JSON, e.g. {"circuits_per_rack": 4}'),
          ack: Optional[list[str]] = typer.Option(None, help="acknowledged semantics: SCALING_IS_NOT_SUM, WORK_UNITS_SCALING")):
    """Write the decided value into the current model -> NEW model version, approval invalidated."""
    conv = None
    if factor is not None:
        conv = {"factor": factor, "formula": formula or "", "inputs": json.loads(inputs) if inputs else None}
    sf = _sf()
    r = _run(lambda: sf.data(_proj(sf, slug)).apply(dataset, decision_id, target, target_basis, by, conversion=conv, acknowledge=ack))
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
    from .reporting.report import HEADLINE, fmt, kpi_rows
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
        typer.echo(f"  {r['label']:<22} {fmt(r['metric'], r['mean']):>14}{ci}")
