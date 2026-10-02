"""Edits of the `availability` block (used by the CLI and the UI). Every function returns a NEW validated model;
saving it creates a new model version, and the changed content hash invalidates the approval."""

from __future__ import annotations

import copy
from typing import Any

from .calendar import DAYS
from .isms import ISMSModel
from .isms_ext import SimModel


class CalendarEditError(ValueError):
    pass


def _data(model: ISMSModel) -> dict:
    return copy.deepcopy(model.model_dump(mode="json"))


def _avail(data: dict) -> dict:
    if not data.get("availability"):
        raise CalendarEditError("El modelo no tiene calendarios todavía: configura primero el modo (setup).")
    return data["availability"]


def _done(data: dict) -> SimModel:
    return SimModel.model_validate(data)


def parse_days(text: str) -> list[str]:
    """'mon-fri', 'sat,sun', 'all', 'mon'."""
    t = text.strip().lower()
    if t in ("all", "*", "todos"):
        return list(DAYS)
    out: list[str] = []
    for part in t.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            i, j = DAYS.index(a), DAYS.index(b)
            out += DAYS[i:j + 1] if i <= j else DAYS[i:] + DAYS[:j + 1]
        elif part:
            if part not in DAYS:
                raise CalendarEditError(f"día desconocido '{part}' (usa {', '.join(DAYS)})")
            out.append(part)
    return list(dict.fromkeys(out))


def parse_windows(text: str) -> list[dict]:
    """'06:00-14:00, 14:00-22:00' -> [{"start": "06:00", "end": "14:00"}, ...]."""
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise CalendarEditError(f"intervalo inválido '{part}' (formato HH:MM-HH:MM)")
        a, b = (x.strip() for x in part.split("-", 1))
        out.append({"start": a, "end": b})
    return out


def setup(model: ISMSModel, mode: str, start_weekday: str = "mon", start_time: str = "00:00", start_date: str | None = None,
          timezone: str | None = None) -> SimModel:
    data = _data(model)
    av = data.get("availability") or {"calendars": [], "resources": {}, "nodes": {}, "always_available": [], "operations": {}}
    av.update({"mode": mode, "start_weekday": start_weekday, "start_time": start_time, "start_date": start_date,
               "timezone": timezone})
    data["availability"] = av
    return _done(data)


def upsert_calendar(model: ISMSModel, cal_id: str, name: str = "", shifts: dict[str, list[dict]] | None = None,
                    breaks: list[dict] | None = None, description: str = "") -> SimModel:
    """Create or replace the weekly pattern of a calendar (exceptions kept)."""
    data = _data(model)
    av = _avail(data)
    cals = av["calendars"]
    old = next((c for c in cals if c["id"] == cal_id), None)
    new = {"id": cal_id, "name": name or (old or {}).get("name", ""), "description": description or (old or {}).get("description", ""),
           "weekly": shifts if shifts is not None else (old or {}).get("weekly", {}),
           "breaks": breaks if breaks is not None else (old or {}).get("breaks", []),
           "exceptions": (old or {}).get("exceptions", [])}
    if old:
        cals[cals.index(old)] = new
    else:
        cals.append(new)
    return _done(data)


def add_exception(model: ISMSModel, cal_id: str, exception: dict[str, Any]) -> SimModel:
    data = _data(model)
    c = next((c for c in _avail(data)["calendars"] if c["id"] == cal_id), None)
    if c is None:
        raise CalendarEditError(f"No existe el calendario '{cal_id}'.")
    c.setdefault("exceptions", []).append(exception)
    return _done(data)


def remove_exception(model: ISMSModel, cal_id: str, date: str) -> SimModel:
    data = _data(model)
    c = next((c for c in _avail(data)["calendars"] if c["id"] == cal_id), None)
    if c is None:
        raise CalendarEditError(f"No existe el calendario '{cal_id}'.")
    c["exceptions"] = [e for e in c.get("exceptions", []) if str(e["date"]) != date]
    return _done(data)


def assign(model: ISMSModel, target: str, cal_id: str | None, kind: str) -> SimModel:
    """kind = 'resource' | 'node'. cal_id None or 'ALWAYS_AVAILABLE' = explicitly always available."""
    data = _data(model)
    av = _avail(data)
    ids = {r["id"] for r in data["resources"]} if kind == "resource" else {n["id"] for n in data["nodes"]}
    if target not in ids:
        raise CalendarEditError(f"No existe el {'recurso' if kind == 'resource' else 'nodo'} '{target}'.")
    section = av["resources"] if kind == "resource" else av["nodes"]
    section.pop(target, None)
    av["always_available"] = [x for x in av.get("always_available", []) if x != target]
    if cal_id in (None, "ALWAYS_AVAILABLE"):
        av["always_available"].append(target)
    else:
        if cal_id not in {c["id"] for c in av["calendars"]}:
            raise CalendarEditError(f"No existe el calendario '{cal_id}'.")
        section[target] = cal_id
    return _done(data)


def set_policy(model: ISMSModel, node_id: str, at_unavailability: str | None, start_rule: str | None, reason: str = "") -> SimModel:
    data = _data(model)
    av = _avail(data)
    if node_id not in {n["id"] for n in data["nodes"]}:
        raise CalendarEditError(f"No existe el nodo '{node_id}'.")
    av["operations"][node_id] = {"at_unavailability": at_unavailability, "start_rule": start_rule, "reason": reason}
    return _done(data)


def remove_calendar(model: ISMSModel, cal_id: str) -> SimModel:
    data = _data(model)
    av = _avail(data)
    used = [k for k, v in {**av["resources"], **av["nodes"]}.items() if v == cal_id]
    if used:
        raise CalendarEditError(f"El calendario '{cal_id}' está asignado a {used}: reasígnalos antes de borrarlo.")
    av["calendars"] = [c for c in av["calendars"] if c["id"] != cal_id]
    return _done(data)
