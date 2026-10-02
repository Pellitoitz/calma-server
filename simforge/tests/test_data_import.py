"""Data import: CSV/XLSX readers, format detection, security limits, row validation, units. SYNTHETIC TEST DATA only."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("openpyxl")

from simforge.data import importers  # noqa: E402
from simforge.data.dataset import ColumnMapping, RowStatus  # noqa: E402
from simforge.data.importers import AmbiguousFormatError, ImportError_, preview, read_table  # noqa: E402
from simforge.data.quantities import QuantityType, normalize_unit, support_table  # noqa: E402
from simforge.data.validation import interpret, parse_number  # noqa: E402
from simforge.domain.units import Dimension, UnitError  # noqa: E402

SYN = Path(__file__).parents[1] / "examples" / "data" / "synthetic"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _obs(table, unit="s", quantity=QuantityType.PROCESSING_TIME, **mapping):
    m = ColumnMapping(value=mapping.pop("value", table.header[-1]), unit=unit if "unit_column" not in mapping else None, **mapping)
    return interpret(table, m, quantity)


# ------------------------------------------------------------------------------------------------- CSV
def test_csv_comma_delimiter_decimal_point(tmp_path):
    t = read_table(_write(tmp_path, "a.csv", "id,tiempo\n1,12.4\n2,13.7\n3,11.9\n"))
    assert t.delimiter == "," and t.decimal == "." and t.header == ["id", "tiempo"]
    obs, unit, _, _ = _obs(t)
    assert [o.value for o in obs] == [12.4, 13.7, 11.9] and unit == "s"


def test_csv_semicolon_and_decimal_comma(tmp_path):
    t = read_table(_write(tmp_path, "b.csv", "id;tiempo\n1;12,4\n2;13,7\n3;11,9\n"))
    assert t.delimiter == ";" and t.decimal == ","
    obs, _, tr, _ = _obs(t)
    assert [o.value for o in obs] == [12.4, 13.7, 11.9]
    assert any("DECIMAL_COMMA" in x for x in tr)  # the interpretation is recorded


def test_csv_single_column_decimal_comma(tmp_path):
    t = read_table(_write(tmp_path, "c.csv", "tiempo\n12,4\n13,7\n11,9\n"))
    assert t.delimiter is None and t.decimal == ","
    assert [o.value for o in _obs(t)[0]] == [12.4, 13.7, 11.9]


def test_csv_ambiguous_decimal_asks(tmp_path):
    p = _write(tmp_path, "d.csv", "id;tiempo\n1;12,5\n2;13.25\n")
    with pytest.raises(AmbiguousFormatError) as e:
        read_table(p)
    assert e.value.what == "decimal" and set(e.value.options) == {",", "."}
    t = read_table(p, decimal=",")  # the engineer chooses
    obs = _obs(t)[0]
    assert obs[0].value == 12.5 and obs[1].status is RowStatus.INVALID  # '13.25' cannot be read with decimal ','


def test_csv_ambiguous_delimiter_asks(tmp_path):
    p = _write(tmp_path, "e.csv", "a;b,c\n1;2,3\n4;5,6\n")
    with pytest.raises(AmbiguousFormatError) as e:
        read_table(p)
    assert e.value.what == "delimiter"
    assert read_table(p, delimiter=";").header == ["a", "b,c"]


def test_thousands_separator_is_recorded(tmp_path):
    t = read_table(_write(tmp_path, "f.csv", "id;t\n1;1.250,5\n2;12,5\n"))
    obs = _obs(t)[0]
    assert obs[0].value == 1250.5 and obs[0].status is RowStatus.WARNING and "THOUSANDS_SEPARATOR_REMOVED" in obs[0].issues


def test_parse_number_strict():
    assert parse_number("12,5", ",")[0] == 12.5
    with pytest.raises(ValueError):
        parse_number("12.5", ",")
    with pytest.raises(ValueError):
        parse_number("abc", ".")


def test_synthetic_files_detect_correctly():
    assert read_table(SYN / "SYNTHETIC_B_skewed.csv").delimiter == ";"
    f = read_table(SYN / "SYNTHETIC_F_decimal_comma.csv")
    assert (f.delimiter, f.decimal) == (";", ",")


# ------------------------------------------------------------------------------------------------ XLSX
def test_xlsx_multiple_sheets_requires_choice_and_column_selection():
    p = SYN / "SYNTHETIC_G_multisheet.xlsx"
    assert importers.list_sheets(p) == ["Info", "Montaje", "Soldadura"]
    with pytest.raises(AmbiguousFormatError):
        read_table(p)  # never assumes the first sheet
    t = read_table(p, sheet="Montaje")
    assert t.header == ["tiempo (s)", "operario", "media"]
    obs, unit, _, _ = interpret(t, ColumnMapping(value="tiempo (s)", unit="s"), QuantityType.PROCESSING_TIME)
    assert len(obs) == 30 and all(o.status is RowStatus.VALID for o in obs) and unit == "s"
    pv = preview(p, sheet="Montaje")
    assert pv["unit_hints"] == {"tiempo (s)": "s"} and pv["column_types"]["tiempo (s)"] == "number"


def test_xlsx_formula_is_never_evaluated_and_flagged():
    t = read_table(SYN / "SYNTHETIC_G_multisheet.xlsx", sheet="Montaje")
    assert list(t.formula_cells.values()) == ["=AVERAGE(A2:A31)"]
    obs = interpret(t, ColumnMapping(value="media", unit="s"), QuantityType.PROCESSING_TIME)[0]
    # openpyxl does not compute formulas: no cached value -> INVALID (missing), still flagged as formula
    assert obs[0].status is RowStatus.INVALID and any("FORMULA" in i for i in obs[0].issues)


def test_xlsx_formula_with_cached_value_requires_review(tmp_path):
    """A workbook saved by Excel stores the formula's last value: it is used only after review."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["t"])
    ws.append([10.0])
    ws.append(["=A2*2"])
    p = tmp_path / "f.xlsx"
    wb.save(p)
    # simulate Excel's cached value: data_only read returns None for openpyxl-written files, so patch the reader output
    t = read_table(p)
    t.rows[1][0] = 20.0
    obs = interpret(t, ColumnMapping(value="t", unit="s"), QuantityType.PROCESSING_TIME)[0]
    assert obs[1].status is RowStatus.REQUIRES_REVIEW and obs[1].value == 20.0


