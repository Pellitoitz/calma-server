"""Engine 0.9.0: economics & decision support. Expected values are derived by hand from the declared formulas.
Formula cases use a stored-run object built from explicit physical KPIs (economics only ever reads those); invariance,
labor, energy, persistence and comparisons use real simulation runs."""

from __future__ import annotations

import copy
import json

import pytest
import yaml

from simforge.analytics.kpis import aggregate
from simforge.domain.economics import EconomicsSpec
from simforge.domain.io import dump_model, load_model, model_from_dict, save_model
from simforge.domain.paths import set_value
from simforge.economics import compare_evaluations, evaluate_run
from simforge.economics.evaluate import EconomicsError
from simforge.experiments.runner import SimulationResult, run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.validation.economics import economics_issues

from .conftest import EXAMPLES

REG = ComponentRegistry.load_default(None)
H = 3600.0


def C(v, unit="s"):
    return {"dist": "constant", "value": v, "unit": unit}


def money(v, basis, ccy="EUR", **kw):
    return {"value": v, "currency": ccy, "basis": basis, **kw}


def spec(**kw):
    return EconomicsSpec.model_validate({"currency": "EUR", **kw})


def station(horizon_h=8, proc_h=5, extra=None):
    d = {"meta": {"name": "econ"}, "simulation": {"horizon": {"value": horizon_h, "unit": "h"}},
         "resources": [{"id": "op", "quantity": 1}],
         "nodes": [{"id": "src", "component": "source", "params": {"max_entities": 1}},
                   {"id": "m", "component": "manual_assembly", "params": {"process_time": C(proc_h, "h"), "resources": [{"resource": "op"}]}},
                   {"id": "out", "component": "sink"}],
         "edges": [{"source": "src", "target": "m"}, {"source": "m", "target": "out"}]}
    d.update(extra or {})
    return model_from_dict(d)


def fake_run(model, kpis_list, horizon_h=8.0, seeds=None):
    """A stored run with given physical KPIs (what persistence keeps): economics reads nothing else."""
    seeds = seeds or list(range(1, len(kpis_list) + 1))
    return SimulationResult(run_id="r" + model.content_hash()[:6], model_name="x", model_hash=model.content_hash(),
                            component_versions={}, engine="simpy-des", engine_version="0.9.0", app_version="0", seeds=seeds,
                            started_at="2026-10-02T00:00:00+00:00", wall_time_s=0.0, horizon_s=horizon_h * H, warmup_s=0.0,
                            kpis=aggregate(kpis_list), per_replication=kpis_list, findings=[])


def total(ev):
    return ev.totals["evaluated_total_cost"]["mean"]


# ------------------------------------------------------------------------------------ 43: labor paid vs busy
def test_43_labor_paid_vs_busy():
    m = station()
    run = run_simulation(m, REG)  # 8 h window, operator busy 5 h
    paid = evaluate_run(run, m, spec(labor=[{"resource": "op", "paid_time": "CALENDAR_WINDOW", "rate": money(30, "PER_PAID_HOUR")}]))
    busy = evaluate_run(run, m, spec(labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}]))
    assert total(paid) == 240 and total(busy) == 150
    assert paid.line("labor.0").formula_id == "labor_paid_v1" and busy.line("labor.0").formula_id == "labor_busy_v1"
    declared = evaluate_run(run, m, spec(labor=[{"resource": "op", "paid_time": "DECLARED", "declared_paid_hours_per_unit": 7.5,
                                                 "rate": money(28, "PER_PAID_HOUR")}]))
    assert total(declared) == 210  # 7.5 h x 28
    nohours = evaluate_run(run, m, spec(scope=["labor"], labor=[{"resource": "op", "paid_time": "DECLARED", "rate": money(28, "PER_PAID_HOUR")}]))
    assert nohours.line("labor.0").status == "MISSING" and nohours.status == "PARTIAL_MISSING_INPUTS"


