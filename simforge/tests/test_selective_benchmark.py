"""Benchmark phase tests: engine semantics fixes, invariants, deadlock detection and the
selective-soldering benchmark pipeline.

The repository configuration must stay free of invented data. Every numeric value used below
to exercise the pipeline is SYNTHETIC TEST DATA written to a temporary copy.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from simforge.benchmark.compare import KPI_COLUMNS, ReferenceError_, Tolerance, compare, load_reference
from simforge.benchmark.run_selective_soldering import run_benchmark, run_trace
from simforge.benchmark.selective_soldering import REQUIRED, BenchmarkBlocked, Config, build_model, check_inputs
from simforge.cli import app as cli
from simforge.domain.io import model_from_dict
from simforge.engine import DesEngine
from simforge.engine.des.engine import DeadlockError
from simforge.engine.des.runtime import InvariantViolation, TravelDataError
from simforge.experiments.runner import run_simulation
from simforge.validation.verifier import compile_model

BENCH = Path(__file__).parents[1] / "benchmark"

SYNTHETIC = {
    "benchmark.anylogic_model_file": "SYNTHETIC.alp", "simulation.warmup": 0, "simulation.production_definition": "sink_count_at_stop_time",
    "simulation.simultaneous_events": "FIFO", "simulation.randomness": "deterministic", "initial_state.racks_location": "all_available_at_assembly",
    "initial_state.system_empty": True, "initial_state.operator_location": "assembly", "racks.circuits_per_rack": 10,
    "operator.walking_speed": 1.0, "operator.loaded_speed": 0.8, "operator.wip_target": 2, "operator.wip_comparison": "assembly_if_wip < target",
    "operator.wip_counted_locations": ["assembly_conveyor", "transport_to_selective", "selective_entry"], "operator.count_rack_in_assembly": True,
    "operator.feeding_tasks": ["assembly", "transport_to_selective"], "operator.unblock_selective_first": True,
    "operator.preempt_review_below": "never", "operator.same_class_order": "FIFO", "assembly.stations": 1, "assembly.output_conveyor_transit": 0,
    "transport_to_selective.exists": True, "transport_to_selective.start_only_if_destination_has_room": True,
    "transport_to_selective.load_time": 3, "transport_to_selective.unload_time": 3, "selective.racks_inside": 1,
    "second_branch.enabled": True, "second_branch.share": 0.2, "second_branch.routing_rule": "probabilistic_share",
    "second_branch.seconds_per_circuit": 5, "second_branch.racks_inside": 1, "transport_to_review.exists": True,
    "transport_to_review.start_only_if_destination_has_room": True, "transport_to_review.load_time": 3, "transport_to_review.unload_time": 3,
    "rack_return.mode": "transport_to_assembly", "rack_return.load_time": 2, "rack_return.unload_time": 2,
    "layout.distances.assembly__selective_in": 5, "layout.distances.assembly__selective_out": 7, "layout.distances.assembly__review": 4,
    "layout.distances.selective_in__selective_out": 3, "layout.distances.selective_in__review": 6, "layout.distances.selective_out__review": 4,
}


def synthetic_dir(tmp_path: Path, **overrides) -> Path:
    d = tmp_path / "bench"
    d.mkdir()
    shutil.copy(BENCH / "selective_soldering_config.yaml", d)
    raw = yaml.safe_load((d / "selective_soldering_config.yaml").read_text())
    for key, val in {**SYNTHETIC, **overrides}.items():
        cur = raw
        for part in key.split("."):
            cur = cur[part]
        cur.update(value=val, status="CONFIRMED", source="SYNTHETIC TEST DATA")
    (d / "selective_soldering_config.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    return d


def C(v):
    return {"dist": "constant", "value": v, "unit": "s"}


# ============================================================ repository state (no invented data)
def test_repository_config_is_blocked_and_reference_is_empty():
    cfg = Config.load(BENCH / "selective_soldering_config.yaml")
    chk = check_inputs(cfg)
    assert not chk.runnable and len(chk.missing) >= 30
    assert {"racks.circuits_per_rack", "operator.wip_target", "operator.walking_speed"} <= set(chk.missing)
    for key, e in cfg.entries():  # nothing marked CONFIRMED without an AnyLogic source
        assert e["status"] in (REQUIRED, "USER_STATED_TO_CONFIRM", "ENGINE_CHOICE"), key
        if e["status"] == REQUIRED:
            assert e["value"] is None, key
    stated = {k: e["value"] for k, e in cfg.entries() if e["status"] == "USER_STATED_TO_CONFIRM"}
    assert stated["assembly.seconds_per_circuit"] == 6 and stated["selective.seconds_per_circuit"] == 5
    ref = load_reference(BENCH / "anylogic_results.csv")
    assert sorted(ref) == list(range(1, 11)) and all(v is None for row in ref.values() for v in row.values())
    with pytest.raises(BenchmarkBlocked):
        build_model(cfg, 3)


# ============================================================ engine semantics
def test_transport_keeps_unit_upstream_until_loaded(registry):
    """No phantom buffer place: while waiting for pickup the unit still occupies the upstream buffer."""
    m = model_from_dict({"meta": {"name": "pickup"}, "simulation": {"horizon": {"value": 1, "unit": "h"}, "trace": True},
                         "resources": [{"id": "op", "quantity": 1}],
                         "nodes": [{"id": "src", "component": "source"},
                                   {"id": "m1", "component": "machine", "params": {"process_time": C(1)}},
                                   {"id": "buf", "component": "buffer", "params": {"capacity": 2}},
                                   {"id": "tr", "component": "transport", "priority": 1, "params": {
                                       "distance": {"value": 50, "unit": "m"}, "speed": {"value": 1, "unit": "m/s"},
                                       "load_time": C(0), "unload_time": C(0), "resources": [{"resource": "op"}]}},
                                   {"id": "out", "component": "sink"}],
                         "edges": [{"source": a, "target": b} for a, b in [("src", "m1"), ("m1", "buf"), ("buf", "tr"), ("tr", "out")]]})
    rec = DesEngine().run(compile_model(m, registry), 1, trace=True)
    assert rec.level_max["buffer:buf"] == 2  # the unit waiting for pickup still counts in the buffer
    # WIP = m1 (1, blocked) + buffer (2) + at most 1 on board -> never more than 4
    assert rec.level_max["wip"] <= 4


def test_missing_travel_data_is_an_error_not_zero(registry):
    m = model_from_dict({"meta": {"name": "travel"}, "simulation": {"horizon": {"value": 1, "unit": "h"}},
                         "resources": [{"id": "op", "quantity": 1, "home": "a", "travel": {"speed": {"value": 1, "unit": "m/s"}}}],
                         "nodes": [{"id": "src", "component": "source"},
                                   {"id": "a", "component": "manual_process", "params": {"process_time": C(10), "resources": [{"resource": "op"}]}},
                                   {"id": "b", "component": "manual_process", "params": {"process_time": C(10), "resources": [{"resource": "op"}]}},
                                   {"id": "out", "component": "sink"}],
                         "edges": [{"source": x, "target": y} for x, y in [("src", "a"), ("a", "b"), ("b", "out")]]})
    with pytest.raises(TravelDataError):
        run_simulation(m, registry)
    data = m.model_dump(mode="json")
    data["resources"][0]["travel"]["distances"] = [{"a": "a", "b": "b", "distance": {"value": 5, "unit": "m"}}]
    res = run_simulation(model_from_dict(data), registry)
    # a 10 s -> walk 5 s -> b 10 s -> walk 5 s back: 30 s per unit -> 120 per hour
    assert res.kpis.mean("units_completed") == pytest.approx(120, abs=1)
    assert res.kpis.mean("resource.op.walking_h") == pytest.approx(1 / 3, rel=0.02)  # 10 s walking per 30 s cycle


def deadlock_model(reserve: bool):
    """Operator carries a unit to a full station that waits for the same operator (circular wait).
    The precondition is EXPLICIT: static priority transport (1) before review (2). With engine 0.2.0 this deadlock
    also appeared under FIFO, but only because of SimPy's internal ordering of two same-instant requests; since
    0.3.0 same-instant ties go to the older unit (the review), so the FIFO variant no longer deadlocks."""
    return model_from_dict({
        "meta": {"name": "deadlock"}, "simulation": {"horizon": {"value": 1, "unit": "h"}},
        "resources": [{"id": "op", "quantity": 1, "dispatch": "priority"}],
        "nodes": [{"id": "src", "component": "source"},
                  {"id": "m1", "component": "machine", "params": {"process_time": C(1)}},
                  {"id": "buf", "component": "buffer", "params": {"capacity": 5}},
                  {"id": "tr", "component": "transport", "priority": 1, "params": {
                      "distance": {"value": 1, "unit": "m"}, "speed": {"value": 1, "unit": "m/s"}, "load_time": C(0),
                      "unload_time": C(0), "resources": [{"resource": "op"}], "reserve_destination": reserve, "return_empty": False}},
                  {"id": "review", "component": "inspection", "priority": 2,
                   "params": {"process_time": C(5), "resources": [{"resource": "op"}]}},
                  {"id": "out", "component": "sink"}],
        "edges": [{"source": a, "target": b} for a, b in [("src", "m1"), ("m1", "buf"), ("buf", "tr"), ("tr", "review"), ("review", "out")]]})


def test_deadlock_is_detected_and_reserve_destination_avoids_it(registry):
    with pytest.raises(DeadlockError) as e:
        run_simulation(deadlock_model(reserve=False), registry)
    assert "DEADLOCK" in str(e.value) and "op" in str(e.value)
    res = run_simulation(deadlock_model(reserve=True), registry)
    # review (5 s) + trip (1 s) per unit, one operator: 6 s -> 600/h
    assert res.kpis.mean("units_completed") == pytest.approx(600, abs=2)


def test_rack_conservation_invariant_catches_a_leak(registry, monkeypatch):
    from simforge.engine.des import nodes

    def leaky_release(ctx, e, resource, via=None):  # simulated engine bug: racks vanish
        e.carriers.clear()

    monkeypatch.setattr(nodes, "release_carrier", leaky_release)
    m = model_from_dict({"meta": {"name": "leak"}, "simulation": {"horizon": {"value": 1, "unit": "h"}},
                         "resources": [{"id": "racks", "kind": "carrier", "quantity": 2}],
                         "nodes": [{"id": "src", "component": "source"},
                                   {"id": "a", "component": "machine", "seize": [{"resource": "racks"}], "params": {"process_time": C(10)}},
                                   {"id": "b", "component": "machine", "release": ["racks"], "params": {"process_time": C(10)}},
                                   {"id": "out", "component": "sink"}],
                         "edges": [{"source": x, "target": y} for x, y in [("src", "a"), ("a", "b"), ("b", "out")]]})
    with pytest.raises(InvariantViolation):
        run_simulation(m, registry)


def test_dispatch_timing_option_changes_only_tie_resolution(registry):
    from tests.test_benchmark_elements import shared_operator_line  # noqa: PLC0415

    base = shared_operator_line("priority", trace=False)
    a = run_simulation(base, registry)
    data = base.model_dump(mode="json")
    data["simulation"]["dispatch_timing"] = "immediate"
    b = run_simulation(model_from_dict(data), registry)
    assert a.model_hash != b.model_hash  # a different semantics is a different model (no cache mix-up)
    assert b.kpis.mean("units_completed") > 0


# ============================================================ benchmark pipeline (SYNTHETIC)
def test_synthetic_benchmark_full_pipeline(tmp_path, registry):
    d = synthetic_dir(tmp_path)
    run = run_benchmark(d, registry, sensitivity=True, charts=True)
    assert run.status.startswith("PRELIMINARY")
    assert sorted(run.engine) == list(range(1, 11))
    for racks, row in run.engine.items():
        assert "error" not in row, row
        assert row["sanity_throughput_le_bound"] is True
        assert row["max_wip"] <= racks + 1  # a rack only exists with its board (+1 unit waiting for a rack at assembly)
        assert row["invariant_checks"] > 0
        total = row["assembly_time_h"] + row["review_time_h"] + row["transport_time_h"] + row["walking_time"] + row["idle_time_h"]
        assert total == pytest.approx(8.0, abs=1e-6)  # one operator: every second accounted for once
        for col in ("operator_utilization", "selective_utilization", "selective_starvation", "selective_blocking"):
            assert 0 <= row[col] <= 1
    with (d / "engine_results.csv").open() as fh:
        header = next(csv.reader(fh))
    with (BENCH / "anylogic_results.csv").open() as fh:
        ref_header = next(csv.reader(fh))
    assert header[: len(ref_header)] == ref_header  # same structure as the AnyLogic template
    for f in ("engine_results_detail.csv", "engine_production_timeseries.csv", "comparison.csv", "run_manifest.json",
              "benchmark_report.md", "required_inputs.md", "charts/production.png", "generated_models/racks_03.yaml"):
        assert (d / f).exists(), f
    report = (d / "benchmark_report.md").read_text()
    for section in ["1. Model configuration", "2. AnyLogic configuration", "3. KPI definitions", "4. Results", "5. Differences",
                    "6. Passed tolerances", "7. Failed tolerances", "8. Possible explanations", "9. Outstanding questions", "10. Validation status"]:
        assert section in report, section
    assert "score" not in report.lower()


def test_synthetic_benchmark_reports_engine_deadlocks(tmp_path, registry, monkeypatch):
    """A deadlocked scenario is reported as an error and blocks validation (never reported as results).
    The deadlock is injected: whether the no-reservation configuration deadlocks depends on same-instant tie
    semantics (it did with engine 0.2.0, it does not with 0.3.0), so it is not a stable way to test reporting."""
    from simforge.engine.des import engine as eng

    def deadlocked_run(self, model, seed, trace=False):
        raise eng.DeadlockError("DEADLOCK (injected for the reporting test)")
    monkeypatch.setattr(eng.DesEngine, "run", deadlocked_run)
    d = synthetic_dir(tmp_path, **{"transport_to_selective.start_only_if_destination_has_room": False,
                                   "transport_to_review.start_only_if_destination_has_room": False})
    run = run_benchmark(d, registry, sensitivity=False, charts=False)
    errors = {sc: r["error"] for sc, r in run.engine.items() if "error" in r}
    assert errors and all("DeadlockError" in v for v in errors.values())
    assert run.status.startswith("NOT VALIDATED")


def test_comparison_formulas_and_tolerance_types():
    engine = {1: {"production": 101.0, "operator_utilization": 0.805, "avg_wip": 0.2, "trips": 10.0}}
    reference = {1: {"production": 100.0, "operator_utilization": 0.80, "avg_wip": 0.0, "trips": None}}  # SYNTHETIC
    tol = {"production": Tolerance("abs", 1), "operator_utilization": Tolerance("pp", 0.4), "avg_wip": Tolerance("rel", 1)}
    rows = {r["kpi"]: r for r in compare(engine, reference, tol)}
    p = rows["production"]
    assert p["absolute_difference"] == 1 and p["relative_error_percent"] == pytest.approx(1.0) and p["status"] == "PASS"
    u = rows["operator_utilization"]
    assert u["pp_difference"] == pytest.approx(0.5) and u["status"] == "FAIL"
    w = rows["avg_wip"]
    assert w["relative_error_percent"] is None and w["status"] == "FAIL_REF_ZERO"
    assert rows["trips"]["status"] == "NO_REFERENCE"
    assert rows["selective_utilization"]["status"] == "NO_ENGINE_VALUE"
    assert len(rows) == len(KPI_COLUMNS)


def test_reference_import_rejects_percentages(tmp_path):
    p = tmp_path / "ref.csv"
    p.write_text("racks,production,operator_utilization\n1,100,85\n")
    with pytest.raises(ReferenceError_):
        load_reference(p)


def test_short_trace_and_cli(tmp_path, registry):
    d = synthetic_dir(tmp_path)
    events, decisions, stem = run_trace(d, registry, racks=3, minutes=10)
    assert events and decisions and max(e["t"] for e in events) <= 600 + 1e-6
    op = [x for x in decisions if x["resource"] == "operator"]
    assert op
    for dec in decisions:
        assert {"time", "resource", "current_task", "candidates", "chosen_node", "reason_code", "reason", "state", "system"} <= set(dec)
        assert "carriers_available" in dec["system"] and "buffers" in dec["system"] and "stations" in dec["system"]
    for dec in op:
        assert {"feed_wip", "target", "selective_1_state"} <= set(dec["state"])
        assert dec["reason_code"] in {"WIP_BELOW_TARGET", "WIP_AT_OR_ABOVE_TARGET", "PROTECTED_BLOCKED", "NO_FEEDER_WAITING",
                                      "ONLY_FEEDER_WAITING", "PREEMPT_WIP_BELOW_THRESHOLD"}
    assert Path(f"{stem}_decisions.csv").exists()
    r = CliRunner().invoke(cli, ["benchmark", "trace", "--dir", str(d), "--racks", "2", "--minutes", "5", "--show", "20"])
    assert r.exit_code == 0 and "DECISION operator" in r.output
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    shutil.copy(BENCH / "selective_soldering_config.yaml", blocked)
    r = CliRunner().invoke(cli, ["benchmark", "selective-soldering", "--dir", str(blocked)])
    assert r.exit_code == 2 and "BLOCKED" in r.output and (blocked / "required_inputs.md").exists()
