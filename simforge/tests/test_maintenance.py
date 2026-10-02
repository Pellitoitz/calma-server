"""Engine 0.8.0: maintenance & reliability. Expected values are derived by hand from the contracts written in
docs/maintenance_and_reliability.md (never copied from an engine run)."""

from __future__ import annotations

import pytest

from simforge.domain.io import load_model, model_from_dict, save_model
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.semantics import verify_model

from .conftest import EXAMPLES

REG = ComponentRegistry.load_default(None)
H = 3600.0
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def C(v):
    return {"dist": "constant", "value": v, "unit": "s"}


def line(maint, proc=10, horizon=115, src=None, nodes_extra=(), edges_extra=(), resources=(), availability=None,
         production=None, machine_params=None, entities=None):
    mp = {"process_time": C(proc)} if proc is not None else {}
    mp.update(machine_params or {})
    d = {"meta": {"name": "maint"}, "simulation": {"horizon": {"value": horizon, "unit": "s"}},
         "resources": list(resources),
         "nodes": [{"id": "src", "component": "source", **({"params": src} if src else {})},
                   {"id": "m", "component": "machine", "params": mp}, {"id": "out", "component": "sink"}, *nodes_extra],
         "edges": [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}, *edges_extra],
         "maintenance": {"nodes": {"m": maint}}}
    if availability:
        d["availability"] = availability
    if production:
        d["production"] = production
    if entities:
        d["entities"] = entities
    return model_from_dict(d)


def failure(clock="ELAPSED_TIME", ttf=25, repair=10, exposure=None, resources=None, **kw):
    f = {"clock": clock, "time_to_failure": C(ttf), "repair_time": C(repair), "repair_age_effect": "RESET", **kw}
    if exposure is not None:
        f["exposure"] = exposure
    if resources:
        f["repair_resources"] = [{"resource": r} for r in resources]
    return f


def pm(pid="pm1", due=25, duration=10, every=None, effect="NO_RESET", resources=None, usage=None, **kw):
    t = {"id": pid, "duration": C(duration), "start_policy": "AFTER_CURRENT_ACTIVITY", "failure_age_effect": effect, **kw}
    if usage is not None:
        t.update(trigger="USAGE_BASED", usage_states=usage[0], usage_threshold=C(usage[1]))
    else:
        t.update(trigger="CALENDAR_BASED", first_due=C(due))
        if every is not None:
            t["every"] = C(every)
    if resources:
        t["resources"] = [{"resource": r} for r in resources]
    return t


def run(m, seed=None):
    rep, cm = verify_model(m, REG)
    assert cm is not None, [str(i) for i in rep.errors]
    return run_simulation(m, REG, trace=True, keep_records=True, **({"base_seed": seed} if seed else {}))


def codes(m):
    return {i.code for i in verify_model(m, REG)[0].errors}


def ev(r, *names, node="m"):
    return [(e["t"], e["event"]) for e in r.records[0].events if e["node"] == node and e["event"] in names]


def done(r):
    return [d for _, _, d in r.records[0].completions]


def rows(r, kind):
    return [x for x in r.records[0].maintenance if x["type"] == kind]


def cal(cid, a="06:00", b="14:00"):
    return {"id": cid, "weekly": {d: [{"start": a, "end": b}] for d in DAYS}}


SHIFT = {"mode": "relative_week", "calendars": [cal("mach")], "nodes": {"m": "mach"}, "always_available": ["src"],
         "operations": {"m": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}}
TECH = [{"id": "tech", "kind": "operator", "quantity": 1}]


def other_station(busy_s, arrive=None):
    """'o' holds tech for busy_s from its arrival (src2 interarrival `arrive`, or t=0 with an infinite source)."""
    src2 = {"max_entities": 1} if arrive is None else {"arrival": "interarrival", "interarrival": C(arrive), "max_entities": 1}
    return ([{"id": "src2", "component": "source", "params": src2},
             {"id": "o", "component": "manual_assembly", "params": {"process_time": C(busy_s), "resources": [{"resource": "tech"}]}},
             {"id": "out2", "component": "sink"}],
            [{"source": "src2", "target": "o"}, {"source": "o", "target": "out2"}])