# ------------------------------------------------------------------------------------ 44: energy
def test_44_energy_price_change_without_rerunning():
    m = station(horizon_h=10, proc_h=20)  # machine processing the whole 10 h window
    run = run_simulation(m, REG)
    e = {"price": money(0.20, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 10.0}}}
    a = evaluate_run(run, m, spec(energy=e))
    b = evaluate_run(run, m, spec(energy={**e, "price": money(0.30, "PER_KWH")}))
    assert a.line("energy.m").quantity["mean"] == pytest.approx(100) and total(a) == pytest.approx(20)
    assert total(b) == pytest.approx(30)
    assert a.run_id == b.run_id and a.physical_model_hash == b.physical_model_hash and a.economic_hash != b.economic_hash
    none = evaluate_run(run, m, spec(scope=["energy"], energy={"price": money(0.2, "PER_KWH")}))
    assert none.coverage["energy"] == "NOT_APPLICABLE"  # no declared power: no kWh, never estimated


# ------------------------------------------------------------------------------------ 45: unit costs
def test_45_cost_per_produced_and_good_unit():
    m = station()
    s = spec(machine=[{"node": "m", "rate": money(1000, "FIXED_PER_RUN")}])
    ev = evaluate_run(fake_run(m, [{"units_completed": 80, "units_scrapped": 20}]), m, s)
    assert total(ev) == 1000
    assert ev.unit_costs["cost_per_produced_unit"]["mean"] == 10 and ev.unit_costs["cost_per_good_unit"]["mean"] == 12.5
    zero = evaluate_run(fake_run(m, [{"units_completed": 0, "units_scrapped": 20}]), m, s)
    assert zero.unit_costs["cost_per_good_unit"] == "UNDEFINED_METRIC" and zero.unit_costs["cost_per_produced_unit"]["mean"] == 50


# ------------------------------------------------------------------------------------ 46: scrap, no double count
def test_46_scrap_material_not_double_counted():
    m = station()
    run = fake_run(m, [{"units_completed": 90, "units_scrapped": 10}])
    ev = evaluate_run(run, m, spec(material=[{"rate": money(5, "PER_CONSUMED_UNIT")}]))
    assert total(ev) == 500  # 100 consumed units x 5: the 10 scrapped units are INSIDE
    memo = ev.line("material.0.scrapped_share")
    assert memo.status == "MEMO" and memo.value["mean"] == 50 and ev.totals["by_category"]["material"]["mean"] == 500
    both = evaluate_run(run, m, spec(material=[{"rate": money(5, "PER_CONSUMED_UNIT")}], scrap=[{"rate": money(5, "PER_SCRAP_UNIT")}]))
    assert both.line("scrap.0").status == "REQUIRES_ENGINEER_DECISION" and total(both) == 500
    assert both.status == "REQUIRES_ENGINEER_DECISION"
    split = evaluate_run(run, m, spec(material=[{"rate": money(5, "PER_GOOD_UNIT")}], scrap=[{"rate": money(5, "PER_SCRAP_UNIT")}]))
    assert total(split) == 500 and split.status == "COMPLETE_FOR_REQUESTED_SCOPE"  # 450 + 50, disjoint bases


# ------------------------------------------------------------------------------------ 47-49: annual, CAPEX, payback
def per_run(cost, runs_per_year=None, capex=None):
    kw = {"machine": [{"node": "m", "rate": money(cost, "FIXED_PER_RUN")}]}
    if runs_per_year is not None:
        kw["annualization"] = {"mode": "REPEAT_RUN", "runs_per_year": runs_per_year}
    if capex is not None:
        kw["capex"] = [{"category": "equipment", "amount": money(capex, "FIXED")}]
    return spec(**kw)


def pair(base_spec, alt_spec):
    m = station()
    run = fake_run(m, [{"units_completed": 1, "units_scrapped": 0}])
    return evaluate_run(run, m, base_spec), evaluate_run(run, m, alt_spec)


def test_47_run_vs_annualized():
    b, a = pair(per_run(1000), per_run(800))
    c = compare_evaluations(b, a)
    assert c.savings["mean"] == 200 and c.annual["status"] == "MISSING" and b.annualized["status"] == "MISSING"
    b, a = pair(per_run(1000, 440), per_run(800, 440))
    c = compare_evaluations(b, a)
    assert c.annual["savings_per_year"]["mean"] == 88000


