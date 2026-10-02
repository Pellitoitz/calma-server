"""Real-data calendar validation PROTOCOL (scripts/validation/calendar_validation.py). These tests target the validator,
not the engine: it must be able to FAIL, it must never state REAL_DATA_VALIDATED for synthetic data, without sign-off,
without full calendar coverage or beyond the capabilities the period actually exercised, and EXPECTED stays independent
of the engine."""

from __future__ import annotations

import datetime as dt
import importlib.util
import inspect
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "validation_studies" / "calendars"
_spec = importlib.util.spec_from_file_location("calendar_validation", ROOT / "scripts" / "validation" / "calendar_validation.py")
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)
WEEK = {"from": "2026-10-05", "to": "2026-10-11"}
PLC = {"source_type": "PLC", "source_reference": "PLC Machine_A log", "confirmed_by_role": "maintenance technician",
       "extraction_date": "2026-10-20", "clock_sync_status": "CONFIRMED_SYNCED"}


@pytest.fixture(scope="module", autouse=True)
def _fast_regression():
    # the 01-05 regression is covered by the engine tests; here only its effect on the status is checked
    orig = cv._regression
    cv._regression = lambda: {"ok": True, "expected": {}, "got": {}}
    yield
    cv._regression = orig


def study(tmp_path, synthetic=False, signed=True, edit_study=None, edit_model=None, observed=None, plc=None, rows=None,
          files=None):
    d = tmp_path / "S"
    shutil.copytree(STUDIES / "EXAMPLE_SYNTHETIC", d)
    for g in ("expected", "simforge", "comparison"):
        shutil.rmtree(d / g, ignore_errors=True)
    s = yaml.safe_load((d / "input" / "study.yaml").read_text())
    s.update(synthetic=synthetic, study_id="TEST_FIXTURE",
             engineer_sign_off={"name": "Process engineer", "date": "2026-10-21", "notes": "test"} if signed else {})
    if observed:
        s["sources"]["plc"] = {**PLC, **(plc or {})}
        s["data_streams"]["observed_events"] = WEEK
        (d / "input" / "observed_events.csv").write_text(
            "timestamp,target,event,evidence_type,source_ref,temporal_resolution,note\n" + "\n".join(observed) + "\n")
    if edit_study:
        edit_study(s)
    (d / "input" / "study.yaml").write_text(yaml.safe_dump(s))
    if edit_model:
        (d / "input" / "model.yaml").write_text(edit_model((d / "input" / "model.yaml").read_text()))
    if rows:
        p = d / "input" / "calendar_rows.csv"
        p.write_text(rows(p.read_text().splitlines()))
    for name, text in (files or {}).items():
        (d / "input" / name).write_text(text)
    return d


def fails(r):
    return [x for x in r["metrics"] + r["events"] if x["status"] == "FAIL"]


def caps(r):
    return {c["capability"]: c["real"] for c in r["capabilities"]}


def validated(r):
    return {c for c, v in caps(r).items() if v == "REAL_DATA_VALIDATED"}


def ev(name, kind, ts, res="SECOND", evidence="OBSERVED", src="plc"):
    return f"{ts},{name},{kind},{evidence},{src},{res},"


