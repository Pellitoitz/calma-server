"""`simforge calendar ...`: shifts, breaks, exceptions, assignments and end-of-availability policies, on projects.

Every change is a NEW model version (the approval is invalidated by the content hash).

    simforge calendar setup linea --mode relative_week --start-weekday mon --start-time 00:00
    simforge calendar create linea turno_manana --days mon-fri --shifts 06:00-14:00 --breaks 10:00-10:15,12:30-13:00
    simforge calendar assign linea turno_manana --resource operator_1
    simforge calendar assign linea ALWAYS_AVAILABLE --node machine
    simforge calendar policy linea assembly --at-unavailability PAUSE_RESUME --start-rule START_ANY_TIME
    simforge calendar exception linea turno_manana --date 2026-10-12 --type NON_WORKING_DAY --reason "festivo" --scope SHIFTS_STARTING_ON_DATE
    simforge calendar show linea
    simforge calendar validate linea           (or a model file: simforge calendar validate model.yaml)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

calendar_app = typer.Typer(help="Calendars, shifts, breaks, exceptions and availability policies (engine >= 0.6.0)",
                           no_args_is_help=True)


def _sf():
    from .services.app import SimForgeApp
    return SimForgeApp(provider=None)


def _ctx(slug: str):
    sf = _sf()
    try:
        p = sf.open_project(slug)
    except Exception as e:  # noqa: BLE001
        typer.secho(f"Proyecto '{slug}' no encontrado: {e}", fg="red")
        raise typer.Exit(2) from None
    m = p.current_model()
    if m is None:
        typer.secho("El proyecto no tiene modelo.", fg="red")
        raise typer.Exit(2)
    return sf, p, m


def _save(sf, p, new, msg: str, by: str) -> None:
    v = sf.save_model(p, new, msg, actor="user")
    typer.secho(f"v{v}: {msg} (nueva versión; la aprobación anterior ya no vale para esta versión)", fg="green")
    _issues(new, sf.registry, quiet_ok=True)


def _edit(fn):
    from pydantic import ValidationError

    from .domain.calendar_edit import CalendarEditError
    try:
        return fn()
    except (CalendarEditError, ValidationError, ValueError, KeyError) as e:
        typer.secho(str(e), fg="red")
        raise typer.Exit(1) from None


def _issues(model, registry, quiet_ok: bool = False) -> bool:
    from .validation.availability import availability_issues
    issues = availability_issues(model, registry)
    for i in issues:
        tag = "REQUIRES_ENGINEER_DECISION" if i.code.startswith("DECISION_") else i.level.value.upper()
        typer.secho(f"{tag:<27} {i.code}: {i.message}", fg="red" if i.level.value == "error" else "yellow")
    if not issues and not quiet_ok:
        typer.secho("Calendarios sin problemas.", fg="green")
    return not any(i.level.value == "error" for i in issues)


@calendar_app.command("setup")
def setup(slug: str, mode: str = typer.Option(..., help="relative_week | dated"), start_weekday: str = "mon",
          start_time: str = "00:00", start_date: Optional[str] = typer.Option(None, help="dated: YYYY-MM-DD (simulation t=0)"),
          timezone: Optional[str] = typer.Option(None, help="dated: IANA zone, e.g. Europe/Madrid or UTC (no default)"),
          by: str = "engineer"):
    """Create/adjust the availability block: relative week or dated calendar (never mixed)."""
    from .domain import calendar_edit as ce
    sf, p, m = _ctx(slug)
    _save(sf, p, _edit(lambda: ce.setup(m, mode, start_weekday, start_time, start_date, timezone)),
          f"calendars: mode {mode}", by)


@calendar_app.command("create")
def create(slug: str, cal_id: str, name: str = "", days: str = typer.Option("mon-fri", help="mon-fri | sat,sun | all"),
           shifts: str = typer.Option(..., help="06:00-14:00,14:00-22:00 (22:00-06:00 crosses midnight)"),
           breaks: str = typer.Option("", help="10:00-10:15,12:30-13:00 (applied on the same days)"),
           add_days: Optional[list[str]] = typer.Option(None, help="extra pattern: 'sat=06:00-12:00' (repeatable)"),
           by: str = "engineer"):
    """Create or replace a calendar's weekly pattern (exceptions are kept)."""
    from .domain import calendar_edit as ce
    sf, p, m = _ctx(slug)

    def build():
        weekly = {d: ce.parse_windows(shifts) for d in ce.parse_days(days)}
        for extra in add_days or []:
            d, _, w = extra.partition("=")
            for day in ce.parse_days(d):
                weekly[day] = ce.parse_windows(w)
        brks = [{**b, "days": ce.parse_days(days)} for b in ce.parse_windows(breaks)] if breaks else []
        return ce.upsert_calendar(m, cal_id, name, weekly, brks)
    _save(sf, p, _edit(build), f"calendar {cal_id}: {days} {shifts}" + (f" breaks {breaks}" if breaks else ""), by)


@calendar_app.command("exception")
def exception(slug: str, cal_id: str, date: str = typer.Option(..., help="YYYY-MM-DD (dated mode)"),
              type_: str = typer.Option(..., "--type", help="NON_WORKING_DAY | OVERRIDE_WORKING_INTERVALS | OVERTIME | EXTRA_SHIFT"),
              intervals: str = typer.Option("", help="06:00-12:00 (not for NON_WORKING_DAY)"),
              reason: str = typer.Option(...), breaks_apply: Optional[bool] = typer.Option(None, "--breaks-apply/--no-breaks-apply"),
              scope: Optional[str] = typer.Option(None, help="NON_WORKING_DAY: SHIFTS_STARTING_ON_DATE | CALENDAR_DAY"),
              by: str = "engineer"):
    """Add a dated exception: holiday, override of the day, overtime or extra shift."""
    from .domain import calendar_edit as ce
    sf, p, m = _ctx(slug)
    exc = {"date": date, "type": type_, "intervals": ce.parse_windows(intervals) if intervals else [], "reason": reason,
           "breaks_apply": breaks_apply, "scope": scope}
    _save(sf, p, _edit(lambda: ce.add_exception(m, cal_id, exc)), f"calendar {cal_id}: {type_} {date}", by)


