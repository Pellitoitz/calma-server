"""Engine 0.8.0 technical closure: exact ELAPSED_TIME contract, fixed PM schedule, usage reset point, merged dues,
PM delay and its causes, failures around pending PM, shared technicians, anti-deadlock rule (cycles only), DOWN gate,
calendars, RESET / NO_RESET and RNG, metric partitions, horizon closure, same-instant cases, persistence."""

from __future__ import annotations

import pytest

from simforge.domain.io import load_model, model_from_dict, save_model
from simforge.domain.paths import set_value

from .test_maintenance import (AB, H, SHIFT, TECH, C, cal, codes, done, ev, failure, line, other_station, pm, rows, run)


def age_at_failures(r):
    return [(x["t_fail"], x["age_s"]) for x in rows(r, "failure")]


IDLE = {"arrival": "interarrival", "interarrival": C(10 ** 7)}  # no part ever arrives: the machine stays idle


# --------------------------------------------------------------------------------- 1. ELAPSED_TIME exact contract
def test_1a_off_shift_and_idle_age_under_elapsed():
    # machine idle (no parts) and off-shift most of the time: TTF 20 h -> failure exactly at 20 h
    r = run(line({"failure": failure(ttf=20 * H, repair=60)}, horizon=21 * H, src=IDLE, availability=SHIFT))
    assert age_at_failures(r) == [(20 * H, 20 * H)]


def test_1c_pm_waiting_ages_and_1d_active_pm_does_not():
    # PM due at 10 waits for tech (busy 0-50) -> PM_WAITING 10-50 ages; PM active 50-60 does not: TTF 70 -> 70 + 10 = 80
    nx_, ex = other_station(50)
    r = run(line({"failure": failure(ttf=70, repair=5), "preventive": [pm(due=10, duration=10, resources=["tech"])]},
                 horizon=90, src=IDLE, nodes_extra=nx_, edges_extra=ex, resources=TECH))
    assert ev(r, "pm_start", "pm_end") == [(50, "pm_start"), (60, "pm_end")]
    assert age_at_failures(r) == [(80, 70)]


def test_1e_down_and_repair_do_not_age():
    # failure 10, tech busy 0-30: waiting 10-30 + repair 30-40; RESET at 40 -> next failure 40 + 10 = 50 (age 10)
    nx_, ex = other_station(30)
    r = run(line({"failure": failure(ttf=10, repair=10, resources=["tech"])}, horizon=55, src=IDLE, nodes_extra=nx_,
                 edges_extra=ex, resources=TECH))
    assert age_at_failures(r) == [(10, 10), (50, 10)]


def test_2_operating_time_ignores_everything_but_declared_states():
    r = run(line({"failure": failure("OPERATING_TIME", 15, 5, exposure=["PROCESSING"]),
                  "preventive": [pm(due=12, duration=100)]}, proc=10, horizon=200,
                 src={"arrival": "interarrival", "interarrival": C(50)}))
    # PM due 12 on the idle machine -> PM 12-112 (no exposure); the part arrived at 50 waits for the PM: 112-122 (10);
    # the part arrived at 100 runs 122-127 -> exposure 15 at 127 (the PM's 100 s and the idle time never count)
    assert age_at_failures(r)[0] == (127, 15)


# --------------------------------------------------------------------------------- 3/5. CALENDAR_BASED fixed plan
def test_3_calendar_pm_delay_does_not_shift_the_plan():
    # PM every Monday 06:00 (6 h + k*168 h); machine down from 5 h until 53 h (Wednesday): PM 53-54 h; next due 174 h
    r = run(line({"failure": failure(ttf=5 * H, repair=48 * H), "preventive": [pm(due=6 * H, every=168 * H, duration=H)]},
                 horizon=175 * H, src=IDLE))
    assert [t for t, _ in ev(r, "pm_due")] == [6 * H, 174 * H]
    p = rows(r, "pm")[0]
    assert (p["due"], p["start"], p["delay_s"]) == (6 * H, 53 * H, 47 * H)


