"""Selective-soldering benchmark: configuration -> input checks -> ISMS model.

The configuration (benchmark/selective_soldering_config.yaml) holds EVERY datum with a status.
This module never fills a missing value: it reports it. It only translates confirmed/stated
values into a model built from generic library components (no benchmark-specific engine code).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..domain.io import model_from_dict
from ..domain.isms import ISMSModel

REQUIRED = "REQUIRED_FROM_ANYLOGIC"
STATED = "USER_STATED_TO_CONFIRM"
CONFIRMED = "CONFIRMED"
ENGINE = "ENGINE_CHOICE"
POINTS = ("assembly", "selective_in", "selective_out", "review")


class BenchmarkBlocked(Exception):
    def __init__(self, missing: list[str], invalid: list[str]):
        self.missing, self.invalid = missing, invalid
        super().__init__(f"Benchmark blocked: {len(missing)} missing inputs, {len(invalid)} invalid/unsupported inputs")


@dataclass
class Config:
    path: Path
    raw: dict

    @classmethod
    def load(cls, path: Path) -> "Config":
        return cls(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]

    def entry(self, key: str) -> dict:
        cur: Any = self.raw
        for part in key.split("."):
            cur = cur[part]
        return cur

    def v(self, key: str) -> Any:
        return self.entry(key).get("value")

    def entries(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []

        def walk(obj: Any, prefix: str) -> None:
            if isinstance(obj, dict) and "status" in obj:
                out.append((prefix, obj))
            elif isinstance(obj, dict):
                for k, val in obj.items():
                    if prefix == "" and k == "tolerances":
                        continue
                    walk(val, f"{prefix}.{k}" if prefix else k)

        walk(self.raw, "")
        return out


# ---------------------------------------------------------------------------------------------
# applicability of conditional inputs
# ---------------------------------------------------------------------------------------------
def _true(x: Any) -> bool | None:
    return None if x is None else bool(x)


def visited_points(cfg: Config) -> set[str]:
    pts = {"assembly", "review"}
    if _true(cfg.v("transport_to_selective.exists")):
        pts |= {"assembly", "selective_in"}
    if _true(cfg.v("transport_to_review.exists")):
        pts |= {"selective_out", "review"}
    if cfg.v("rack_return.mode") == "transport_to_assembly":
        pts |= {"review", "assembly"}
    return pts


def applicable(cfg: Config, key: str) -> tuple[bool, str]:
    """Is this input needed given the structural answers so far? (unknown structure -> needed)."""
    if key.startswith("transport_to_selective.") and key != "transport_to_selective.exists":
        e = _true(cfg.v("transport_to_selective.exists"))
        return (e is not False, "only if transport_to_selective.exists = true")
    if key.startswith("transport_to_review.") and key != "transport_to_review.exists":
        e = _true(cfg.v("transport_to_review.exists"))
        return (e is not False, "only if transport_to_review.exists = true")
    if key in ("rack_return.load_time", "rack_return.unload_time"):
        m = cfg.v("rack_return.mode")
        return (m in (None, "transport_to_assembly"), "only if rack_return.mode = transport_to_assembly")
    if key.startswith("second_branch.") and key != "second_branch.enabled":
        e = _true(cfg.v("second_branch.enabled"))
        return (e is not False, "only if second_branch.enabled = true")
    if key == "operator.loaded_speed":
        any_transport = (_true(cfg.v("transport_to_selective.exists")) is not False or _true(cfg.v("transport_to_review.exists")) is not False
                         or cfg.v("rack_return.mode") in (None, "transport_to_assembly"))
        return (any_transport, "only if the operator carries racks")
    if key.startswith("layout.distances."):
        a, b = key.split(".")[-1].split("__")
        known = all(v is not None for v in (cfg.v("transport_to_selective.exists"), cfg.v("transport_to_review.exists"), cfg.v("rack_return.mode")))
        if not known:
            return (True, "needed if the operator moves between these points")
        pts = visited_points(cfg)
        return (a in pts and b in pts, "only if the operator moves between these points")
    return (True, "")


# ---------------------------------------------------------------------------------------------
# input checks
# ---------------------------------------------------------------------------------------------
@dataclass
class InputCheck:
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not self.missing and not self.invalid

    @property
    def official(self) -> bool:
        return self.runnable and not self.unconfirmed


def check_inputs(cfg: Config) -> InputCheck:
    chk = InputCheck()
    for key, e in cfg.entries():
        ok, _why = applicable(cfg, key)
        if not ok:
            chk.not_applicable.append(key)
            continue
        if e.get("value") is None:
            chk.missing.append(key)
        elif e.get("status") == STATED:
            chk.unconfirmed.append(key)
        elif e.get("status") == REQUIRED:
            chk.invalid.append(f"{key}: has a value but status is still {REQUIRED}; set CONFIRMED (and source)")
    # implemented options
    opt_checks = {
        "initial_state.racks_location": ["all_available_at_assembly"],
        "simulation.randomness": ["deterministic"],
        "simulation.production_definition": ["sink_count_at_stop_time", "completions_strictly_before_stop"],
        "second_branch.routing_rule": ["probabilistic_share"],
        "rack_return.mode": ["immediate_at_review_end", "transport_to_assembly"],
        "operator.strategy": ["WIP_TARGET_PRIORITY"],
        "operator.wip_comparison": ["assembly_if_wip < target", "assembly_if_wip <= target"],
        "operator.same_class_order": ["FIFO"],
        "supply.mode": ["infinite"],
        "initial_state.operator_location": ["assembly", "review"],
    }
    for key, allowed in opt_checks.items():
        val = cfg.v(key)
        if val is not None and applicable(cfg, key)[0] and val not in allowed:
            chk.invalid.append(f"{key} = {val!r}: NOT IMPLEMENTED in the benchmark builder (supported: {allowed})")
    loc = cfg.v("operator.wip_counted_locations")
    if loc is not None:
        allowed = set(cfg.entry("operator.wip_counted_locations")["options"])
        if not isinstance(loc, list) or not set(loc) <= allowed:
            chk.invalid.append(f"operator.wip_counted_locations must be a list within {sorted(allowed)}")
    ft = cfg.v("operator.feeding_tasks")
    if ft is not None and (not isinstance(ft, list) or "assembly" not in ft):
        chk.invalid.append("operator.feeding_tasks must be a list that includes 'assembly'")
    pre = cfg.v("operator.preempt_review_below")
    if pre is not None and pre != "never" and not isinstance(pre, int):
        chk.invalid.append("operator.preempt_review_below must be 'never' or an integer")
    if cfg.v("simulation.randomness") == "stochastic":
        chk.invalid.append("simulation.randomness = stochastic: build a deterministic equivalent first (phase rule)")
    return chk


# ---------------------------------------------------------------------------------------------
# model builder (generic components only)
# ---------------------------------------------------------------------------------------------
def _dist(cfg: Config, a: str, b: str) -> float:
    if a == b:
        return 0.0
    key = f"layout.distances.{a}__{b}" if f"{a}__{b}" in cfg.raw["layout"]["distances"] else f"layout.distances.{b}__{a}"
    return float(cfg.v(key))


def _const(v: float) -> dict:
    return {"dist": "constant", "value": v, "unit": "s"}


def build_model(cfg: Config, racks: int) -> ISMSModel:
    chk = check_inputs(cfg)
    if not chk.runnable:
        raise BenchmarkBlocked(chk.missing, chk.invalid)
    v = cfg.v
    circuits = v("racks.circuits_per_rack")
    t_sel = bool(v("transport_to_selective.exists"))
    t_rev = bool(v("transport_to_review.exists"))
    rr_transport = v("rack_return.mode") == "transport_to_assembly"
    branch2 = bool(v("second_branch.enabled"))
    n_ops = int(v("operator.count"))
    point = {"assembly": "assembly", "assembly_conveyor": "assembly", "selective_entry": "selective_in",
             "selective_1": "selective_in", "selective_2": "selective_in", "selective_out": "selective_out", "review": "review"}
    pts = sorted(visited_points(cfg))
    distances = [{"a": a, "b": b, "distance": {"value": _dist(cfg, a, b), "unit": "m"}}
                 for i, a in enumerate(pts) for b in pts[i + 1:]]
    op_uses = [{"resource": "operator"}]

    def transport(tid: str, origin: str, dest: str, prefix: str) -> dict:
        return {"id": tid, "name": tid.replace("_", " "), "component": "rack_transport",
                "params": {"origin": origin, "destination": dest,
                           "distance": {"value": _dist(cfg, point[origin], point[dest]), "unit": "m"},
                           "speed": {"value": v("operator.loaded_speed"), "unit": "m/s"},
                           "capacity": int(v(f"{prefix}.racks_per_trip")) if f"{prefix}.racks_per_trip" in _keys(cfg) else 1,
                           "load_time": _const(v(f"{prefix}.load_time")), "unload_time": _const(v(f"{prefix}.unload_time")),
                           "resources": op_uses, "return_empty": False,
                           "reserve_destination": bool(v(f"{prefix}.start_only_if_destination_has_room"))
                           if f"{prefix}.start_only_if_destination_has_room" in _keys(cfg) else False}}

    transit = float(v("assembly.output_conveyor_transit"))
    conveyor = ({"id": "assembly_conveyor", "name": "Assembly conveyor", "component": "buffer",
                 "params": {"capacity": int(v("assembly.output_conveyor_capacity"))}} if transit == 0 else
                {"id": "assembly_conveyor", "name": "Assembly conveyor", "component": "transport_delay",
                 "notes": "non-accumulating approximation: capacity positions travelling for transit time",
                 "params": {"capacity": int(v("assembly.output_conveyor_capacity")), "process_time": _const(transit)}})
    nodes: list[dict] = [
        {"id": "src", "name": "Supply", "component": "source", "params": {"arrival": "infinite"}},
        {"id": "assembly", "name": "Assembly", "component": "manual_assembly", "seize": [{"resource": "racks"}],
         "params": {"capacity": int(v("assembly.stations")), "process_time": _const(v("assembly.seconds_per_circuit")),
                    "work_units": circuits, "resources": op_uses}},
        conveyor,
    ]
    if t_sel:
        nodes.append(transport("transport_to_selective", "assembly_conveyor", "selective_entry", "transport_to_selective"))
    nodes += [
        {"id": "selective_entry", "name": "Selective entry", "component": "buffer", "params": {"capacity": int(v("selective.input_capacity"))}},
        {"id": "selective_1", "name": "Selective (branch 1)", "component": "selective_soldering",
         "params": {"capacity": int(v("selective.racks_inside")), "process_time": _const(v("selective.seconds_per_circuit")), "work_units": circuits}},
    ]
    if branch2:
        nodes.append({"id": "selective_2", "name": "Selective (branch 2)", "component": "selective_soldering",
                      "params": {"capacity": int(v("second_branch.racks_inside")),
                                 "process_time": _const(v("second_branch.seconds_per_circuit")), "work_units": circuits}})
    nodes.append({"id": "selective_out", "name": "Selective output buffer", "component": "buffer",
                  "params": {"capacity": int(v("selective.output_buffer_capacity"))}})
    if t_rev:
        nodes.append(transport("transport_to_review", "selective_out", "review", "transport_to_review"))
    review = {"id": "review", "name": "Review + cleaning", "component": "inspection", "release": ["racks"],
              "params": {"capacity": int(v("review.tables_per_operator")) * max(n_ops, 1),
                         "process_time": _const(v("review.seconds_per_circuit")), "work_units": circuits, "resources": op_uses}}
    if rr_transport:
        review["release_via"] = {"racks": "rack_return"}
    nodes += [review, {"id": "out", "name": "Output", "component": "sink"}]
    if rr_transport:
        nodes.append(transport("rack_return", "review", "assembly", "rack_return"))
        nodes[-1]["params"]["capacity"] = 1

    chain = ["src", "assembly", "assembly_conveyor"] + (["transport_to_selective"] if t_sel else []) + ["selective_entry"]
    edges = [{"source": a, "target": b} for a, b in zip(chain, chain[1:])]
    share = float(v("second_branch.share")) if branch2 else 0.0
    parameters = []
    if branch2:
        parameters.append({"id": "branch2_share", "value": share, "min": 0, "max": 1, "description": "second branch routing share",
                           "provenance": {"status": "provided_by_client", "source": str(cfg.entry("second_branch.share").get("source"))}})
        edges += [{"source": "selective_entry", "target": "selective_1", "probability": "1 - $branch2_share"},
                  {"source": "selective_entry", "target": "selective_2", "probability": "$branch2_share"},
                  {"source": "selective_2", "target": "selective_out"}]
    else:
        edges.append({"source": "selective_entry", "target": "selective_1"})
    edges.append({"source": "selective_1", "target": "selective_out"})
    tail = ["selective_out"] + (["transport_to_review"] if t_rev else []) + ["review", "out"]
    edges += [{"source": a, "target": b} for a, b in zip(tail, tail[1:])]

    feed_map = {"assembly_conveyor": "assembly_conveyor", "transport_to_selective": "transport_to_selective", "selective_entry": "selective_entry"}
    feed_nodes = [feed_map[x] for x in v("operator.wip_counted_locations") if x != "transport_to_selective" or t_sel]
    feeders = [x for x in v("operator.feeding_tasks") if x == "assembly" or (x == "transport_to_selective" and t_sel)
               or (x == "rack_return" and rr_transport)]
    target = int(v("operator.wip_target")) + (1 if v("operator.wip_comparison") == "assembly_if_wip <= target" else 0)
    pre = v("operator.preempt_review_below")
    operator = {
        "id": "operator", "name": "Shared operator", "kind": "operator", "quantity": n_ops,
        "home": v("initial_state.operator_location"), "dispatch": "wip_target",
        "travel": {"speed": {"value": v("operator.walking_speed"), "unit": "m/s"}, "distances": distances,
                   "locations": {k: val for k, val in point.items()}},
        "wip_target": {"protected_node": "selective_1", "feed_nodes": feed_nodes, "feeder_nodes": feeders, "target": target,
                       "count_feeder_in_process": bool(v("operator.count_rack_in_assembly")),
                       "unblock_protected": bool(v("operator.unblock_selective_first")),
                       "preempt_below": None if pre == "never" else int(pre)},
    }
    horizon = float(v("simulation.horizon"))
    warmup = float(v("simulation.warmup"))
    data = {
        "meta": {"name": f"Selective soldering benchmark - {racks} racks", "domain": "electronics",
                 "tags": ["benchmark", "anylogic"], "description": f"Generated from {cfg.path.name} (config hash {cfg.hash})"},
        "simulation": {"horizon": {"value": horizon, "unit": "h"}, "warmup": {"value": warmup, "unit": "h"},
                       "kind": "terminating", "replications": int(v("simulation.replications")),
                       "base_seed": int(v("simulation.base_seed")), "dispatch_timing": v("simulation.dispatch_timing"),
                       "check_invariants": True},
        "parameters": parameters,
        "resources": [operator, {"id": "racks", "name": "Racks", "kind": "carrier", "quantity": int(racks)}],
        "nodes": nodes, "edges": edges,
    }
    return model_from_dict(data)


def _keys(cfg: Config) -> set[str]:
    return {k for k, _ in cfg.entries()}


# ---------------------------------------------------------------------------------------------
# required-inputs document
# ---------------------------------------------------------------------------------------------
def required_inputs_markdown(cfg: Config) -> str:
    chk = check_inputs(cfg)
    L = ["# Benchmark inputs — selective soldering", "",
         f"Generated from `{cfg.path.name}` (hash `{cfg.hash}`) with `simforge benchmark inputs`. Do not edit by hand.", "",
         f"**Missing (REQUIRED_FROM_ANYLOGIC): {len(chk.missing)}** · stated in conversation, to confirm: {len(chk.unconfirmed)} · "
         f"invalid/unsupported: {len(chk.invalid)} · not applicable with current answers: {len(chk.not_applicable)}", "",
         "| Parameter | Description | Unit | Current value | Source | Status | Where in AnyLogic |", "|---|---|---|---|---|---|---|"]
    for key, e in cfg.entries():
        ok, why = applicable(cfg, key)
        status = e.get("status")
        if not ok:
            status = f"N/A ({why})"
        elif e.get("value") is None:
            status = "**REQUIRED**" + (f" — {why}" if why else "")
        desc = (e.get("note") or "") + (f" Options: {', '.join(map(str, e['options']))}" if e.get("options") else "")
        val = "?" if e.get("value") is None else f"`{e.get('value')}`"
        L.append(f"| `{key}` | {desc.strip()} | {e.get('unit', '')} | {val} | {e.get('source', 'AnyLogic' if status != ENGINE else 'SimForge')} "
                 f"| {status} | {e.get('anylogic', '')} |")
    if chk.invalid:
        L += ["", "## Invalid / unsupported", ""] + [f"- {x}" for x in chk.invalid]
    L += ["", "## AnyLogic results", "",
          "Fill `anylogic_results.csv` (one row per rack count). Units: throughput racks/h; lead_time s; utilizations and "
          "starvation/blocking as fractions 0–1 (not %); walking_time h. Leave empty what AnyLogic does not measure. "
          "Describe how each KPI is computed in AnyLogic in `anylogic_kpi_definitions.yaml`."]
    return "\n".join(L) + "\n"