# ------------------------------------------------------------------------------------ existing guarantees kept
def test_matching_signed_study_validates_only_its_exercised_capabilities_with_scope(tmp_path):
    r = cv.run_study(study(tmp_path / "a"))
    assert r["status"] == "REAL_DATA_VALIDATED", (fails(r), r["config_errors"], r["coverage_gate"])
    assert validated(r) == {"shift_start_end", "breaks", "multiple_shifts", "machine_operator_calendar_intersection"}
    assert "in case TEST_FIXTURE" in r["scope"] and "2026-10-05T00:00:00" in r["scope"] and "Not valid for other" in r["scope"]
    rep = (tmp_path / "a" / "S" / "VALIDATION_REPORT.md").read_text()
    for h in ("## Scope", "## Case ID", "## Period", "## Evidence sources", "## Data coverage", "## Planned calendar",
              "## Observed operation", "## Independent expected availability", "## SimForge availability",
              "## Calendar event comparison", "## Operational evidence", "## Capability coverage", "## Differences",
              "## Root-cause classification", "## Limitations", "## Engineer sign-off", "## Validation status"):
        assert h in rep, h
    pa = {(m["target"], m["metric"]): m["expected_s"] for m in r["metrics"]}
    assert pa[("Operator_1", "PLANNED_AVAILABLE_TIME")] == 5 * (8 * 3600 - 900)
    assert cv.run_study(study(tmp_path / "b", signed=False))["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_regression_failure_blocks_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_regression", lambda: {"ok": False, "expected": {}, "got": {}})
    assert cv.run_study(study(tmp_path))["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_break_entered_wrongly_in_the_model_fails_with_zero_tolerance(tmp_path):
    r = cv.run_study(study(tmp_path, edit_model=lambda t: t.replace('end: "10:15"', 'end: "10:16"')))
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    f = fails(r)
    assert {x.get("metric") for x in f} >= {"PLANNED_AVAILABLE_TIME", "BREAK_TIME", "ENGINE_TRACKED_PLANNED_TIME"}
    plan = [x for x in f if x.get("event") == "BREAK_END" and x["evidence_type"] == "PLANNED"]
    assert len(plan) == 5 and all(x["delta_s"] == 60.0 for x in plan)
    assert caps(r)["breaks"] == "REAL_DATA_VALIDATION_FAILED" and not validated(r)
    assert all(x["classification"] == "UNKNOWN" for x in r["differences"] if x["kind"] == "STRUCTURAL")


def test_holiday_in_real_schedule_missing_in_model_fails(tmp_path):
    def rows(lines):
        keep = [x for x in lines if ",2026-10-07," not in x]
        return "\n".join(keep + ["Machine_A,2026-10-07,,,HOLIDAY,PLANNED,plan,MINUTE,", "Operator_1,2026-10-07,,,HOLIDAY,PLANNED,plan,MINUTE,"]) + "\n"
    r = cv.run_study(study(tmp_path, rows=rows))
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    assert caps(r)["holiday"] == "REAL_DATA_VALIDATION_FAILED"
    assert any(e["evidence_type"] == "SIMFORGE only" for e in r["events"])


def test_holiday_in_schedule_and_model_is_validated_for_holiday(tmp_path):
    def rows(lines):
        keep = [x for x in lines if ",2026-10-07," not in x]
        return "\n".join(keep + ["Machine_A,2026-10-07,,,HOLIDAY,PLANNED,plan,MINUTE,", "Operator_1,2026-10-07,,,HOLIDAY,PLANNED,plan,MINUTE,"]) + "\n"
    exc = '\n      exceptions: [{date: 2026-10-07, type: NON_WORKING_DAY, reason: "local holiday"}]'
    r = cv.run_study(study(tmp_path, rows=rows, edit_model=lambda t: t.replace(
        '{start: "14:00", end: "22:00"}]}\n', '{start: "14:00", end: "22:00"}]}' + exc + "\n").replace(
        '      breaks: [{start: "10:00", end: "10:15"}]', '      breaks: [{start: "10:00", end: "10:15"}]' + exc)))
    assert r["status"] == "REAL_DATA_VALIDATED", (fails(r), r["config_errors"])
    assert caps(r)["holiday"] == "REAL_DATA_VALIDATED"


def test_model_period_or_mode_mismatch_is_incomplete_not_failed(tmp_path):
    r = cv.run_study(study(tmp_path / "a", edit_model=lambda t: t.replace("start_date: 2026-10-05", "start_date: 2026-10-06")))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("starts" in c for c in r["config_errors"])
    r = cv.run_study(study(tmp_path / "b", edit_study=lambda s: s.update(period_end="2026-10-11T00:00:00")))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("horizon" in c for c in r["config_errors"])


def test_policy_missing_in_model_does_not_run(tmp_path):
    r = cv.run_study(study(tmp_path, edit_model=lambda t: t.split("  operations:")[0]))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("verify" in c for c in r["config_errors"])


def test_template_and_missing_inputs(tmp_path):
    shutil.copytree(STUDIES / "TEMPLATE", tmp_path / "T")
    r = cv.run_study(tmp_path / "T")
    assert r["status"] == "NOT_TESTED" and "timezone" in r["missing"] and "sources" in r["missing"]
    d = study(tmp_path)
    (d / "input" / "model.yaml").unlink()
    assert cv.run_study(d)["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_expected_side_is_independent_of_the_engine():
    for fn in (cv.expected_from_rows, cv.expected_events, cv._union, cv._minus, cv._inter, cv.dst_transitions):
        assert "simforge" not in inspect.getsource(fn)


def test_expected_handles_overnight_and_fall_dst_by_itself():
    tz = ZoneInfo("Europe/Madrid")
    t0, t1 = dt.datetime(2026, 10, 24, tzinfo=tz), dt.datetime(2026, 10, 26, tzinfo=tz)
    rows = [{"resource": "M", "date": "2026-10-24", "start": "22:00", "end": "06:00", "kind": "SHIFT"},
            {"resource": "M", "date": "2026-10-25", "start": "02:00", "end": "02:30", "kind": "BREAK"}]
    e = cv.expected_from_rows(rows, tz, t0, t1)["M"]
    assert cv._len(e["available"]) + cv._len(e["break"]) == 9 * 3600  # 25 Oct 03:00 -> 02:00: one hour longer
    assert e["horizon"] == 49 * 3600
    assert [c for _, c in cv.dst_transitions(tz, t0, t1)] == ["DST_autumn"]


def test_engine_matches_independent_expectation_across_fall_dst_overnight_shift(tmp_path):
    def es(s):
        s.update(period_start="2026-10-19T00:00:00", period_end="2026-10-26T00:00:00")

    def em(t):
        t = t.replace("start_date: 2026-10-05", "start_date: 2026-10-19").replace("value: 168, unit: h", "value: 169, unit: h")
        return t.replace('fri: [{start: "06:00", end: "14:00"}, {start: "14:00", end: "22:00"}]}',
                         'fri: [{start: "06:00", end: "14:00"}, {start: "14:00", end: "22:00"}],\n'
                         '               sat: [{start: "22:00", end: "06:00"}]}')

    def rows(lines):
        out = []
        for line in lines[1:]:
            r = line.split(",")
            r[1] = str(dt.date.fromisoformat(r[1]) + dt.timedelta(days=14))
            if not (r[0] == "Machine_A" and r[1] == "2026-10-24"):
                out.append(",".join(r))
        out.append("Machine_A,2026-10-24,22:00,06:00,SHIFT,PLANNED,plan,MINUTE,overnight across DST end")
        return "\n".join([lines[0]] + out) + "\n"
    r = cv.run_study(study(tmp_path, edit_study=es, edit_model=em, rows=rows))
    assert r["status"] == "REAL_DATA_VALIDATED", (fails(r), r["config_errors"], r["coverage_gate"])
    pa = {(m["target"], m["metric"]): m["simforge_s"] for m in r["metrics"]}
    assert pa[("Machine_A", "PLANNED_AVAILABLE_TIME")] == 5 * 16 * 3600 + 9 * 3600
    assert pa[("Machine_A", "CALENDAR_TIME")] == 169 * 3600
    assert {"DST_autumn", "overnight_shift"} <= validated(r) and caps(r)["DST_spring"] == "NOT_OBSERVED_IN_REAL_DATA"


# --------------------------------------------------------------------------------------- hardening A-I (+ extras)
def test_A_simple_week_without_holiday_leaves_exceptions_and_dst_not_observed(tmp_path):
    r = cv.run_study(study(tmp_path))
    c = caps(r)
    for cap in ("holiday", "overtime", "extra_shift", "overnight_shift", "calendar_day", "shifts_starting_on_date",
                "DST_spring", "DST_autumn"):
        assert c[cap] == "NOT_OBSERVED_IN_REAL_DATA", cap
    assert all(x["synthetic"] == "SYNTHETICALLY_VALIDATED" for x in r["capabilities"])


def test_B_pause_resume_not_observed_without_real_boundary_evidence_and_validated_with_it(tmp_path):
    r = cv.run_study(study(tmp_path / "none"))
    assert caps(r)["PAUSE_RESUME"] == "NOT_OBSERVED_IN_REAL_DATA" and caps(r)["STOP_RESTART"] == "NOT_OBSERVED_IN_REAL_DATA"
    obs = [ev("Machine_A", "PAUSE", "2026-10-05T14:00:00"), ev("Machine_A", "RESUME", "2026-10-06T06:00:00")]
    r = cv.run_study(study(tmp_path / "seen", observed=obs))
    assert r["status"] == "REAL_DATA_VALIDATED" and caps(r)["PAUSE_RESUME"] == "REAL_DATA_VALIDATED"
    assert caps(r)["STOP_RESTART"] == "NOT_OBSERVED_IN_REAL_DATA"  # never validated by association


def test_B2_observed_behaviour_contradicting_declared_policy_fails_that_capability(tmp_path):
    obs = [ev("Machine_A", "OPERATION_START", "2026-10-05T13:55:00"), ev("Machine_A", "OPERATION_END", "2026-10-05T14:03:00")]
    r = cv.run_study(study(tmp_path, observed=obs))
    assert caps(r)["PAUSE_RESUME"] == "REAL_DATA_VALIDATION_FAILED"
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    assert not any(x["classification"] == "CALENDAR_ERROR" for x in r["differences"])


def test_C_missing_calendar_day_blocks_validation(tmp_path):
    r = cv.run_study(study(tmp_path / "a", rows=lambda ls: "\n".join(x for x in ls if not x.startswith("Operator_1,2026-10-07")) + "\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("2026-10-07" in g for g in r["coverage_gate"])
    r = cv.run_study(study(tmp_path / "b", rows=lambda ls: "\n".join(x for x in ls if ",OFF," not in x) + "\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE"  # weekend without rows is not "not worked" by default
    r = cv.run_study(study(tmp_path / "c", files={"missing_data.csv": "stream,target,from,to,status,note\n"
                                                  "calendar,Machine_A,2026-10-08,2026-10-08,MISSING,sheet lost\n"}))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and not validated(r)
    cov = {(c["stream"], c["target"]): c for c in r["coverage"]}
    assert cov[("calendar", "Machine_A")]["covered_days"] == 6 and cov[("failures", "*")]["covered_days"] == 0


def test_D_first_cycle_after_shift_start_and_finish_after_break_are_not_calendar_errors(tmp_path):
    obs = [ev("Operator_1", "FIRST_PROCESS_START", "2026-10-05T06:04:00", "MINUTE"),
           ev("Operator_1", "OPERATION_END", "2026-10-05T10:02:00", "MINUTE")]
    r = cv.run_study(study(tmp_path, observed=obs))
    o = {x["event"]: x for x in r["operational_events"]}
    assert o["FIRST_PROCESS_START"]["status"].startswith("CONSISTENT") and o["FIRST_PROCESS_START"]["delta_s"] == 240
    assert o["OPERATION_END"]["status"].startswith("AFTER_BOUNDARY")
    assert r["status"] == "REAL_DATA_VALIDATED" and not [x for x in r["differences"] if x["kind"] in ("STRUCTURAL", "OPERATIONAL")]
    assert not any(e["event"] == "SHIFT_START" and e["evidence_type"] == "OBSERVED" for e in r["events"])


def test_D2_finish_current_observed_and_applied_is_validated(tmp_path):
    obs = [ev("Machine_A", "OPERATION_START", "2026-10-05T13:58:00"), ev("Machine_A", "OPERATION_END", "2026-10-05T14:06:00")]
    r = cv.run_study(study(tmp_path, observed=obs, edit_model=lambda t: t.replace(
        "at_unavailability: PAUSE_RESUME", "at_unavailability: FINISH_CURRENT")))
    assert caps(r)["FINISH_CURRENT"] == "REAL_DATA_VALIDATED", [c for c in r["capabilities"] if c["capability"] == "FINISH_CURRENT"]
    assert caps(r)["PAUSE_RESUME"] == "NOT_OBSERVED_IN_REAL_DATA"


def test_E_minute_resolution_is_not_treated_as_second_precision(tmp_path):
    r = cv.run_study(study(tmp_path / "m", observed=[ev("Machine_A", "PAUSE", "2026-10-05T14:01:00", "MINUTE")]))
    assert r["operational_events"][0]["status"].startswith("CONSISTENT") and r["operational_events"][0]["resolution_s"] == 60
    r = cv.run_study(study(tmp_path / "s", observed=[ev("Machine_A", "PAUSE", "2026-10-05T14:01:00", "SECOND")]))
    assert r["operational_events"][0]["status"] == "PLAN_VS_ACTUAL_DIFFERENCE"
    r = cv.run_study(study(tmp_path / "q", observed=[ev("Machine_A", "PAUSE", "2026-10-05T14:00:30", "MINUTE")]))
    assert r["operational_events"][0]["status"] == "DATA_QUALITY"  # claims more precision than it has
    r = cv.run_study(study(tmp_path / "row", rows=lambda ls: "\n".join(ls).replace(
        "Operator_1,2026-10-05,06:00,14:00", "Operator_1,2026-10-05,06:00:30,14:00") + "\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("more precise" in c for c in r["config_errors"])


def test_F_known_clock_offset_correction_is_traced_and_unapplied_offset_is_weak(tmp_path):
    obs = [ev("Machine_A", "PAUSE", "2026-10-05T14:01:30"), ev("Machine_A", "RESUME", "2026-10-06T06:01:30")]
    off = {"clock_sync_status": "KNOWN_OFFSET", "known_offset_s": 90, "offset_reference": "NTP check 2026-10-19"}
    r = cv.run_study(study(tmp_path / "a", observed=obs, plc={**off, "apply_offset": True}))
    assert [c["corrected"][:19] for c in r["clock_corrections"]] == ["2026-10-05T14:00:00", "2026-10-06T06:00:00"]
    assert all(c["raw"] != c["corrected"] and c["offset_s"] == 90 for c in r["clock_corrections"])
    assert caps(r)["PAUSE_RESUME"] == "REAL_DATA_VALIDATED"
    assert any(x["classification"] == "SOURCE_CLOCK_DIFFERENCE" for x in r["differences"])
    assert "Clock corrections applied" in (tmp_path / "a" / "S" / "VALIDATION_REPORT.md").read_text()
    r = cv.run_study(study(tmp_path / "b", observed=obs, plc={**off, "apply_offset": False}))
    assert not r["clock_corrections"] and all(o["strength"].startswith("WEAK") for o in r["operational_events"])
    assert caps(r)["PAUSE_RESUME"] == "NOT_OBSERVED_IN_REAL_DATA"
    r = cv.run_study(study(tmp_path / "c", observed=obs, plc={"clock_sync_status": "UNKNOWN"}))
    assert caps(r)["PAUSE_RESUME"] == "NOT_OBSERVED_IN_REAL_DATA"


def test_G_unmodelled_plant_condition_is_model_scope_difference_and_question_is_mandatory(tmp_path):
    def es(s):
        s["additional_constraints"] = [{"constraint": "QA release of first part", "modelled": False, "note": "each shift"}]
    r = cv.run_study(study(tmp_path / "a", edit_study=es))
    assert [x["classification"] for x in r["differences"] if x["kind"] == "SCOPE"] == ["MODEL_SCOPE_DIFFERENCE"]
    assert r["status"] == "REAL_DATA_VALIDATED"  # the calendar itself is still reproduced exactly; limitation reported
    r = cv.run_study(study(tmp_path / "b", edit_study=lambda s: s.pop("additional_constraints")))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("additional_constraints" in c for c in r["config_errors"])


def test_H_operator_only_case_validates_only_shifts_and_breaks(tmp_path):
    def es(s):
        s["targets"] = {"Operator_1": {"resource": "operator_1"}}
    r = cv.run_study(study(tmp_path, edit_study=es))
    assert r["status"] == "REAL_DATA_VALIDATED"
    assert validated(r) == {"shift_start_end", "breaks"}
    assert caps(r)["machine_operator_calendar_intersection"] == "NOT_APPLICABLE"


def test_I_synthetic_never_validates_even_with_matching_observed_evidence(tmp_path):
    obs = [ev("Machine_A", "PAUSE", "2026-10-05T14:00:00"), ev("Machine_A", "RESUME", "2026-10-06T06:00:00")]
    r = cv.run_study(study(tmp_path, synthetic=True, observed=obs))
    assert r["status"] == "NOT_TESTED" and not validated(r) and r["scope"] is None
    assert not fails(r) and "SYNTHETIC EXAMPLE" in (tmp_path / "S" / "VALIDATION_REPORT.md").read_text()


def test_operational_metrics_have_no_percentage_threshold_and_stay_unknown_without_evidence(tmp_path):
    m = "target,metric,from,to,value,unit,evidence_type,source_ref,note\nOperator_1,ACTUAL_WORKING_TIME,2026-10-05T00:00:00,2026-10-12T00:00:00,33.5,h,OBSERVED,plc,\n"
    r = cv.run_study(study(tmp_path / "a", observed=[ev("Operator_1", "FIRST_PROCESS_START", "2026-10-05T06:00:00")], files={"observed_metrics.csv": m}))
    p = r["operational_metrics"][0]
    assert p["observed"] == 33.5 * 3600 and p["simforge"] == 38.75 * 3600 and p["relative_difference"] is not None
    assert r["status"] == "REAL_DATA_VALIDATED"  # planned availability != actual working time: not a calendar error
    assert r["representativeness"].startswith("DIFFERENCES_TO_CLASSIFY")
    pid = p["id"]
    r = cv.run_study(study(tmp_path / "b", observed=[ev("Operator_1", "FIRST_PROCESS_START", "2026-10-05T06:00:00")], files={
        "observed_metrics.csv": m, "classifications.csv": f"id,classification,evidence\n{pid},UNMODELLED_EVENT,\n"}))
    assert r["representativeness"].startswith("DIFFERENCES_TO_CLASSIFY")  # a class without evidence is not accepted
    r = cv.run_study(study(tmp_path / "c", observed=[ev("Operator_1", "FIRST_PROCESS_START", "2026-10-05T06:00:00")], files={
        "observed_metrics.csv": m, "classifications.csv": f"id,classification,evidence\n{pid},UNMODELLED_EVENT,material shortage log\n"}))
    assert r["representativeness"].startswith("ASSESSED")


def test_calendar_rows_must_carry_planned_or_reconstructed_evidence_and_known_source(tmp_path):
    r = cv.run_study(study(tmp_path / "a", rows=lambda ls: "\n".join(ls).replace(",PLANNED,plan,", ",OBSERVED,plan,", 1) + "\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("evidence_type" in c for c in r["config_errors"])
    r = cv.run_study(study(tmp_path / "b", rows=lambda ls: "\n".join(ls).replace(",PLANNED,plan,", ",PLANNED,nowhere,", 1) + "\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("source_ref" in c for c in r["config_errors"])
    r = cv.run_study(study(tmp_path / "c", rows=lambda ls: "\n".join(ls) + "\nMachine_A,2026-10-10,06:00,10:00,SHIFT,PLANNED,plan,MINUTE,\n"))
    assert r["status"] == "REAL_DATA_TEST_INCOMPLETE" and any("both non-working" in c for c in r["config_errors"])