def test_5_dues_while_pending_merge_into_one_job_but_are_audited():
    # PM every 24 h from 6 h; down 1 h -> 73 h: dues 6, 30, 54 -> ONE PM at 73 h with 3 due occurrences
    r = run(line({"failure": failure(ttf=H, repair=72 * H), "preventive": [pm(due=6 * H, every=24 * H, duration=1800)]},
                 horizon=76 * H, src=IDLE))
    p = rows(r, "pm")
    assert len(p) == 1 and p[0]["due_occurrences"] == 3 and p[0]["due_times"] == [6 * H, 30 * H, 54 * H]
    assert ev(r, "pm_start") == [(73 * H, "pm_start")] and len(ev(r, "pm_due_merged")) == 2
    k = r.kpis
    assert k.mean("node.m.preventive_maintenance_count") == 1 and k.mean("node.m.pm_due_occurrences") == 3
    assert k.mean("node.m.max_pm_delay_s") == 67 * H


# --------------------------------------------------------------------------------- 4. USAGE_BASED reset point
def test_4_usage_resets_only_when_the_pm_completes():
    # usage 25 reached at 25 (part 20-30); PM waits tech busy until 45: PM 45-50. No usage while reserved (30-45).
    # usage counted from 50: parts 50-60, 60-70, 70-75 -> due at 75 (not at 55 or 70)
    nx_, ex = other_station(45)
    r = run(line({"preventive": [pm(usage=(["PROCESSING"], 25), duration=5, resources=["tech"])]}, proc=10, horizon=78,
                 nodes_extra=nx_, edges_extra=ex, resources=TECH))
    assert ev(r, "pm_due", "pm_start", "pm_end") == [(25, "pm_due"), (45, "pm_start"), (50, "pm_end"), (75, "pm_due")]


# --------------------------------------------------------------------------------- 6/7. delay and causes
def test_6_7_pm_delay_and_its_causes_are_reconstructible():
    nx_, ex = other_station(50)
    r = run(line({"preventive": [pm(due=25, duration=10, resources=["tech"])]}, proc=15, horizon=62,
                 nodes_extra=nx_, edges_extra=ex, resources=TECH))
    p = rows(r, "pm")[0]
    assert p["delay_s"] == 25  # due 25 -> start 50
    assert p["wait_causes"] == [[25, ["CURRENT_ACTIVITY"]], [30, ["WAITING_RESOURCE"]]]
    assert r.kpis.mean("node.m.mean_pm_delay_s") == 25


# --------------------------------------------------------------------------------- 8/9. failure while PM pending
def test_8_elapsed_failure_while_waiting_for_the_pm_technician():
    # age reaches TTF 40 while the machine is reserved for the PM (due 25, part ends 30, tech busy until 60):
    # PM_DUE 25 -> PM_WAITING 30 -> FAILURE 40 -> repair 40-50 (no resource) -> PM still pending -> PM at 60 -> parts
    nx_, ex = other_station(60)
    r = run(line({"failure": failure(ttf=40, repair=10), "preventive": [pm(due=25, duration=10, resources=["tech"])]},
                 proc=15, horizon=90, nodes_extra=nx_, edges_extra=ex, resources=TECH))
    assert ev(r, "pm_due", "failure", "repair_end", "pm_start", "pm_end") == [
        (25, "pm_due"), (40, "failure"), (50, "repair_end"), (60, "pm_start"), (70, "pm_end")]
    assert [t for t, _ in ev(r, "start_process")] == [0, 15, 70, 85]
    p = rows(r, "pm")[0]
    assert p["wait_causes"] == [[25, ["CURRENT_ACTIVITY"]], [30, ["WAITING_RESOURCE"]], [40, ["MACHINE_DOWN", "WAITING_RESOURCE"]],
                                [50, ["WAITING_RESOURCE"]]]