# ------------------------------------------------------------------------------------- 44: ELAPSED_TIME
def test_44_elapsed_failure_manual_sequence():
    # contract: clock from t=0, age = all time except DOWN/PM, RESET at repair end. 10 s parts, TTF 25, repair 10:
    # parts 0-10, 10-20, 20-25|fail 25|down 25-35|35-40; next failure 35+25=60 = end of part 50-60 (completes);
    # down 60-70; parts 70-80, 80-90, 90-95|fail 95|down 95-105|105-110
    r = run(line({"failure": failure()}))
    assert done(r) == [10, 20, 40, 50, 60, 80, 90, 110]
    assert [(x["t_fail"], x["t_repair_start"], x["t_repair_end"]) for x in rows(r, "failure")] == [(25, 25, 35), (60, 60, 70), (95, 95, 105)]
    k = r.kpis
    assert k.mean("node.m.failure_count") == 3 and k.mean("node.m.corrective_downtime_h") * H == pytest.approx(30)
    assert k.mean("node.m.observed_mean_active_repair_s") == 10 and k.mean("node.m.reliability_availability") == pytest.approx(85 / 115)
    assert k.mean("node.m.failure_exposure_h") * H == pytest.approx(85) and k.mean("node.m.observed_mtbf_exposure_h") * H == pytest.approx(85 / 3)


def test_44b_new_elapsed_without_pm_reproduces_legacy_timing_for_constant_times():
    legacy = model_from_dict({"meta": {"name": "l"}, "simulation": {"horizon": {"value": 115, "unit": "s"}},
                              "nodes": [{"id": "src", "component": "source"},
                                        {"id": "m", "component": "machine", "params": {"process_time": C(10),
                                         "failures": {"mtbf": C(25), "mttr": C(10)}}}, {"id": "out", "component": "sink"}],
                              "edges": [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}]})
    assert done(run(legacy)) == done(run(line({"failure": failure()})))


# ------------------------------------------------------------------------------------- 45: OPERATING_TIME
def test_45_operating_time_counts_exposure_not_wall_clock():
    # 20 s of processing 13:59:40-14:00, off-shift, next part from 06:00: failure at 06:00:10 (30 s of exposure)
    m = line({"failure": failure("OPERATING_TIME", 30, 10, exposure=["PROCESSING"])}, proc=20, horizon=31 * H,
             src={"arrival": "interarrival", "interarrival": C(50380), "max_entities": 2}, availability=SHIFT)
    r = run(m)
    f = rows(r, "failure")
    assert [(x["t_fail"], x["age_s"]) for x in f] == [(30 * H + 10, 30)]
    assert f[0]["interrupted"] == [{"slot": 0, "activity": "process", "remaining_s": 10}]
    assert done(r) == [14 * H, 30 * H + 30]  # resumed after the 10 s repair with the 10 s left


# ------------------------------------------------------------------------------------- 46: idle does not age
PROD_AB = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
           "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}},
           "processing": {"m": {"a": C(10), "b": C(20)}}}
AB = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]


def test_46_idle_hour_does_not_age_the_machine():
    m = line({"failure": failure("OPERATING_TIME", 30, 10, exposure=["PROCESSING"])}, proc=None, horizon=3 * H,
             src={"arrival": "interarrival", "interarrival": C(3600)}, production=PROD_AB, entities=AB)
    r = run(m)
    assert [(x["t_fail"], x["age_s"]) for x in rows(r, "failure")] == [(7220, 30)]  # 10 s, 1 h idle, 20 s
    assert done(r) == [3610, 7220]


# ------------------------------------------------------------------------------------- 47: setup exposure
def setup_model(exposure):
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"], "repeat": True}},
            "processing": {"m": {"a": C(10), "b": C(10)}},
            "setups": {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(20)}, "B": {"A": C(20)}}}}}
    return line({"failure": failure("OPERATING_TIME", 25, 5, exposure=exposure)}, proc=None, horizon=74, production=prod, entities=AB)


def test_47_setup_exposure_changes_the_failure_exactly_by_contract():
    # PROCESSING: a 0-10 (10), setup 10-30, b 30-40 (20), setup 40-60, a 60-65 -> fails at 65 (age 25)
    p = rows(run(setup_model(["PROCESSING"])), "failure")
    assert [(x["t_fail"], x["interrupted"][0]["activity"]) for x in p] == [(65, "process")]
    # PROCESSING + SETUP: a 0-10 (10), setup 10-25 -> fails at 25 during the setup (5 s left)
    r = run(setup_model(["PROCESSING", "SETUP"]))
    ps = rows(r, "failure")
    assert [(x["t_fail"], x["interrupted"]) for x in ps][0] == (25, [{"slot": 0, "activity": "setup", "remaining_s": 5}])
    s = r.records[0].setups[0]
    assert (s["from"], s["to"], s["end"]) == ("A", "B", 35)  # repair 25-30, setup resumes 30-35: state changes at 35