def test_48_capex_and_simple_payback():
    b, a = pair(per_run(100000, 1), per_run(80000, 1, capex=50000))
    c = compare_evaluations(b, a)
    assert c.annual["savings_per_year"]["mean"] == 20000 and c.capex["incremental"] == 50000
    assert c.payback["status"] == "AVAILABLE" and c.payback["years"] == 2.5
    assert c.payback["formula"] == "incremental CAPEX / annual evaluated savings"
    assert c.annual_return_on_incremental_capex["value"] == 0.4


def test_49_no_payback_when_savings_are_negative():
    b, a = pair(per_run(100000, 1), per_run(105000, 1, capex=50000))
    c = compare_evaluations(b, a)
    assert c.payback["status"] == "NOT_REACHED" and "years" not in c.payback
    missing = pair(per_run(100000, 1), spec(machine=[{"node": "m", "rate": money(80000, "FIXED_PER_RUN")}],
                                            annualization={"mode": "REPEAT_RUN", "runs_per_year": 1},
                                            capex=[{"category": "equipment", "amount": money(None, "FIXED")}]))
    c = compare_evaluations(*missing)
    assert c.capex["status"] == "MISSING" and c.payback["status"] == "UNDEFINED_METRIC"  # MISSING CAPEX is never 0


# ------------------------------------------------------------------------------------ 50: coverage
def test_50_coverage_lists_what_is_in_and_what_is_missing():
    m = station()
    run = run_simulation(m, REG)
    ev = evaluate_run(run, m, spec(scope=["labor", "energy", "material"],
                                   labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}],
                                   energy={"price": money(0.2, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 2}}}))
    assert ev.coverage["labor"] == "INCLUDED" and ev.coverage["energy"] == "INCLUDED" and ev.coverage["material"] == "MISSING"
    assert ev.status == "PARTIAL_MISSING_INPUTS" and ev.totals["included_categories"] == ["labor", "energy"]
    assert "depreciation" in ev.out_of_scope and "full" not in str(ev.totals)