def test_9_pending_pm_survives_a_failure_and_goes_before_new_work():
    r = run(line({"failure": failure(ttf=12, repair=8), "preventive": [pm(due=11, duration=5)]}, proc=10, horizon=45))
    # PM due 11 (part 10-20 running); failure 12 (8 s left); up 20; the part finishes 20-28; PM 28-33; next part 33
    assert ev(r, "pm_start", "pm_end") == [(28, "pm_start"), (33, "pm_end")]
    assert done(r)[:2] == [10, 28] and [t for t, _ in ev(r, "start_process")][2] == 33


# --------------------------------------------------------------------------------- 10/11. technicians
def test_10_pm_grant_and_failure_same_instant_no_leak():
    # tech free at 50 (= PM grant) and failure at 50: failures precede end-of-instant grants -> grant, returned, repair
    nx_, ex = other_station(50)
    r = run(line({"failure": failure(ttf=50, repair=10, resources=["tech"]), "preventive": [pm(due=25, duration=10, resources=["tech"])]},
                 proc=15, horizon=80, nodes_extra=nx_, edges_extra=ex, resources=TECH))
    rec = r.records[0]
    f = rows(r, "failure")[0]
    assert (f["t_fail"], f["t_repair_start"], f["t_repair_end"]) == (50, 50, 60)
    assert ev(r, "pm_start", "pm_end") == [(60, "pm_start"), (70, "pm_end")]  # after the repair, never during it
    assert rec.resource_state_time["tech"].get("working:m#repair") == 10 and rec.resource_state_time["tech"]["working:m#pm"] == 10


def test_11_technician_in_pm_is_not_preempted_by_another_failure():
    d = {"meta": {"name": "two"}, "simulation": {"horizon": {"value": 60, "unit": "s"}}, "resources": TECH,
         "nodes": [{"id": "s1", "component": "source", "params": IDLE}, {"id": "ma", "component": "machine", "params": {"process_time": C(10)}},
                   {"id": "o1", "component": "sink"}, {"id": "s2", "component": "source", "params": IDLE},
                   {"id": "mb", "component": "machine", "params": {"process_time": C(10)}}, {"id": "o2", "component": "sink"}],
         "edges": [{"source": "s1", "target": "ma"}, {"source": "ma", "target": "o1"}, {"source": "s2", "target": "mb"},
                   {"source": "mb", "target": "o2"}],
         "maintenance": {"nodes": {"ma": {"preventive": [pm(due=5, duration=20, resources=["tech"])]},
                                   "mb": {"failure": failure(ttf=10, repair=10, resources=["tech"])}}}}
    r = run(model_from_dict(d))
    assert ev(r, "pm_start", "pm_end", node="ma") == [(5, "pm_start"), (25, "pm_end")]
    f = rows(r, "failure")[0]
    assert (f["t_fail"], f["t_repair_start"], f["t_repair_end"]) == (10, 25, 35)  # waits, never pre-empts the PM


# --------------------------------------------------------------------------------- 12/13. anti-deadlock
def test_12_setup_technician_that_also_repairs_the_same_machine_is_rejected():
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}},
            "processing": {"m": {"a": C(10), "b": C(10)}},
            "setups": {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(20), "resources": [{"resource": "tech"}]}}}
    assert "MAINTENANCE_RESOURCE_DEADLOCK_RISK" in codes(line({"failure": failure(resources=["tech"])}, proc=None, resources=TECH,
                                                              production=prod, entities=AB))


