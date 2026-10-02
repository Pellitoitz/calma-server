"""Engine 0.6.0 closure: boundary cases of calendars (PAUSE_RESUME resource contract, failures + calendars, remaining
work, double interruption, overnight exceptions, spring DST, STOP_RESTART sample, source clock, persistence)."""

from __future__ import annotations

import pytest

from simforge.domain.calendar import AvailabilitySpec, expand, measure
from simforge.domain.io import load_model, model_from_dict
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import verify_model

from .conftest import EXAMPLES

REG = ComponentRegistry.load_default(None)
H = 3600.0
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def cal(cid, a="06:00", b="14:00", days=DAYS):
    return {"id": cid, "weekly": {d: [{"start": a, "end": b}] for d in days}}


def station(machine_cal, resource_cals: dict, policy="PAUSE_RESUME", pt=420, failures=None, horizon=32, rework_source=None):
    """src -> assembly (own calendar + resources) -> out; optional second line src2 -> rework (operator 'op') -> out2."""
    params = {"process_time": {"dist": "constant", "value": pt}, "resources": [{"resource": r} for r in resource_cals]}
    if failures:
        params["failures"] = failures
    nodes = [{"id": "src", "component": "source"}, {"id": "assembly", "component": "manual_assembly", "params": params},
             {"id": "out", "component": "sink"}]
    edges = [{"source": "src", "target": "assembly"}, {"source": "assembly", "target": "out"}]
    ops = {"assembly": {"at_unavailability": policy, "start_rule": "START_ANY_TIME"}}
    always = []
    if rework_source is not None:
        nodes += [{"id": "src2", "component": "source", "params": rework_source},
                  {"id": "rework", "component": "manual_assembly",
                   "params": {"process_time": {"dist": "constant", "value": 60}, "resources": [{"resource": "op"}]}},
                  {"id": "out2", "component": "sink"}]
        edges += [{"source": "src2", "target": "rework"}, {"source": "rework", "target": "out2"}]
        ops["rework"] = {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}
        always.append("rework")
    cals = {machine_cal["id"]: machine_cal, **{c["id"]: c for c in resource_cals.values()}}
    return model_from_dict({
        "meta": {"name": "closure"}, "simulation": {"horizon": {"value": horizon, "unit": "h"}},
        "resources": [{"id": r, "kind": "operator" if r == "op" else "tool", "quantity": 1} for r in resource_cals],
        "nodes": nodes, "edges": edges,
        "availability": {"mode": "relative_week", "calendars": list(cals.values()), "nodes": {"assembly": machine_cal["id"]},
                         "resources": {r: c["id"] for r, c in resource_cals.items()}, "always_available": always,
                         "operations": ops}})


def run(m, reps=1):
    rep, _ = verify_model(m, REG)
    assert rep.ok, [str(i) for i in rep.errors]
    return run_simulation(m, REG, replications=reps, trace=True, keep_records=True)


def trace(r, node="assembly", skip=("enter", "leave", "wait_resource")):
    return [(e["t"], e["event"], e.get("remaining_s")) for e in r.records[0].events if e["node"] == node and e["event"] not in skip]


def decisions(r, node, a, b):
    return [d for d in r.records[0].decisions if d["chosen_node"] == node and a < d["t"] < b]


def conserved(r):
    rec = r.records[0]
    return rec.created == len(rec.completions) + rec.wip_end + len(rec.scrapped)


FAIL = lambda mtbf, mttr: {"mtbf": {"dist": "constant", "value": mtbf}, "mttr": {"dist": "constant", "value": mttr}}  # noqa: E731


# ---------------------------------------------------------------------------------------- A: same frontier
def test_A_machine_operator_and_tool_end_together_single_pause():
    m = station(cal("mach"), {"op": cal("opc"), "jig": cal("jigc")})  # three calendars, same 14:00 frontier
    traces = []
    for _ in range(4):
        r = run(m)
        t = [x for x in trace(r) if 14 * H - 1 <= x[0] <= 30 * H + 200]
        assert t == [(14 * H, "paused_by_calendar", 180.0), (30 * H, "resume_process", 180.0), (30 * H + 180, "end_process", None),
                     (30 * H + 180, "start_process", None)]  # ONE pause, remaining reduced once (240 s done of 420)
        assert [d["t"] for d in decisions(r, "assembly", 14 * H - 1, 30 * H + 1)] == [30 * H, 30 * H]  # one re-acquire per resource
        assert conserved(r)  # a double release would have aborted the run (released-but-not-in-use invariant)
        traces.append([(e["t"], e["event"], e["entity"], e["node"]) for e in r.records[0].events])
    assert all(x == traces[0] for x in traces)
    st = r.records[0].node_state_time["assembly"]
    assert st["paused_by_calendar"] == pytest.approx(16 * H)  # counted once (14:00 -> 06:00)


