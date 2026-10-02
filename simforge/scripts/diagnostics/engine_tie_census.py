# ruff: noqa: E402, E701, E702 - compact one-off diagnostic script
"""Diagnostic: how often same-instant ties are resolved by the explicit tie-break, per model (engine >= 0.3.0)."""
import sys
import tempfile
import pathlib
import collections
import re
sys.path.insert(0, "src"); sys.path.insert(0, "."); sys.path.insert(0, "scripts/diagnostics")
from simforge.domain.io import load_model
from simforge.library.registry import ComponentRegistry
from simforge.validation.verifier import compile_model
from simforge.engine.des.engine import DesEngine
import simforge.benchmark.selective_soldering as sb
from tests.test_selective_benchmark import synthetic_dir
import selective_racks as S
reg = ComponentRegistry.load_default()
def ties(m, label):
    rec = DesEngine().run(compile_model(m, reg), m.simulation.base_seed, trace=True)
    ops = [x for x in rec.decisions if x["kind"] == "assign" and not x["resource"].startswith("racks")]
    t = [x for x in ops if "tie at" in x["reason"]]
    pairs = collections.Counter()
    for x in t:
        same_t = sorted({c["node"] for c in x["candidates"] if abs(c["waiting_s"]) < 1e-9})
        pairs[f"{'/'.join(same_t)} -> {x['chosen_node']} ({re.search(r'resolved by ([a-z ]+)', x['reason']).group(1)})"] += 1
    print(f"{label:28} decisions {len(ops):5}  ties {len(t):4}  {dict(pairs)}")
for ex in sorted(pathlib.Path("examples").glob("*.yaml")):
    ties(load_model(ex), ex.stem)
for n in (1, 2, 3, 4):
    ties(S.model_for(n)[0], f"selective (test) racks={n}")
cfg = sb.Config.load(synthetic_dir(pathlib.Path(tempfile.mkdtemp())) / "selective_soldering_config.yaml")
for n in (2, 3, 4):
    ties(sb.build_model(cfg, racks=n), f"synthetic benchmark racks={n}")