def test_13_safe_cases_are_not_over_restricted():
    # tech is the PROCESSING operator of machine A (which can fail, repaired by 'fitter') and the repair resource of B
    d = {"meta": {"name": "safe"}, "simulation": {"horizon": {"value": 100, "unit": "s"}},
         "resources": [{"id": "tech", "quantity": 1}, {"id": "fitter", "quantity": 1}],
         "nodes": [{"id": "s1", "component": "source"},
                   {"id": "ma", "component": "manual_assembly", "params": {"process_time": C(10), "resources": [{"resource": "tech"}]}},
                   {"id": "o1", "component": "sink"}, {"id": "s2", "component": "source"},
                   {"id": "mb", "component": "machine", "params": {"process_time": C(10)}}, {"id": "o2", "component": "sink"}],
         "edges": [{"source": "s1", "target": "ma"}, {"source": "ma", "target": "o1"}, {"source": "s2", "target": "mb"},
                   {"source": "mb", "target": "o2"}],
         "maintenance": {"nodes": {"ma": {"failure": failure(ttf=25, repair=5, resources=["fitter"])},
                                   "mb": {"failure": failure(ttf=33, repair=5, resources=["tech"])}}}}
    m = model_from_dict(d)
    assert "MAINTENANCE_RESOURCE_DEADLOCK_RISK" not in codes(m)  # tech -> fitter, nothing back to tech: no cycle
    rows_ = rows(run(m), "failure")
    assert {x["node"] for x in rows_} == {"ma", "mb"} and all("t_repair_end" in x for x in rows_ if x["t_fail"] < 80)
    # closing the cycle (A repaired by the operator B holds while down, B repaired by A's operator) is rejected
    d2 = {**d, "resources": [{"id": "tech", "quantity": 1}, {"id": "fitter", "quantity": 1}]}
    d2["nodes"] = [*d["nodes"][:4], {"id": "mb", "component": "manual_assembly",
                                     "params": {"process_time": C(10), "resources": [{"resource": "fitter"}]}}, d["nodes"][5]]
    assert "MAINTENANCE_RESOURCE_DEADLOCK_RISK" in codes(model_from_dict(d2))


# --------------------------------------------------------------------------------- 14. DOWN blocks every new activity
def test_14_request_granted_while_down_does_not_start_work():
    # part waits for op (busy on 'o' 0-30); machine fails at 20 (repair 20); op freed at 30 while DOWN: nothing starts;
    # the part starts only at 40 (repair end) and takes op then
    nx_ = [{"id": "src2", "component": "source", "params": {"max_entities": 1}},
           {"id": "o", "component": "manual_assembly", "params": {"process_time": C(30), "resources": [{"resource": "tech"}]}},
           {"id": "out2", "component": "sink"}]
    ex = [{"source": "src2", "target": "o"}, {"source": "o", "target": "out2"}]
    m = line({"failure": failure(ttf=20, repair=20)}, proc=5, horizon=50, nodes_extra=nx_, edges_extra=ex, resources=TECH,
             machine_params={"resources": [{"resource": "tech"}]})
    m = set_value(m, "nodes.src.params", {"arrival": "interarrival", "interarrival": C(1), "max_entities": 1})  # o takes tech first
    r = run(m)
    assert [t for t, _ in ev(r, "start_process")] == [40]
    tech = r.records[0].resource_state_time["tech"]
    assert tech["working:m"] == 5 and tech["working:o"] == 30  # never held by m while DOWN


# --------------------------------------------------------------------------------- 15-19. calendars
def test_15_repaired_at_02_00_is_up_but_not_productive_until_06_00():
    m = line({"failure": failure(ttf=50105, repair=26 * H - 50105)}, proc=10, horizon=31 * H, availability=SHIFT)
    r = run(m)
    assert rows(r, "failure")[0]["t_repair_end"] == 26 * H  # 02:00
    assert not [t for t, _ in ev(r, "start_process", "end_process") if 26 * H <= t < 30 * H]
    cond = r.records[0].node_condition_time["m"]
    assert cond["up"] + cond["repair"] == pytest.approx(31 * H)