# ------------------------------------------------------------------------------------- 48/49: technicians
def test_48_waiting_for_technician_is_not_repair_time():
    nx, ex = other_station(25)  # tech busy 0-25 on 'o'
    m = line({"failure": failure(ttf=5, repair=10, resources=["tech"])}, proc=100, horizon=39, nodes_extra=nx, edges_extra=ex,
             resources=TECH)
    r = run(m)
    f = rows(r, "failure")[0]
    assert (f["t_fail"], f["t_repair_start"], f["t_repair_end"]) == (5, 25, 35)
    k = r.kpis
    assert k.mean("node.m.waiting_for_repair_resource_h") * H == pytest.approx(20)
    assert k.mean("node.m.active_repair_time_h") * H == pytest.approx(10)
    assert k.mean("node.m.corrective_downtime_h") * H == pytest.approx(30)
    assert k.mean("node.m.observed_mean_active_repair_s") == 10 and k.mean("node.m.observed_mean_corrective_downtime_s") == 30


def test_49_shared_technician_fifo_one_repair_at_a_time():
    d = {"meta": {"name": "two"}, "simulation": {"horizon": {"value": 46, "unit": "s"}}, "resources": TECH,
         "nodes": [{"id": "s1", "component": "source"}, {"id": "ma", "component": "machine", "params": {"process_time": C(1000)}},
                   {"id": "o1", "component": "sink"}, {"id": "s2", "component": "source"},
                   {"id": "mb", "component": "machine", "params": {"process_time": C(1000)}}, {"id": "o2", "component": "sink"}],
         "edges": [{"source": "s1", "target": "ma"}, {"source": "ma", "target": "o1"}, {"source": "s2", "target": "mb"},
                   {"source": "mb", "target": "o2"}],
         "maintenance": {"nodes": {"ma": {"failure": failure(ttf=5, repair=10, resources=["tech"])},
                                   "mb": {"failure": failure(ttf=6, repair=10, resources=["tech"])}}}}
    runs = [run(model_from_dict(d)) for _ in range(3)]
    assert all(x.records[0].events == runs[0].records[0].events for x in runs)
    got = sorted((x["node"], x["t_fail"], x["t_repair_start"], x.get("t_repair_end")) for x in runs[0].records[0].maintenance)
    # A 5 -> 5-15; B 6 waits -> 15-25; A 15+5=20 waits -> 25-35; B 25+6=31 waits -> 35-45; A 35+5=40 waits -> 45-
    assert got == [("ma", 5, 5, 15), ("ma", 20, 25, 35), ("ma", 40, 45, None), ("mb", 6, 15, 25), ("mb", 31, 35, 45)]


# ------------------------------------------------------------------------------------- 50-53: preventive
def test_50_pm_after_current_activity():
    r = run(line({"preventive": [pm(due=25, duration=10)]}, proc=15, horizon=71))
    assert ev(r, "pm_due", "pm_start", "pm_end") == [(25, "pm_due"), (30, "pm_start"), (40, "pm_end")]
    assert [t for t, _ in ev(r, "start_process")] == [0, 15, 40, 55, 70]
    assert done(r) == [15, 30, 55, 70]


def test_51_pm_waits_for_technician_and_blocks_new_work():
    nx, ex = other_station(50)
    r = run(line({"preventive": [pm(due=25, duration=10, resources=["tech"])]}, proc=15, horizon=75,
                 nodes_extra=nx, edges_extra=ex, resources=TECH))
    assert ev(r, "pm_due", "pm_start", "pm_end") == [(25, "pm_due"), (50, "pm_start"), (60, "pm_end")]
    assert [t for t, _ in ev(r, "start_process")] == [0, 15, 60, 75]  # nothing starts 30-60 (reserved for the PM); 75 = horizon, included
    assert r.kpis.mean("node.m.waiting_for_pm_h") * H == pytest.approx(20)


