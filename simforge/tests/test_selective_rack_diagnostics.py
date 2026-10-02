"""Regression coverage for the selective-soldering rack anomaly (docs/diagnostics/selective_rack_anomaly.md).

Deliberately NO golden numbers: these tests pin invariants and relations demonstrated in the diagnosis.
The two defects found (same-instant contract, feed-WIP double count) were pinned as xfail(strict) and are fixed
since engine 0.3.0; their tests now pass as regular tests.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "diagnostics"))
import selective_racks as S  # noqa: E402

WORK_PER_RACK = 4 * 30 + 5 + 10 / 1.2 + 5 + 4 * 15  # assembly + load + loaded travel + unload + review (s)


def test_diagnostic_model_is_the_tested_configuration():
    m, _ = S.model_for(3)
    p = {x.id: x.value for x in m.parameters}
    assert p == {"circuitos_per_unit": 4, "manual_assembly_time": 30, "transport_1_load_time": 5, "transport_1_unload_time": 5,
                 "buffer_de_entrada_capacity": 3, "selective_soldering_time": 20, "inspection_time": 15, "racks_count": 3,
                 "operator_1_count": 1, "dist_manual_assembly_buffer_de_entrada": 10, "dist_buffer_de_entrada_inspection": 5,
                 "operator_walking_speed": 1.2, "wip_target": 2}
    op = next(r for r in m.resources if r.id == "operator_1")
    assert op.dispatch.value == "wip_target" and op.wip_target.feed_nodes == [S.BUF]
    assert op.wip_target.feeder_nodes == [S.ASM, S.TRN] and op.wip_target.unblock_protected
    assert m.simulation.dispatch_timing == "end_of_timestep"


@pytest.mark.parametrize("racks", [1, 2, 3, 4])
def test_operator_time_balance_and_rack_conservation(racks):
    rec, k, _ = S.run(racks)
    st = rec.resource_state_time["operator_1"]
    assert sum(st.values()) == pytest.approx(rec.horizon_s)  # work + walking + transporting + idle = horizon
    # a single operator bounds production: never more units than horizon / pure work per rack
    assert k["units_completed"] <= rec.horizon_s / WORK_PER_RACK
    rows = S.rack_tracking(rec, racks)
    assert rec.invariant_checks > 0 and rows and all(r["sum_ok"] for r in rows)


def test_drop_from_2_to_3_racks_is_operator_walking():
    """Demonstrated mechanism: with walking (operator travel) made ~free, the 2->3 drop disappears."""
    free = {"resources.operator_1.travel.speed": {"value": 1000, "unit": "m/s"}}
    p2 = S.run_variant(2, free)[1]["units_completed"]
    p3 = S.run_variant(3, free)[1]["units_completed"]
    assert abs(p2 - p3) <= 1
    # and in the base runs the operator never idles: lost production == extra walking
    (r2, _, _), (r3, _, _) = S.run(2), S.run(3)
    for r in (r2, r3):
        assert r.resource_state_time["operator_1"].get("idle", 0.0) == pytest.approx(0.0)


def test_three_racks_reviews_are_forced_by_protected_blocked_rule():
    """WIP_TARGET_PRIORITY rule 1 (contract): with >= 3 racks every review decision comes from PROTECTED_BLOCKED."""
    rec, _, _ = S.run(3)
    reviews = [d for d in rec.decisions if d["resource"] == "operator_1" and d["chosen_node"] == S.INS]
    assert reviews and all(d["reason_code"] == "PROTECTED_BLOCKED" for d in reviews)


@pytest.mark.parametrize("racks", [2, 3])
def test_feed_wip_target_is_never_reached_at_decisions(racks):
    """Structural fact of this configuration (single operator, selective much faster than the operator): at decision
    instants the feed WIP is 0 or 1, so targets 2, 3, 4 behave identically. If this fails, re-run the diagnosis."""
    rec, _, _ = S.run(racks)
    feeds = {d["state"]["feed_wip"] for d in rec.decisions if d["resource"] == "operator_1"}
    assert feeds <= {0, 1}


def test_end_of_timestep_every_simultaneous_request_competes():
    """Fixed in engine 0.3.0 (was xfail): requests cascaded at the same instant compete (68 misses with 0.2.0)."""
    rec, _, _ = S.run(2)
    assert S.missed_simultaneous_requests(rec) == []


def test_feed_wip_counts_each_physical_unit_once():
    """Fixed in engine 0.3.0 (was xfail): a rack seen both at the assembly place (BLOCKED) and by the transport that
    reserved it counts once ('shared'); the feed WIP never exceeds the number of physical units that could count."""
    samples = S.feed_wip_probe(2)
    assert not any(p["same_unit_counted_twice"] for p in samples)
    assert any(p["shared"] for p in samples)  # the overlap window exists and is deduplicated