def test_17_pm_started_before_shift_end_finishes_after_it():
    r = run(line({"preventive": [pm(due=13 * H + 55 * 60, duration=600, at_unavailability="FINISH_CURRENT")]}, proc=None,
                 machine_params={"process_time": C(10)}, horizon=15 * H, src=IDLE, availability=SHIFT))
    assert ev(r, "pm_start", "pm_end") == [(13 * H + 3300, "pm_start"), (14 * H + 300, "pm_end")]
    k = r.kpis
    assert k.mean("node.m.preventive_maintenance_time_h") * H == pytest.approx(600)
    assert k.mean("node.m.preventive_maintenance_time_inside_planned_h") * H == pytest.approx(300)


def test_18_19_technician_calendar_for_repair_and_pm():
    av = {"mode": "relative_week", "calendars": [cal("techc")], "resources": {"tech": "techc"}}
    pol = {"resource_unavailability_policy": "FINISH_CURRENT"}
    # repair starts 13:50, 30 min, technician shift ends 14:00: the repair finishes at 14:20
    r = run(line({"failure": failure(ttf=13 * H + 3000, repair=1800, resources=["tech"], **pol)}, horizon=15 * H, src=IDLE,
                 resources=TECH, availability=av))
    f = rows(r, "failure")[0]
    assert (f["t_repair_start"], f["t_repair_end"]) == (13 * H + 3000, 14 * H + 1200)
    # PM due 14:30 (technician off): waits to 06:00; PM due 13:55 (10 min): finishes 14:05
    r = run(line({"preventive": [pm(due=14 * H + 1800, duration=600, resources=["tech"], at_unavailability="FINISH_CURRENT")]},
                 horizon=31 * H, src=IDLE, resources=TECH, availability=av))
    assert ev(r, "pm_start") == [(30 * H, "pm_start")]
    r = run(line({"preventive": [pm(due=13 * H + 3300, duration=600, resources=["tech"], at_unavailability="FINISH_CURRENT")]},
                 horizon=15 * H, src=IDLE, resources=TECH, availability=av))
    assert ev(r, "pm_start", "pm_end") == [(13 * H + 3300, "pm_start"), (14 * H + 300, "pm_end")]


# --------------------------------------------------------------------------------- 21. RESET / NO_RESET and RNG
def test_21_no_reset_consumes_no_random_number():
    expo = {"dist": "exponential", "mean": 50, "unit": "s"}
    base = {"failure": {**failure(repair=5), "time_to_failure": expo}}
    plain = run(line(base, horizon=400, src=IDLE), seed=4)
    nores = run(line({**base, "preventive": [pm(due=20, every=60, duration=5, effect="NO_RESET")]}, horizon=400, src=IDLE), seed=4)
    reset = run(line({**base, "preventive": [pm(due=20, every=60, duration=5, effect="RESET")]}, horizon=400, src=IDLE), seed=4)
    ttf = lambda r: [x["ttf_s"] for x in rows(r, "failure")]  # noqa: E731
    n = min(len(ttf(plain)), len(ttf(nores)))
    assert n >= 3 and ttf(nores)[:n] == ttf(plain)[:n]  # same sample sequence: NO_RESET draws nothing
    # RESET at the first PM end (25) draws the next sample: the first failure of 'reset' uses plain's 2nd sample
    assert ttf(reset)[0] == ttf(plain)[1]
    p = rows(nores, "pm")[0]
    assert p["age_after_s"] == p["age_before_s"]


