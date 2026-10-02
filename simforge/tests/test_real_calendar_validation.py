"""Real-data calendar validation tool (scripts/validation/calendar_validation.py): it must be able to FAIL, it never
reports REAL_DATA_VALIDATED for synthetic data or without sign-off, and EXPECTED is independent of the engine."""

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


@pytest.fixture(scope="module", autouse=True)
def _fast_regression():
    # the 01-05 regression is covered by the engine tests; here only its effect on the status is checked
    orig = cv._regression
    cv._regression = lambda: {"ok": True, "expected": {}, "got": {}}
    yield
    cv._regression = orig


def study(tmp_path, synthetic=False, signed=True, edit_study=None, edit_model=None, observed=None):
    d = tmp_path / "S"
    shutil.copytree(STUDIES / "EXAMPLE_SYNTHETIC", d)
    for g in ("expected", "simforge", "comparison"):
        shutil.rmtree(d / g, ignore_errors=True)
    s = yaml.safe_load((d / "input" / "study.yaml").read_text())
    s["synthetic"] = synthetic
    s["study_id"] = "TEST_FIXTURE"
    s["engineer_sign_off"] = {"name": "Engineer_1", "date": "2026-10-02", "notes": "test"} if signed else {}
    if edit_study:
        edit_study(s)
    (d / "input" / "study.yaml").write_text(yaml.safe_dump(s))
    if edit_model:
        txt = (d / "input" / "model.yaml").read_text()
        (d / "input" / "model.yaml").write_text(edit_model(txt))
    if observed:
        (d / "input" / "observed_events.csv").write_text("timestamp,resource,event,precision_s,source\n" + "\n".join(observed) + "\n")
    return d


def fails(r):
    return [x for x in r["metrics"] + r["events"] if x["status"] == "FAIL"]


def test_synthetic_example_is_never_validated_even_if_everything_passes(tmp_path):
    r = cv.run_study(study(tmp_path, synthetic=True))
    assert r["status"] == "NOT_TESTED"
    assert not fails(r) and not r["config_errors"]
    assert "SYNTHETIC EXAMPLE" in (tmp_path / "S" / "VALIDATION_REPORT.md").read_text()


