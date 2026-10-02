# ruff: noqa: E402, E701, E702 - compact one-off diagnostic script
"""Diagnostic: run the same measurements on two engine versions. Usage: python scripts/diagnostics/engine_before_after.py <repo_root> (e.g. a git worktree of the older commit)."""
import json
import sys
import tempfile
import pathlib
root = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root / "src")); sys.path.insert(0, str(root))
from simforge import ENGINE_VERSION
from simforge.domain.io import load_model
from simforge.domain.paths import set_value
from simforge.library.registry import ComponentRegistry
from simforge.experiments.runner import run_simulation
from simforge.services.app import SimForgeApp
reg = ComponentRegistry.load_default()
out = {"engine": ENGINE_VERSION}
for ex in sorted((root / "examples").glob("*.yaml")):
    m = load_model(ex); r = run_simulation(m, reg)
    out[ex.stem] = r.kpis.mean("units_completed")
t = pathlib.Path(tempfile.mkdtemp()); app = SimForgeApp(workspace=t / "ws", library_dir=t / "lib", provider=None)
from tests.test_nl_orchestration import MVP_SPEC_TEXT
from tests.test_nl_selective import SELECTIVE_TEXT, ANSWERS
p = app.create_project("mvp"); m = app.parse_process(p, MVP_SPEC_TEXT).outcome.model
out["MVP (generated)"] = run_simulation(m, reg).kpis.mean("units_completed")
p = app.create_project("sel"); app.parse_process(p, SELECTIVE_TEXT); m = app.answer_questions(p, ANSWERS).outcome.model
for n in range(1, 11):
    out[f"selective racks={n}"] = run_simulation(set_value(m, "parameters.racks_count.value", n), reg).kpis.mean("units_completed")
from tests.test_selective_benchmark import synthetic_dir
from simforge.benchmark.run_selective_soldering import run_benchmark
for label, kw in (("synthetic benchmark (reservation)", {}), ("synthetic benchmark (NO reservation)",
        {"transport_to_selective.start_only_if_destination_has_room": False, "transport_to_review.start_only_if_destination_has_room": False})):
    run = run_benchmark(synthetic_dir(pathlib.Path(tempfile.mkdtemp()), **kw), reg, sensitivity=False, charts=False)
    out[label] = [r.get("production", "DEADLOCK" if "error" in r else None) for _, r in sorted(run.engine.items())]
print(json.dumps(out))
