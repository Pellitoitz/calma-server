"""`simforge products ...`: product mix, explicit sequences, product routes/times and setups (engine >= 0.7.0).

Read-only views + run; the configuration is edited in the model file (YAML `production:` block) and saved as a new
version like any other change (the content hash covers it, so an earlier approval stops being valid).

    simforge products show model.yaml            (or a project slug)
    simforge products run model.yaml --seed 1    product KPIs + setup KPIs
"""

from __future__ import annotations

from pathlib import Path

import typer

products_app = typer.Typer(help="Product mix, sequences, product routes/times and setups (engine >= 0.7.0)",
                           no_args_is_help=True)


def _load(target: str):
    from .services.app import SimForgeApp
    sf = SimForgeApp(provider=None)
    if Path(target).exists():
        from .domain.io import load_model
        return sf, load_model(target)
    try:
        m = sf.open_project(target).current_model()
    except Exception as e:  # noqa: BLE001
        typer.secho(f"'{target}' no es un fichero de modelo ni un proyecto: {e}", fg="red")
        raise typer.Exit(2) from None
    if m is None:
        typer.secho("El proyecto no tiene modelo.", fg="red")
        raise typer.Exit(2)
    return sf, m


def _dist(d) -> str:
    j = d.model_dump(mode="json", exclude_none=True)
    j.pop("provenance", None)
    unit = j.pop("unit", "s")
    kind = j.pop("dist")
    if kind == "constant":
        return f"{j['value']} {unit}"
    return f"{kind}({', '.join(f'{k}={v}' for k, v in j.items())}) {unit}"


def describe(model) -> list[str]:
    from .domain.production import UNCONFIGURED
    prod = getattr(model, "production", None)
    if prod is None:
        return ["Modelo sin bloque 'production': un solo tipo de entidad, sin setups (comportamiento legacy)."]
    names = {e.id: e.name for e in model.entities}
    L = ["Productos (setup_key):"]
    L += [f"  {p:<14} {names.get(p, '?'):<16} setup_key={ps.setup_key or '—'}" for p, ps in prod.products.items()]
    L.append("Generación:")
    for s, g in prod.generation.items():
        if g.mode == "PROBABILISTIC_MIX":
            L.append(f"  {s}: PROBABILISTIC_MIX " + ", ".join(f"{p}={w:g}" for p, w in sorted(g.mix.items())))
        else:
            L.append(f"  {s}: EXPLICIT_SEQUENCE [{', '.join(g.sequence)}] repeat={g.repeat}")
    if prod.routes:
        L.append("Rutas:")
        L += [f"  {p}: {' → '.join(r.nodes)}" for p, r in prod.routes.items()]
    else:
        L.append("Rutas: enrutado del grafo (probabilidades de las conexiones, iguales para todos los productos)")
    if prod.processing:
        L.append("Tiempos por producto:")
        for n, t in prod.processing.items():
            L.append(f"  {n}: " + "; ".join(f"{p} = {_dist(d)}" for p, d in t.items()))
    for n, st in prod.setups.items():
        L.append(f"Setups en '{n}': {st.mode}, estado inicial {st.initial_state}, recursos "
                 f"{[u.resource for u in st.resources] or 'solo máquina'}, al acabar disponibilidad: {st.at_unavailability or '—'}")
        if st.constant is not None:
            L.append(f"  cualquier cambio de setup_key: {_dist(st.constant)}")
        for k, d in st.by_target.items():
            L.append(f"  → {k}: {_dist(d)}")
        for a, row in st.matrix.items():
            for b, d in row.items():
                L.append(f"  {a} → {b}: {_dist(d)}")
        for k, d in st.from_unconfigured.items():
            L.append(f"  {UNCONFIGURED} → {k}: {_dist(d)}")
    return L


@products_app.command("show")
def show(target: str = typer.Argument(..., help="model file or project slug")):
    """Products, mix/sequence, routes, product times and setup configuration, plus verification issues."""
    from .validation.semantics import verify_model
    sf, m = _load(target)
    for line in describe(m):
        typer.echo(line)
    rep, _ = verify_model(m, sf.registry)
    codes = ("PRODUCT", "MIX", "ROUTE", "ROUTING", "SETUP", "MISSING")
    issues = [i for i in rep.issues if i.code.startswith(codes)]
    if issues:
        typer.echo("Verificación:")
        for i in issues:
            typer.secho(f"  {i}", fg="red" if i.level.value == "error" else "yellow")


@products_app.command("run")
def run(target: str = typer.Argument(..., help="model file or project slug"), seed: int = typer.Option(None),
        replications: int = typer.Option(None)):
    """Run and print per-product and setup KPIs (means over replications)."""
    from .experiments.runner import run_simulation
    from .validation.semantics import verify_model
    sf, m = _load(target)
    rep, cm = verify_model(m, sf.registry)
    if cm is None:
        for i in rep.errors:
            typer.secho(str(i), fg="red")
        raise typer.Exit(1)
    kw = {k: v for k, v in (("base_seed", seed), ("replications", replications)) if v is not None}
    r = run_simulation(m, sf.registry, **kw)
    k = r.kpis
    typer.echo(f"engine {r.engine_version} · model {r.model_hash} · seeds {r.seeds}")
    typer.echo(f"units_completed {k.mean('units_completed'):g} · throughput {k.mean('throughput_per_hour'):.3f}/h")
    prods = sorted({key.split(".")[1] for key in k.stats if key.startswith("product.")})
    if prods:
        typer.echo(f"{'product':<14}{'created':>9}{'completed':>11}{'thr/h':>9}{'avg WIP':>9}{'lead time s':>13}")
        for p in prods:
            typer.echo(f"{p:<14}{k.mean(f'product.{p}.created'):>9.1f}{k.mean(f'product.{p}.completed'):>11.1f}"
                       f"{k.mean(f'product.{p}.throughput_per_hour'):>9.2f}{k.mean(f'product.{p}.avg_wip'):>9.2f}"
                       f"{k.mean(f'product.{p}.avg_lead_time_s'):>13.1f}")
    nodes = sorted({key.split(".")[1] for key in k.stats if key.endswith(".setup_count") and key.startswith("node.")})
    for n in nodes:
        typer.echo(f"node {n}: setups {k.mean(f'node.{n}.setup_count'):g}, setup {k.mean(f'node.{n}.setup_time_h'):.4f} h "
                   f"(util {k.mean(f'node.{n}.utilization_setup'):.3f}), processing {k.mean(f'node.{n}.processing_time_h'):.4f} h "
                   f"(util {k.mean(f'node.{n}.utilization_processing'):.3f})")
    if "total_setup_count" in k.stats:
        typer.echo(f"total setups {k.mean('total_setup_count'):g} · total setup time {k.mean('total_setup_time_h'):.4f} h")