# --------------------------------------------------------------------------------- 22/23. metrics partition
def test_22_23_corrective_availability_and_no_double_count():
    # failure 13:55 (5 min inside planned) repaired 15:55 (2 h, 1 h 55 min off-shift)
    m = line({"failure": failure(ttf=50100, repair=2 * H)}, proc=10, horizon=24 * H, availability=SHIFT)
    r = run(m)
    k = r.kpis
    assert k.mean("node.m.corrective_downtime_h") * H == pytest.approx(2 * H)
    assert k.mean("node.m.corrective_downtime_inside_planned_h") * H == pytest.approx(300)
    planned = k.mean("node.m.planned_available_h") * H
    assert k.mean("node.m.corrective_reliability_availability") == pytest.approx((planned - 300) / planned)
    assert k.mean("node.m.reliability_availability") == k.mean("node.m.corrective_reliability_availability")
    st = r.records[0].node_state_time["m"]
    assert sum(st.values()) == pytest.approx(24 * H)  # each second once in the slot partition (0.6 invariant also checked)
    cond = r.records[0].node_condition_time["m"]
    assert sum(cond.values()) == pytest.approx(24 * H)


# --------------------------------------------------------------------------------- 24/25. horizon closure
def test_24_exposure_closes_at_the_horizon_not_at_the_last_event():
    r = run(line({"failure": failure(ttf=10 ** 6, repair=5)}, horizon=1000, src=IDLE))  # no event after t=0 at all
    assert r.kpis.mean("node.m.failure_exposure_h") * H == pytest.approx(1000)


@pytest.mark.parametrize("horizon,state,case", [(15, "down_waiting_repair_resource", "fail"), (55, "repair", "fail"),
                                                (30, "pm_waiting", "pm"), (60, "preventive_maintenance", "pm"), (95, "up", "pm")])
def test_25_horizon_inside_each_condition(horizon, state, case):
    # fail: failure 10 waits tech (busy 0-50), repair 50-60. pm: PM due 10 waits tech (busy 0-50), PM 50-70
    nx_, ex = other_station(50)
    maint = ({"failure": failure(ttf=10, repair=10, resources=["tech"])} if case == "fail"
             else {"preventive": [pm(due=10, duration=20, resources=["tech"])]})
    r = run(line(maint, horizon=horizon, src=IDLE, nodes_extra=nx_, edges_extra=ex, resources=TECH))
    cond = r.records[0].node_condition_time["m"]
    assert sum(cond.values()) == pytest.approx(horizon) and cond.get(state, 0) > 0
    for x in r.records[0].maintenance:  # nothing is completed after the horizon
        assert x.get("t_repair_end", 0) <= horizon and x.get("end", 0) <= horizon


# --------------------------------------------------------------------------------- 26. same instant
def same_kpis(a, b) -> bool:  # NaN-aware (NaN != NaN)
    return a.keys() == b.keys() and all(a[k] == b[k] or (a[k] != a[k] and b[k] != b[k]) for k in a)


def deterministic(m):
    rs = [run(m) for _ in range(3)]
    assert all(x.records[0].events == rs[0].records[0].events and same_kpis(x.per_replication[0], rs[0].per_replication[0])
               for x in rs)
    return rs[0]


def test_26_same_instant_matrix():
    # A) PM_DUE + FAILURE (25): failure first, PM after the repair and the interrupted part
    r = deterministic(line({"failure": failure(ttf=25, repair=10), "preventive": [pm(due=25, duration=5)]}, proc=10, horizon=60))
    assert ev(r, "pm_start")[0][0] == 40
    # B) PM resource grant + FAILURE (50): covered by test_10 (grant returned, repair first)
    # C) REPAIR_END + SHIFT_START
    r = deterministic(line({"failure": failure(ttf=50105, repair=108000 - 50105)}, proc=10, horizon=30 * H + 20, availability=SHIFT))
    assert 30 * H + 5 in done(r)
    # D) PM_END + SHIFT_END: PM 13:50-14:00 completes, nothing after it until 06:00
    r = deterministic(line({"preventive": [pm(due=13 * H + 3000, duration=600, at_unavailability="FINISH_CURRENT")]}, proc=10,
                           horizon=30 * H + 30, availability=SHIFT))
    assert ev(r, "pm_end") == [(14 * H, "pm_end")] and not [t for t, _ in ev(r, "start_process") if 14 * H <= t < 30 * H]
    # E) FAILURE + SETUP_END and G/H) PM_DUE + PROCESSING_END / SHIFT_END: test_maintenance.test_55 (A-F)
    # F) FAILURE + PROCESSING_END (60): the part completes, then the machine is down
    r = deterministic(line({"failure": failure()}, proc=10))
    assert 60 in done(r) and rows(r, "failure")[1]["interrupted"] in ([], [{"slot": 0, "activity": "process", "remaining_s": 0}])