@calendar_app.command("assign")
def assign(slug: str, cal_id: str = typer.Argument(..., help="calendar id or ALWAYS_AVAILABLE"),
           resource: Optional[str] = None, node: Optional[str] = None, by: str = "engineer"):
    """Assign a calendar (or explicit ALWAYS_AVAILABLE) to an operator/tool or a machine/source."""
    from .domain import calendar_edit as ce
    if (resource is None) == (node is None):
        typer.secho("Indica --resource o --node.", fg="red")
        raise typer.Exit(2)
    sf, p, m = _ctx(slug)
    target, kind = (resource, "resource") if resource else (node, "node")
    _save(sf, p, _edit(lambda: ce.assign(m, target, cal_id, kind)), f"calendar: {kind} {target} -> {cal_id}", by)


@calendar_app.command("policy")
def policy(slug: str, node: str,
           at_unavailability: str = typer.Option(..., help="FINISH_CURRENT | PAUSE_RESUME | STOP_RESTART"),
           start_rule: str = typer.Option(..., help="START_ANY_TIME | REQUIRE_FULL_WINDOW (deterministic times only)"),
           reason: str = "", by: str = "engineer"):
    """What happens to an operation when its node/resources become unavailable (engineer decision)."""
    from .domain import calendar_edit as ce
    sf, p, m = _ctx(slug)
    _save(sf, p, _edit(lambda: ce.set_policy(m, node, at_unavailability, start_rule, reason)),
          f"calendar policy {node}: {at_unavailability}, {start_rule}", by)


@calendar_app.command("remove")
def remove(slug: str, cal_id: str, by: str = "engineer"):
    """Delete a calendar that is no longer assigned."""
    from .domain import calendar_edit as ce
    sf, p, m = _ctx(slug)
    _save(sf, p, _edit(lambda: ce.remove_calendar(m, cal_id)), f"calendar {cal_id} removed", by)


@calendar_app.command("list")
def list_(slug: str):
    """Calendars, assignments and policies of the current model version."""
    _, p, m = _ctx(slug)
    av = getattr(m, "availability", None)
    if av is None:
        typer.echo("Sin calendarios: todos los recursos disponibles siempre (modelo legacy).")
        return
    typer.echo(f"mode {av.mode}" + (f" start {av.start_date} {av.start_time} {av.timezone}" if av.mode == "dated"
                                     else f" start {av.start_weekday} {av.start_time}") + f" | calendars hash {av.calendar_hash()}")
    for c in av.calendars:
        typer.echo(f"  {c.id:<20} {c.name:<24} days {','.join(c.weekly)}  breaks {len(c.breaks)}  exceptions {len(c.exceptions)}")
    for rid, cid in av.resources.items():
        typer.echo(f"  resource {rid:<20} -> {cid}")
    for nid, cid in av.nodes.items():
        typer.echo(f"  node     {nid:<20} -> {cid}")
    for x in av.always_available:
        typer.echo(f"  {x:<29} -> ALWAYS_AVAILABLE")
    for nid, pol in av.operations.items():
        typer.echo(f"  policy   {nid:<20} at_unavailability={pol.at_unavailability} start_rule={pol.start_rule}")


@calendar_app.command("show")
def show(slug: str, cal_id: Optional[str] = typer.Argument(None)):
    """Weekly view (shifts, breaks, planned hours, exceptions) + planned time over the simulated horizon."""
    from .domain.calendar import week_view
    from .validation.availability import planned_summary
    sf, p, m = _ctx(slug)
    av = getattr(m, "availability", None)
    if av is None:
        typer.echo("Sin calendarios.")
        return
    for c in av.calendars:
        if cal_id in (None, c.id):
            typer.echo(week_view(av, c) + "\n")
    rows = planned_summary(m, sf.registry)
    if rows:
        typer.echo(f"PLANNED OVER THE HORIZON ({m.simulation.horizon.value:g} {m.simulation.horizon.unit} elapsed):")
        for r in rows:
            typer.echo(f"  {r['kind']:<8} {r['id']:<18} {r['calendar']:<24} planned {r['planned_available_s'] / 3600:7.2f} h  "
                       f"breaks {r['break_s'] / 3600:6.2f} h  off {r['off_shift_s'] / 3600:7.2f} h"
                       + (f"  policy {r.get('at_unavailability')}/{r.get('start_rule')}" if r["kind"] == "node" else ""))


@calendar_app.command("validate")
def validate(target: str = typer.Argument(..., help="project slug or model file (.yaml/.json)")):
    """Calendar checks: ERROR, WARNING and REQUIRES_ENGINEER_DECISION (nothing is resolved silently)."""
    from .domain.io import load_model
    if Path(target).suffix in (".yaml", ".yml", ".json") and Path(target).exists():
        sf = _sf()
        m = load_model(target)
    else:
        sf, _, m = _ctx(target)
    if getattr(m, "availability", None) is None:
        typer.echo("Sin calendarios: disponibilidad continua (compatibilidad).")
        return
    raise typer.Exit(0 if _issues(m, sf.registry) else 1)