# ------------------------------------------------------------------------------------ 51: same physics, two economics
def test_51_same_physical_run_two_economics(monkeypatch):
    m = station()
    run = run_simulation(m, REG)
    import simforge.experiments.runner as runner
    monkeypatch.setattr(runner, "run_simulation", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no DES allowed")))
    a = evaluate_run(run, m, spec(labor=[{"resource": "op", "rate": money(25, "PER_BUSY_HOUR")}]))
    b = evaluate_run(run, m, spec(labor=[{"resource": "op", "rate": money(35, "PER_BUSY_HOUR")}]))
    assert a.run_id == b.run_id and a.physical_model_hash == b.physical_model_hash == m.content_hash()
    assert a.economic_hash != b.economic_hash and a.evaluation_id != b.evaluation_id
    assert (total(a), total(b)) == (125, 175) and json.dumps(a.physical, sort_keys=True) == json.dumps(b.physical, sort_keys=True)


# ------------------------------------------------------------------------------------ 52: maintenance
MAINT = {"resources": [{"id": "op", "quantity": 1}, {"id": "tech", "quantity": 1}],
         "maintenance": {"nodes": {"m": {"failure": {"clock": "ELAPSED_TIME", "time_to_failure": C(2, "h"), "repair_time": C(45, "min"),
                                                      "repair_age_effect": "RESET", "repair_resources": [{"resource": "tech"}]}}}}}


def test_52_maintenance_technician_costs():
    m = station(extra=MAINT)
    run = fake_run(m, [{"units_completed": 3, "units_scrapped": 0, "node.m.failure_count": 2, "node.m.corrective_downtime_h": 3.0,
                        "resource.tech.task_h.m#repair": 1.5, "resource.tech.task_h.m#pm": 0.5}])
    ev = evaluate_run(run, m, spec(maintenance=[
        {"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(40, "PER_BUSY_HOUR")},
        {"kind": "PM_LABOR", "node": "m", "resource": "tech", "rate": money(40, "PER_BUSY_HOUR")}]))
    assert ev.line("maintenance.0").value["mean"] == 60 and ev.line("maintenance.1").value["mean"] == 20 and total(ev) == 80
    assert ev.coverage["downtime"] == "NOT_REQUESTED"  # no downtime cost without an explicit input
    with_dt = evaluate_run(run, m, spec(downtime=[{"node": "m", "rate": money(100, "PER_CORRECTIVE_DOWNTIME_HOUR")}]))
    assert total(with_dt) == 300 and with_dt.totals["included_categories"] == ["downtime"]


# ------------------------------------------------------------------------------------ 53/54: comparison facts
def test_53_scenario_comparison_conventions_and_no_recommendation():
    b, a = pair(per_run(120000, 1), per_run(100000, 1, capex=60000))
    c = compare_evaluations(b, a)
    assert c.cost_deltas["machine"]["mean"] == -20000 and c.savings["mean"] == 20000  # delta = alt - base; savings = base - alt
    assert c.payback["years"] == 3
    d = c.to_dict()
    assert "does not rank, choose or recommend" in d.pop("note")
    flat = str(d).lower()
    assert not any(w in flat for w in ("winner", "best", "optimal", "recommend"))


def test_54_physical_trade_off_shown_not_converted_to_revenue():
    m = station()
    e = {"energy": {"price": money(0.2, "PER_KWH"), "power_kw": {"m": {"PROCESSING": 10}}}}
    base = fake_run(m, [{"units_completed": 100, "units_scrapped": 0, "throughput_per_hour": 12.5, "node.m.utilization": 0.5}])
    alt = fake_run(m, [{"units_completed": 120, "units_scrapped": 0, "throughput_per_hour": 15.0, "node.m.utilization": 0.75}])
    c = compare_evaluations(evaluate_run(base, m, spec(**e)), evaluate_run(alt, m, spec(**e)))
    assert c.physical_deltas["throughput_per_hour"]["delta"] == 2.5 and c.physical_deltas["throughput_per_hour"]["delta_pct"] == 20
    assert c.cost_deltas["energy"]["mean"] == pytest.approx(4.0)  # (0.75-0.5) x 8 h x 10 kW x 0.2
    assert c.revenue_delta is None  # no sale price declared: more throughput is NOT revenue


# ------------------------------------------------------------------------------------ 55: replications
def test_55_replication_statistics_are_simulation_derived():
    m = station()
    kp = [{"units_completed": 1, "units_scrapped": 0, "resource.op.working_h": h} for h in (100 / 30, 120 / 30, 110 / 30)]
    ev = evaluate_run(fake_run(m, kp), m, spec(labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}]))
    t = ev.totals["evaluated_total_cost"]
    assert t["n"] == 3 and t["mean"] == pytest.approx(110) and t["std"] == pytest.approx(10)
    assert t["ci95_low"] < 110 < t["ci95_high"] and ev.uncertainty_label == "SIMULATION_DERIVED_ECONOMIC_UNCERTAINTY"


def test_55b_paired_comparison_with_common_random_numbers():
    m = model_from_dict(yaml.safe_load(open(EXAMPLES / "03_machine_breakdowns.yaml")))
    s = spec(machine=[{"node": "press", "rate": money(10, "PER_PROCESSING_HOUR")}])
    r1 = run_simulation(m, REG, replications=4, base_seed=7)
    r2 = run_simulation(m, REG, replications=4, base_seed=7)
    c = compare_evaluations(evaluate_run(r1, m, s), evaluate_run(r2, m, s))
    assert c.paired and c.cost_deltas["machine"]["mean"] == 0 and c.cost_deltas["machine"]["std"] == 0
    r3 = run_simulation(m, REG, replications=4, base_seed=99)
    assert not compare_evaluations(evaluate_run(r1, m, s), evaluate_run(r3, m, s)).paired


# ------------------------------------------------------------------------------------ 56: product mix, shared costs
def test_56_direct_vs_shared_costs_without_allocation():
    prod = {"entities": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "production": {"products": {"a": {}, "b": {}}, "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a", "b"]}}}}
    m = station(extra=prod)
    run = fake_run(m, [{"units_completed": 30, "units_scrapped": 0, "product.a.completed": 20, "product.b.completed": 10,
                        "resource.op.working_h": 4}])
    ev = evaluate_run(run, m, spec(labor=[{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}],
                                   material=[{"product": "a", "rate": money(2, "PER_GOOD_UNIT")},
                                             {"product": "b", "rate": money(3, "PER_GOOD_UNIT")}]))
    p = ev.products
    assert p["allocation_policy"] == "NONE" and p["direct"]["a"]["mean"] == 40 and p["direct"]["b"]["mean"] == 30
    assert p["shared"]["mean"] == 120  # the operator is NOT spread over products
    assert p["direct"]["a"]["mean"] + p["direct"]["b"]["mean"] + p["shared"]["mean"] == total(ev)