# --------------------------------------------------------------------------------- 27/28. conservation, setup_state
def test_27_28_interrupted_part_exists_once_and_setup_state_survives_repair_and_pm():
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b", "b"]}},
            "processing": {"m": {"a": C(10), "b": C(10)}},
            "setups": {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(5)}}}}}
    # a 0-10, setup 10-15 (B), b 15-25 interrupted at 20 (failure, PM due 21), repair 20-30, b 30-35, PM 35-40, b 40-50
    r = run(line({"failure": failure(ttf=20, repair=10), "preventive": [pm(due=21, duration=5)]}, proc=None, horizon=60,
                 production=prod, entities=AB))
    rec = r.records[0]
    assert done(r) == [10, 35, 50] and len(rec.setups) == 1
    states = [e["setup_state"] for e in rec.events if e["event"] in ("failure", "up", "pm_start", "pm_end")]
    assert len(states) >= 4 and set(states) == {"B"}  # incl. a 2nd failure at 55 (age 5 + 15 after the PM)
    assert rec.created_by_product == {"a": 1, "b": 2} and rec.wip_end == 0


# --------------------------------------------------------------------------------- 29/30. hash, persistence
def test_29_pm_type_schedule_and_policy_fields_change_hash():
    base = line({"failure": failure(), "preventive": [pm(due=50, every=100, duration=5)]})
    variants = [line({"failure": failure(), "preventive": [pm(usage=(["PROCESSING"], 50), duration=5)]}),  # PM type
                line({"failure": failure(), "preventive": [pm(due=60, every=100, duration=5)]}),  # schedule
                line({"failure": failure(), "preventive": [pm(due=50, every=90, duration=5)]}),
                line({"failure": failure(resource_unavailability_policy="FINISH_CURRENT"), "preventive": [pm(due=50, every=100, duration=5)]}),
                line({"failure": failure(), "preventive": [pm(due=50, every=100, duration=5, at_unavailability="FINISH_CURRENT")]})]
    hashes = {base.content_hash(), *(v.content_hash() for v in variants)}
    assert len(hashes) == 1 + len(variants)
    # start_policy has a single admitted value in 0.8 (AFTER_CURRENT_ACTIVITY): any other is rejected, never ignored
    with pytest.raises(Exception):
        line({"preventive": [{**pm(), "start_policy": "IMMEDIATE_INTERRUPT"}]})


def test_30_persistence_with_delayed_pm_and_failure_interaction(tmp_path):
    from .test_maintenance import full_model
    m = set_value(full_model(), "maintenance.nodes.m.preventive.0.usage_threshold.value", 3600)
    m = set_value(m, "maintenance.nodes.m.preventive.0.failure_age_effect", "NO_RESET")  # failures really happen
    m = set_value(m, "maintenance.nodes.m.failure.time_to_failure", {"dist": "constant", "value": 3, "unit": "h"})
    save_model(m, tmp_path / "m.yaml")
    back = load_model(tmp_path / "m.yaml")
    a, b = run(m, seed=21), run(back, seed=21)
    assert back.content_hash() == m.content_hash()
    assert a.records[0].events == b.records[0].events and a.records[0].maintenance == b.records[0].maintenance
    assert same_kpis(a.per_replication[0], b.per_replication[0])
    pms = rows(a, "pm")
    assert pms and any(p.get("delay_s", 0) > 0 for p in pms) and rows(a, "failure")