# ---------------------------------------------------------------------------------- B: only the machine ends
def test_B_only_machine_ends_operator_released_and_no_resume_priority():
    # rework arrivals at 14:00 (operator free for it) and at 04:00 next day (waits for the operator shift)
    m = station(cal("mach"), {"op": cal("opc", "06:00", "22:00")},
                rework_source={"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 14 * H}, "max_entities": 2})
    r = run(m)
    assert (14 * H, "paused_by_calendar", 180.0) in trace(r)
    assert [d["t"] for d in decisions(r, "rework", 14 * H - 1, 14 * H + 1)] == [14 * H]  # operator reassigned at once
    at6 = [d for d in r.records[0].decisions if 30 * H <= d["t"] < 30 * H + 120]
    assert [d["chosen_node"] for d in at6] == ["rework", "assembly"]  # FIFO: rework waited since 04:00; no resume priority
    assert (30 * H + 60, "resume_process", 180.0) in trace(r)
    assert not decisions(r, "assembly", 14 * H, 30 * H)  # nothing granted to the off-shift machine


# ---------------------------------------------------------------------------------- C: failure at shift end
@pytest.mark.parametrize("policy,end", [("PAUSE_RESUME", 30 * H + 180), ("STOP_RESTART", 30 * H + 420)])
def test_C_breakdown_exactly_at_shift_end(policy, end):
    m = station(cal("mach"), {"op": cal("opc", "06:00", "22:00")}, policy=policy, failures=FAIL(14 * H, 3 * H))
    logs = []
    for _ in range(3):
        r = run(m)
        t = [x for x in trace(r) if 14 * H - 1 <= x[0] <= end and x[1] != "start_process"]
        left = 180.0 if policy == "PAUSE_RESUME" else 420.0
        expect = ([(14 * H, "restart_lost_work", None)] if policy == "STOP_RESTART" else []) + [
            (14 * H, "paused_by_calendar", left), (14 * H, "down", None), (17 * H, "up", None),
            (30 * H, "resume_process", left), (end, "end_process", None)]
        assert t == expect  # calendar first (ONE interruption), then the failure finds nothing to interrupt
        assert sum(1 for x in trace(r) if x[1] == "down" and 14 * H <= x[0] <= end) == 1 and conserved(r)
        logs.append(r.records[0].events)
    assert all(x == logs[0] for x in logs)


# --------------------------------------------------------------------------------- D: repair during off-shift
def test_D_repair_off_shift_does_not_produce_nor_request():
    # FINISH_CURRENT: the 13:56 operation ends at 14:03; the next unit asks for the (still on-shift) operator; failure 15:00,
    # repaired 17:00 while the machine is off -> no grant, no start until 06:00
    m = station(cal("mach"), {"op": cal("opc", "06:00", "22:00")}, policy="FINISH_CURRENT", failures=FAIL(15 * H, 2 * H))
    r = run(m)
    t = trace(r)
    assert (15 * H, "down", None) in t and (17 * H, "up", None) in t
    assert not [x for x in t if x[1] == "start_process" and 14 * H + 180 < x[0] < 30 * H]
    assert not decisions(r, "assembly", 14 * H + 180, 30 * H)  # no operator granted to the off-shift machine
    assert [d["t"] for d in decisions(r, "assembly", 30 * H - 1, 30 * H + 1)] == [30 * H]  # normal again at 06:00


def test_E_machine_still_down_when_shift_starts():
    m = station(cal("mach"), {}, policy="PAUSE_RESUME", pt=60, failures=FAIL(5 * H, 2 * H), horizon=10)
    r = run(m)
    ends = [x[0] for x in trace(r) if x[1] == "end_process"]
    assert min(ends) == 7 * H + 60  # failed 05:00, shift 06:00, repaired 07:00: nothing produced 06:00-07:00
    st = r.records[0].node_state_time["assembly"]
    assert st["down"] == pytest.approx(1 * H) and st["off_shift"] == pytest.approx(6 * H)  # 05-06 is off-shift, not down


# ---------------------------------------------------------------------------------- remaining-work audit
def test_remaining_never_consumed_while_down_paused_or_waiting():
    # op starts 13:56 (420 s); failure 13:58 (120 s done, 300 left); repaired 14:58 while the calendar went off at 14:00
    # -> paused with 300 s; a second failure 04:56-05:56 happens off-shift; 06:00 resumes with exactly 300 s
    m = station(cal("mach"), {"op": cal("opc", "06:00", "22:00")}, failures=FAIL(13 * H + 58 * 60, H))
    r = run(m)
    t = [x for x in trace(r) if 13 * H + 55 * 60 < x[0] <= 30 * H + 300 and x[1] != "start_process"]
    assert t == [(13 * H + 56 * 60, "end_process", None), (13 * H + 58 * 60, "down", None), (14 * H + 58 * 60, "up", None),
                 (14 * H + 58 * 60, "paused_by_calendar", 300.0), (28 * H + 56 * 60, "down", None), (29 * H + 56 * 60, "up", None),
                 (30 * H, "resume_process", 300.0), (30 * H + 300, "end_process", None)]  # DOWN and off-shift time never consumed


def test_calendar_during_preemption_reacquire_no_double_interrupt():
    """Regression (bug fixed in this closure): a task suspended by WIP_TARGET pre-emption, waiting to re-acquire its
    operator, received a calendar interrupt outside its handler and the run crashed."""
    from .test_benchmark_elements import shared_operator_line
    d = shared_operator_line("wip_target", target=2, preempt_below=1, review_s=60).model_dump(mode="json")
    d["availability"] = {"mode": "relative_week",
                         "calendars": [{"id": "rev", "weekly": {x: [{"start": "00:00", "end": "24:00"}] for x in DAYS},
                                        "breaks": [{"start": "00:01:46", "end": "00:02:46"}]}],
                         "nodes": {"review": "rev"}, "always_available": ["op", "assembly", "machine"],
                         "operations": {"review": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}}
    r = run(model_from_dict(d))
    t = trace(r, "review")
    assert t[:4] == [(60.0, "start_process", None), (105.0, "preempted", 15.0),  # suspended, re-requests its operator
                     (166.0, "resume_process", None), (181.0, "end_process", None)]  # granted only after the break: 166 + 15
    assert not decisions(r, "review", 105.0, 166.0) and conserved(r)  # nothing granted to review during its break


# ---------------------------------------------------------------------------- F/G: overnight + holiday scope
def _dated(exc_scope):
    night = {"id": "night", "weekly": {d: [{"start": "22:00", "end": "06:00"}] for d in ("mon", "tue")},
             "exceptions": [{"date": "2026-10-06", "type": "NON_WORKING_DAY", "reason": "festivo", "scope": exc_scope}]}
    spec = AvailabilitySpec.model_validate({"mode": "dated", "start_date": "2026-10-05", "timezone": "UTC", "calendars": [night]})
    return expand(spec, spec.calendars[0], 4 * 24 * H).available


def test_F_overnight_shift_cut_by_calendar_day_holiday():
    # Monday 22:00 shift is cut at Tuesday 00:00; Tuesday's own night shift (starts on the holiday) is removed entirely
    assert _dated("CALENDAR_DAY") == [(22 * H, 24 * H)]


def test_G_calendar_day_vs_shifts_starting_on_date():
    # SHIFTS_STARTING_ON_DATE: Monday's night shift (started the day before the holiday) is kept whole; Tuesday's removed
    assert _dated("SHIFTS_STARTING_ON_DATE") == [(22 * H, 30 * H)]
    assert measure(_dated("CALENDAR_DAY")) == 2 * H and measure(_dated("SHIFTS_STARTING_ON_DATE")) == 8 * H


# --------------------------------------------------------------------------------------------- H: spring DST
def test_H_spring_dst_night_shift_is_7_real_hours():
    night = cal("night", "22:00", "06:00", days=["sat"])
    spec = AvailabilitySpec.model_validate({"mode": "dated", "start_date": "2026-03-28", "timezone": "Europe/Madrid",
                                           "calendars": [night]})
    tl = expand(spec, spec.calendars[0], 2 * 24 * H)
    assert tl.available == [(22 * H, 29 * H)]  # 22:00 Sat -> 06:00 Sun = 7 h elapsed (02:00 -> 03:00 does not exist)
    assert all(b > a for a, b, _ in tl.segments)  # no negative / empty segments
    m = model_from_dict({**load_model(EXAMPLES / "01_simple_line.yaml").model_dump(mode="json")})
    gap = {"id": "gap", "weekly": {"sun": [{"start": "02:30", "end": "06:00"}]}}
    data = m.model_dump(mode="json")
    data["simulation"]["horizon"] = {"value": 48, "unit": "h"}
    data["availability"] = {"mode": "dated", "start_date": "2026-03-28", "timezone": "Europe/Madrid", "calendars": [gap],
                            "nodes": {n["id"]: "gap" for n in data["nodes"] if n["component"] == "machine"},
                            "operations": {n["id"]: {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}
                                           for n in data["nodes"] if n["component"] == "machine"}}
    rep, _ = verify_model(model_from_dict(data), REG)
    w = [i for i in rep.warnings if i.code == "CAL_DST_BOUNDARY"]
    assert w and "02:30" in w[0].message and "2026-03-29" in w[0].message  # never resolved silently


# ------------------------------------------------------------------------------- I: STOP_RESTART same sample
def test_I_stop_restart_reuses_the_original_random_sample():
    src = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 13 * H + 58 * 60}, "max_entities": 2}

    def build(policy):
        d = station(cal("mach"), {"op": cal("opc")}, policy=policy, horizon=60).model_dump(mode="json")
        d["nodes"][0]["params"] = src  # arrivals 13:58 day 1 and 03:56 day 2 (waits for the 06:00 shift)
        d["nodes"][1]["params"]["process_time"] = {"dist": "uniform", "low": 250, "high": 350}
        return model_from_dict(d)
    fin, stop = run(build("FINISH_CURRENT")), run(build("STOP_RESTART"))

    def durations(r):
        ev = [x for x in trace(r) if x[1] in ("start_process", "end_process", "resume_process")]
        return ev
    f, s = durations(fin), durations(stop)
    d1 = f[1][0] - f[0][0]  # first unit's sampled duration (FINISH_CURRENT runs it uninterrupted)
    resume, end1 = [x for x in s if x[1] == "resume_process"][0], [x for x in s if x[1] == "end_process"][0]
    assert resume[2] == pytest.approx(d1, abs=1e-3) and end1[0] - resume[0] == pytest.approx(d1)  # restart = same duration
    d2_fin = f[3][0] - f[2][0]
    s_after = [x for x in s if x[0] >= end1[0] and x[1] != "end_process" or x[0] > end1[0]]
    d2_stop = s_after[1][0] - s_after[0][0]  # second unit: start (= end of the first) -> end
    assert d2_stop == pytest.approx(d2_fin)  # the second unit got the SAME draw: no extra sample was consumed