def test_52_pm_due_while_down_waits_for_the_repair():
    # idle machine: failure 5, repair 5-25, PM due 10 (pending), PM 25-35, first part arrives 30, starts 35
    r = run(line({"failure": failure(ttf=5, repair=20), "preventive": [pm(due=10, duration=10, effect="RESET")]}, proc=10,
                 horizon=39, src={"arrival": "interarrival", "interarrival": C(30)}))
    assert ev(r, "failure", "repair_end", "pm_due", "pm_start", "pm_end") == [
        (5, "failure"), (10, "pm_due"), (25, "repair_end"), (25, "pm_start"), (35, "pm_end")]
    assert [t for t, _ in ev(r, "start_process")] == [35]
    # interrupted part: failure 7 (3 s left), repair 7-27, the part resumes 27-30 (activity in progress), PM 30-40
    r = run(line({"failure": failure(ttf=7, repair=20), "preventive": [pm(due=10, duration=10, effect="RESET")]}, proc=10, horizon=46))
    assert ev(r, "pm_start", "pm_end") == [(30, "pm_start"), (40, "pm_end")] and done(r)[0] == 30
    assert [t for t, _ in ev(r, "start_process")] == [0, 40]


def test_53_pm_during_setup_keeps_setup_state():
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}},
            "processing": {"m": {"a": C(10), "b": C(10)}},
            "setups": {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(20)}}}}}
    r = run(line({"preventive": [pm(due=20, duration=10)]}, proc=None, horizon=60, production=prod, entities=AB))
    rec = r.records[0]
    assert [(s["from"], s["to"], s["start"], s["end"]) for s in rec.setups] == [("A", "B", 10, 30)]
    pms = [e for e in rec.events if e["event"] in ("pm_start", "pm_end")]
    assert [(e["t"], e["setup_state"]) for e in pms] == [(30, "B"), (40, "B")]
    assert done(r) == [10, 50]


def test_53b_usage_based_pm_and_failure_never_during_active_pm():
    r = run(line({"preventive": [pm(usage=(["PROCESSING"], 25), duration=5)]}, proc=10, horizon=70))
    # usage 25 reached at 25 (part 20-30) -> PM 30-35; usage restarts at 35: 25 more at 35+25=60 (part 55-65) -> PM 65-70
    assert ev(r, "pm_due", "pm_start") == [(25, "pm_due"), (30, "pm_start"), (60, "pm_due"), (65, "pm_start")]
    # ELAPSED clock paused during active PM: TTF 30, idle machine, PM 10-60 -> failure at 80, never during the PM
    r = run(line({"failure": failure(ttf=30, repair=5), "preventive": [pm(due=10, duration=50)]}, horizon=100,
                 src={"arrival": "interarrival", "interarrival": C(1000)}))
    assert [x["t_fail"] for x in rows(r, "failure")] == [80]


# ------------------------------------------------------------------------------------- 54: calendars
def test_54_repair_ends_off_shift_machine_repaired_but_not_productive():
    # parts from 06:00 every 10 s; failure 13:55:05 (5 s left), repair 1 h -> up 14:55:05 (off-shift): no work until 06:00
    m = line({"failure": failure(ttf=50105, repair=3600)}, proc=10, horizon=31 * H, availability=SHIFT)
    r = run(m)
    f = rows(r, "failure")
    assert (f[0]["t_fail"], f[0]["t_repair_end"]) == (50105, 53705)
    assert f[1]["t_fail"] == 53705 + 50105  # the ELAPSED clock also ran off-shift
    assert not [t for t, _ in ev(r, "start_process", "end_process") if 53705 <= t < 30 * H]
    assert min(d for d in done(r) if d > 14 * H) == 30 * H + 5


def test_54b_shift_start_while_still_down():
    m = line({"failure": failure(ttf=5 * H, repair=2 * H)}, proc=10, horizon=8 * H, availability=SHIFT)
    r = run(m)
    assert [t for t, _ in ev(r, "start_process")][0] == 7 * H  # not 06:00: still under repair


# ------------------------------------------------------------------------------------- 55: same instant
def repeat3(m):
    rs = [run(m) for _ in range(3)]
    assert all(x.records[0].events == rs[0].records[0].events for x in rs)
    return rs[0]