def test_xlsx_macros_and_bombs_are_refused_or_ignored(tmp_path, monkeypatch):
    import zipfile
    p = tmp_path / "m.xlsm"
    src = SYN / "SYNTHETIC_G_multisheet.xlsx"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(p, "w") as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i.filename))
        zout.writestr("xl/vbaProject.bin", b"\x00" * 100)
    t = read_table(p, sheet="Montaje")
    assert any("macros VBA: IGNORADAS" in n for n in t.notes)
    monkeypatch.setattr(importers, "MAX_COMPRESSION_RATIO", 1)
    with pytest.raises(ImportError_, match="bomba ZIP"):
        read_table(src, sheet="Montaje")


def test_size_limits(tmp_path, monkeypatch):
    p = _write(tmp_path, "big.csv", "t\n" + "1\n" * 50)
    monkeypatch.setattr(importers, "MAX_FILE_BYTES", 10)
    with pytest.raises(ImportError_, match="demasiado grande"):
        read_table(p)
    monkeypatch.setattr(importers, "MAX_FILE_BYTES", 10**6)
    monkeypatch.setattr(importers, "MAX_ROWS", 10)
    with pytest.raises(ImportError_, match="Demasiadas filas"):
        read_table(p)
    with pytest.raises(ImportError_, match="no soportado"):
        read_table(_write(tmp_path, "x.xls", "x"))
    with pytest.raises(ImportError_, match="ZIP"):
        read_table(_write(tmp_path, "fake.xlsx", "not a zip"))


def test_excel_duration_cells_are_converted_with_warning(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["t"])
    ws.append([dt.time(0, 2, 30)])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    o = interpret(read_table(p), ColumnMapping(value="t", unit="min"), QuantityType.PROCESSING_TIME)[0][0]
    assert o.status is RowStatus.WARNING and o.normalized_value == 150 and o.original_unit == "s"


# ------------------------------------------------------------------------------------------ validation
def test_missing_nonnumeric_negative_zero_are_classified_not_removed():
    t = read_table(SYN / "SYNTHETIC_D_missing.csv")
    obs = _obs(t)[0]
    assert len(obs) == 60  # nothing dropped
    by_idx = {o.index: o for o in obs}
    assert by_idx[3].status is RowStatus.INVALID and "MISSING_VALUE" in by_idx[3].issues[0]
    assert by_idx[11].status is RowStatus.INVALID and "NOT_A_NUMBER" in by_idx[11].issues[0]
    assert by_idx[25].status is RowStatus.INVALID and by_idx[25].issues == ["NEGATIVE_VALUE"]
    assert by_idx[33].status is RowStatus.REQUIRES_REVIEW  # 0 s: real or 'no data'? the engineer says
    assert by_idx[3].value is None  # never filled
    assert sum(o.status is RowStatus.VALID for o in obs) == 53