def test_matching_signed_study_validates_only_with_sign_off(tmp_path):
    r = cv.run_study(study(tmp_path / "a"))
    assert r["status"] == "REAL_DATA_VALIDATED", (fails(r), r["config_errors"])
    pa = {(m["target"], m["metric"]): m["expected_s"] for m in r["metrics"]}
    assert pa[("Operator_1", "PLANNED_AVAILABLE_TIME")] == 5 * (8 * 3600 - 900)
    assert pa[("Machine_A", "PLANNED_AVAILABLE_TIME")] == 5 * 16 * 3600
    assert not any(e["event"] == "SHIFT_END" and "14:00" in e["expected"] and e["target"] == "Machine_A" for e in r["events"])
    assert cv.run_study(study(tmp_path / "b", signed=False))["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_regression_failure_blocks_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "_regression", lambda: {"ok": False, "expected": {}, "got": {}})
    assert cv.run_study(study(tmp_path))["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_break_entered_wrongly_in_the_model_fails_with_zero_tolerance(tmp_path):
    r = cv.run_study(study(tmp_path, edit_model=lambda t: t.replace('end: "10:15"', 'end: "10:16"')))
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    f = fails(r)
    assert {x.get("metric") for x in f} >= {"PLANNED_AVAILABLE_TIME", "BREAK_TIME", "ENGINE_TRACKED_PLANNED_TIME"}
    be = [x for x in f if x.get("event") == "BREAK_END"]
    plan = [x for x in be if x["source"].startswith("PLAN")]
    assert len(plan) == 5 and all(x["delta_s"] == 60.0 for x in plan)
    assert len(be) == 10  # each wrong 10:16 transition is also reported as "SIMFORGE only"
    assert all(x["classification"] == "UNKNOWN" for x in f)  # never auto-explained


def test_holiday_in_real_schedule_missing_in_model_fails(tmp_path):
    d = study(tmp_path)
    rows = [r for r in (d / "input" / "calendar_rows.csv").read_text().splitlines() if "2026-10-07" not in r]
    (d / "input" / "calendar_rows.csv").write_text("\n".join(rows + ["Machine_A,2026-10-07,,,HOLIDAY,"]) + "\n")
    r = cv.run_study(d)
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    assert any(e["source"] == "SIMFORGE only" for e in r["events"])


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
    assert r["status"] == "NOT_TESTED" and "timezone" in r["missing"]
    d = study(tmp_path)
    (d / "input" / "model.yaml").unlink()
    assert cv.run_study(d)["status"] == "REAL_DATA_TEST_INCOMPLETE"


def test_observed_timestamps_use_declared_precision_only(tmp_path):
    obs = ["2026-10-05T14:00:30,Operator_1,SHIFT_END,60,manual sheet",
           "2026-10-06T14:00:30,Operator_1,SHIFT_END,0,PLC"]
    r = cv.run_study(study(tmp_path, observed=obs))
    o = [e for e in r["events"] if e["source"].startswith("OBSERVED")]
    assert [e["status"] for e in o] == ["PASS", "FAIL"] and o[1]["delta_s"] == -30.0
    assert r["status"] == "REAL_DATA_VALIDATION_FAILED"
    assert r["boundary_observed"] is False  # shift ends are not boundary behaviour -> NOT_OBSERVED_IN_REAL_DATA


def test_expected_side_is_independent_of_the_engine():
    for fn in (cv.expected_from_rows, cv.expected_events, cv._union, cv._minus, cv._inter):
        assert "simforge" not in inspect.getsource(fn)


def test_expected_handles_overnight_and_fall_dst_by_itself():
    tz = ZoneInfo("Europe/Madrid")
    t0 = dt.datetime(2026, 10, 24, tzinfo=tz)
    t1 = dt.datetime(2026, 10, 26, tzinfo=tz)
    rows = [{"resource": "M", "date": "2026-10-24", "start": "22:00", "end": "06:00", "kind": "SHIFT"},
            {"resource": "M", "date": "2026-10-25", "start": "02:00", "end": "02:30", "kind": "BREAK"}]
    e = cv.expected_from_rows(rows, tz, t0, t1)["M"]
    assert cv._len(e["available"]) + cv._len(e["break"]) == 9 * 3600  # 25 Oct 03:00 -> 02:00: one hour longer
    assert e["horizon"] == 49 * 3600


def test_engine_matches_independent_expectation_across_fall_dst_overnight_shift(tmp_path):
    def es(s):
        s.update(period_start="2026-10-19T00:00:00", period_end="2026-10-26T00:00:00")

    def em(t):
        t = t.replace("start_date: 2026-10-05", "start_date: 2026-10-19").replace("value: 168, unit: h", "value: 169, unit: h")
        return t.replace('fri: [{start: "06:00", end: "14:00"}, {start: "14:00", end: "22:00"}]}',
                         'fri: [{start: "06:00", end: "14:00"}, {start: "14:00", end: "22:00"}],\n'
                         '               sat: [{start: "22:00", end: "06:00"}]}')
    d = study(tmp_path, edit_study=es, edit_model=em)
    rows = []
    for line in (d / "input" / "calendar_rows.csv").read_text().splitlines()[1:]:
        r = line.split(",")
        r[1] = (dt.date.fromisoformat(r[1]) + dt.timedelta(days=14)).isoformat()
        rows.append(",".join(r))
    rows.append("Machine_A,2026-10-24,22:00,06:00,SHIFT,overnight across DST end")
    (d / "input" / "calendar_rows.csv").write_text("resource,date,start,end,kind,note\n" + "\n".join(rows) + "\n")
    r = cv.run_study(d)
    assert r["status"] == "REAL_DATA_VALIDATED", (fails(r), r["config_errors"])
    pa = {(m["target"], m["metric"]): m["simforge_s"] for m in r["metrics"]}
    assert pa[("Machine_A", "PLANNED_AVAILABLE_TIME")] == 5 * 16 * 3600 + 9 * 3600
    assert pa[("Machine_A", "CALENDAR_TIME")] == 169 * 3600
