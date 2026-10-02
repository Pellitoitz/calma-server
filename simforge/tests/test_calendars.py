"""Calendars, shifts and availability (engine 0.6.0): the 16 mandatory cases + invariants + compatibility.

Time origin of every model: Monday 00:00 (relative_week) unless stated. 60 s per unit, infinite source.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from simforge.domain.calendar import AVAILABLE, AvailabilitySpec, expand, measure
from simforge.domain.io import dump_model, load_model, model_from_dict
from simforge.domain.isms import Approval
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import verify_model

from .conftest import EXAMPLES

REG = ComponentRegistry.load_default(None)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
H = 3600.0


def every_day(*windows, days=DAYS):
    return {d: [{"start": a, "end": b} for a, b in windows] for d in days}


def cal(cid="shift", windows=(("06:00", "14:00"),), breaks=(), days=DAYS, exceptions=()):
    return {"id": cid, "weekly": every_day(*windows, days=days),
            "breaks": [{"start": a, "end": b} for a, b in breaks], "exceptions": list(exceptions)}


def line(calendars, resources=None, nodes=None, policy="FINISH_CURRENT", rule="START_ANY_TIME", pt=60, horizon_h=24,
         source=None, mode="relative_week", extra_avail=None, always=("assembly",)):
    """source -> assembly (operator_1) -> sink."""
    d = {"meta": {"name": "cal test"}, "simulation": {"horizon": {"value": horizon_h, "unit": "h"}},
         "resources": [{"id": "operator_1", "kind": "operator", "quantity": 1}],
         "nodes": [{"id": "src", "component": "source", "params": source or {}},
                   {"id": "assembly", "component": "manual_assembly",
                    "params": {"process_time": {"dist": "constant", "value": pt}, "resources": [{"resource": "operator_1"}]}},
                   {"id": "out", "component": "sink"}],
         "edges": [{"source": "src", "target": "assembly"}, {"source": "assembly", "target": "out"}],
         "availability": {"mode": mode, "calendars": list(calendars),
                          "resources": resources if resources is not None else {"operator_1": calendars[0]["id"]},
                          "nodes": nodes or {}, "always_available": [a for a in always if a not in (nodes or {})],
                          "operations": {"assembly": {"at_unavailability": policy, "start_rule": rule}}}}
    if extra_avail:
        d["availability"].update(extra_avail)
    return model_from_dict(d)


def run(m, reps=1, trace=False):
    rep, _ = verify_model(m, REG)
    assert rep.ok, [str(i) for i in rep.errors]
    return run_simulation(m, REG, replications=reps, trace=trace, keep_records=True)


def units(m, **kw):
    return run(m, **kw).kpis.mean("units_completed")


def events(res, kind, node="assembly"):
    return [e for e in res.records[0].events if e["event"] == kind and e["node"] == node]


ONE_AT_1358 = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 13 * H + 58 * 60}, "max_entities": 1}


# ------------------------------------------------------------------------------------------------- CASE 1
def test_case01_single_shift_480():
    m = line([cal()])
    r = run(m, trace=True)
    assert r.kpis.mean("units_completed") == 480  # 8 h = 28 800 s / 60 s
    ends = [e["t"] for e in events(r, "end_process")]
    assert ends[0] == 6 * H + 60 and ends[-1] == 14 * H  # the last unit finishes exactly at 14:00:00 and counts
    starts = [e["t"] for e in events(r, "start_process")]
    assert max(starts) == 14 * H - 60  # nothing starts at 14:00:00 (the operator is off from that instant)
    av = r.records[0].availability["resources"]["operator_1"]
    assert av["planned_available_s"] == 8 * H and av["off_shift_s"] == 16 * H and av["break_s"] == 0


# ------------------------------------------------------------------------------------------------- CASE 2
def test_case02_breaks_435():
    m = line([cal(breaks=(("10:00", "10:15"), ("12:30", "13:00")))])
    r = run(m)
    assert r.kpis.mean("units_completed") == 435  # 8 h - 45 min = 26 100 s / 60 s
    assert r.kpis.mean("resource.operator_1.planned_available_h") == pytest.approx(26100 / H)
    assert r.kpis.mean("resource.operator_1.break_h") == pytest.approx(0.75)


# ------------------------------------------------------------------------------------------------- CASE 3
def test_case03_seven_productive_hours_420():
    m = line([cal(breaks=(("09:00", "09:20"), ("11:00", "11:20"), ("13:00", "13:20")))])
    assert units(m) == 420  # 8 h - 60 min = 25 200 s


# ------------------------------------------------------------------------------------------------- CASE 4
def test_case04_two_consecutive_shifts_continuous():
    c = cal(windows=(("06:00", "14:00"), ("14:00", "22:00")))
    spec = AvailabilitySpec.model_validate({"mode": "relative_week", "calendars": [c]})
    tl = expand(spec, spec.calendars[0], 24 * H)
    assert tl.available == [(6 * H, 22 * H)]  # one continuous window: no transition, no double availability at 14:00
    assert units(line([c])) == 960


# ------------------------------------------------------------------------------------------------- CASE 5
def test_case05_night_shift_crosses_midnight():
    c = cal(windows=(("22:00", "06:00"),), days=["mon"])
    r = run(line([c], horizon_h=48), trace=True)
    assert r.kpis.mean("units_completed") == 480  # Mon 22:00 -> Tue 06:00 = 8 h, counted once
    ends = [e["t"] for e in events(r, "end_process")]
    assert ends[0] == 22 * H + 60 and ends[-1] == 30 * H
    assert sum(1 for t in ends if t > 24 * H) == 360  # 00:00-06:00 belongs to Monday's night shift


# --------------------------------------------------------------------------------------------- CASES 6-8
def _boundary(policy):
    m = line([cal()], policy=policy, pt=300, horizon_h=48, source=ONE_AT_1358)
    return run(m, trace=True)


def test_case06_finish_current_ends_1403():
    r = _boundary("FINISH_CURRENT")
    assert [e["t"] for e in events(r, "start_process")] == [13 * H + 58 * 60]
    assert [e["t"] for e in events(r, "end_process")] == [14 * H + 3 * 60]
    assert r.kpis.mean("node.assembly.busy_outside_planned_h") == pytest.approx(3 / 60)
    assert r.kpis.mean("resource.operator_1.outside_planned_h") == pytest.approx(3 / 60)


def test_case07_pause_resume_keeps_remaining_work():
    r = _boundary("PAUSE_RESUME")
    paused = events(r, "paused_by_calendar")
    assert [e["t"] for e in paused] == [14 * H] and paused[0]["remaining_s"] == 180  # 2 min done, 3 min left
    assert [e["t"] for e in events(r, "resume_process")] == [24 * H + 6 * H]
    assert [e["t"] for e in events(r, "end_process")] == [30 * H + 3 * 60]  # 06:03 next day
    assert r.kpis.mean("node.assembly.paused_by_calendar_h") == pytest.approx(16)


def test_case08_stop_restart_loses_work():
    r = _boundary("STOP_RESTART")
    assert events(r, "restart_lost_work")[0]["lost_s"] == 120
    assert [e["t"] for e in events(r, "end_process")] == [30 * H + 5 * 60]  # 06:00 + full 5 min


def test_operation_completing_exactly_at_shift_end_is_complete_under_every_policy():
    for pol in ("FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART"):
        r = run(line([cal()], policy=pol), trace=True)
        assert r.kpis.mean("units_completed") == 480
        assert not events(r, "paused_by_calendar") and not events(r, "restart_lost_work")


def test_require_full_window_deterministic():
    m = line([cal()], rule="REQUIRE_FULL_WINDOW", pt=600, horizon_h=48, source=ONE_AT_1358)
    r = run(m, trace=True)
    assert events(r, "start_deferred")[0]["window_left_s"] == 120
    assert [e["t"] for e in events(r, "start_process")] == [30 * H]  # not at 13:58: starts next shift 06:00
    assert [e["t"] for e in events(r, "end_process")] == [30 * H + 600]


def test_require_full_window_with_random_time_is_refused():
    m = line([cal()], rule="REQUIRE_FULL_WINDOW")
    m = set_value(m, "nodes.assembly.params.process_time", {"dist": "uniform", "low": 50, "high": 70})
    rep, cm = verify_model(m, REG)
    assert cm is None and any(i.code == "CAL_POLICY_UNSUPPORTED" and "aleatorio" in i.message for i in rep.errors)


# ------------------------------------------------------------------------------------------------- CASE 9
def test_case09_machine_24_7_and_operator_one_shift():
    m = line([cal("machine_24_7", windows=(("00:00", "24:00"),)), cal("op_shift")],
             resources={"operator_1": "op_shift"}, nodes={"assembly": "machine_24_7"})
    r = run(m)
    assert r.kpis.mean("units_completed") == 480
    assert r.kpis.mean("node.assembly.planned_available_h") == pytest.approx(8)  # intersection
    assert r.kpis.mean("node.assembly.busy_outside_planned_h") == 0


# ------------------------------------------------------------------------------------------------ CASE 10
def test_case10_intersection_of_machine_and_operator_calendars():
    m = line([cal("machine", windows=(("06:00", "22:00"),)), cal("op", windows=(("08:00", "16:00"),))],
             resources={"operator_1": "op"}, nodes={"assembly": "machine"}, horizon_h=24)
    r = run(m, trace=True)
    assert r.kpis.mean("units_completed") == 480
    starts = [e["t"] for e in events(r, "start_process")]
    assert min(starts) == 8 * H and max(starts) == 16 * H - 60
    assert r.kpis.mean("node.assembly.planned_available_h") == pytest.approx(8)


# ------------------------------------------------------------------------------------------------ CASE 11
def test_case11_weekend_off():
    m = line([cal(days=DAYS[:5])], horizon_h=168)
    r = run(m)
    assert r.kpis.mean("units_completed") == 5 * 480
    assert r.kpis.mean("resource.operator_1.planned_available_h") == pytest.approx(40)
    assert r.kpis.mean("resource.operator_1.planned_availability_ratio") == pytest.approx(40 / 168)


# ------------------------------------------------------------------------------------------- CASES 12-13
DATED = {"start_date": "2026-10-05", "timezone": "UTC"}  # 2026-10-05 is a Monday


def test_case12_holiday_non_working_day():
    hol = {"date": "2026-10-07", "type": "NON_WORKING_DAY", "reason": "festivo local", "scope": "SHIFTS_STARTING_ON_DATE"}
    m = line([cal(days=DAYS[:5], exceptions=[hol])], horizon_h=168, mode="dated", extra_avail=DATED)
    r = run(m)
    assert r.kpis.mean("units_completed") == 4 * 480
    assert r.kpis.mean("resource.operator_1.planned_available_h") == pytest.approx(32)


def test_case13_saturday_overtime_window():
    ot = {"date": "2026-10-10", "type": "OVERTIME", "intervals": [{"start": "06:00", "end": "12:00"}],
          "reason": "pedido urgente", "breaks_apply": False}
    m = line([cal(days=DAYS[:5], exceptions=[ot])], horizon_h=168, mode="dated", extra_avail=DATED)
    r = run(m, trace=True)
    sat = [e["t"] for e in events(r, "end_process") if 5 * 24 * H <= e["t"] < 6 * 24 * H]
    assert len(sat) == 360 and min(sat) == 5 * 24 * H + 6 * H + 60 and max(sat) == 5 * 24 * H + 12 * H
    assert r.kpis.mean("units_completed") == 5 * 480 + 360


def test_relative_week_cannot_hold_dated_exceptions():
    ot = {"date": "2026-10-10", "type": "OVERTIME", "intervals": [{"start": "06:00", "end": "12:00"}], "reason": "x y z",
          "breaks_apply": False}
    rep, cm = verify_model(line([cal(exceptions=[ot])]), REG)
    assert cm is None and any(i.code == "CAL_EXCEPTIONS_NEED_DATES" for i in rep.errors)


def test_dated_mode_requires_timezone_and_handles_dst():
    rep, cm = verify_model(line([cal()], mode="dated", extra_avail={"start_date": "2026-10-05"}), REG)
    assert cm is None and any(i.code == "CAL_TIMEZONE_MISSING" for i in rep.errors)
    # Europe/Madrid leaves summer time on 2026-10-25 at 03:00 -> a 22:00-06:00 night shift lasts 9 h that night
    night = cal(windows=(("22:00", "06:00"),), days=["sat"])
    spec = AvailabilitySpec.model_validate({"mode": "dated", "start_date": "2026-10-24", "timezone": "Europe/Madrid",
                                           "calendars": [night]})
    assert measure(expand(spec, spec.calendars[0], 3 * 24 * H).available) == pytest.approx(9 * H)


# ------------------------------------------------------------------------------------------------ CASE 14
def test_case14_operation_ends_exactly_at_break_start_deterministic():
    m = line([cal(breaks=(("10:00", "10:15"),))], policy="PAUSE_RESUME")
    logs = []
    for _ in range(5):
        r = run(m, trace=True)
        assert r.kpis.mean("units_completed") == 465
        assert not events(r, "paused_by_calendar")  # the unit ending at 10:00:00 is complete, not paused
        logs.append([(e["t"], e["event"], e["entity"]) for e in r.records[0].events])
    assert all(x == logs[0] for x in logs)
    ends = [e["t"] for e in events(r, "end_process")]
    assert 10 * H in ends and not any(10 * H < t <= 10 * H + 15 * 60 for t in ends)


def test_shift_start_and_arrival_at_same_instant_starts_immediately():
    src = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 6 * H}, "max_entities": 1}
    r = run(line([cal()], source=src), trace=True)
    assert [e["t"] for e in events(r, "start_process")] == [6 * H]


def test_arrival_at_break_start_waits_until_break_end():
    src = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 10 * H}, "max_entities": 1}
    r = run(line([cal(breaks=(("10:00", "10:15"),))], source=src), trace=True)
    assert [e["t"] for e in events(r, "start_process")] == [10 * H + 15 * 60]


# ------------------------------------------------------------------------------------------------ CASE 15
def test_case15_queue_blocking_and_conservation():
    d = {"meta": {"name": "queue"}, "simulation": {"horizon": {"value": 48, "unit": "h"}},
         "nodes": [{"id": "src", "component": "source",
                    "params": {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 120}}},
                   {"id": "buf", "component": "buffer", "params": {"capacity": 50}},
                   {"id": "machine", "component": "machine", "params": {"process_time": {"dist": "constant", "value": 60}}},
                   {"id": "out", "component": "sink"}],
         "edges": [{"source": "src", "target": "buf"}, {"source": "buf", "target": "machine"},
                   {"source": "machine", "target": "out"}],
         "availability": {"mode": "relative_week", "calendars": [cal("m8h")], "nodes": {"machine": "m8h"},
                          "always_available": ["src"],
                          "operations": {"machine": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}}}
    m = model_from_dict(d)
    r = run(m, trace=True)
    rec = r.records[0]
    assert rec.level_max["buffer:buf"] == 50  # accumulates up to its capacity off-shift, then blocks upstream
    assert rec.created == r.kpis.mean("units_completed") + rec.wip_end  # no entity disappears at shift change
    ends = [e["t"] for e in events(r, "end_process", "machine")]
    assert all(6 * H < t % (24 * H) <= 14 * H or t % (24 * H) == 0 for t in ends)
    day2 = [t for t in ends if t > 24 * H]
    assert min(day2) == 30 * H + 60  # resumes at the next shift with the queue it found
    assert len(day2) == 480  # the queue (>= 50 + blocked arrivals) keeps the machine busy the whole shift


# ------------------------------------------------------------------------------------------------ CASE 16
def test_case16_shared_operator_after_break_uses_dispatch_rule():
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    spec = {"mode": "relative_week", "calendars": [cal("op", windows=(("00:00", "08:00"),), breaks=(("04:00", "04:30"),))],
            "resources": {"operator_1": "op"}, "always_available": ["assembly", "machine", "inspection"],
            "operations": {"assembly": {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"},
                           "inspection": {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}}}
    m = set_value(m, "simulation.trace", True)
    m = model_from_dict({**m.model_dump(mode="json"), "availability": spec})
    r = run(m, trace=True)
    after = [d for d in r.records[0].decisions if d["t"] == 4.5 * H and d["kind"] == "assign"]
    assert after, "the operator must get a task exactly at the end of the break"
    first = after[0]
    assert first["rule"] == "priority" and first["reason_code"] != "CALENDAR"
    waiting = {c["node"] for c in first["candidates"]}
    assert {"assembly", "inspection"} <= waiting  # both tasks accumulated during the break
    assert first["chosen_node"] == "inspection"  # lower priority value wins, exactly as without calendars
    assert not any(4 * H < d["t"] < 4.5 * H and d["kind"] == "assign" for d in r.records[0].decisions)  # nothing during break


# ------------------------------------------------------------------------------------------- invariants & co
def test_no_resource_works_off_shift_except_finish_current():
    for pol, expect in (("PAUSE_RESUME", 0.0), ("STOP_RESTART", 0.0)):
        r = _boundary(pol)
        assert r.kpis.mean("resource.operator_1.outside_planned_h") == expect
        assert r.kpis.mean("node.assembly.busy_outside_planned_h") == expect


def test_time_accounting_has_no_double_count():
    m = line([cal(windows=(("06:00", "14:00"), ("13:00", "15:00")))])  # overlapping shifts: refused, never counted twice
    rep, cm = verify_model(m, REG)
    assert cm is None and any(i.code == "CAL_SHIFT_OVERLAP" for i in rep.errors)
    m = line([cal(breaks=(("10:00", "10:30"), ("10:15", "10:45"), ("13:30", "14:30")))])  # overlapping + partly outside
    rep, cm = verify_model(m, REG)
    codes = {i.code for i in rep.warnings}
    assert {"CAL_BREAKS_OVERLAP", "CAL_BREAK_PARTIAL"} <= codes
    r = run(m)
    av = r.records[0].availability["resources"]["operator_1"]
    assert av["break_s"] == 45 * 60 + 30 * 60  # 10:00-10:45 merged + 13:30-14:00 inside the shift
    assert av["planned_available_s"] + av["break_s"] + av["off_shift_s"] == av["calendar_time_s"]
    assert av["planned_states_s"] == av["planned_available_s"]  # engine states agree with the calendar (checked in-run)


def test_same_seed_same_result_with_random_times_and_calendars():
    m = line([cal(breaks=(("10:00", "10:15"),))], policy="PAUSE_RESUME")
    m = set_value(m, "nodes.assembly.params.process_time", {"dist": "lognormal", "mean": 60, "std": 20})
    a, b = run(m, reps=3), run(m, reps=3)
    assert a.per_replication == b.per_replication and a.seeds == b.seeds


def test_legacy_models_unchanged_and_hash_stable():
    import json
    hashes = json.loads((EXAMPLES.parent / "tests" / "data" / "model_hashes_engine_0_3_0.json").read_text())
    expected = {"01_simple_line.yaml": 59, "02_shared_operator.yaml": 359, "05_selective_soldering.yaml": 130}
    for f, units_ in expected.items():
        m = load_model(EXAMPLES / f)
        assert m.content_hash() == hashes[f]["content_hash"] and "availability" not in dump_model(m)
        assert run_simulation(m, REG).kpis.mean("units_completed") == units_


def test_calendar_changes_hash_and_invalidates_approval():
    m = line([cal(breaks=(("10:00", "10:15"),))])
    approved = m.model_copy(update={"approval": Approval(approved=True, by="ana", at=datetime.now(timezone.utc),
                                                         model_hash=m.content_hash())})
    assert approved.is_approved
    rep, _ = verify_model(approved, REG)
    assert rep.readiness.value == "ENGINEER_APPROVED" and not any(i.code == "APPROVAL_STALE" for i in rep.issues)
    for path, value in [("availability.calendars.0.breaks.0.end", "10:20"),
                        ("availability.calendars.0.weekly.mon.0.end", "14:30"),
                        ("availability.operations.assembly.at_unavailability", "PAUSE_RESUME")]:
        data = copy.deepcopy(approved.model_dump(mode="json"))
        cur = data
        keys = path.split(".")
        for k in keys[:-1]:
            cur = cur[int(k)] if k.isdigit() else cur[k]
        cur[keys[-1]] = value
        changed = model_from_dict(data)
        assert changed.content_hash() != m.content_hash() and not changed.is_approved
        rep, _ = verify_model(changed, REG)
        assert any(i.code == "APPROVAL_STALE" for i in rep.issues)


def test_calendar_persists_and_historical_run_is_reproducible(tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("cal")
    m = line([cal(breaks=(("10:00", "10:15"),))])
    v1 = sf.save_model(p, m, "with break")
    r1 = sf.run_simulation(p)
    assert r1.engine_version == "0.6.0" and r1.availability_hash
    sf.save_model(p, set_value(p.current_model(), "availability.calendars.0.breaks.0.end", "11:00"), "longer break")
    assert run_simulation(p.current_model(), REG).kpis.mean("units_completed") != r1.kpis.mean("units_completed")
    old = p.load_version(v1)
    again = run_simulation(old, REG)
    assert again.kpis.mean("units_completed") == r1.kpis.mean("units_completed") == 465
    assert again.availability_hash == r1.availability_hash


def test_validation_requires_engineer_decisions_and_detects_errors():
    m = line([cal()])
    data = m.model_dump(mode="json")
    data["availability"]["operations"] = {}
    rep, cm = verify_model(model_from_dict(data), REG)
    assert cm is None and {"DECISION_INTERRUPTION_POLICY", "DECISION_START_RULE"} <= {i.code for i in rep.errors}
    data = m.model_dump(mode="json")
    data["availability"]["resources"] = {"operator_1": "nope"}
    assert any(i.code == "CAL_UNKNOWN_CALENDAR" for i in verify_model(model_from_dict(data), REG)[0].errors)
    night = cal(windows=(("22:00", "06:00"),),
                exceptions=[{"date": "2026-10-07", "type": "NON_WORKING_DAY", "reason": "festivo"}])
    rep, _ = verify_model(line([night], mode="dated", extra_avail=DATED), REG)
    assert any(i.code == "DECISION_HOLIDAY_SCOPE" for i in rep.errors)
    with pytest.raises(Exception, match="duración cero"):
        line([cal(windows=(("06:00", "06:00"),))])
    m2 = load_model(EXAMPLES / "05_selective_soldering.yaml")
    d5 = {**m2.model_dump(mode="json"), "availability": {"mode": "relative_week", "calendars": [cal()],
                                                         "resources": {"racks": "shift"}}}
    assert any(i.code == "CAL_CARRIER_UNSUPPORTED" for i in verify_model(model_from_dict(d5), REG)[0].errors)


def test_undeclared_availability_warns_unless_explicit():
    rep, _ = verify_model(line([cal()], always=()), REG)
    assert any(i.code == "CAL_AVAILABILITY_UNDECLARED" and "assembly" in i.message for i in rep.warnings)
    rep, _ = verify_model(line([cal()]), REG)
    assert not any(i.code == "CAL_AVAILABILITY_UNDECLARED" for i in rep.warnings)


def test_source_calendar_pauses_the_arrival_clock():
    src = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 3600}, "max_entities": 10}
    m = line([cal("src_cal"), cal("op", windows=(("00:00", "24:00"),))], resources={"operator_1": "op"},
             nodes={"src": "src_cal"}, source=src, horizon_h=48)
    r = run(m, trace=True)
    created = [e["t"] for e in r.records[0].events if e["event"] == "created"]
    assert created[:8] == [h * H for h in range(7, 15)] and created[8] == 31 * H  # paused 14:00 -> 06:00


def test_week_view_is_readable():
    from simforge.domain.calendar import week_view
    spec = AvailabilitySpec.model_validate({"mode": "relative_week",
                                           "calendars": [cal(breaks=(("10:00", "10:15"), ("12:30", "13:00")), days=DAYS[:5])]})
    v = week_view(spec, spec.calendars[0])
    assert "MON" in v and "[break 10:00-10:15]" in v and "= 7.25 h" in v and "SAT" in v and "36.25 h" in v


def test_experiments_keep_working_with_calendars():
    from simforge.domain.isms import ExperimentSpec, Factor
    from simforge.experiments.runner import run_experiment
    m = line([cal()])
    res = run_experiment(m, ExperimentSpec(name="pt", factors=[Factor(path="nodes.assembly.params.process_time.value",
                                                                       values=[60, 120])]), REG)
    assert [s.result.kpis.mean("units_completed") for s in res.scenarios] == [480, 240]


def test_timeline_label_partition():
    spec = AvailabilitySpec.model_validate({"mode": "relative_week", "calendars": [cal(breaks=(("10:00", "10:15"),))]})
    tl = expand(spec, spec.calendars[0], 24 * H)
    assert tl.time_in(AVAILABLE, 0, 24 * H) + tl.time_in("break", 0, 24 * H) + tl.time_in("off_shift", 0, 24 * H) == 24 * H
    assert tl.label_at(10 * H) == "break" and tl.label_at(14 * H) == "off_shift" and tl.label_at(6 * H) == AVAILABLE


def test_ui_calendar_tab_without_yaml(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    ws = tmp_path / "ws"
    sf = SimForgeApp(workspace=ws, library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("UI cal")
    sf.save_model(p, load_model(EXAMPLES / "02_shared_operator.yaml"), "base")
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(ws))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=120)
    at.run()

    def button(label):
        return next(b for b in at.button if b.label == label)

    def text(label):
        return next(t for t in at.text_input if t.label == label)
    button("Guardar modo").click().run()
    assert not at.exception
    text("Id del calendario").input("turno")
    text("Nombre").input("Turno mañana")
    text("Turnos").input("06:00-14:00")
    text("Descansos (esos días)").input("10:00-10:15, 12:30-13:00")
    button("Crear / reemplazar patrón semanal").click().run()
    assert not at.exception
    assert any("[break 10:00-10:15]" in c.value and "7.25 h" in c.value for c in at.code)
    next(s for s in at.selectbox if s.label == "Recurso / nodo").select("resource:operator_1")
    next(s for s in at.selectbox if s.label == "Calendario a asignar").select("turno")
    button("Asignar").click().run()
    assert not at.exception
    assert any("DECISION_INTERRUPTION_POLICY" in e.value for e in at.error)  # never decided silently
    next(s for s in at.selectbox if s.label == "Operación (nodo)").select("assembly")
    next(s for s in at.selectbox if s.label == "Fin de disponibilidad").select("PAUSE_RESUME")
    button("Guardar decisión").click().run()
    assert not at.exception
    m = sf.open_project(p.meta.slug).current_model()
    assert m.availability.resources == {"operator_1": "turno"}
    assert m.availability.operations["assembly"].at_unavailability == "PAUSE_RESUME"
    assert len(m.availability.calendars[0].breaks) == 2


def test_cli_calendar_flow(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from simforge.cli import app as cli
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    runner = CliRunner()

    def ok(*args, code=0):
        r = runner.invoke(cli, list(map(str, args)))
        assert r.exit_code == code, r.output
        return r.output
    ok("project", "new", "Linea", "--model", EXAMPLES / "02_shared_operator.yaml")
    ok("calendar", "setup", "linea", "--mode", "relative_week")
    ok("calendar", "create", "linea", "turno", "--days", "all", "--shifts", "06:00-14:00", "--breaks", "10:00-10:15,12:30-13:00")
    ok("calendar", "assign", "linea", "turno", "--resource", "operator_1")
    out = ok("calendar", "validate", "linea", code=1)
    assert "REQUIRES_ENGINEER_DECISION" in out and "DECISION_INTERRUPTION_POLICY" in out
    for n in ("assembly", "inspection"):
        ok("calendar", "policy", "linea", n, "--at-unavailability", "FINISH_CURRENT", "--start-rule", "START_ANY_TIME")
    ok("calendar", "validate", "linea")
    out = ok("calendar", "show", "linea")
    assert "[break 10:00-10:15]" in out and "planned" in out
    assert "operator_1" in ok("calendar", "list", "linea")
    ok("calendar", "assign", "linea", "nope", "--resource", "operator_1", code=1)


def test_transport_with_calendared_resource_only_finish_current():
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    data = m.model_dump(mode="json")
    data["nodes"].insert(2, {"id": "carry", "component": "transport",
                             "params": {"distance": {"value": 10, "unit": "m"}, "speed": {"value": 1, "unit": "m/s"},
                                        "load_time": {"dist": "constant", "value": 5}, "unload_time": {"dist": "constant", "value": 5},
                                        "resources": [{"resource": "operator_1"}]}})
    data["edges"] = [{"source": "src", "target": "assembly"}, {"source": "assembly", "target": "carry"},
                     {"source": "carry", "target": "buffer_1"}] + data["edges"][2:]
    data["availability"] = {"mode": "relative_week", "calendars": [cal()], "resources": {"operator_1": "shift"},
                            "always_available": ["assembly", "machine", "inspection"],
                            "operations": {n: {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}
                                           for n in ("assembly", "inspection")} | {
                                "carry": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}}
    rep, cm = verify_model(model_from_dict(data), REG)
    assert cm is None and any(i.code == "CAL_POLICY_UNSUPPORTED" and "carry" in i.message for i in rep.errors)
    data["availability"]["operations"]["carry"]["at_unavailability"] = "FINISH_CURRENT"
    m2 = model_from_dict(data)
    r = run(m2)
    assert r.kpis.mean("units_completed") > 0 and r.kpis.mean("resource.operator_1.planned_available_h") == pytest.approx(2)