def test_55_same_instant_cases_are_deterministic():
    # A) failure exactly at SHIFT_END (part ends at 14:00 too): calendar first, the part completes, the failure finds no work
    r = repeat3(line({"failure": failure(ttf=50400, repair=60)}, proc=10, horizon=15 * H, availability=SHIFT))
    f = rows(r, "failure")[0]
    assert f["t_fail"] == 14 * H and f["interrupted"] == [] and 14 * H in done(r)
    # B) repair end exactly at SHIFT_START: the interrupted part continues once, at 06:00
    r = repeat3(line({"failure": failure(ttf=50105, repair=108000 - 50105)}, proc=10, horizon=30 * H + 20, availability=SHIFT))
    assert rows(r, "failure")[0]["t_repair_end"] == 30 * H and 30 * H + 5 in done(r)
    assert len([t for t, n in ev(r, "end_process") if 50105 <= t <= 30 * H + 5]) == 1  # the interrupted part ends once
    # C) PM due exactly at the end of a part: the part completes, the PM goes before the next part
    r = repeat3(line({"preventive": [pm(due=20, duration=5)]}, proc=10, horizon=40))
    assert ev(r, "pm_start", "pm_end") == [(20, "pm_start"), (25, "pm_end")] and [t for t, _ in ev(r, "start_process")][2] == 25
    # D) PM due exactly at SHIFT_END: pending, starts with the next shift, before production
    r = repeat3(line({"preventive": [pm(due=50400, duration=60, at_unavailability="FINISH_CURRENT")]}, proc=10,
                     horizon=30 * H + 120, availability=SHIFT))
    assert ev(r, "pm_start", "pm_end") == [(30 * H, "pm_start"), (30 * H + 60, "pm_end")]
    assert [t for t, _ in ev(r, "start_process") if t >= 14 * H][0] == 30 * H + 60
    # E) failure exactly at SETUP_END: the setup completes (state B), then the machine is down
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}},
            "processing": {"m": {"a": C(10), "b": C(10)}},
            "setups": {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "matrix": {"A": {"B": C(20)}}}}}
    r = repeat3(line({"failure": failure(ttf=30, repair=5)}, proc=None, horizon=50, production=prod, entities=AB))
    s = r.records[0].setups[0]
    assert (s["end"], s["to"]) == (30, "B") and rows(r, "failure")[0]["t_fail"] == 30 and done(r) == [10, 45]
    # F) failure and PM due at the same instant: the PM waits for the repair and for the interrupted part
    r = repeat3(line({"failure": failure(ttf=25, repair=10), "preventive": [pm(due=25, duration=5)]}, proc=10, horizon=60))
    assert ev(r, "failure", "pm_due", "repair_end", "pm_start") == [(25, "pm_due"), (25, "failure"), (35, "repair_end"), (40, "pm_start")]


# ------------------------------------------------------------------------------------- 56: RESET vs NO_RESET
def test_56_pm_reset_vs_no_reset():
    def model(effect):
        return line({"failure": failure("OPERATING_TIME", 40, 5, exposure=["PROCESSING"]),
                     "preventive": [pm(due=25, duration=5, effect=effect)]}, proc=10, horizon=80)
    # age 30 at the PM (30-35). RESET: 40 more -> 75. NO_RESET: 10 more -> 45
    assert [(x["t_fail"], x["age_s"]) for x in rows(run(model("RESET")), "failure")] == [(75, 40)]
    r = run(model("NO_RESET"))
    assert [x["t_fail"] for x in rows(r, "failure")] == [45]
    p = rows(r, "pm")[0]
    assert (p["age_before_s"], p["age_after_s"]) == (30, 30)


# ------------------------------------------------------------------------------------- 57: persistence
def full_model():
    prod = {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}},
            "generation": {"src": {"mode": "PROBABILISTIC_MIX", "mix": {"a": 0.5, "b": 0.5}}},
            "processing": {"m": {"a": {"dist": "uniform", "low": 50, "high": 70, "unit": "s"}, "b": C(80)}},
            "setups": {"m": {"mode": "SEQUENCE_DEPENDENT", "initial_state": "A", "at_unavailability": "PAUSE_RESUME",
                             "matrix": {"A": {"B": C(300)}, "B": {"A": C(200)}}}}}
    maint = {"failure": {**failure("OPERATING_TIME", 0, 0, exposure=["PROCESSING", "SETUP"], resources=["tech"]),
                         "time_to_failure": {"dist": "exponential", "mean": 2, "unit": "h"},
                         "repair_time": {"dist": "lognormal", "mean": 20, "std": 5, "unit": "min"}},
             "preventive": [pm(usage=(["PROCESSING"], 4 * H), duration=900, effect="RESET", resources=["tech"],
                               at_unavailability="FINISH_CURRENT")]}
    m = line(maint, proc=None, horizon=48 * H, production=prod, entities=AB, resources=TECH, availability=SHIFT)
    return m


