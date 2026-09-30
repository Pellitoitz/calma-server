"""Engine vs. reference comparison, KPI by KPI and scenario by scenario. No aggregate score.

    absolute_difference    = engine - reference
    relative_error_percent = |engine - reference| / |reference| x 100     (None when reference = 0)
    pp_difference          = |engine - reference| x 100                   (fractions only: percentage points)

Tolerance types: abs (same unit as the KPI), rel (%), pp (percentage points, for 0-1 fractions).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The benchmark table (shared column layout for AnyLogic and engine results)
KPI_COLUMNS: list[tuple[str, str, str]] = [  # (column, unit, kind)
    ("production", "racks", "count"),
    ("throughput", "racks/h", "rate"),
    ("avg_wip", "racks", "level"),
    ("max_wip", "racks", "count"),
    ("lead_time", "s", "time"),
    ("operator_utilization", "fraction", "fraction"),
    ("selective_utilization", "fraction", "fraction"),
    ("selective_starvation", "fraction", "fraction"),
    ("selective_blocking", "fraction", "fraction"),
    ("trips", "trips", "count"),
    ("racks_transported", "racks", "count"),
    ("walking_time", "h", "time"),
]
FRACTIONS = {c for c, _, k in KPI_COLUMNS if k == "fraction"}
SCENARIO = "racks"


class ReferenceError_(ValueError):
    pass


def _num(x: Any) -> float | None:
    if x is None or str(x).strip() == "":
        return None
    return float(str(x).strip().replace(",", "."))


def reference_template(scenarios: list[int]) -> str:
    lines = [",".join([SCENARIO, *[c for c, _, _ in KPI_COLUMNS]])]
    lines += [",".join([str(s)] + [""] * len(KPI_COLUMNS)) for s in scenarios]
    return "\n".join(lines) + "\n"


def load_reference(path: Path) -> dict[int, dict[str, float | None]]:
    """Blank cells stay None (never filled in). Fractions > 1 are rejected (probably entered as %)."""
    if not path.exists():
        return {}
    out: dict[int, dict[str, float | None]] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or []) - {SCENARIO, *[c for c, _, _ in KPI_COLUMNS]}
        if unknown:
            raise ReferenceError_(f"Unknown columns in {path.name}: {sorted(unknown)}")
        for row in reader:
            sc = _num(row.get(SCENARIO))
            if sc is None:
                continue
            vals = {c: _num(row.get(c)) for c, _, _ in KPI_COLUMNS}
            for c in FRACTIONS:
                if vals[c] is not None and not 0 <= vals[c] <= 1:
                    raise ReferenceError_(f"{path.name}: {c} = {vals[c]} for racks={int(sc)} must be a fraction 0-1 (not %)")
            out[int(sc)] = vals
    return out


@dataclass
class Tolerance:
    type: str  # abs | rel | pp
    value: float
    justification: str = ""
    status: str = "PROPOSED"


def load_tolerances(raw: dict) -> dict[str, Tolerance]:
    return {k: Tolerance(t["type"], float(t["value"]), t.get("justification", ""), t.get("status", "PROPOSED")) for k, t in raw.items()}


def compare(engine: dict[int, dict[str, Any]], reference: dict[int, dict[str, float | None]],
            tolerances: dict[str, Tolerance]) -> list[dict[str, Any]]:
    rows = []
    for sc in sorted(engine):
        e_row, r_row = engine[sc], reference.get(sc, {})
        for col, unit, _kind in KPI_COLUMNS:
            e, r = e_row.get(col), r_row.get(col)
            tol = tolerances.get(col)
            row: dict[str, Any] = {"racks": sc, "kpi": col, "unit": unit, "anylogic": r, "engine": e,
                                   "absolute_difference": None, "relative_error_percent": None, "pp_difference": None,
                                   "tolerance": f"{tol.type} {tol.value:g}" if tol else None, "status": None}
            if e_row.get("error"):
                row["status"] = "ENGINE_ERROR"
            elif e is None:
                row["status"] = "NO_ENGINE_VALUE"
            elif r is None:
                row["status"] = "NO_REFERENCE"
            else:
                d = e - r
                row["absolute_difference"] = d
                row["relative_error_percent"] = abs(d) / abs(r) * 100 if r != 0 else None
                if col in FRACTIONS:
                    row["pp_difference"] = abs(d) * 100
                if tol is None:
                    row["status"] = "NO_TOLERANCE"
                else:
                    if tol.type == "abs":
                        ok = abs(d) <= tol.value + 1e-12
                    elif tol.type == "pp":
                        ok = abs(d) * 100 <= tol.value + 1e-12
                    elif r == 0:
                        ok = e == 0  # relative tolerance undefined at reference 0
                    else:
                        ok = row["relative_error_percent"] <= tol.value + 1e-12
                    row["status"] = "PASS" if ok else ("FAIL_REF_ZERO" if tol.type == "rel" and r == 0 else "FAIL")
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    keys = columns or list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
