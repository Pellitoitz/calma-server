"""Structured edits on the ISMS (the chat is never the model).

When an edited field holds a parameter reference ('$buffer_1_capacity'), the PARAMETER is changed,
so provenance stays traceable: "Cambia el buffer a 8" -> parameters.buffer_1_capacity.value: 5 -> 8
(USER_PROVIDED, source chat). Engineer changes to AI-generated values are recorded as corrections.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..domain.isms import ISMSModel
from ..domain.paths import PathError, flatten, get_value
from ..domain.units import UnitError, dimension_of, from_base, to_base

REF = re.compile(r"^\$([a-z][a-z0-9_]*)$")


def _param(model: ISMSModel, pid: str):
    return next((p for p in model.parameters if p.id == pid), None)


def resolve_edit(model: ISMSModel, path: str, value: Any) -> tuple[str, Any]:
    """Map an edit on a field to the parameter it references (if any). Returns (path, value) to set."""
    try:
        cur = get_value(model, path)
    except (KeyError, PathError):
        return path, value
    if isinstance(cur, str) and REF.match(cur):
        return f"parameters.{REF.match(cur).group(1)}.value", value
    if isinstance(cur, dict) and isinstance(value, dict) and cur.get("dist") == value.get("dist") == "constant":
        ref = cur.get("value")
        if isinstance(ref, str) and REF.match(ref):
            pid = REF.match(ref).group(1)
            prm = _param(model, pid)
            v = value.get("value")
            new_unit, field_unit = value.get("unit", "s"), cur.get("unit", "s")
            if prm is not None and new_unit != field_unit:
                try:
                    v = from_base(to_base(float(v), new_unit), field_unit)
                except (UnitError, KeyError):
                    pass
            return f"parameters.{pid}.value", v
    return path, value


def resolve_factor_path(model: ISMSModel, path: str) -> str:
    try:
        cur = get_value(model, path)
    except (KeyError, PathError):
        return path
    if isinstance(cur, str) and REF.match(cur):
        return f"parameters.{REF.match(cur).group(1)}.value"
    if isinstance(cur, dict) and isinstance(cur.get("value"), str) and REF.match(cur["value"]):
        return f"parameters.{REF.match(cur['value']).group(1)}.value"
    return path


def chat_provenance(request: str, source: str = "chat") -> dict:
    return {"status": "provided_by_client", "source": source, "note": request[:160],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def usages(model: ISMSModel, pid: str) -> list[str]:
    ref = f"${pid}"
    return [p for p, v in flatten(model).items() if isinstance(v, str) and re.search(re.escape(ref) + r"\b", v)]


def friendly(model: ISMSModel, changes: list[tuple[str, Any, Any]]) -> list[dict[str, Any]]:
    out = []
    for path, before, after in changes:
        m = re.match(r"parameters\.([a-z0-9_]+)\.value$", path)
        if m:
            pid = m.group(1)
            prm = _param(model, pid)
            out.append({"parameter": pid, "used_in": ", ".join(usages(model, pid)) or "—", "before": before, "after": after,
                        "unit": prm.unit if prm else ""})
        elif ".provenance" not in path:
            out.append({"parameter": path, "used_in": path, "before": before, "after": after, "unit": ""})
    return out


def correction_reason(request: str) -> str | None:
    m = re.search(r"\b(porque|ya que|debido a|because|since|as)\b(.+)$", request, re.I)
    return m.group(2).strip(" .") if m else None


def is_ai_value(model: ISMSModel, pid: str) -> bool:
    """A parameter value produced by the AI build (description, assumption, default), not yet set by the engineer."""
    prm = _param(model, pid)
    if prm is None:
        return False
    if prm.provenance is None:
        return True
    return prm.provenance.source in (None, "description", "assumed", "default", "calculated") or prm.provenance.status.value in (
        "assumed", "default")


def unit_ok(unit: str) -> bool:
    try:
        dimension_of(unit)
        return True
    except UnitError:
        return False
