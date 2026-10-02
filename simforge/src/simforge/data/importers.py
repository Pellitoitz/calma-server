"""CSV / XLSX readers. Imported files are UNTRUSTED input.

* Nothing in a file is executed: no macros, no formulas, no external links, no embedded objects.
  XLSX is opened with openpyxl read_only + data_only: a formula cell yields the value Excel CACHED at the last save
  (never re-evaluated); such cells are flagged so the engineer knows the number came from a formula.
* Hard limits on file size, decompressed size (zip bombs), rows and columns.
* Format detection (delimiter, decimal mark) never guesses between two plausible readings: it raises
  AmbiguousFormatError with the options and the engineer chooses (CLI --delimiter / --decimal).
* The reader returns raw cells + their file row numbers. Interpretation (numbers, units) happens in validation.py,
  per row, with every problem recorded.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED = 300 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_ROWS = 1_000_000
MAX_COLUMNS = 1_000
DELIMITERS = [";", ",", "\t", "|"]


class ImportError_(ValueError):  # noqa: N801 - avoid shadowing the builtin ImportError
    """The file cannot be imported (format, limits, security)."""


class AmbiguousFormatError(ImportError_):
    def __init__(self, what: str, options: list[str], detail: str):
        self.what, self.options, self.detail = what, options, detail
        super().__init__(f"Formato ambiguo ({what}): {detail}. Opciones: {options}. Indica cuál es (p. ej. --{what} ...).")


@dataclass
class RawTable:
    header: list[str]
    rows: list[list[Any]]
    row_numbers: list[int]  # row number in the file (1-based, header included) -> traceability
    source_file: str
    file_sha256: str
    file_bytes: int
    file_format: str  # csv | xlsx
    sheet: str | None = None
    encoding: str | None = None
    delimiter: str | None = None
    decimal: str | None = None
    formula_cells: dict[tuple[int, int], str] = field(default_factory=dict)  # (row idx, col idx) -> formula text
    notes: list[str] = field(default_factory=list)

    def column_index(self, name: str) -> int:
        if name in self.header:
            return self.header.index(name)
        low = [h.strip().lower() for h in self.header]
        if name.strip().lower() in low:
            return low.index(name.strip().lower())
        raise ImportError_(f"No existe la columna '{name}'. Columnas: {self.header}")

    def column(self, name: str) -> list[Any]:
        i = self.column_index(name)
        return [r[i] if i < len(r) else None for r in self.rows]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_bytes(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ImportError_(f"Archivo demasiado grande ({size / 1e6:.1f} MB > {MAX_FILE_BYTES / 1e6:.0f} MB).")
    if size == 0:
        raise ImportError_("Archivo vacío.")
    return path.read_bytes()


def read_table(path: Path, sheet: str | None = None, delimiter: str | None = None, decimal: str | None = None,
               header_row: int = 1) -> RawTable:
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt", ".tsv"):
        return read_csv(path, delimiter=delimiter, decimal=decimal, header_row=header_row)
    if suffix in (".xlsx", ".xlsm"):
        return read_xlsx(path, sheet=sheet, header_row=header_row)
    if suffix == ".xls":
        raise ImportError_("Formato .xls (Excel 97-2003) no soportado: guárdalo como .xlsx o .csv.")
    raise ImportError_(f"Extensión no soportada '{suffix}'. Soportadas: .csv, .txt, .tsv, .xlsx, .xlsm (macros ignoradas).")


# ------------------------------------------------------------------------------------------------- CSV
def _decode(b: bytes) -> tuple[str, str]:
    if b"\x00" in b[:4096]:
        raise ImportError_("El archivo parece binario (bytes nulos), no un CSV de texto.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return b.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ImportError_("Codificación no reconocida (ni UTF-8 ni Windows-1252).")


def _split(text: str, delim: str) -> list[list[str]]:
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]


def detect_delimiter(text: str) -> tuple[str | None, list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()][:200]
    sample = "\n".join(lines)
    consistent = []
    for d in DELIMITERS:
        rows = _split(sample, d)
        widths = {len(r) for r in rows}
        if rows and len(widths) == 1 and widths.pop() > 1:
            consistent.append(d)
    if not consistent:
        if any(d in sample for d in DELIMITERS if d != ","):
            raise AmbiguousFormatError("delimiter", DELIMITERS, "ningún separador da el mismo número de columnas en todas las filas")
        return None, ["una sola columna (sin separador)"]
    if len(consistent) == 1:
        return consistent[0], [f"separador '{consistent[0]}' (único con columnas consistentes)"]
    raise AmbiguousFormatError("delimiter", consistent, "varios separadores dan columnas consistentes")


_DEC_COMMA = re.compile(r"^[-+]?\d+,\d+$")
_DEC_DOT = re.compile(r"^[-+]?\d+\.\d+$")
_THOUSANDS_DOT = re.compile(r"^[-+]?\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^[-+]?\d{1,3}(,\d{3})+$")


def detect_decimal(cells: list[str], delimiter: str | None) -> tuple[str, str]:
    """Return (decimal mark, note). ',' as delimiter forces '.'; otherwise decided from the data."""
    if delimiter == ",":
        return ".", "separador ',' -> decimal '.'"
    vals = [c.strip() for c in cells if c and c.strip()]
    comma = sum(bool(_DEC_COMMA.match(v)) for v in vals)
    dot = sum(bool(_DEC_DOT.match(v)) for v in vals)
    if comma and dot:
        # '1.500' (thousands) next to '12,5' is consistent with decimal ','; anything else is a real conflict
        dots_are_thousands = all(_THOUSANDS_DOT.match(v) for v in vals if _DEC_DOT.match(v))
        if dots_are_thousands:
            return ",", f"decimal ',' ({comma} celdas); valores como '1.500' tratados como miles"
        raise AmbiguousFormatError("decimal", [",", "."], f"{comma} celdas con coma decimal y {dot} con punto decimal")
    if comma:
        return ",", f"decimal ',' ({comma} celdas con coma decimal)"
    return ".", f"decimal '.' ({dot} celdas con punto decimal)" if dot else "sin decimales en los datos: '.' por defecto"


def read_csv(path: Path, delimiter: str | None = None, decimal: str | None = None, header_row: int = 1) -> RawTable:
    b = _read_bytes(path)
    text, enc = _decode(b)
    notes = [f"codificación {enc}"]
    if delimiter is None:
        delimiter, n = detect_delimiter(text)
        notes += n
    else:
        notes.append(f"separador '{delimiter}' indicado por el usuario")
    all_rows = _split(text, delimiter) if delimiter else [[ln] for ln in text.splitlines() if ln.strip()]
    if len(all_rows) > MAX_ROWS + header_row:
        raise ImportError_(f"Demasiadas filas ({len(all_rows)} > {MAX_ROWS}).")
    if header_row < 1 or header_row > len(all_rows):
        raise ImportError_("Fila de cabecera fuera del archivo.")
    header = [h.strip() for h in all_rows[header_row - 1]]
    if len(header) > MAX_COLUMNS:
        raise ImportError_(f"Demasiadas columnas ({len(header)} > {MAX_COLUMNS}).")
    body = all_rows[header_row:]
    if decimal is None:
        decimal, n = detect_decimal([c for r in body for c in r], delimiter)
        notes.append(n)
    else:
        notes.append(f"decimal '{decimal}' indicado por el usuario")
    # row numbers count non-empty lines (blank lines are skipped by _split); good enough for tracing to the file
    return RawTable(header=header, rows=body, row_numbers=list(range(header_row + 1, header_row + 1 + len(body))),
                    source_file=path.name, file_sha256=sha256_bytes(b), file_bytes=len(b), file_format="csv",
                    encoding=enc, delimiter=delimiter, decimal=decimal, notes=notes)


# ------------------------------------------------------------------------------------------------ XLSX
def _check_zip(path: Path) -> list[str]:
    with path.open("rb") as fh:
        if fh.read(4) != b"PK\x03\x04":
            raise ImportError_("No es un .xlsx válido (no es un contenedor ZIP/OOXML).")
    notes = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        total = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos) or 1
        if total > MAX_XLSX_UNCOMPRESSED or total / packed > MAX_COMPRESSION_RATIO:
            raise ImportError_(f"XLSX rechazado: tamaño descomprimido {total / 1e6:.0f} MB (ratio {total / packed:.0f}) "
                               "excede los límites (posible bomba ZIP).")
        names = [i.filename for i in infos]
        if any(n.endswith("vbaProject.bin") for n in names):
            notes.append("el libro contiene macros VBA: IGNORADAS (nunca se ejecutan)")
        if any(n.startswith("xl/externalLinks/") for n in names):
            notes.append("el libro tiene vínculos externos: IGNORADOS (no se actualizan)")
        if any(n.startswith("xl/embeddings/") for n in names):
            notes.append("el libro tiene objetos incrustados: IGNORADOS")
    return notes


def _openpyxl():
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover - depends on installation
        raise ImportError_("Leer .xlsx requiere openpyxl: pip install 'simforge[data]'") from e
    return openpyxl


def list_sheets(path: Path) -> list[str]:
    _read_bytes(path)
    _check_zip(path)
    wb = _openpyxl().load_workbook(path, read_only=True, data_only=True, keep_vba=False, keep_links=False)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _cell(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip()
    return v


def read_xlsx(path: Path, sheet: str | None = None, header_row: int = 1) -> RawTable:
    b = _read_bytes(path)
    notes = _check_zip(path)
    opx = _openpyxl()
    wb = opx.load_workbook(path, read_only=True, data_only=True, keep_vba=False, keep_links=False)
    try:
        names = list(wb.sheetnames)
        if sheet is None:
            if len(names) > 1:
                raise AmbiguousFormatError("sheet", names, "el libro tiene varias hojas")
            sheet = names[0]
        if sheet not in names:
            raise ImportError_(f"No existe la hoja '{sheet}'. Hojas: {names}")
        ws = wb[sheet]
        rows: list[list[Any]] = []
        for i, r in enumerate(ws.iter_rows(values_only=True), start=1):
            if i > MAX_ROWS + header_row:
                raise ImportError_(f"Demasiadas filas (> {MAX_ROWS}).")
            if len(r) > MAX_COLUMNS:
                raise ImportError_(f"Demasiadas columnas ({len(r)} > {MAX_COLUMNS}).")
            rows.append([_cell(v) for v in r])
    finally:
        wb.close()
    # second, formula-text pass (still nothing evaluated): which cells hold a formula?
    wbf = opx.load_workbook(path, read_only=True, data_only=False, keep_vba=False, keep_links=False)
    formulas: dict[tuple[int, int], str] = {}
    try:
        for i, r in enumerate(wbf[sheet].iter_rows(values_only=True), start=1):
            if i <= header_row:
                continue
            for j, v in enumerate(r):
                if isinstance(v, str) and v.startswith("="):
                    formulas[(i - header_row - 1, j)] = v
    finally:
        wbf.close()
    if formulas:
        notes.append(f"{len(formulas)} celdas con fórmula: se usa el valor CACHEADO por Excel (no se recalcula); se marcan para revisión")
    if header_row > len(rows):
        raise ImportError_("Fila de cabecera fuera de la hoja.")
    header = [str(h).strip() if h is not None else f"col_{j + 1}" for j, h in enumerate(rows[header_row - 1])]
    body_all = rows[header_row:]
    formula_rows = {r for r, _ in formulas}
    keep = [(k, r) for k, r in enumerate(body_all) if any(c not in (None, "") for c in r) or k in formula_rows]
    remap = {old: new for new, (old, _) in enumerate(keep)}
    formulas = {(remap[r], c): f for (r, c), f in formulas.items() if r in remap}
    return RawTable(header=header, rows=[r for _, r in keep], row_numbers=[header_row + 1 + k for k, _ in keep],
                    source_file=path.name, file_sha256=sha256_bytes(b), file_bytes=len(b), file_format="xlsx",
                    sheet=sheet, formula_cells=formulas, notes=notes)


def preview(path: Path, sheet: str | None = None, n: int = 10, delimiter: str | None = None, decimal: str | None = None,
            header_row: int = 1) -> dict:
    """What the engineer sees BEFORE importing: sheets, columns, first rows, detection notes, unit hints."""
    from .quantities import unit_from_header
    out: dict[str, Any] = {"file": path.name}
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        out["sheets"] = list_sheets(path)
        if sheet is None and len(out["sheets"]) > 1:
            out["needs"] = "sheet"
            return out
    t = read_table(path, sheet=sheet, delimiter=delimiter, decimal=decimal, header_row=header_row)
    out.update({"sheet": t.sheet, "columns": t.header, "rows": len(t.rows), "first_rows": [list(map(_fmt, r)) for r in t.rows[:n]],
                "delimiter": t.delimiter, "decimal": t.decimal, "encoding": t.encoding, "notes": t.notes,
                "unit_hints": {h: u for h in t.header if (u := unit_from_header(h))},
                "column_types": {h: _column_type([r[j] if j < len(r) else None for r in t.rows[:500]], t.decimal or ".")
                                 for j, h in enumerate(t.header)}})
    return out


def _column_type(cells: list[Any], decimal: str) -> str:
    """Detected type of a column (from the first 500 rows), shown at preview: number / text / datetime / duration / empty."""
    from .validation import NumberParseError, parse_number
    kinds: dict[str, int] = {}
    for v in cells:
        if v is None or (isinstance(v, str) and not v.strip()):
            k = "empty"
        elif isinstance(v, bool):
            k = "text"
        elif isinstance(v, (int, float)):
            k = "number"
        elif isinstance(v, (dt.datetime, dt.date)):
            k = "datetime"
        elif isinstance(v, (dt.time, dt.timedelta)):
            k = "duration"
        else:
            try:
                parse_number(str(v), decimal)
                k = "number"
            except NumberParseError:
                k = "text"
        kinds[k] = kinds.get(k, 0) + 1
    filled = {k: n for k, n in kinds.items() if k != "empty"}
    if not filled:
        return "empty"
    main = max(filled, key=filled.get)
    other = sum(filled.values()) - filled[main]
    return main + (f" ({other} no-{main}, {kinds.get('empty', 0)} vacías)" if other or kinds.get("empty") else "")


def _fmt(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return str(v)
    return v