# ------------------------------------------------------------------------------------ 57: save / load
FULL_ECON = {"currency": "EUR", "scope": ["labor", "machine", "energy", "maintenance"],
             "labor": [{"resource": "op", "rate": money(28, "PER_PLANNED_HOUR", provenance={"status": "provided_by_client", "source": "HR 2026"})}],
             "machine": [{"node": "m", "rate": money(12, "PER_PROCESSING_HOUR")}],
             "energy": {"price": money(0.18, "PER_KWH", reference="tariff 2026"), "power_kw": {"m": {"PROCESSING": 4}}},
             "maintenance": [{"kind": "REPAIR_LABOR", "node": "m", "resource": "tech", "rate": money(40, "PER_BUSY_HOUR")},
                             {"kind": "PER_FAILURE", "node": "m", "rate": money(150, "PER_FAILURE")}],
             "capex": [{"category": "equipment", "amount": money(42000, "FIXED")}, {"category": "training", "amount": money(None, "FIXED")}],
             "annualization": {"mode": "REPEAT_RUN", "runs_per_year": 440}}


def full_model():
    extra = copy.deepcopy(MAINT)
    extra["availability"] = {"mode": "relative_week", "calendars": [{"id": "s", "weekly": {d: [{"start": "00:00", "end": "24:00"}] for d in
                                                                                          ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}],
                             "resources": {"op": "s"}, "operations": {"m": {"at_unavailability": "FINISH_CURRENT", "start_rule": "START_ANY_TIME"}}}
    extra["entities"] = [{"id": "a", "name": "A"}]
    extra["production"] = {"products": {"a": {}}, "generation": {"src": {"mode": "EXPLICIT_SEQUENCE", "sequence": ["a"], "repeat": True}}}
    extra["economics"] = FULL_ECON
    m = station(horizon_h=8, proc_h=0.5, extra=extra)
    return set_value(m, "nodes.src.params", {})


def test_57_save_load_identical_evaluation(tmp_path):
    m = full_model()
    run = run_simulation(m, REG, replications=2)
    save_model(m, tmp_path / "m.yaml")
    back = load_model(tmp_path / "m.yaml")
    assert back.content_hash() == m.content_hash() and back.economic_hash() == m.economic_hash()
    a, b = evaluate_run(run, m), evaluate_run(run, back)
    assert a.to_dict() == b.to_dict()
    assert a.capex["status"] == "PARTIAL_MISSING_INPUTS" and a.capex["missing"] == ["training"] and a.capex["total"] == 42000
    assert a.line("labor.0").parameter["provenance"]["source"] == "HR 2026" and a.line("energy.m").parameter["reference"] == "tariff 2026"


# ------------------------------------------------------------------------------------ physical invariance
def same_kpis(a, b):
    return a.keys() == b.keys() and all(a[k] == b[k] or (a[k] != a[k] and b[k] != b[k]) for k in a)


def test_economics_never_changes_the_des():
    with_e = full_model()
    data = with_e.model_dump(mode="json")
    data.pop("economics")
    without = model_from_dict(data)
    other = set_value(with_e, "economics.labor.0.rate.value", 99)
    hashes = {with_e.content_hash(), without.content_hash(), other.content_hash()}
    assert len(hashes) == 1 and with_e.economic_hash() != other.economic_hash()
    runs = [run_simulation(x, REG, replications=2, base_seed=3, trace=True, keep_records=True) for x in (with_e, without, other)]
    for r in runs[1:]:
        assert all(same_kpis(x, y) for x, y in zip(r.per_replication, runs[0].per_replication))
        assert [x.events for x in r.records] == [x.events for x in runs[0].records]


def test_economics_change_keeps_physical_approval_and_legacy_hashes():
    m = full_model()
    m = m.model_copy(update={"approval": m.approval.model_copy(update={"approved": True, "model_hash": m.content_hash()})})
    assert m.is_approved and set_value(m, "economics.currency", "USD").is_approved
    changed = set_value(m, "economics.machine.0.rate.value", 13)
    assert changed.is_approved  # economics does not invalidate the PHYSICAL approval
    assert not set_value(m, "simulation.horizon.value", 9).is_approved
    from simforge.domain.isms import ISMSModel
    for f in ("01_simple_line.yaml", "05_selective_soldering.yaml"):
        lm = load_model(EXAMPLES / f)
        assert lm.content_hash() == ISMSModel.model_validate(lm.model_dump(mode="json")).content_hash()
        assert "economics" not in dump_model(lm)


def test_wrong_physics_is_rejected():
    m = station()
    run = run_simulation(m, REG)
    with pytest.raises(EconomicsError):
        evaluate_run(run, set_value(m, "simulation.horizon.value", 9), spec(labor=[{"resource": "op", "rate": money(1, "PER_BUSY_HOUR")}]))


# ------------------------------------------------------------------------------------ verifier
@pytest.mark.parametrize("kw,code", [
    ({"labor": [{"resource": "op", "rate": money(30, "PER_BUSY_HOUR", ccy="USD")}]}, "ECONOMICS_CURRENCY_MIXED"),
    ({"labor": [{"resource": "ghost", "rate": money(30, "PER_BUSY_HOUR")}]}, "UNKNOWN_RESOURCE"),
    ({"labor": [{"resource": "op", "rate": money(30, "PER_KWH")}]}, "ECONOMICS_BASIS_INVALID"),
    ({"material": [{"rate": money(5, "PER_UNIT")}]}, "ECONOMICS_BASIS_UNSUPPORTED"),
    ({"labor": [{"resource": "op", "rate": money(30, "PER_PAID_HOUR")}]}, "ECONOMICS_PAID_TIME_RULE_MISSING"),
    ({"annualization": {"mode": "REPEAT_RUN", "runs_per_year": 0}}, "ECONOMICS_ANNUALIZATION_INVALID"),
    ({"capex": [{"category": "equipment", "amount": money(-5, "FIXED")}]}, "ECONOMICS_NEGATIVE"),
    ({"labor": [{"resource": "op", "rate": money(30, "PER_BUSY_HOUR", provenance={"status": "default"})}]}, "ECONOMICS_DEFAULT_VALUE"),
    ({"labor": [{"resource": "op", "rate": money(30, "PER_BUSY_HOUR")}, {"resource": "op", "paid_time": "CALENDAR_WINDOW",
                                                                         "rate": money(30, "PER_PAID_HOUR")}]}, "REQUIRES_ENGINEER_DECISION"),
    ({"machine": [{"node": "m", "rate": money(1, "PER_PROCESSING_HOUR")}, {"node": "m", "rate": money(1, "PER_OPERATING_HOUR")}]},
     "REQUIRES_ENGINEER_DECISION"),
    ({"maintenance": [{"kind": "PER_FAILURE", "node": "m", "rate": money(1, "PER_FAILURE")}]}, "ECONOMICS_NO_PHYSICAL_METRIC"),
    ({"labor": [{"resource": "op", "rate": money(None, "PER_BUSY_HOUR")}]}, "ECONOMIC_INPUT_MISSING"),
])
def test_verifier(kw, code):
    assert code in {i.code for i in economics_issues(spec(**kw), station(), REG)}


def test_invalid_values_rejected_at_load():
    for bad in ({"value": float("inf"), "currency": "EUR", "basis": "FIXED"}, {"value": 1, "currency": "euros", "basis": "FIXED"}):
        with pytest.raises(Exception):
            spec(capex=[{"category": "x", "amount": bad}])
    with pytest.raises(Exception):
        spec(scope=["profit"])


def test_comparability_checks():
    m = station()
    s = spec(machine=[{"node": "m", "rate": money(1, "FIXED_PER_RUN")}])
    b = evaluate_run(fake_run(m, [{"units_completed": 1, "units_scrapped": 0}]), m, s)
    m16 = station(horizon_h=16)
    a = evaluate_run(fake_run(m16, [{"units_completed": 1, "units_scrapped": 0}], horizon_h=16), m16, s)
    c = compare_evaluations(b, a, m, m16)
    assert c.status == "COMPARABLE_WITH_WARNINGS" and any("horizon" in w for w in c.warnings)
    usd = evaluate_run(fake_run(m, [{"units_completed": 1, "units_scrapped": 0}]), m,
                       EconomicsSpec.model_validate({"currency": "USD", "machine": [{"node": "m", "rate": money(1, "FIXED_PER_RUN", ccy="USD")}]}))
    assert compare_evaluations(b, usd).status == "NOT_COMPARABLE"
    cov = evaluate_run(fake_run(m, [{"units_completed": 1, "units_scrapped": 0, "resource.op.working_h": 1}]), m,
                       spec(machine=[{"node": "m", "rate": money(1, "FIXED_PER_RUN")}], labor=[{"resource": "op", "rate": money(5, "PER_BUSY_HOUR")}]))
    c = compare_evaluations(b, cov)
    assert c.mismatched_categories == {"only_baseline": [], "only_alternative": ["labor"]} and c.savings["mean"] == 0


# ------------------------------------------------------------------------------------ persistence / history / CLI / UI
def test_project_history_many_evaluations_one_run(tmp_path):
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("econ")
    m = full_model()
    sf.save_model(p, m, "physics + economics")
    sf.approve_model(p, by="eng")
    run = sf.run_simulation(p)
    e1 = sf.evaluate_economics(p, run.run_id)
    e2 = sf.evaluate_economics(p, run.run_id, EconomicsSpec.model_validate({**FULL_ECON, "labor": [
        {"resource": "op", "rate": money(35, "PER_PLANNED_HOUR")}]}))
    assert len(p.runs()) == 1 and [e["run_id"] for e in p.evaluations()] == [run.run_id, run.run_id]
    assert json.dumps(p.load_evaluation(e1.evaluation_id).to_dict()) == json.dumps(e1.to_dict()) and e1.economic_hash != e2.economic_hash
    p.approve_evaluation(e1.evaluation_id, "controller")
    assert [e["approved_by"] for e in p.evaluations()] == ["controller", None]
    c = sf.compare_economics(p, e1.evaluation_id, e2.evaluation_id)
    assert c.paired and c.cost_deltas["labor"]["mean"] > 0
    # changing only economics keeps the physical approval valid
    v = sf.save_model(p, set_value(p.current_model(), "economics.machine.0.rate.value", 15), "machine rate")
    assert p.load_version(v).is_approved


def test_cli_economics(tmp_path):
    from typer.testing import CliRunner

    from simforge.cli import app as cli
    m = full_model()
    save_model(m, tmp_path / "m.yaml")
    alt = dict(FULL_ECON, labor=[{"resource": "op", "rate": money(35, "PER_PLANNED_HOUR")}])
    (tmp_path / "e2.yaml").write_text(yaml.safe_dump({"economics": alt}))
    r = CliRunner().invoke(cli, ["economics", "show", str(tmp_path / "m.yaml")])
    assert r.exit_code == 0, r.output
    assert "economic_hash" in r.output
    r = CliRunner().invoke(cli, ["economics", "evaluate", str(tmp_path / "m.yaml"), "--economics", str(tmp_path / "e2.yaml")])
    assert r.exit_code == 0, r.output
    assert "evaluated_total_cost" in r.output and "MISSING" in r.output
    r = CliRunner().invoke(cli, ["economics", "compare", str(tmp_path / "m.yaml"), str(tmp_path / "m.yaml"), "--replications", "2"])
    assert r.exit_code == 0, r.output
    assert "paired=True" in r.output and "does not rank" in r.output


def test_ui_economics_tab(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    ws = tmp_path / "ws"
    sf = SimForgeApp(workspace=ws, library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("UI econ")
    sf.save_model(p, full_model(), "econ")
    sf.approve_model(p, by="eng")
    run = sf.run_simulation(p)
    sf.evaluate_economics(p, run.run_id)
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(ws))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("economic_hash" in c.value for c in at.caption)
