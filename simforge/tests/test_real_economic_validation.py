"""Real-data ECONOMIC validation PROTOCOL (scripts/validation/economic_validation.py). These tests target the validator,
not Economics: it must be able to FAIL; it must never state REAL_DATA_VALIDATED for synthetic data, without sign-off,
with circular or derived evidence, with unvalidated physical drivers, with unjustified tolerances, beyond the
capabilities actually exercised; and its reference calculator stays independent of simforge.economics."""

from __future__ import annotations

import csv
import importlib.util
import inspect
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "validation_studies" / "economics"
_spec = importlib.util.spec_from_file_location("economic_validation", ROOT / "scripts" / "validation" / "economic_validation.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)
REAL_INPUT_SOURCES = ("S1", "S2", "S3", "S6", "S7")
REAL_REFERENCE_SOURCES = ("S4", "S5", "S8")


@pytest.fixture(scope="module", autouse=True)
def _fast_regression():
    orig = ev._regression
    ev._regression = lambda: {"ok": True, "expected": {}, "got": {}}  # 01-05 are covered by the engine tests
    yield
    ev._regression = orig


def rows(d: Path, name: str) -> list[dict]:
    with (d / "input" / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(d: Path, name: str, data: list[dict]) -> None:
    with (d / "input" / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
        w.writeheader()
        w.writerows(data)


def edit(d: Path, name: str, key: str, ident: str, **changes) -> None:
    data = rows(d, name)
    for r in data:
        if r[key] == ident:
            r.update(changes)
    write(d, name, data)


def case_edit(d: Path, fn) -> None:
    p = d / "input" / "case.yaml"
    c = yaml.safe_load(p.read_text(encoding="utf-8"))
    fn(c)
    p.write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")


def study(tmp_path, real=True, scope=None) -> Path:
    """The synthetic example, optionally converted to a REAL-like case (evidence classes, measured drivers)."""
    d = tmp_path / "CASE"
    shutil.copytree(STUDIES / "EXAMPLE_SYNTHETIC", d, ignore=shutil.ignore_patterns("comparison", "VALIDATION_REPORT.md"))
    if real:
        case_edit(d, lambda c: c.update(data_nature="REAL"))
        src = rows(d, "sources.csv")
        for s in src:
            s["evidence_class"] = "REAL_SOURCE_INPUT" if s["source_id"] in REAL_INPUT_SOURCES else "INDEPENDENT_REFERENCE"
        write(d, "sources.csv", src)
        drv = rows(d, "physical_drivers.csv")
        for x in drv:
            x["classification"] = "MEASURED"
        write(d, "physical_drivers.csv", drv)
    if scope is not None:
        case_edit(d, lambda c: c.update(economic_scope=scope))
    return d


def run(d: Path) -> dict:
    return ev.evaluate_case(ev.load_case(d))


def cap(out, name):
    return out["capabilities"][name]["status"]


def metric(out, ref, level):
    return next(m for m in out["metrics"] if m["reference_id"] == ref and m["level"] == level)


# --------------------------------------------------------------------------------------------- baseline behaviour
def test_synthetic_demo_never_validates_anything():
    out = run(STUDIES / "EXAMPLE_SYNTHETIC")
    assert out["status"] == "SYNTHETIC_DEMO_NOT_A_VALIDATION"
    assert "REAL_DATA_VALIDATED" not in {v["status"] for v in out["capabilities"].values()}
    assert out["statement"].startswith("SYNTHETIC DEMO: no capability is REAL_DATA_VALIDATED")
    assert all(m["result"] == "PASS" for m in out["metrics"] if m["level"] == "A")  # the tool itself works on the demo


def test_synthetic_source_in_a_real_case_blocks_validation(tmp_path):
    d = study(tmp_path)
    edit(d, "sources.csv", "source_id", "S1", evidence_class="SYNTHETIC")
    out = run(d)
    assert out["status"] == "SYNTHETIC_DEMO_NOT_A_VALIDATION" and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"


def test_real_case_validates_only_exercised_capabilities_with_scoped_statement(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME", "MACHINE_TIME_COST", "COST_PER_GOOD_UNIT", "EVALUATED_SAVINGS", "SIMPLE_PAYBACK"])
    out = run(d)
    ok = [k for k, v in out["capabilities"].items() if v["status"] == "REAL_DATA_VALIDATED"]
    assert ok == ["LABOR_PAID_TIME", "MACHINE_TIME_COST", "COST_PER_GOOD_UNIT", "EVALUATED_SAVINGS", "SIMPLE_PAYBACK"]
    assert out["status"] == "REAL_DATA_STUDY_VALID_FOR_SCOPE"
    s = out["statement"]
    assert s.startswith("REAL_DATA_VALIDATED for [LABOR_PAID_TIME, MACHINE_TIME_COST, COST_PER_GOOD_UNIT, EVALUATED_SAVINGS, "
                        "SIMPLE_PAYBACK] in case [ECON-DEMO-001] during [2026-10-05..2026-10-09], using [")
    assert "PER_PAID_HOUR" in s and "PER_PROCESSING_HOUR" in s
    assert "Not validated by this study: [LABOR_PLANNED_TIME, LABOR_BUSY_TIME," in s and "PM_LABOR_COST" in s
    assert "Costs not represented in the data: overhead, tooling wear." in s
    assert "SimForge Economics est" not in s and "validated with real data" not in s.lower()
    for c in ("LABOR_BUSY_TIME", "LABOR_PLANNED_TIME", "PM_LABOR_COST", "ENERGY_COST"):
        assert cap(out, c) == "NOT_OBSERVED"  # capability-specific: paid-time labor validated != busy-time labor
    assert all(m["result"] == "PASS" for m in out["metrics"] if m["level"] in "AB")


def test_requested_but_unreferenced_capabilities_keep_the_study_incomplete(tmp_path):
    out = run(study(tmp_path))  # scope also lists ANNUALIZATION and CAPEX, without a reference
    assert cap(out, "ANNUALIZATION") == cap(out, "CAPEX") == "INCOMPLETE"
    assert out["status"] == "REAL_DATA_STUDY_INCOMPLETE"


# --------------------------------------------------------------------------------------------- MISSING / NO_EVENT
def test_missing_input_is_never_zero_and_explicit_zero_is_data(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "economic_inputs.csv", "economic_input_id", "I1", value="")
    out = run(d)
    assert cap(out, "LABOR_PAID_TIME") == "INCOMPLETE" and metric(out, "R1", "A")["simforge"] is None
    assert metric(out, "R1", "B")["reference_calc"] is None  # never 0 x hours
    d2 = study(tmp_path / "z", scope=["SIMPLE_PAYBACK"])  # I3 = explicit 0 CAPEX of the baseline: it is data
    assert metric(run(d2), "R5", "A")["result"] == "PASS"


def test_undeclared_capex_is_never_zero(tmp_path):
    d = study(tmp_path, scope=["SIMPLE_PAYBACK"])
    write(d, "economic_inputs.csv", [r for r in rows(d, "economic_inputs.csv") if r["economic_input_id"] != "I3"])
    out = run(d)
    assert metric(out, "R5", "A")["result"] == "INCOMPLETE" and cap(out, "SIMPLE_PAYBACK") == "INCOMPLETE"


def test_no_event_is_not_missing_data(tmp_path):
    d = study(tmp_path)
    errs, _ = ev.check_config(ev.load_case(d))
    assert errs == []  # D7: failure_count NO_EVENT with value 0 is accepted
    edit(d, "physical_drivers.csv", "driver_id", "D7", value="2")
    assert any("NO_EVENT" in e for e in ev.check_config(ev.load_case(d))[0])
    edit(d, "physical_drivers.csv", "driver_id", "D7", value="0", event_status="MISSING_DATA")
    assert any("MISSING_DATA must have an empty value" in e for e in ev.check_config(ev.load_case(d))[0])
    edit(d, "physical_drivers.csv", "driver_id", "D7", value="0", event_status="NO_EVENT")
    edit(d, "physical_drivers.csv", "driver_id", "D3", value="", event_status="MISSING_DATA", classification="MISSING")
    out = run(d)
    assert cap(out, "MACHINE_TIME_COST") == "INCOMPLETE" and metric(out, "R2", "A")["simforge"] is None


# --------------------------------------------------------------------------------------------- evidence
def test_circular_evidence_is_detected(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "sources.csv", "source_id", "S4", source_type="SIMFORGE_EXPORT")
    out = run(d)
    b = metric(out, "R1", "B")
    assert b["evidence"] == "CIRCULAR" and b["result"] == "INCOMPLETE" and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"


def test_real_but_not_independent_reference(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "references.csv", "reference_id", "R1", source_id="S1")  # same Excel gives rate AND cost
    edit(d, "sources.csv", "source_id", "S1", evidence_class="INDEPENDENT_REFERENCE")
    out = run(d)
    assert metric(out, "R1", "B")["evidence"] == "DERIVED" and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"


@pytest.mark.parametrize("klass", ["DERIVED_REFERENCE", "ENGINEER_CONFIRMED"])
def test_reference_classification(tmp_path, klass):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "sources.csv", "source_id", "S4", evidence_class=klass)
    out = run(d)
    assert metric(out, "R1", "B")["result"] == "PASS" and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"  # arithmetic only


# --------------------------------------------------------------------------------------------- tolerances
@pytest.mark.parametrize("change", [
    {"absolute_tolerance": "50", "tolerance_basis": "SOURCE_PRECISION", "tolerance_reason": "large"},  # > derived bound
    {"absolute_tolerance": "0.1", "tolerance_basis": "", "tolerance_reason": ""},  # no basis / reason
    {"relative_tolerance": "0.05", "tolerance_basis": "ROUNDING", "tolerance_reason": "5 %"},  # % without METHOD
])
def test_unjustified_tolerance_rejected(tmp_path, change):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "references.csv", "reference_id", "R1", **change)
    out = run(d)
    assert metric(out, "R1", "B")["result"] == "INCOMPLETE" and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"


def test_derived_tolerance_from_resolutions(tmp_path):
    out = run(study(tmp_path, scope=["LABOR_PAID_TIME"]))
    assert metric(out, "R1", "B")["tolerance"] == pytest.approx(40 * 0.01 + 0.005)  # rate precision x hours + ref/2
    assert metric(out, "R1", "A")["reason"].startswith("|1136 - 1136| <=")  # level A: exact up to representation


# --------------------------------------------------------------------------------------------- failures and sign-off
def test_material_difference_fails_and_signoff_cannot_override(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "references.csv", "reference_id", "R1", value="1150.00")
    out = run(d)
    assert metric(out, "R1", "B")["result"] == "FAIL" and cap(out, "LABOR_PAID_TIME") == "FAILED"
    assert out["status"] == "REAL_DATA_STUDY_FAILED" and "No capability is REAL_DATA_VALIDATED" in out["statement"]
    write(d, "classifications.csv", [{"difference_id": "B:R1", "class": "ROUNDING", "material": "no", "resolved": "yes",
                                      "explanation": "engineer accepts", "evidence": ""}])
    assert cap(run(d), "LABOR_PAID_TIME") == "FAILED"  # a signed classification never turns a failure into a PASS
    write(d, "classifications.csv", [{"difference_id": "B:R1", "class": "PERIOD_DIFFERENCE", "material": "yes",
                                      "resolved": "yes", "explanation": "payroll covers 6 days", "evidence": ""}])
    out = run(d)
    assert cap(out, "LABOR_PAID_TIME") == "INCOMPLETE" and out["status"] != "REAL_DATA_STUDY_VALID_FOR_SCOPE"


def test_without_signoff_nothing_is_validated(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    case_edit(d, lambda c: c.update(signoff={"role": "process engineer", "date": "2026-10-20", "reviewed": False,
                                              "scope_accepted": True}))
    out = run(d)
    assert cap(out, "LABOR_PAID_TIME") == "INCOMPLETE" and out["status"] == "REAL_DATA_STUDY_INCOMPLETE"


def test_level_a_detects_a_software_discrepancy(tmp_path, monkeypatch):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    orig = ev.simforge_value
    monkeypatch.setattr(ev, "simforge_value", lambda *a: ((orig(*a)[0] or 0) + 0.01, ""))
    out = run(d)
    assert metric(out, "R1", "A")["result"] == "FAIL" and cap(out, "LABOR_PAID_TIME") == "FAILED"
    assert any(x["class"] == "POSSIBLE_SOFTWARE_BUG" for x in out["differences"])


def test_failed_regression_keeps_the_study_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_regression", lambda: {"ok": False})
    assert run(study(tmp_path, scope=["LABOR_PAID_TIME"]))["status"] == "REAL_DATA_STUDY_INCOMPLETE"


# --------------------------------------------------------------------------------------------- definitions / coverage
def test_formula_definition_mismatch(tmp_path):
    d = study(tmp_path, scope=["SIMPLE_PAYBACK"])
    edit(d, "references.csv", "reference_id", "R5", method="DISCOUNTED_PAYBACK")
    out = run(d)
    assert metric(out, "R5", "B")["result"] == "NOT_COMPARABLE" and cap(out, "SIMPLE_PAYBACK") == "INCOMPLETE"
    assert any(x["class"] == "FORMULA_DEFINITION_DIFFERENCE" for x in out["differences"])


def test_labor_concept_is_not_reinterpreted(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    edit(d, "references.csv", "reference_id", "R1", economic_concept="ACTIVITY_COST")
    out = run(d)
    assert metric(out, "R1", "B")["result"] == "NOT_COMPARABLE"
    assert any(x["class"] == "BASIS_DIFFERENCE" for x in out["differences"]) and cap(out, "LABOR_PAID_TIME") == "INCOMPLETE"


def test_coverage_mismatch_and_machine_rate_double_count(tmp_path):
    d = study(tmp_path, scope=["MACHINE_TIME_COST"])
    edit(d, "references.csv", "reference_id", "R2", included_components="ownership;maintenance;energy")
    out = run(d)
    assert any(x["class"] == "COVERAGE_DIFFERENCE" for x in out["differences"]) and cap(out, "MACHINE_TIME_COST") == "INCOMPLETE"
    d2 = study(tmp_path / "dc", scope=["MACHINE_TIME_COST"])
    edit(d2, "economic_inputs.csv", "economic_input_id", "I2", included_components="ownership;maintenance;energy")
    inp = rows(d2, "economic_inputs.csv")
    inp.append({**inp[0], "economic_input_id": "I9", "category": "energy", "resource_or_node": "", "paid_time": "",
                "value": "0.20", "unit": "EUR/kWh", "basis": "PER_KWH", "economic_concept": "", "included_components": ""})
    inp.append({**inp[0], "economic_input_id": "I10", "category": "energy_power", "resource_or_node": "m", "paid_time": "",
                "state": "PROCESSING", "value": "3", "unit": "kW", "basis": "", "economic_concept": "", "included_components": ""})
    write(d2, "economic_inputs.csv", inp)
    out = run(d2)
    assert cap(out, "MACHINE_TIME_COST") == "INCOMPLETE"
    assert any("possible double count" in r for r in out["capabilities"]["MACHINE_TIME_COST"]["reasons"])


def test_unsupported_capability_is_never_validated(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    refs = rows(d, "references.csv")
    refs.append({**refs[0], "reference_id": "R9", "capability": "REPLICATION_ECONOMIC_UNCERTAINTY"})
    write(d, "references.csv", refs)
    assert cap(run(d), "REPLICATION_ECONOMIC_UNCERTAINTY") == "INCOMPLETE"


def test_annualization_needs_a_real_planning_source(tmp_path):
    d = study(tmp_path, scope=["SIMPLE_PAYBACK"])
    edit(d, "sources.csv", "source_id", "S6", source_type="ENGINEER_CONFIRMED")
    out = run(d)
    assert cap(out, "SIMPLE_PAYBACK") == "INCOMPLETE"
    assert any("runs_per_year" in x for x in out["capabilities"]["SIMPLE_PAYBACK"]["reasons"])


# --------------------------------------------------------------------------------------------- physical drivers / level C
def test_unvalidated_physical_driver_limits_the_verdict(tmp_path):
    d = study(tmp_path, scope=["EVALUATED_SAVINGS"])
    edit(d, "physical_drivers.csv", "driver_id", "D6", classification="RECONSTRUCTED")
    out = run(d)
    assert metric(out, "R4", "A")["result"] == "PASS" and cap(out, "EVALUATED_SAVINGS") == "INCOMPLETE"
    assert any("RECONSTRUCTED" in x for x in out["capabilities"]["EVALUATED_SAVINGS"]["reasons"])
    assert metric(out, "R4", "C")["result"] == "INCOMPLETE"  # simulated drivers NOT_VALIDATED: no end-to-end claim


def test_end_to_end_level_c_gates(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])

    def validated(c):
        for s in c["scenarios"].values():
            s["simulated_run"]["drivers_validation"] = "VALIDATED_MODEL_OUTPUT"
    case_edit(d, validated)
    out = run(d)
    assert metric(out, "R1", "C")["result"] == "PASS" and "A+B+C" in out["capabilities"]["LABOR_PAID_TIME"]["reasons"][0]
    case_edit(d, lambda c: c.update(unrepresented_costs={"answer": "UNKNOWN", "concepts": []}))
    out = run(d)
    assert metric(out, "R1", "C")["result"] == "INCOMPLETE" and "UNKNOWN" in out["statement"]


# --------------------------------------------------------------------------------------------- configuration
@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c.pop("unrepresented_costs"), "unrepresented_costs.answer"),
    (lambda c: c.update(unrepresented_costs={"answer": "YES", "concepts": []}), "answer YES needs"),
    (lambda c: c.update(economic_scope=["EVERYTHING"]), "unknown capability"),
    (lambda c: c.update(period_end="2026-10-01"), "invalid period"),
])
def test_case_configuration_errors(tmp_path, mutate, needle):
    d = study(tmp_path)
    case_edit(d, mutate)
    out = run(d)
    assert out["status"] == "CONFIG_INVALID" and any(needle in e for e in out["config_errors"])


def test_inputs_need_currency_unit_precision_and_registered_source(tmp_path):
    d = study(tmp_path)
    edit(d, "economic_inputs.csv", "economic_input_id", "I1", currency="USD")
    assert any("no FX" in e for e in ev.check_config(ev.load_case(d))[0])
    d = study(tmp_path / "u")
    edit(d, "economic_inputs.csv", "economic_input_id", "I1", unit="EUR/unit")
    assert any("inconsistent with basis" in e for e in ev.check_config(ev.load_case(d))[0])
    d = study(tmp_path / "p")
    edit(d, "economic_inputs.csv", "economic_input_id", "I2", precision="", source_id="S99")
    errs = ev.check_config(ev.load_case(d))[0]
    assert any("precision" in e for e in errs) and any("S99" in e for e in errs)


def test_anonymised_sources_accepted_personal_data_rejected(tmp_path):
    d = study(tmp_path)
    assert ev.check_config(ev.load_case(d))[0] == []  # SRC-HR-RATES-2026 etc.: anonymised references are fine
    edit(d, "sources.csv", "source_id", "S1", source_reference="mail from j.doe@company.com")
    assert any("personal" in e for e in ev.check_config(ev.load_case(d))[0])


# --------------------------------------------------------------------------------------------- independence / outputs
def test_reference_calculator_is_independent_of_simforge_economics():
    for fn in (ev.reference_lines, ev.reference_value, ev._qty, ev._kwh, ev._total, ev._capex, ev._cap_lines):
        src = inspect.getsource(fn)
        assert "simforge" not in src and "evaluate_run" not in src and "_simforge" not in src


def test_cli_and_report(tmp_path):
    from typer.testing import CliRunner

    from simforge.cli import app
    d = study(tmp_path, scope=["LABOR_PAID_TIME"])
    res = CliRunner().invoke(app, ["economics", "validate-real", str(d)])
    assert res.exit_code == 0 and "REAL_DATA_STUDY_VALID_FOR_SCOPE" in res.output
    rep = (d / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    for h in ("## A. Case identification", "## G. Evidence independence", "## I. Arithmetic reproduction",
              "## J. Input representativeness", "## K. End-to-end comparison", "## P. Capability matrix",
              "## Q. Final scoped statement"):
        assert h in rep
    caps = list(csv.DictReader((d / "comparison" / "capabilities.csv").open(encoding="utf-8")))
    assert {r["status"] for r in caps} <= set(ev.CAP_STATUSES) and len(caps) == len(ev.CAPABILITIES)


def test_totals_never_validated_on_a_failed_component_nor_outside_scope(tmp_path):
    d = study(tmp_path, scope=["LABOR_PAID_TIME", "COST_PER_GOOD_UNIT", "EVALUATED_SAVINGS"])
    edit(d, "references.csv", "reference_id", "R1", value="1150.00")  # payroll disagrees with hours x rate
    out = run(d)
    assert cap(out, "LABOR_PAID_TIME") == "FAILED"
    for k in ("COST_PER_GOOD_UNIT", "EVALUATED_SAVINGS"):  # their own references match, but labor is a failed component
        assert cap(out, k) == "INCOMPLETE" and "FAILED component" in out["capabilities"][k]["reasons"][0]
    ok = run(study(tmp_path / "s", scope=["LABOR_PAID_TIME"]))
    assert cap(ok, "MACHINE_TIME_COST") == "INCOMPLETE"  # passes A+B but was not requested: no claim
    assert "not in the declared economic_scope" in ok["capabilities"]["MACHINE_TIME_COST"]["reasons"][0]