def test_units_conversion_keeps_original_and_normalized(tmp_path):
    t = read_table(_write(tmp_path, "u.csv", "t;u\n1,5;min\n30;s\n0,5;h\n"))
    obs, unit, tr, _ = interpret(t, ColumnMapping(value="t", unit_column="u"), QuantityType.PROCESSING_TIME)
    assert unit == "s" and any("MIXED_UNITS" in x for x in tr)
    assert [(o.original_value, o.original_unit, o.normalized_value) for o in obs] == [("1,5", "min", 90.0), ("30", "s", 30.0),
                                                                                     ("0,5", "h", 1800.0)]


def test_homogeneous_unit_is_kept_as_analysis_unit():
    t = read_table(SYN / "SYNTHETIC_F_decimal_comma.csv")
    obs, unit, _, _ = interpret(t, ColumnMapping(value="tiempo_min", unit="min"), QuantityType.PROCESSING_TIME)
    assert unit == "min" and obs[0].normalized_value == pytest.approx(obs[0].value * 60)


def test_unit_errors_are_explicit(tmp_path):
    with pytest.raises(UnitError):
        normalize_unit("m", Dimension.TIME)  # minutes or metres? never guessed
    with pytest.raises(UnitError):
        normalize_unit("min", Dimension.LENGTH)
    assert normalize_unit("segundos", Dimension.TIME) == "s" and normalize_unit("km", Dimension.LENGTH) == "km"
    t = read_table(_write(tmp_path, "w.csv", "t;u\n5;fortnight\n5;\n7 min;s\n"))
    obs = interpret(t, ColumnMapping(value="t", unit_column="u"), QuantityType.PROCESSING_TIME)[0]
    assert all(o.status is RowStatus.INVALID for o in obs)
    assert "UNIT_CONFLICT" in obs[2].issues[0]
    with pytest.raises(ValueError):
        ColumnMapping(value="t")  # a unit is mandatory (or explicitly UNKNOWN)


def test_unknown_unit_is_analysable_but_flagged(tmp_path):
    t = read_table(_write(tmp_path, "k.csv", "t\n5\n6\n"))
    obs, unit, _, notes = interpret(t, ColumnMapping(value="t", unit="UNKNOWN"), QuantityType.PROCESSING_TIME)
    assert unit == "UNKNOWN" and obs[0].value == 5 and obs[0].normalized_value is None and obs[0].status is RowStatus.WARNING
    assert any("UNIT_UNKNOWN" in n for n in notes)


def test_distance_quantity_and_duplicate_timestamps(tmp_path):
    t = read_table(_write(tmp_path, "d.csv", "ts,d\n2026-01-01 08:00:00,1.2\n2026-01-01 08:00:00,1.3\n2026-01-01 08:05:00,950\n"))
    obs, unit, _, notes = interpret(t, ColumnMapping(value="d", unit="m", timestamp="ts"), QuantityType.DISTANCE)
    assert unit == "m" and "DUPLICATE_TIMESTAMP" in obs[0].issues and obs[2].status is RowStatus.VALID
    obs2 = interpret(t, ColumnMapping(value="d", unit="cm", timestamp="ts"), QuantityType.DISTANCE)[0]
    assert obs2[2].normalized_value == pytest.approx(9.5)


def test_support_table_separates_import_from_simulation_use():
    rows = {r["quantity"]: r for r in support_table()}
    assert all(r["data_import"] == "DATA_IMPORT_SUPPORTED" for r in rows.values())
    assert rows["SETUP_TIME"]["simulation"] == "SIMULATION_USE_NOT_YET_SUPPORTED"
    assert rows["TRANSPORT_TIME"]["simulation"] == "SIMULATION_USE_NOT_YET_SUPPORTED"
    assert rows["PROCESSING_TIME"]["simulation"] == "SIMULATION_USE_SUPPORTED"
    assert rows["REPAIR_TIME"]["targets"] == ["params.failures.mttr"]
    assert rows["DISTANCE"]["distributions_in_engine"] is False
