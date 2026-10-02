"""`simforge maintenance ...`: failure models, corrective repair and preventive maintenance (engine >= 0.8.0).

    simforge maintenance show model.yaml         (or a project slug)
    simforge maintenance run model.yaml --seed 1  reliability KPIs + basic maintenance timeline
"""

from __future__ import annotations

import typer

from .cli_products import _dist, _load

maintenance_app = typer.Typer(help="Failures, corrective repair and preventive maintenance (engine >= 0.8.0)",
                              no_args_is_help=True)


def describe(model) -> list[str]:
    spec = getattr(model, "maintenance", None)
    if spec is None:
        return ["Modelo sin bloque 'maintenance' (averías legacy en params.failures, si las hay, con su contrato histórico)."]
    L = []
    for nid, nm in spec.nodes.items():
        L.append(f"Nodo '{nid}':")
        f = nm.failure
        if f is not None:
            exp = f" exposure={f.exposure}" if f.exposure else ""
            L.append(f"  fallo: {f.clock}{exp}, TTF {_dist(f.time_to_failure)}, reparación {_dist(f.repair_time)}, "
                     f"recursos {[u.resource for u in f.repair_resources] or 'ninguno'}, tras reparar: {f.repair_age_effect}")
        for t in nm.preventive:
            trig = (f"cada {_dist(t.every)} desde {_dist(t.first_due)}" if t.trigger == "CALENDAR_BASED" and t.every is not None
                    else f"en {_dist(t.first_due)}" if t.trigger == "CALENDAR_BASED"
                    else f"cada {_dist(t.usage_threshold)} de {t.usage_states}")
            L.append(f"  PM '{t.id}': {t.trigger} {trig}, duración {_dist(t.duration)}, recursos "
                     f"{[u.resource for u in t.resources] or 'ninguno'}, {t.start_policy}, edad de fallo: {t.failure_age_effect}")
    return L


@maintenance_app.command("show")
def show(target: str = typer.Argument(..., help="model file or project slug")):
    from .validation.semantics import verify_model
    sf, m = _load(target)
    for line in describe(m):
        typer.echo(line)
    rep, _ = verify_model(m, sf.registry)
    issues = [i for i in rep.issues if i.code.startswith("MAINTENANCE") or "maintenance" in (i.path or "")]
    for i in issues:
        typer.secho(f"  {i}", fg="red" if i.level.value == "error" else "yellow")


@maintenance_app.command("run")
def run(target: str = typer.Argument(..., help="model file or project slug"), seed: int = typer.Option(None)):
    from .experiments.runner import run_simulation
    from .validation.semantics import verify_model
    sf, m = _load(target)
    rep, cm = verify_model(m, sf.registry)
    if cm is None:
        for i in rep.errors:
            typer.secho(str(i), fg="red")
        raise typer.Exit(1)
    r = run_simulation(m, sf.registry, replications=1, keep_records=True, **({"base_seed": seed} if seed is not None else {}))
    k, rec = r.kpis, r.records[0]
    typer.echo(f"engine {r.engine_version} · model {r.model_hash} · seed {r.seeds[0]}")
    for nid in sorted(rec.node_condition_time):
        g = lambda key: k.mean(f"node.{nid}.{key}")  # noqa: E731
        typer.echo(f"node {nid}: failures {g('failure_count'):g}, corrective downtime {g('corrective_downtime_h'):.3f} h "
                   f"(waiting {g('waiting_for_repair_resource_h'):.3f} h + active {g('active_repair_time_h'):.3f} h), "
                   f"PM {g('preventive_maintenance_count'):g} ({g('preventive_maintenance_time_h'):.3f} h, waiting "
                   f"{g('waiting_for_pm_h'):.3f} h), uptime {g('uptime_h'):.3f} h")
        if f"node.{nid}.reliability_availability" in k.stats:
            typer.echo(f"  reliability availability {g('reliability_availability'):.4f} · observed MTBF (exposure) "
                       f"{g('observed_mtbf_exposure_h'):.3f} h · mean active repair {g('observed_mean_active_repair_s'):.1f} s")
    typer.echo("Timeline (maintenance):")
    for x in sorted(rec.maintenance, key=lambda x: x.get("t_fail", x.get("due", 0))):
        if x["type"] == "failure":
            typer.echo(f"  {x['node']}: FAILURE {x['t_fail']:.1f}s -> repair {x.get('t_repair_start', float('nan')):.1f}s "
                       f"-> up {x.get('t_repair_end', float('nan')):.1f}s")
        else:
            typer.echo(f"  {x['node']}: PM {x['pm']} due {x['due']:.1f}s -> start {x.get('start', float('nan')):.1f}s "
                       f"-> end {x.get('end', float('nan')):.1f}s")
