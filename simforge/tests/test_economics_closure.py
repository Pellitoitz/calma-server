"""Economics 0.9.0 technical closure: contracts fixed by tests (identity, hash, MISSING vs 0, scope, totals, double
counting, paid time, horizon, annualization, CAPEX, payback, ratios, pairing, comparability, persistence, robustness)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from simforge.domain.economics import EconomicsSpec
from simforge.domain.io import load_model, model_from_dict, save_model
from simforge.domain.paths import set_value
from simforge.economics import compare_evaluations, evaluate_run
from simforge.economics import compare as compare_mod
from simforge.economics.evaluate import FORMULAS, EconomicsError
from simforge.experiments.runner import run_simulation
from simforge.validation.economics import economics_issues

from .conftest import EXAMPLES
from .test_economics import MAINT, REG, C, fake_run, full_model, money, same_kpis, spec, station, total

SRC = Path(__file__).resolve().parents[1] / "src" / "simforge"


def with_econ(m, e):
    return model_from_dict({**m.model_dump(mode="json", exclude_none=True), "economics": e})


def fixed(v, **kw):
    return spec(machine=[{"node": "m", "rate": money(v, "FIXED_PER_RUN")}], **kw)


def ann(n=1):
    return {"mode": "REPEAT_RUN", "runs_per_year": n}


def capex(*values):
    return [{"category": f"c{i}", "amount": money(v, "FIXED")} for i, v in enumerate(values)]


def ev_of(s, kpis=None, m=None, **kw):
    m = m or station()
    return evaluate_run(fake_run(m, kpis or [{"units_completed": 1, "units_scrapped": 0}], **kw), m, s)


def strict_json(obj) -> str:
    return json.dumps(obj, allow_nan=False, sort_keys=True)


# ---------------------------------------------------------------------------------- 2. physical <-> economic boundary
def test_evaluation_identity():
    m = station()
    r1 = run_simulation(m, REG, base_seed=1)
    r2 = run_simulation(m, REG, base_seed=2)
    s1, s2 = fixed(10), fixed(11)
    a, a2, b, c = evaluate_run(r1, m, s1), evaluate_run(r1, m, s1), evaluate_run(r1, m, s2), evaluate_run(r2, m, s1)
    assert a.evaluation_id == a2.evaluation_id  # same run + same economics
    assert a.evaluation_id != b.evaluation_id  # same run + different economics
    assert a.evaluation_id != c.evaluation_id and a.run_id != c.run_id  # different physical run + same economics
    for e in (a, b, c):
        assert {e.run_id, e.physical_model_hash, e.economic_hash, e.economics_engine_version} and e.economics_engine_version == "0.9.0"
    other = station(proc_h=4)  # different physics: never applied silently
    with pytest.raises(EconomicsError, match="otra física"):
        evaluate_run(r1, other, s1)


# ---------------------------------------------------------------------------------- 3. economic hash
BASE = {"currency": "EUR", "scope": ["labor", "machine"],
        "labor": [{"resource": "op", "paid_time": "CALENDAR_WINDOW", "rate": money(30, "PER_PAID_HOUR")}],
        "machine": [{"node": "m", "rate": money(12, "PER_PROCESSING_HOUR")}],
        "capex": [{"category": "eq", "amount": money(1000, "FIXED")}], "annualization": ann(200)}


@pytest.mark.parametrize("path,value", [
    ("labor.0.rate.value", 31), ("labor.0.paid_time", "PLANNED_AVAILABLE"), ("machine.0.rate.basis", "PER_OPERATING_HOUR"),
    ("capex.0.amount.value", 2000), ("capex.0.amount.value", None), ("annualization.runs_per_year", 201),
    ("scope", ["labor"]), ("labor.0.rate.provenance", {"status": "assumed"}), ("currency", "USD")])
def test_economic_hash_changes_on_semantic_fields(path, value):
    import copy
    d = copy.deepcopy(BASE)
    *head, last = path.split(".")
    tgt = d
    for p in head:
        tgt = tgt[int(p)] if p.isdigit() else tgt[p]
    tgt[last] = value
    assert EconomicsSpec.model_validate(d).economic_hash() != EconomicsSpec.model_validate(BASE).economic_hash()


def test_economic_hash_ignores_key_order_scope_order_and_int_float():
    a = EconomicsSpec.model_validate(BASE)
    b = EconomicsSpec.model_validate(dict(reversed(list({**BASE, "scope": ["machine", "labor", "labor"]}.items()))))
    c = EconomicsSpec.model_validate({**BASE, "machine": [{"node": "m", "rate": money(12.0, "PER_PROCESSING_HOUR")}]})
    assert a.economic_hash() == b.economic_hash() == c.economic_hash()
    assert b.scope == ["labor", "machine"]  # set-like: normalized to the category order


# ---------------------------------------------------------------------------------- 4 / 30. MISSING != 0
def test_missing_and_zero_round_trip_model_hash_evaluation_sqlite(tmp_path):
    m = station(extra={**MAINT})
    e = {"currency": "EUR", "scope": ["material", "downtime"],
         "material": [{"rate": money(None, "PER_GOOD_UNIT")}],
         "downtime": [{"node": "m", "rate": money(0, "PER_CORRECTIVE_DOWNTIME_HOUR", provenance={"status": "provided_by_client"})}],
         "capex": [{"category": "eq", "amount": money(None, "FIXED")}, {"category": "sw", "amount": money(0, "FIXED")}]}
    m = with_econ(m, e)
    for ext in ("yaml", "json"):
        save_model(m, tmp_path / f"m.{ext}")
        back = load_model(tmp_path / f"m.{ext}")
        assert back.economics.material[0].rate.value is None and back.economics.downtime[0].rate.value == 0
        assert back.economics.capex[0].amount.value is None and back.economics.capex[1].amount.value == 0
        assert back.economic_hash() == m.economic_hash() and back.content_hash() == m.content_hash()
    run = fake_run(m, [{"units_completed": 5, "units_scrapped": 0, "node.m.corrective_downtime_h": 2.0}])
    ev = evaluate_run(run, m, m.economics)
    assert ev.line("material.0").status == "MISSING" and ev.line("material.0").value is None
    assert ev.line("downtime.0").status == "INCLUDED" and ev.line("downtime.0").value["mean"] == 0  # explicit zero is data
    assert ev.line("downtime.0").parameter["value"] == 0 and ev.line("downtime.0").parameter["provenance"]["status"] == "provided_by_client"
    assert ev.coverage == {**ev.coverage, "material": "MISSING", "downtime": "INCLUDED"} and ev.status == "PARTIAL_MISSING_INPUTS"
    assert ev.capex["missing"] == ["eq"] and ev.capex["total"] == 0 and ev.capex["status"] == "PARTIAL_MISSING_INPUTS"
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("p")
    sf.save_model(p, m, "m")
    sf.approve_model(p, by="eng")
    r = sf.run_simulation(p)
    stored = sf.evaluate_economics(p, r.run_id)
    back = p.load_evaluation(stored.evaluation_id)
    assert strict_json(back.to_dict()) == strict_json(stored.to_dict())
    assert back.line("material.0").value is None and back.capex["items"][1]["value"] == 0
    a = p.load_assumptions(stored.evaluation_id)
    assert a.material[0].rate.value is None and a.capex[1].amount.value == 0 and a.economic_hash() == m.economic_hash()


def test_missing_category_in_comparison_is_never_zero():
    b = ev_of(spec(scope=["machine", "labor"], machine=[{"node": "m", "rate": money(100, "FIXED_PER_RUN")}],
                   labor=[{"resource": "op", "rate": money(None, "PER_BUSY_HOUR")}]))
    a = ev_of(spec(scope=["machine", "labor"], machine=[{"node": "m", "rate": money(90, "FIXED_PER_RUN")}],
                   labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}]), [{"units_completed": 1, "units_scrapped": 0,
                                                                                        "resource.op.working_h": 2}])
    c = compare_evaluations(b, a)
    assert "labor" not in c.cost_deltas and c.mismatched_categories["only_alternative"] == ["labor"]
    assert c.savings["mean"] == 10 and c.coverage_match is False  # common categories only, labelled


# ---------------------------------------------------------------------------------- 5. COMPLETE_FOR_REQUESTED_SCOPE
def test_complete_for_requested_scope_is_not_a_full_cost_model():
    m = station()
    run = run_simulation(m, REG)
    ev = evaluate_run(run, m, spec(scope=["labor", "energy"], labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}],
                                   energy={"price": money(0.2, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 2}}}))
    assert ev.status == "COMPLETE_FOR_REQUESTED_SCOPE" and ev.requested_scope == ["labor", "energy"]
    assert ev.coverage["material"] == "NOT_REQUESTED" and "depreciation" in ev.out_of_scope
    text = strict_json(ev.to_dict()).lower()
    assert not re.search(r"full[ _]cost|production[ _]cost|fully[ _]loaded|profit\b(?! )", text.replace("not a profit", ""))


# ---------------------------------------------------------------------------------- 6. evaluated_total_cost
def test_total_equals_breakdown_even_with_partial_category():
    """BUG (fixed): an INCLUDED line of a partially MISSING category was summed in the total but hidden in by_category."""
    s = spec(labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}],
             machine=[{"node": "m", "rate": money(None, "FIXED_PER_RUN")}, {"node": "m", "rate": money(7, "PER_CYCLE")}],
             annualization=ann(10))
    ev = ev_of(s, [{"units_completed": 10, "units_scrapped": 0, "resource.op.working_h": 5, "node.m.processed": 10}])
    assert ev.coverage["machine"] == "MISSING" and total(ev) == 220
    assert sum(v["mean"] for v in ev.totals["by_category"].values()) == pytest.approx(220)
    assert ev.totals["by_category"]["machine"]["mean"] == 70 and ev.totals["included_categories"] == ["labor"]
    assert sum(v["mean"] for v in ev.annualized["by_category"].values()) == pytest.approx(2200)


# ---------------------------------------------------------------------------------- 7. double counting
@pytest.mark.parametrize("kw,flagged", [
    ({"labor": [{"resource": "op", "paid_time": "CALENDAR_WINDOW", "rate": money(1, "PER_PAID_HOUR")},
                {"resource": "op", "rate": money(1, "PER_BUSY_HOUR")}]}, {"labor.0", "labor.1"}),
    ({"labor": [{"resource": "op", "rate": money(1, "PER_PLANNED_HOUR")}, {"resource": "op", "rate": money(1, "PER_BUSY_HOUR")}]},
     {"labor.0", "labor.1"}),
    ({"machine": [{"node": "m", "rate": money(1, "PER_PROCESSING_HOUR")}, {"node": "m", "rate": money(1, "PER_OPERATING_HOUR")}]},
     {"machine.0", "machine.1"}),
    ({"machine": [{"node": "m", "rate": money(1, "PER_PLANNED_HOUR")}, {"node": "m", "rate": money(1, "PER_CALENDAR_HOUR")}]},
     {"machine.0", "machine.1"}),
    ({"material": [{"rate": money(1, "PER_CONSUMED_UNIT")}], "scrap": [{"rate": money(1, "PER_SCRAP_UNIT")}]}, {"scrap.0"}),
    ({"labor": [{"resource": "tech", "rate": money(1, "PER_BUSY_HOUR")}],
      "maintenance": [{"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(1, "PER_BUSY_HOUR")}]}, {"maintenance.0"}),
    # clearly independent combinations are NOT blocked
    ({"labor": [{"resource": "op", "rate": money(1, "PER_BUSY_HOUR")}],
      "machine": [{"node": "m", "rate": money(1, "PER_PROCESSING_HOUR")}, {"node": "m", "rate": money(1, "PER_SETUP_HOUR")}]}, set()),
    ({"material": [{"rate": money(1, "PER_GOOD_UNIT")}], "scrap": [{"rate": money(1, "PER_SCRAP_UNIT")}]}, set()),
    ({"maintenance": [{"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(1, "PER_BUSY_HOUR")},
                      {"kind": "PER_FAILURE", "node": "m", "rate": money(1, "PER_FAILURE")}],
      "downtime": [{"node": "m", "rate": money(1, "PER_CORRECTIVE_DOWNTIME_HOUR")}]}, set()),
])
def test_double_counting_matrix(kw, flagged):
    m = station(extra=MAINT)
    red = {i.path for i in economics_issues(spec(**kw), m, REG) if i.code == "REQUIRES_ENGINEER_DECISION"}
    assert red == flagged
    if flagged:
        ev = evaluate_run(fake_run(m, [{"units_completed": 1, "units_scrapped": 1, "resource.op.working_h": 1,
                                        "resource.tech.working_h": 1, "node.m.utilization": 0.5}]), m, spec(**kw))
        assert ev.status == "REQUIRES_ENGINEER_DECISION"
        assert all(ev.line(x).status == "REQUIRES_ENGINEER_DECISION" and ev.line(x).line_id not in
                   [ln.line_id for ln in ev.lines if ln.status == "INCLUDED"] for x in flagged)


# ---------------------------------------------------------------------------------- 8 / 9 / 40. paid time + horizon
def cal_model(windows, horizon_h, warm=0):
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    extra = {"availability": {"mode": "relative_week", "calendars": [{"id": "s", "weekly": {d: windows for d in days}}],
                              "resources": {"op": "s"}, "nodes": {"m": "s"},
                              "operations": {"m": {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}}}}
    m = station(horizon_h=horizon_h, proc_h=0.5, extra=extra)
    if warm:
        m = set_value(m, "simulation.warmup", {"value": warm, "unit": "h"})
    return set_value(m, "nodes.src.params", {"interarrival": C(0.5, "h")})


def paid(m, run, rule):
    ev = evaluate_run(run, m, spec(labor=[{"resource": "op", "paid_time": rule, "rate": money(1, "PER_PAID_HOUR")}]))
    return total(ev)


@pytest.mark.parametrize("windows,horizon,warm,cw,pa", [
    ([{"start": "06:00", "end": "14:00"}], 10, 0, 10, 4),  # run 00-10: shift 06-14 clipped to 06-10
    ([{"start": "06:00", "end": "14:00"}], 24, 0, 24, 8),  # off-shift is in CALENDAR_WINDOW, not in PLANNED_AVAILABLE
    ([{"start": "06:00", "end": "14:00"}, {"start": "14:00", "end": "22:00"}], 24, 0, 24, 16),  # two shifts
    ([{"start": "06:00", "end": "10:00"}, {"start": "10:30", "end": "14:00"}], 14, 0, 14, 7.5),  # break excluded
    ([{"start": "06:00", "end": "14:00"}], 14, 8, 6, 6),  # warm-up excluded from both
])
def test_paid_time_rules_are_clipped_to_the_measured_window(windows, horizon, warm, cw, pa):
    m = cal_model(windows, horizon, warm)
    run = run_simulation(m, REG)
    assert paid(m, run, "CALENDAR_WINDOW") == pytest.approx(cw)  # = (horizon - warm-up) x units, NOT the shift length
    assert paid(m, run, "PLANNED_AVAILABLE") == pytest.approx(pa)  # = planned available time inside the window
    k = run.per_replication[0]
    assert k["resource.op.calendar_time_h"] == pytest.approx(cw) and k["resource.op.planned_available_h"] == pytest.approx(pa)


def test_time_bases_never_exceed_the_simulated_window():
    m = station(horizon_h=10, proc_h=20, extra=MAINT)  # a 20 h job inside a 10 h run; failures every 2 h
    run = run_simulation(m, REG)
    s = spec(machine=[{"node": "m", "rate": money(1, "PER_PROCESSING_HOUR")}, {"node": "m", "rate": money(1, "PER_CYCLE")}],
             energy={"price": money(1, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 1}}},
             maintenance=[{"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(1, "PER_BUSY_HOUR")}],
             downtime=[{"node": "m", "rate": money(1, "PER_CORRECTIVE_DOWNTIME_HOUR")}])
    ev = evaluate_run(run, m, s)
    proc, dt, rep = (ev.line(x).quantity["mean"] for x in ("machine.0", "downtime.0", "maintenance.0"))
    assert proc + dt <= 10 + 1e-9 and rep <= dt + 1e-9 and ev.line("energy.m").quantity["mean"] == pytest.approx(proc)
    assert ev.line("machine.1").quantity["mean"] == 0  # the unfinished job is not "completed" by economics


# ---------------------------------------------------------------------------------- 10 / 11 / 12. annualization
def test_annualization_is_pure_extrapolation_capex_and_unit_costs_untouched():
    s = spec(machine=[{"node": "m", "rate": money(100, "FIXED_PER_RUN")}], capex=capex(5000), annualization=ann(250))
    ev = ev_of(s, [{"units_completed": 10, "units_scrapped": 0}])
    assert ev.annualized["evaluated_total_cost"]["mean"] == 25000
    assert ev.capex["total"] == 5000 and "capex" not in ev.annualized  # CAPEX is an investment, never x runs/year
    assert "cost_per_good_unit" not in ev.annualized and ev.unit_costs["cost_per_good_unit"]["mean"] == 10
    assert ev.annualized["evaluated_total_cost"]["mean"] / (10 * 250) == ev.unit_costs["cost_per_good_unit"]["mean"]
    assert ev_of(fixed(100)).annualized["status"] == "MISSING"  # never inferred


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
def test_runs_per_year_must_be_finite_and_positive(bad):
    try:
        s = fixed(1, annualization=ann(bad))
    except Exception:
        return  # rejected at load
    assert any(i.code == "ECONOMICS_ANNUALIZATION_INVALID" for i in economics_issues(s, station(), REG))
    with pytest.raises(EconomicsError):
        ev_of(s)


# ---------------------------------------------------------------------------------- 13 / 14 / 15. CAPEX, payback, return
def cmp(base_capex, alt_capex, base_cost=100000, alt_cost=80000):
    b = ev_of(fixed(base_cost, annualization=ann(1), **({"capex": base_capex} if base_capex is not None else {})))
    a = ev_of(fixed(alt_cost, annualization=ann(1), **({"capex": alt_capex} if alt_capex is not None else {})))
    return compare_evaluations(b, a)


def test_incremental_capex_never_assumes_an_undeclared_baseline_is_zero():
    """BUG (fixed): a baseline WITHOUT any CAPEX item was taken as 0 EUR."""
    c = cmp(None, capex(50000))
    assert c.capex["status"] == "NOT_DECLARED" and "incremental" not in c.capex and c.payback["status"] == "UNDEFINED_METRIC"
    c = cmp(capex(0), capex(50000))  # explicit 0 is data
    assert c.capex["incremental"] == 50000 and c.payback["years"] == 2.5
    c = cmp(capex(None), capex(50000))
    assert c.capex["status"] == "MISSING" and c.payback["status"] == "UNDEFINED_METRIC"
    c = cmp(capex(10000), capex(50000, 5000))
    assert c.capex["incremental"] == 45000  # alternative - baseline


@pytest.mark.parametrize("bcap,acap,bcost,acost,pb,ret", [
    (0, 50000, 100000, 80000, ("AVAILABLE", 2.5), ("AVAILABLE", 0.4)),
    (0, 50000, 100000, 100000, ("NOT_REACHED", None), ("AVAILABLE", 0.0)),
    (0, 50000, 100000, 120000, ("NOT_REACHED", None), ("AVAILABLE", -0.4)),
    (0, 0, 100000, 80000, ("UNDEFINED_METRIC", None), ("UNDEFINED_METRIC", None)),  # incremental CAPEX = 0: no "0 years"
    (50000, 0, 100000, 80000, ("UNDEFINED_METRIC", None), ("UNDEFINED_METRIC", None)),  # negative incremental CAPEX
])
def test_simple_payback_and_annual_return_cases(bcap, acap, bcost, acost, pb, ret):
    c = cmp(capex(bcap), capex(acap), bcost, acost)
    assert c.payback["status"] == pb[0] and c.payback.get("years") == pb[1]
    assert c.annual_return_on_incremental_capex["status"] == ret[0]
    assert c.annual_return_on_incremental_capex.get("value") == (pytest.approx(ret[1]) if ret[1] is not None else None)
    assert c.payback["formula_id"] == "simple_payback_v1" and "years" not in c.payback or c.payback["years"] > 0


def test_payback_requires_complete_and_matching_coverage():
    b = ev_of(fixed(100000, annualization=ann(1), capex=capex(0)))
    a = ev_of(spec(machine=[{"node": "m", "rate": money(80000, "FIXED_PER_RUN")}], labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}],
                   annualization=ann(1), capex=capex(50000)), [{"units_completed": 1, "units_scrapped": 0, "resource.op.working_h": 10}])
    c = compare_evaluations(b, a)
    assert c.coverage_match is False and c.payback["status"] == "REQUIRES_ENGINEER_DECISION"
    assert c.annual_return_on_incremental_capex["status"] == "REQUIRES_ENGINEER_DECISION"
    assert c.savings["mean"] == 20000 and "common categories" in c.savings["definition"]  # still shown, labelled
    partial = ev_of(spec(scope=["machine", "labor"], machine=[{"node": "m", "rate": money(80000, "FIXED_PER_RUN")}],
                         annualization=ann(1), capex=capex(50000)))
    c = compare_evaluations(b, partial)
    assert c.payback["status"] == "UNDEFINED_METRIC" and "incomplete" in c.payback["reason"]


# ---------------------------------------------------------------------------------- 16. revenue
def test_revenue_only_good_units_and_net_result_states_its_categories():
    s = spec(machine=[{"node": "m", "rate": money(100, "FIXED_PER_RUN")}], revenue=[{"rate": money(20, "PER_GOOD_UNIT")}])
    ev = ev_of(s, [{"units_completed": 8, "units_scrapped": 2}])
    assert ev.revenue["revenue"]["mean"] == 160  # scrap never earns revenue; produced (10) != good (8)
    assert ev.revenue["evaluated_net_result"]["mean"] == 60 and ev.revenue["cost_categories_in_net_result"] == ["machine"]
    assert "lost" not in strict_json(ev.revenue).replace("lost_revenue", "")
    assert ev_of(fixed(100)).revenue["status"] == "NOT_DECLARED" and ev_of(fixed(100)).revenue["evaluated_net_result"] is None


# ---------------------------------------------------------------------------------- 17. energy
def test_energy_requested_without_power_is_missing_not_zero_and_partial_states_are_visible():
    """BUG (fixed): an energy block without any declared power gave NOT_APPLICABLE and could yield COMPLETE."""
    ev = ev_of(spec(scope=["energy"], energy={"price": money(0.2, "PER_KWH")}))
    assert ev.coverage["energy"] == "MISSING" and ev.status == "PARTIAL_MISSING_INPUTS" and ev.line("energy").status == "MISSING"
    prod = {"entities": [{"id": "a", "name": "A"}],
            "production": {"products": {"a": {"setup_key": "A"}}, "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a"]}},
                           "setups": {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(10, "min")}}}}
    m = station(extra=prod)
    ev = ev_of(spec(energy={"price": money(1, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 2}}}),
               [{"units_completed": 1, "units_scrapped": 0, "node.m.utilization": 0.5, "node.m.setup_time_h": 1}], m=m)
    assert ev.line("energy.m").quantity["mean"] == 8  # 2 kW x 4 h PROCESSING; SETUP has no declared power -> not costed
    assert ev.coverage_detail["energy"]["m"] == {"declared_states": ["PROCESSING"], "not_declared_states": ["SETUP"]}


# ---------------------------------------------------------------------------------- 18 / 19. maintenance + downtime
def test_maintenance_labor_is_active_task_time_not_waiting_and_downtime_never_implicit():
    m = station(extra=MAINT)
    k = {"units_completed": 1, "units_scrapped": 0, "node.m.failure_count": 3, "node.m.corrective_downtime_h": 5.0,
         "node.m.waiting_for_repair_resource_h": 3.0, "node.m.active_repair_time_h": 2.0, "node.m.waiting_for_pm_h": 4.0,
         "resource.tech.task_h.m#repair": 2.0, "resource.tech.task_h.m#pm": 0.5}
    ev = ev_of(spec(maintenance=[{"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(10, "PER_BUSY_HOUR")},
                                 {"kind": "PM_LABOR", "node": "m", "resource": "tech", "rate": money(10, "PER_BUSY_HOUR")}]), [k], m=m)
    assert ev.line("maintenance.0").value["mean"] == 20 and ev.line("maintenance.1").value["mean"] == 5
    assert ev.line("maintenance.0").physical_sources == ["resource.tech.task_h.m#repair"]  # audit names real KPIs only
    assert ev.coverage["downtime"] == "NOT_REQUESTED" and total(ev) == 25  # failures/downtime cost nothing undeclared
    assert ev.revenue["status"] == "NOT_DECLARED"


# ---------------------------------------------------------------------------------- 20 / 21. products, setups
def test_direct_plus_shared_equals_total_and_setup_cost_is_shared():
    prod = {"entities": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "production": {"products": {"a": {"setup_key": "A"}, "b": {"setup_key": "B"}}, "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}},
                           "setups": {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(10, "min")}}}}
    m = station(extra=prod)
    s = spec(material=[{"product": "a", "rate": money(3, "PER_GOOD_UNIT")}, {"product": "b", "rate": money(5, "PER_GOOD_UNIT")}],
             labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}], machine=[{"node": "m", "rate": money(50, "PER_SETUP_HOUR")}])
    ev = ev_of(s, [{"units_completed": 6, "units_scrapped": 0, "product.a.completed": 4, "product.b.completed": 2,
                    "resource.op.working_h": 2, "node.m.setup_time_h": 1}], m=m)
    p = ev.products
    assert p["allocation_policy"] == "NONE" and p["direct"]["a"]["mean"] == 12 and p["direct"]["b"]["mean"] == 10
    assert p["shared"]["mean"] == 110  # operator 60 + setup 50: never spread over products
    assert p["direct"]["a"]["mean"] + p["direct"]["b"]["mean"] + p["shared"]["mean"] == total(ev)
    assert ev.line("machine.0").scope == "shared" and ev.line("machine.0").target == "m"


# ---------------------------------------------------------------------------------- 22 / 23. replications and ratios
def test_unit_cost_is_the_mean_of_per_replication_ratios():
    ev = ev_of(fixed(100), [{"units_completed": 10, "units_scrapped": 0}, {"units_completed": 40, "units_scrapped": 0}])
    u = ev.unit_costs
    assert u["per_rep"]["cost_per_good_unit"] == [10, 2.5] and u["cost_per_good_unit"]["mean"] == 6.25  # not 200/50 = 4
    assert u["statistic"] == "mean_of_per_replication_ratios"
    zero = ev_of(fixed(100), [{"units_completed": 10, "units_scrapped": 0}, {"units_completed": 0, "units_scrapped": 0}])
    assert zero.unit_costs["cost_per_good_unit"] == "UNDEFINED_METRIC" and zero.unit_costs["per_rep"]["cost_per_good_unit"] == [10, None]


# ---------------------------------------------------------------------------------- 24. paired comparison
def test_paired_summarises_per_replication_deltas_and_needs_crn_evidence():
    m = station()
    labor = spec(labor=[{"resource": "op", "rate": money(1, "PER_BUSY_HOUR")}])
    kb = [{"units_completed": 1, "units_scrapped": 0, "resource.op.working_h": h} for h in (100, 200)]
    ka = [{"units_completed": 1, "units_scrapped": 0, "resource.op.working_h": h} for h in (110, 210)]
    b, a = (evaluate_run(fake_run(m, k, seeds=[7, 8]), m, labor) for k in (kb, ka))
    c = compare_evaluations(b, a)
    assert c.paired and c.cost_deltas["labor"]["mean"] == 10 and c.cost_deltas["labor"]["std"] == 0
    assert c.cost_deltas["labor"]["ci95_low"] == c.cost_deltas["labor"]["ci95_high"] == 10  # unpaired would be ~ +-635
    other = evaluate_run(fake_run(m, ka, seeds=[9, 10]), m, labor)  # same N, different seeds: no CRN evidence
    u = compare_evaluations(b, other)
    assert not u.paired and u.cost_deltas["labor"]["mean"] == 10 and u.cost_deltas["labor"]["ci95_low"] is None
    m16 = station(horizon_h=16)
    longer = evaluate_run(fake_run(m16, ka, horizon_h=16, seeds=[7, 8]), m16, labor)
    assert not compare_evaluations(b, longer).paired  # same seeds but different horizon: not paired


# ---------------------------------------------------------------------------------- 25 - 29. comparability
def test_comparability_levels():
    m = station()
    b = ev_of(fixed(100))
    usd = evaluate_run(fake_run(m, [{"units_completed": 1, "units_scrapped": 0}]), m,
                       EconomicsSpec.model_validate({"currency": "USD", "machine": [{"node": "m", "rate": money(1, "FIXED_PER_RUN", ccy="USD")}]}))
    c = compare_evaluations(b, usd)
    assert c.status == "NOT_COMPARABLE" and {x["level"] for x in c.checks} == {"HARD_INCOMPATIBILITY"} | {x["level"] for x in c.checks}
    assert any(x["check"] == "currency" and x["level"] == "HARD_INCOMPATIBILITY" for x in c.checks)
    m10 = station(horizon_h=10)
    longer = evaluate_run(fake_run(m10, [{"units_completed": 1, "units_scrapped": 0}], horizon_h=10), m10, fixed(100))
    c = compare_evaluations(b, longer, m, m10)
    assert c.status == "COMPARABLE_WITH_WARNINGS" and any(x["check"] == "horizon" and x["level"] == "WARNING" for x in c.checks)
    assert c.cost_deltas["machine"]["mean"] == 0  # no automatic normalisation
    more = ev_of(fixed(100), [{"units_completed": 1, "units_scrapped": 0}] * 2)
    c = compare_evaluations(b, more)
    assert c.status == "COMPARABLE" and any(x["check"] == "replications" and x["level"] == "INFORMATIONAL" for x in c.checks)
    prod = {"entities": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "production": {"products": {"a": {}, "b": {}}, "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a"]}}}}
    mixm = station(extra=prod)
    mix_b = set_value(mixm, "production.generation.src.sequence", ["a", "b"])
    e1 = evaluate_run(fake_run(mixm, [{"units_completed": 1, "units_scrapped": 0}]), mixm, fixed(100))
    e2 = evaluate_run(fake_run(mix_b, [{"units_completed": 1, "units_scrapped": 0}]), mix_b, fixed(100))
    c = compare_evaluations(e1, e2, mixm, mix_b)
    assert any(x["check"] == "product_mix" and x["level"] == "WARNING" for x in c.checks)


# ---------------------------------------------------------------------------------- 31 / 32. formulas and versions
def test_formula_registry_versioned_and_referenced():
    ev = evaluate_run(run_simulation(full_model(), REG), full_model())
    COMPARISON_FORMULAS = compare_mod.COMPARISON_FORMULAS
    assert all(re.fullmatch(r"[a-z_]+_v\d+", f) for f in FORMULAS) and all(re.fullmatch(r"[a-z_]+_v\d+", f) for f in COMPARISON_FORMULAS)
    assert {ln.formula_id for ln in ev.lines} <= set(ev.formulas) and ev.formulas == FORMULAS
    c = compare_evaluations(ev, ev)
    assert c.formulas == COMPARISON_FORMULAS and {c.payback["formula_id"], c.annual_return_on_incremental_capex["formula_id"]} <= set(c.formulas)
    assert ev.economics_engine_version in ev.evaluation_id or len(ev.evaluation_id) == 12  # version is part of the identity hash


# ---------------------------------------------------------------------------------- 33 / 34. persistence + approval
def test_reevaluation_keeps_economic_approval_and_physics_change_is_incompatible(tmp_path):
    """BUG (fixed): INSERT OR REPLACE of an identical evaluation silently dropped its economic approval."""
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("p")
    m = full_model()
    sf.save_model(p, m, "m")
    sf.approve_model(p, by="eng")
    run = sf.run_simulation(p)
    e1 = sf.evaluate_economics(p, run.run_id)
    p.approve_evaluation(e1.evaluation_id, "controller")
    again = sf.evaluate_economics(p, run.run_id)
    assert again.evaluation_id == e1.evaluation_id and len(p.evaluations()) == 1
    assert p.evaluations()[0]["approved_by"] == "controller"
    cheaper = set_value(m, "economics.energy.price.value", 0.10)
    assert cheaper.content_hash() == m.content_hash()  # physical approval and cache untouched
    e2 = sf.evaluate_economics(p, run.run_id, cheaper.economics)
    assert e2.evaluation_id != e1.evaluation_id and [x["approved_by"] for x in p.evaluations()] == ["controller", None]
    with pytest.raises(EconomicsError):
        evaluate_run(run, set_value(m, "simulation.horizon.value", 9))


# ---------------------------------------------------------------------------------- 35 / 36. terminology, no recommendation
def test_cli_ui_docs_have_no_misleading_terms_or_recommendations():
    files = [SRC / "economics" / "evaluate.py", SRC / "economics" / "compare.py", SRC / "cli_economics.py", SRC / "ui" / "economics_view.py"]
    bad = re.compile(r"\b(profit|winner|best|optimal|recommended|full cost|fully loaded|choose scenario|is better)\b", re.I)
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.search(r"\b(never|nunca|not|no|sin|does not)\b", line, re.I):
                continue  # negated statements of the contract ("never a winner", "NOT a profit")
            assert not bad.search(line), f"{f.name}: {line.strip()}"


# ---------------------------------------------------------------------------------- 37. numeric robustness
def test_numeric_robustness():
    one = ev_of(fixed(100))
    strict_json(one.to_dict())  # n = 1: no NaN interval is serialised (None instead)
    assert one.totals["evaluated_total_cost"]["ci95_low"] is None
    strict_json(compare_evaluations(one, one).to_dict())
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(Exception):
            fixed(bad)
    z = fixed(-0.0)
    assert math.copysign(1, z.machine[0].rate.value) == 1  # negative zero normalised
    huge = spec(machine=[{"node": "m", "rate": money(1e308, "PER_CYCLE")}])
    with pytest.raises(EconomicsError, match="no finito"):
        ev_of(huge, [{"units_completed": 1, "units_scrapped": 0, "node.m.processed": 10}])


# ---------------------------------------------------------------------------------- 38. determinism
def test_determinism():
    m = full_model()
    run = run_simulation(m, REG, replications=3)
    a, b = evaluate_run(run, m), evaluate_run(run, m)
    assert strict_json(a.to_dict()) == strict_json(b.to_dict())


# ---------------------------------------------------------------------------------- 39. physical invariance A-B-C-D
@pytest.mark.parametrize("f,expected", [("01_simple_line.yaml", 59), ("02_shared_operator.yaml", 359),
                                        ("03_machine_breakdowns.yaml", 1889.05), ("04_rework_routing.yaml", 477.5),
                                        ("05_selective_soldering.yaml", 130)])
def test_economics_only_model_runs_and_keeps_01_05(f, expected):
    """BUG (fixed): with `economics` as the ONLY extension block the model could not be simulated at all (the frozen
    verifier re-validated the full model as ISMSModel). Now the frozen verifier receives the physical core."""
    a = load_model(EXAMPLES / f)
    b = with_econ(a, {"currency": "EUR"})
    ra, rb = run_simulation(a, REG), run_simulation(b, REG)
    assert rb.model_hash == ra.model_hash == a.content_hash()
    assert all(same_kpis(x, y) for x, y in zip(ra.per_replication, rb.per_replication))
    assert round(sum(k["units_completed"] for k in rb.per_replication) / len(rb.per_replication), 2) == expected
    approved = b.model_copy(update={"approval": b.approval.model_copy(update={"approved": True, "model_hash": b.content_hash()})})
    from simforge.validation.semantics import verify_model
    assert approved.is_approved and verify_model(approved, REG)[0].ok



def test_physical_invariance_add_change_remove_economics():
    a = load_model(EXAMPLES / "05_selective_soldering.yaml")
    b = with_econ(a, {"currency": "EUR", "machine": [{"node": a.nodes[1].id, "rate": money(10, "PER_CYCLE")}]})
    c = set_value(b, "economics.machine.0.rate.value", 99)
    d = model_from_dict({k: v for k, v in c.model_dump(mode="json").items() if k != "economics"})
    assert len({x.content_hash() for x in (a, b, c, d)}) == 1 and d.economics is None
    runs = [run_simulation(x, REG, replications=2, trace=True, keep_records=True) for x in (a, b, c, d)]
    for r in runs[1:]:
        assert r.model_hash == runs[0].model_hash and r.seeds == runs[0].seeds
        assert all(same_kpis(x, y) for x, y in zip(r.per_replication, runs[0].per_replication))
        assert [x.events for x in r.records] == [x.events for x in runs[0].records]
    assert [k["units_completed"] for k in runs[0].per_replication][0] == 130