def test_57_save_load_run_identical(tmp_path):
    m = full_model()
    save_model(m, tmp_path / "m.yaml")
    back = load_model(tmp_path / "m.yaml")
    assert back.content_hash() == m.content_hash() and back.maintenance == m.maintenance
    a, b = run(m, seed=11), run(back, seed=11)
    ra, rb = a.records[0], b.records[0]
    assert ra.events == rb.events and ra.maintenance == rb.maintenance and ra.setups == rb.setups
    assert a.per_replication == b.per_replication
    assert rows(a, "failure") and rows(a, "pm")  # the case really exercises failures and PM


@pytest.mark.parametrize("path,value", [
    ("maintenance.nodes.m.failure.clock", "ELAPSED_TIME"), ("maintenance.nodes.m.failure.time_to_failure.mean", 3),
    ("maintenance.nodes.m.failure.exposure", ["PROCESSING"]), ("maintenance.nodes.m.failure.repair_time.mean", 25),
    ("maintenance.nodes.m.failure.repair_resources", []), ("maintenance.nodes.m.preventive.0.usage_threshold.value", 7200),
    ("maintenance.nodes.m.preventive.0.duration.value", 600), ("maintenance.nodes.m.preventive.0.resources", []),
    ("maintenance.nodes.m.preventive.0.failure_age_effect", "NO_RESET"),
])
def test_hash_and_approval(path, value):
    m = full_model()
    m = m.model_copy(update={"approval": m.approval.model_copy(update={"approved": True, "model_hash": m.content_hash()})})
    changed = set_value(m, path, value)
    assert m.is_approved and changed.content_hash() != m.content_hash() and not changed.is_approved


# ------------------------------------------------------------------------------------- RNG / legacy / conservation
def test_rng_streams_are_separate():
    base = full_model()
    data = base.model_dump(mode="json")
    data.pop("maintenance")
    plain = model_from_dict(data)
    prods = lambda r: [e["product"] for e in r.records[0].events if e["event"] == "created"]  # noqa: E731
    with_m, without = run(base, seed=5), run(plain, seed=5)
    n = min(len(prods(with_m)), len(prods(without)))
    assert prods(with_m)[:n] == prods(without)[:n]  # maintenance never shifts the product mix stream
    never = set_value(base, "maintenance.nodes.m.preventive.0.usage_threshold.value", 10 ** 9)
    never = set_value(never, "maintenance.nodes.m.failure.time_to_failure", {"dist": "constant", "value": 10 ** 9, "unit": "s"})
    assert run(never, seed=5).records[0].completions == without.records[0].completions  # no shared stream at all


def test_legacy_models_untouched():
    from simforge.domain.isms import ISMSModel
    for f, units in (("01_simple_line.yaml", 59), ("03_machine_breakdowns.yaml", 1889.05), ("05_selective_soldering.yaml", 130)):
        m = load_model(EXAMPLES / f)
        assert m.content_hash() == ISMSModel.model_validate(m.model_dump(mode="json")).content_hash()
        assert "maintenance" not in m.model_dump(mode="json")
        assert run_simulation(m, REG).kpis.mean("units_completed") == units


def test_conservation_and_no_entity_effect():
    r = run(full_model(), seed=3)
    rec = r.records[0]
    for p, c in rec.created_by_product.items():
        assert c == sum(1 for e, _, _ in rec.completions if rec.entity_product[e] == p) + rec.wip_end_by_product[p]
    assert rec.invariant_checks > 0


# ------------------------------------------------------------------------------------- verifier
@pytest.mark.parametrize("maint,code", [
    ({"failure": failure("OPERATING_TIME", 30, 10)}, "MISSING"),
    ({"failure": failure("OPERATING_TIME", 30, 10, exposure=["IDLE"])}, "MAINTENANCE_EXPOSURE_UNSUPPORTED"),
    ({"failure": failure(exposure=["PROCESSING"])}, "MAINTENANCE_CONTRADICTORY"),
    ({"failure": {**failure(), "repair_age_effect": "NO_RESET"}}, "MAINTENANCE_REPAIR_NO_RESET_UNSUPPORTED"),
    ({"failure": failure(resources=["nobody"])}, "UNKNOWN_RESOURCE"),
    ({"preventive": [pm(usage=(["PROCESSING"], 0))]}, "BAD_PARAM"),
    ({"preventive": [pm(due=10, every=0)]}, "BAD_PARAM"),
    ({"preventive": [pm(duration=0)]}, "BAD_PARAM"),
    ({"preventive": [pm(), pm()]}, "MAINTENANCE_CONTRADICTORY"),
])
def test_verifier_errors(maint, code):
    assert code in codes(line(maint))


