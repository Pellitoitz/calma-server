# ruff: noqa: E402, E701, E702 - compact one-off diagnostic script
"""Attribute 0.2.0 -> 0.3.0 changes: revert ONE mechanism at a time on the 0.3.0 engine (diagnostic monkeypatches)."""
import json
import sys
import tempfile
import pathlib
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from simforge.domain.io import load_model
from simforge.library.registry import ComponentRegistry
from simforge.experiments.runner import run_simulation
from simforge.engine.des import dispatch, runtime
from simforge.engine.base import NodeState
reg = ComponentRegistry.load_default()

def old_tie(r): return (r.seq,)            # 0.2.0: request sequence only (SimPy creation order)
def old_feed(self, pool):                  # 0.2.0: slot/vehicle counts, no dedupe
    nodes = pool.ctx.nodes; detail = {nid: nodes[nid].occupancy() for nid in self.p.feed_nodes}; total = sum(detail.values())
    if self.p.count_feeder_in_process:
        for nid in self.p.feeder_nodes:
            c = nodes[nid].state_counts(); n = c.get(NodeState.BUSY, 0) + c.get(NodeState.BLOCKED, 0)
            detail[f"{nid}(in process)"] = n; total += n
    return total, detail
def old_resolution(self):                  # 0.2.0: every pool decides in its own end-of-instant event, all at once
    if self.ctx.dispatch_timing == "immediate":
        return orig_sched(self)
    if not getattr(self, "_pend", False):
        self._pend = True
        def fire():
            self._pend = False
            while self._decide_one(): pass
        self.ctx.at_end_of_timestep(fire)
orig_sched = runtime.ResourcePool._schedule_dispatch
orig_tie, orig_feed = dispatch.tie_key, dispatch.WipTargetPriority.feed_wip

def run_all():
    res = {"05": run_simulation(load_model("examples/05_selective_soldering.yaml"), reg).kpis.mean("units_completed")}
    from tests.test_selective_benchmark import synthetic_dir
    from simforge.benchmark.run_selective_soldering import run_benchmark
    run = run_benchmark(synthetic_dir(pathlib.Path(tempfile.mkdtemp())), reg, sensitivity=False, charts=False)
    res["synthetic"] = [r.get("production", "DEADLOCK") for _, r in sorted(run.engine.items())]
    return res

combos = {"0.3.0 (all fixes)": (), "revert tie-break": ("tie",), "revert feed dedupe": ("feed",),
          "revert resolution": ("res",), "revert tie+res": ("tie", "res"), "revert all three": ("tie", "feed", "res")}
for name, rev in combos.items():
    dispatch.tie_key = old_tie if "tie" in rev else orig_tie
    dispatch.WipTargetPriority.feed_wip = old_feed if "feed" in rev else orig_feed
    runtime.ResourcePool._schedule_dispatch = old_resolution if "res" in rev else orig_sched
    print(f"{name:22}", json.dumps(run_all()))
