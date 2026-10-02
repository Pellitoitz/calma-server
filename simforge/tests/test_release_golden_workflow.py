"""1.0 GOLDEN WORKFLOW (release suite). The canonical user flow, end to end, through the real CLI in SEPARATE
PROCESSES (nothing mocked): create project -> MISSING -> resolve -> verify -> review assumptions -> approve -> run ->
KPIs -> scenario -> approve -> run -> economics -> compare -> report / manifest -> export -> close -> reopen in another
workspace -> reproduce. Plus save / close / load / run of a model with every extension block."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "examples" / "1_0_golden_project"
EXPECTED = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
pytestmark = pytest.mark.release


def _env(ws: Path, tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "SIMFORGE_DEBUG")}
    env.update(SIMFORGE_WORKSPACE=str(ws), SIMFORGE_LIBRARY=str(tmp / "lib"), SIMFORGE_LOG_DIR=str(tmp / "logs"))
    return env


def sim(args: list[str], env: dict, cwd: Path, ok: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run([sys.executable, "-m", "simforge.cli", *args], env=env, cwd=cwd, capture_output=True, text=True,
                       timeout=600)
    if ok:
        assert p.returncode == 0, f"{args}: {p.stdout}\n{p.stderr}"
    assert "Traceback" not in p.stdout + p.stderr
    return p


def run_id_of(out: str) -> str:
    return re.search(r"run ([0-9a-f]{10}) \|", out).group(1)


def eval_id_of(out: str) -> str:
    return re.search(r"evaluation ([0-9a-f]{12}) ", out).group(1)


def stored_run(ws: Path, slug: str, run_id: str) -> dict:
    con = sqlite3.connect(ws / "projects" / slug / "project.db")
    row = con.execute("SELECT result_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    con.close()
    return json.loads(row[0])


def test_golden_workflow_end_to_end(tmp_path):
    ws, ws2 = tmp_path / "ws", tmp_path / "ws_other_machine"
    env, cwd = _env(ws, tmp_path), tmp_path  # any working directory: absolute paths only
    # 1-2. create project with a model that still has a MISSING value
    sim(["project", "new", "Golden", "--model", str(GOLDEN / "model_with_missing.yaml")], env, cwd)
    # 3-4. verify: the MISSING value blocks verification and execution (never a default)
    p = sim(["validate", str(GOLDEN / "model_with_missing.yaml")], env, cwd, ok=False)
    assert p.returncode == 1 and "MISSING" in p.stdout and "test_cycle" in p.stdout
    p = sim(["project", "run", "golden"], env, cwd, ok=False)
    assert p.returncode == 1 and "MODEL_VALIDATION_ERROR" in p.stdout + p.stderr and "MISSING" in p.stdout + p.stderr
    sim(["project", "save", "golden", str(GOLDEN / "model.yaml"), "-m", "test cycle measured: 46 s"], env, cwd)
    assert "EXECUTABLE" in sim(["validate", str(GOLDEN / "model.yaml")], env, cwd).stdout
    # 5. review assumptions (economic values are ASSUMED teaching values and are shown as such)
    assert "ECONOMICS_ASSUMED" in sim(["economics", "show", str(GOLDEN / "model.yaml")], env, cwd).stdout
    # 6. approve (bound to the exact content hash)
    sim(["project", "approve", "golden", "--by", "process engineer"], env, cwd)
    assert re.search(r"\* v3\s.*approved=True", sim(["project", "versions", "golden"], env, cwd).stdout)
    # 7-8. run + KPIs
    out = sim(["project", "run", "golden"], env, cwd).stdout
    rb = run_id_of(out)
    assert f"{EXPECTED['baseline']['units_completed']:g}" in out.replace(",", "")
    # 9-10. scenario (derived from the baseline) + its own approval + run
    sim(["project", "baseline", "golden"], env, cwd)
    sim(["project", "scenario", "golden", "faster_test", str(GOLDEN / "alternative.yaml")], env, cwd)
    sim(["project", "approve", "golden", "--by", "process engineer"], env, cwd)
    ra = run_id_of(sim(["project", "run", "golden"], env, cwd).stdout)
    # 11-12. economics (stored runs, no re-simulation) + comparison (facts only)
    out_b = sim(["project", "evaluate", "golden", rb, "--from-run"], env, cwd).stdout
    out_a = sim(["project", "evaluate", "golden", ra, "--from-run"], env, cwd).stdout
    assert "assumptions: the run's own model version" in out_b and "COMPLETE_FOR_REQUESTED_SCOPE" in out_b
    eb, ea = eval_id_of(out_b), eval_id_of(out_a)
    cmp = json.loads(sim(["project", "compare", "golden", eb, ea], env, cwd).stdout)
    assert cmp["status"] == EXPECTED["comparison"]["status"] and cmp["paired"] is True
    assert cmp["payback"]["status"] == EXPECTED["comparison"]["payback_status"]
    assert round(cmp["savings"]["mean"], 2) == EXPECTED["comparison"]["savings_per_run"]
    assert not re.search(r"\b(winner|best|optimal|recommended)\b", json.dumps(cmp).replace("does not rank, choose or recommend", ""))
    # 13. export results: report + manifest
    rep = sim(["project", "report", "golden", "--run-id", rb], env, cwd).stdout
    md = Path(re.search(r"markdown: (.+)", rep).group(1).strip()).read_text(encoding="utf-8")
    assert eb in md and "Validation status" in md and rb in md
    man_path = tmp_path / "manifest.json"
    sim(["project", "manifest", "golden", rb, "-o", str(man_path)], env, cwd)
    man = json.loads(man_path.read_text(encoding="utf-8"))
    assert man["approval"]["approved"] and man["seeds"] == EXPECTED["baseline"]["seeds"] and man["economic_evaluations"]
    # 14-15. save (export) and close (every process above already ended)
    sim(["project", "export", "golden", str(tmp_path / "golden.simproject")], env, cwd)
    # 16. reopen on "another machine" (another workspace)
    env2 = _env(ws2, tmp_path)
    slug2 = re.search(r"Project: (\S+)", sim(["project", "import", str(tmp_path / "golden.simproject")], env2, cwd).stdout).group(1)
    versions = sim(["project", "versions", slug2], env2, cwd).stdout
    assert versions.count("approved=True") == 2
    # 17. reproduce: re-simulate the baseline version WITHOUT any cache and compare replication by replication
    original = stored_run(ws2, slug2, rb)
    vfile = ws2 / "projects" / slug2 / "versions" / f"v{man['model_version']:04d}.yaml"
    again = json.loads(sim(["run", str(vfile), "--json"], env2, cwd).stdout)
    assert again["model_hash"] == original["model_hash"] and again["seeds"] == original["seeds"]
    assert json.dumps(again["per_replication"], sort_keys=True) == json.dumps(original["per_replication"], sort_keys=True)
    assert again["cache_hits"] == 0
    # ...and the economic evaluation of the imported run is the same evaluation (same identity, same numbers)
    out_b2 = sim(["project", "evaluate", slug2, rb, "--from-run"], env2, cwd).stdout
    assert eval_id_of(out_b2) == eb


def test_save_close_load_run_preserves_every_block(tmp_path):
    """save -> export -> NEW PROCESS: import, load, compare the full model (approval, calendars, products, setups,
    maintenance, economics, experiments, provenance) and re-run with the same seeds."""
    from simforge.domain.io import model_from_dict
    from simforge.services.app import SimForgeApp
    from tests.test_economics import full_model
    from tests.test_products_setups import C
    m = full_model()
    d = m.model_dump(mode="json", exclude_none=True)
    d["production"]["setups"] = {"m": {"mode": "CONSTANT_CHANGEOVER", "initial_state": "A", "constant": C(5), "at_unavailability": "FINISH_CURRENT"}}
    d["production"]["products"]["a"]["setup_key"] = "A"
    d["experiments"] = [{"name": "ops", "factors": [{"path": "resources.op.quantity", "values": [1, 2]}]}]
    m = model_from_dict(d)
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("blocks")
    sf.save_model(p, m, "v1")
    sf.approve_model(p, by="eng")
    r = sf.run_simulation(p, replications=2)
    sf.run_experiment(p, m.experiments[0])
    sf.evaluate_economics(p, r.run_id)
    original = p.load_version(p.meta.current_version).model_dump(mode="json")
    p.close()
    arch = sf.workspace.export_project("blocks", tmp_path / "blocks.simproject")
    code = f"""