def test_verifier_structural_limits():
    assert "MAINTENANCE_MULTI_SLOT_UNSUPPORTED" in codes(line({"failure": failure()}, machine_params={"capacity": 2}))
    assert "MAINTENANCE_LEGACY_CONFLICT" in codes(line({"failure": failure()}, machine_params={"failures": {"mtbf": C(5), "mttr": C(1)}}))
    two = [{"id": "tech", "quantity": 1}, {"id": "tool", "kind": "tool", "quantity": 1}]
    assert "MAINTENANCE_MULTI_RESOURCE_UNSUPPORTED" in codes(line({"failure": failure(resources=["tech", "tool"])}, resources=two))
    # repair resource = processing operator of a machine that can fail -> circular wait possible
    assert "MAINTENANCE_RESOURCE_DEADLOCK_RISK" in codes(line({"failure": failure(resources=["tech"])}, resources=TECH,
                                                              machine_params={"resources": [{"resource": "tech"}]}))
    assert "MISSING" in codes(line({"preventive": [pm()]}, availability=SHIFT))  # PM at_unavailability on a calendared machine
    with pytest.raises(Exception):
        line({"failure": {**failure(), "clock": "WALL"}})
    with pytest.raises(Exception):
        line({"preventive": [{**pm(), "start_policy": "IMMEDIATE_INTERRUPT"}]})


# ------------------------------------------------------------------------------------- CLI
def test_cli_maintenance_show_and_run(tmp_path):
    from typer.testing import CliRunner

    from simforge.cli import app as cli
    save_model(line({"failure": failure(), "preventive": [pm(due=50, duration=5)]}), tmp_path / "m.yaml")
    out = CliRunner().invoke(cli, ["maintenance", "show", str(tmp_path / "m.yaml")])
    assert out.exit_code == 0, out.output
    assert "ELAPSED_TIME" in out.output and "pm1" in out.output
    out = CliRunner().invoke(cli, ["maintenance", "run", str(tmp_path / "m.yaml")])
    assert out.exit_code == 0, out.output
    assert "failures 3" in out.output and "timeline" in out.output.lower()


def test_pm_never_uses_a_break_and_repair_waits_for_an_off_shift_technician():
    brk = {"mode": "relative_week", "always_available": ["src"],
           "calendars": [{**cal("mach"), "breaks": [{"start": "10:00", "end": "10:15"}]}], "nodes": {"m": "mach"},
           "operations": {"m": {"at_unavailability": "PAUSE_RESUME", "start_rule": "START_ANY_TIME"}}}
    # PM due 10:05 (inside the break): pending, starts when the machine is available again at 10:15
    r = run(line({"preventive": [pm(due=10 * H + 300, duration=60, at_unavailability="FINISH_CURRENT")]}, proc=10,
                 horizon=11 * H, availability=brk))
    assert ev(r, "pm_start") == [(10 * H + 900, "pm_start")]
    # repair technician works 06-14; failure at 15:00 -> waits (off-shift) -> repair 06:00-06:30 next day
    av = {"mode": "relative_week", "calendars": [cal("techc")], "resources": {"tech": "techc"}}
    m = line({"failure": failure(ttf=15 * H, repair=1800, resources=["tech"], resource_unavailability_policy="FINISH_CURRENT")},
             proc=10, horizon=31 * H, resources=TECH, availability=av)
    f = rows(run(m), "failure")[0]
    assert (f["t_fail"], f["t_repair_start"], f["t_repair_end"]) == (15 * H, 30 * H, 30 * H + 1800)
    assert "MISSING" in codes(line({"failure": failure(resources=["tech"])}, resources=TECH, availability=av))


def test_ui_maintenance_tab(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    ws = tmp_path / "ws"
    sf = SimForgeApp(workspace=ws, library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("UI maint")
    sf.save_model(p, line({"failure": failure(), "preventive": [pm(due=50, duration=5)]}), "maintenance")
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(ws))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("fallo: ELAPSED_TIME" in c.value for c in at.code)