# ------------------------------------------------------------------------------------ J: source clock
def test_J_source_interarrival_clock_counts_only_available_time():
    # interarrival 30 min, source available 06:00-13:40: arrivals 06:30 ... 13:30; the 10 min left until 13:40 are
    # consumed, the clock pauses off-shift, and the remaining 20 min run from 06:00 -> next arrival 06:20
    d = station(cal("mach", "00:00", "24:00"), {"op": cal("opc", "00:00", "24:00")}, pt=60, horizon=36).model_dump(mode="json")
    d["nodes"][0]["params"] = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 30 * 60}}
    d["availability"]["calendars"].append(cal("srcc", "06:00", "13:40"))
    d["availability"]["nodes"]["src"] = "srcc"
    r = run(model_from_dict(d))
    created = [e["t"] for e in r.records[0].events if e["event"] == "created"]
    assert created[:15] == [6 * H + k * 1800 for k in range(1, 16)]  # 06:30 ... 13:30
    assert created[15] == 30 * H + 20 * 60  # next day 06:20, not 14:00 nor 06:30


# ---------------------------------------------------------------------- K: persistence, hash, approval, history
def test_K_availability_survives_save_load_approve_run_and_versions(tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("k")
    m = station(cal("mach"), {"op": cal("opc")}, pt=60, horizon=24)
    v1 = sf.save_model(p, m, "with calendars")
    loaded = p.load_version(v1)
    assert loaded.availability == m.availability and loaded.content_hash() == m.content_hash()
    v2 = sf.approve_model(p, by="ana")
    approved = p.current_model()
    assert approved.is_approved and approved.availability == m.availability
    r_old = sf.run_simulation(p)
    assert r_old.model_hash == approved.content_hash() and r_old.availability_hash == m.availability.calendar_hash()
    changed = set_value(approved, "availability.calendars.0.weekly.mon.0.end", "13:00")
    v3 = sf.save_model(p, changed, "machine shift shortened")
    cur = p.current_model()
    assert not cur.is_approved and cur.content_hash() != approved.content_hash()
    assert any("availability.calendars" in c[0] for c in sf.compare_versions(p, v2, v3))
    r_new = sf.run_simulation(p)
    assert r_new.kpis.mean("units_completed") == 420 and r_old.kpis.mean("units_completed") == 480
    again = run_simulation(p.load_version(v2), REG)  # the old approved version, recomputed without cache
    assert again.kpis.mean("units_completed") == 480 and again.availability_hash == r_old.availability_hash
    # rebuilding from the stored description (answer_questions path) never drops the calendars
    assert p.load_version(v3).availability is not None


def test_K_rebuild_from_description_keeps_calendars(tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("rebuild")
    text = ("Fuente infinita. Un operario monta una pieza. Después hay un buffer con capacidad 5. Una máquina procesa cada "
            "pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza durante 20 segundos. Simular 8 horas.")
    sf.parse_process(p, text)
    m = p.current_model()
    data = m.model_dump(mode="json")
    data["availability"] = {"mode": "relative_week", "calendars": [cal("t")], "resources": {"operator_1": "t"}}
    sf.save_model(p, model_from_dict(data), "calendars added by the engineer")
    pr = sf.answer_questions(p, {"param:manual_assembly_time": 60})
    rebuilt = p.load_version(pr.version)
    assert rebuilt.availability is not None and rebuilt.availability.resources == {"operator_1": "t"}
    assert any(h["action"] == "availability_carried_over" for h in p.history())


# ------------------------------------------------------------------------------ preventive (real-data precheck)
def test_pause_resume_with_breakdown_during_the_pause_resumes_only_after_repair():
    # 13:58 start (300 s) -> 14:00 shift end: PAUSE with 180 s left -> 17:00 failure (off-shift) -> 06:00 calendar back
    # but machine still DOWN -> 07:00 repair -> only then the operator is re-requested and the work resumes
    m = station(cal("mach"), {"op": cal("opc")}, policy="PAUSE_RESUME", pt=300, failures=FAIL(17 * H, 14 * H), horizon=40)
    d = m.model_dump(mode="json")
    d["nodes"][0]["params"] = {"arrival": "interarrival", "interarrival": {"dist": "constant", "value": 13 * H + 58 * 60},
                               "max_entities": 1}
    r = run(model_from_dict(d))
    assert trace(r) == [(13 * H + 58 * 60, "start_process", None), (14 * H, "paused_by_calendar", 180.0), (17 * H, "down", None),
                        (31 * H, "up", None), (31 * H, "resume_process", 180.0), (31 * H + 180, "end_process", None)]
    assert [d_["t"] for d_ in r.records[0].decisions] == [13 * H + 58 * 60, 31 * H]  # no re-acquire at 06:00
    st = r.records[0].resource_state_time["op"]
    assert st["working:assembly"] == pytest.approx(300)  # 120 s + 180 s: remaining conserved exactly
    assert conserved(r)


def test_old_fifo_request_of_off_shift_node_does_not_block_available_nodes():
    # 'assembly' (machine 06-14) asks for the 24/7 operator at 13:59 while it is busy; from 14:00 its request stays pending
    # (node off-shift) and the operator keeps serving 'rework' (later requests); at 06:00 assembly is served first (its
    # genuine FIFO seniority), without any priority for having waited
    m = station(cal("mach"), {"op": cal("opc", "00:00", "24:00")}, policy="PAUSE_RESUME",
                rework_source={})  # infinite rework demand
    d = m.model_dump(mode="json")
    r = run(model_from_dict(d))
    grants_off = [x for x in r.records[0].decisions if 14 * H <= x["t"] < 30 * H]
    assert grants_off and all(x["chosen_node"] == "rework" for x in grants_off)
    waiting_assembly = [x for x in grants_off if "assembly" in [c["node"] for c in x["candidates"]]]
    assert waiting_assembly, "the old assembly request was pending while rework kept being served"
    first6 = [x for x in r.records[0].decisions if x["t"] >= 30 * H][0]
    assert first6["chosen_node"] == "assembly" and first6["rule"] == "fifo"