import json, sys
from pathlib import Path
from simforge.services.app import SimForgeApp
sf = SimForgeApp(workspace=Path(r"{tmp_path / 'ws2'}"), library_dir=Path(r"{tmp_path / 'lib'}"), provider=None)
p = sf.workspace.import_project(Path(r"{arch}"))
m = p.load_version(p.meta.current_version)
r = sf.run_simulation(p, model=m, replications=2)
print(json.dumps({{"model": m.model_dump(mode="json"), "approved": m.is_approved, "per_rep": r.per_replication,
                  "experiments": len(p.experiments()), "evaluations": len(p.evaluations()), "runs": len(p.runs())}}))
"""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=600)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["model"] == original and got["approved"] is True
    for block in ("availability", "production", "maintenance", "economics", "experiments", "approval"):
        assert got["model"].get(block) == original.get(block), block
    assert json.dumps(got["per_rep"], sort_keys=True) == json.dumps(r.per_replication, sort_keys=True)
    assert got["experiments"] == 1 and got["evaluations"] == 1 and got["runs"] == 2


def test_golden_expected_results_are_engine_results():
    """expected.json documents the golden results; they must stay exactly what the engine computes (regression)."""
    from simforge.domain.io import load_model
    from simforge.experiments.runner import run_simulation
    from simforge.library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default(None)
    for name, f in (("baseline", "model.yaml"), ("alternative", "alternative.yaml")):
        r = run_simulation(load_model(GOLDEN / f), reg)
        assert r.seeds == EXPECTED[name]["seeds"]
        for k, v in EXPECTED[name]["kpis_mean"].items():
            assert round(r.kpis.mean(k), 4) == v, (name, k)
