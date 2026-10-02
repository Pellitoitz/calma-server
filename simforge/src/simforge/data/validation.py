"""Row-by-row interpretation of a raw table into observations, with every decision recorded.

Never: fill a missing value, guess a unit, drop a row. A row that cannot be read is INVALID (kept, with the reason);
a row that can be read but is suspicious is REQUIRES_REVIEW (kept, not used until accepted).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from typing import Any

from ..domain.units import UnitError, from_base
from .dataset import ColumnMapping, Observation, RowStatus
from .importers import RawTable
from .quantities import SUPPORT, UNKNOWN_UNIT, QuantityType, base_unit, normalize_unit, to_base_value

_NUM_UNIT = re.compile(r"^\s*([-+]?[\d.,]+)\s*([A-Za-zµ/\.]+)?\s*$")
_THOUSANDS_DOT = re.compile(r"^[-+]?\d{1,3}(\.\d{3})+(,\d+)?$")
_THOUSANDS_COMMA = re.compile(r"^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$")


class NumberParseError(ValueError):
    pass


def parse_number(text: str, decimal: str) -> tuple[float, list[str]]:
    """Parse with an EXPLICIT decimal mark. Returns (value, notes)."""
    s = text.strip().replace(" ", "").replace(" ", "")
    notes: list[str] = []
    if decimal == ",":
        if "." in s:
            if not _THOUSANDS_DOT.match(s):
                raise NumberParseError(f"'{text}': punto inesperado con decimal ','")
            s = s.replace(".", "")
            notes.append("THOUSANDS_SEPARATOR_REMOVED")
        s = s.replace(",", ".")
    else:
        if "," in s:
            if not _THOUSANDS_COMMA.match(s):
                raise NumberParseError(f"'{text}': coma inesperada con decimal '.'")
            s = s.replace(",", "")
            notes.append("THOUSANDS_SEPARATOR_REMOVED")
    try:
        v = float(s)
    except ValueError:
        raise NumberParseError(f"'{text}' no es un número") from None
    if not math.isfinite(v):
        raise NumberParseError(f"'{text}' no es un número finito")
    return v, notes


def _duration_seconds(v: Any) -> float | None:
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, dt.time):
        return v.hour * 3600 + v.minute * 60 + v.second + v.microsecond / 1e6
    return None


def _timestamp(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    raise ValueError(s)


def interpret(table: RawTable, mapping: ColumnMapping, quantity: QuantityType) -> tuple[list[Observation], str, list[str], list[str]]:
    """Return (observations, analysis_unit, transformations, notes)."""
    dim = SUPPORT[quantity]["dimension"]
    nunit = base_unit(dim)
    vi = table.column_index(mapping.value)
    ui = table.column_index(mapping.unit_column) if mapping.unit_column else None
    ti = table.column_index(mapping.timestamp) if mapping.timestamp else None
    gi = {role: table.column_index(col) for role, col in mapping.group_columns().items()}
    fixed_unit = normalize_unit(mapping.unit, dim) if mapping.unit else None
    decimal = table.decimal or "."
    transformations: list[str] = []
    notes: list[str] = []

    def cell(r: list[Any], i: int | None) -> Any:
        return r[i] if i is not None and i < len(r) else None

    raw_obs: list[dict] = []
    for k, (r, rownum) in enumerate(zip(table.rows, table.row_numbers)):
        raw = cell(r, vi)
        issues: list[str] = []
        status = RowStatus.VALID
        value_u: float | None = None
        unit = fixed_unit
        orig_text = "" if raw is None else (str(raw) if not isinstance(raw, float) else repr(raw))

        def bad(code: str) -> None:
            nonlocal status
            issues.append(code)
            status = RowStatus.INVALID

        def review(code: str) -> None:
            nonlocal status
            issues.append(code)
            if status is not RowStatus.INVALID:
                status = RowStatus.REQUIRES_REVIEW

        def warn(code: str) -> None:
            nonlocal status
            issues.append(code)
            if status is RowStatus.VALID:
                status = RowStatus.WARNING

        if ui is not None:
            u_raw = cell(r, ui)
            if u_raw in (None, ""):
                bad("MISSING_UNIT")
                unit = None
            else:
                try:
                    unit = normalize_unit(str(u_raw), dim)
                except UnitError as e:
                    bad(f"UNKNOWN_UNIT: {e}")
                    unit = None
        x: float | None = None
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            bad("MISSING_VALUE (no se rellena)")
        elif isinstance(raw, bool):
            bad("NOT_A_NUMBER (booleano)")
        elif (secs := _duration_seconds(raw)) is not None:
            if dim.value != "time":
                bad("TIME_FORMAT_IN_NON_TIME_COLUMN")
            else:
                orig_text = str(raw)
                x = secs
                unit = "s"
                warn("EXCEL_DURATION_FORMAT: hh:mm:ss interpretado como duración en s")
        elif isinstance(raw, (dt.datetime, dt.date)):
            bad("DATE_IN_VALUE_COLUMN")
        elif isinstance(raw, (int, float)):
            if not math.isfinite(float(raw)):
                bad("NOT_A_NUMBER (no finito)")
            else:
                x = float(raw)
        else:
            m = _NUM_UNIT.match(str(raw))
            if not m:
                bad(f"NOT_A_NUMBER: '{raw}'")
            else:
                try:
                    x, n = parse_number(m.group(1), decimal)
                    for code in n:
                        warn(code)
                except NumberParseError as e:
                    bad(f"NOT_A_NUMBER: {e}")
                if x is not None and m.group(2):
                    try:
                        inline = normalize_unit(m.group(2), dim)
                    except UnitError as e:
                        bad(f"UNKNOWN_UNIT_IN_VALUE: {e}")
                        inline = None
                    if inline is not None:
                        if unit is not None and inline != unit:
                            bad(f"UNIT_CONFLICT: valor en '{inline}', columna/fila declara '{unit}'")
                        else:
                            if unit is None and ui is None and fixed_unit is None:
                                unit = inline
                            warn(f"UNIT_IN_VALUE ({inline})")
        if (k, vi) in table.formula_cells:
            review(f"FORMULA_CACHED_VALUE: {table.formula_cells[(k, vi)][:60]} (valor cacheado por Excel, no recalculado)")
        if unit == UNKNOWN_UNIT and x is not None:
            warn("UNIT_UNKNOWN (declarada desconocida: analizable, no aplicable al modelo)")
        if x is not None and unit is not None and status is not RowStatus.INVALID:
            if x < 0:
                bad("NEGATIVE_VALUE")
            elif x == 0:
                review("ZERO_VALUE (¿dato real o 'sin dato' codificado como 0?)")
            value_u = x
        ts = None
        if ti is not None:
            try:
                ts = _timestamp(cell(r, ti))
                if ts is None:
                    warn("MISSING_TIMESTAMP")
            except ValueError:
                warn(f"BAD_TIMESTAMP: '{cell(r, ti)}'")
        groups = {}
        for role, i in gi.items():
            g = cell(r, i)
            if g in (None, ""):
                warn(f"MISSING_GROUP_{role.upper()}")
                groups[role] = "(vacío)"
            else:
                groups[role] = str(g).strip()
        raw_obs.append({"index": k, "row": rownum, "original_value": orig_text, "original_unit": unit, "x": value_u,
                        "status": status, "issues": issues, "timestamp": ts, "groups": groups})

    units = Counter(o["original_unit"] for o in raw_obs if o["x"] is not None)
    if UNKNOWN_UNIT in units and len(units) > 1:
        # some rows with a known unit, others unknown: the unknown ones cannot be put on the same scale
        for o in raw_obs:
            if o["original_unit"] == UNKNOWN_UNIT and o["x"] is not None:
                o["x"] = None
                o["status"] = RowStatus.INVALID
                o["issues"].append("UNIT_UNKNOWN_MIXED_WITH_KNOWN_UNITS")
        units = Counter(o["original_unit"] for o in raw_obs if o["x"] is not None)
    if len(units) == 1:
        analysis_unit = next(iter(units))
    else:
        analysis_unit = nunit
        if len(units) > 1:
            transformations.append(f"MIXED_UNITS {dict(units)} -> todas convertidas a '{nunit}' (unidad de análisis)")
    obs: list[Observation] = []
    for o in raw_obs:
        val = norm = None
        if o["x"] is not None and analysis_unit == UNKNOWN_UNIT:
            val = o["x"]  # NORMALIZED_VALUE stays empty: no conversion possible
        elif o["x"] is not None:
            norm = to_base_value(o["x"], o["original_unit"], dim)
            val = from_base(norm, analysis_unit)
        obs.append(Observation(index=o["index"], row=o["row"], original_value=o["original_value"], original_unit=o["original_unit"],
                               value=val, normalized_value=norm, status=o["status"], issues=o["issues"], timestamp=o["timestamp"],
                               groups=o["groups"]))
    if analysis_unit == UNKNOWN_UNIT:
        notes.append("UNIT_UNKNOWN: unidad declarada desconocida; se puede analizar la forma de los datos pero NO aplicarlos al modelo")
    elif analysis_unit != nunit:
        transformations.append(f"NORMALIZED_VALUE = valor en '{analysis_unit}' convertido a '{nunit}' (se guardan ambos)")
    if table.decimal == "," and table.file_format == "csv":
        transformations.append("DECIMAL_COMMA: '12,5' leído como 12.5")
    if any("THOUSANDS_SEPARATOR_REMOVED" in o.issues for o in obs):
        transformations.append("THOUSANDS_SEPARATOR_REMOVED en algunas filas (marcadas WARNING)")
    if any(i.startswith("EXCEL_DURATION_FORMAT") for o in obs for i in o.issues):
        transformations.append("EXCEL_DURATION_FORMAT: celdas hh:mm:ss convertidas a segundos (marcadas WARNING)")
    # dataset-level checks (information, not row changes)
    if mapping.timestamp:
        c = Counter(o.timestamp for o in obs if o.timestamp)
        dups = {t for t, n in c.items() if n > 1}
        for o in obs:
            if o.timestamp in dups:
                o.issues.append("DUPLICATE_TIMESTAMP")
                if o.status is RowStatus.VALID:
                    o.status = RowStatus.WARNING
        if dups:
            notes.append(f"{len(dups)} marcas de tiempo repetidas (filas en WARNING): ¿filas duplicadas?")
    used = [o.value for o in obs if o.value is not None and o.status in (RowStatus.VALID, RowStatus.WARNING)]
    if used and all(float(v).is_integer() for v in used) and len(set(used)) < max(5, len(used) // 3):
        notes.append(f"ROUNDED_DATA: todos los valores son enteros en '{analysis_unit}' con solo {len(set(used))} valores "
                     "distintos: resolución de medida gruesa (empates); los tests de bondad de ajuste pierden fiabilidad")
    return obs, analysis_unit, transformations, notes
