"""1.0 release smoke: every CLI group answers --help, invalid input gives categorised errors and the documented exit
codes, and the UI renders every tab of a real project (run + economic evaluation) without exceptions, dead buttons,
'coming soon' placeholders or a global validation claim."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from simforge.cli import run_cli
from simforge.domain.io import load_model

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "examples" / "1_0_golden_project"
GROUPS = ["library", "benchmark", "ai", "data", "project", "calendar", "products", "maintenance", "economics"]
COMMANDS = ["validate", "run", "experiment", "report", "parse", "ui"]


@pytest.mark.parametrize("args", [["--help"]] + [[g, "--help"] for g in GROUPS] + [[c, "--help"] for c in COMMANDS]
                         + [["project", c, "--help"] for c in ("new", "save", "checkout", "baseline", "scenario", "approve",
                                                                "run", "runs", "evaluate", "compare", "report", "manifest",
                                                                "export", "import", "versions")])
def test_cli_help(args):
    code, out = run_cli(args)
    assert code == 0 and "Usage" in out and "Traceback" not in out


def test_cli_invalid_inputs_and_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LOG_DIR", str(tmp_path / "logs"))
    assert run_cli(["no-such-command"])[0] == 2
    assert run_cli(["run"])[0] == 2  # missing argument: usage error
    code, out = run_cli(["run", str(tmp_path / "nope.yaml")])
    assert code == 1 and out.startswith("PERSISTENCE_ERROR")
    code, out = run_cli(["run", str(GOLDEN / "model_with_missing.yaml")])
    assert code == 1 and out.startswith("MODEL_VALIDATION_ERROR") and "MISSING" in out
    code, out = run_cli(["project", "run", "does-not-exist"])
    assert code == 2 and "no encontrado" in out
    code, out = run_cli(["run", str(GOLDEN / "model.yaml"), "--reps", "1"])
    assert code == 0 and "Units completed" in out


def test_ui_smoke_all_tabs(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from simforge.services.app import SimForgeApp
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("Golden UI")
    sf.save_model(p, load_model(GOLDEN / "model.yaml"), "golden baseline")
    sf.approve_model(p, by="process engineer")
    run = sf.run_simulation(p, replications=2)
    sf.evaluate_economics(p, run.run_id)
    at = AppTest.from_file(str(ROOT / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception
    assert len(at.tabs) == 12
    cap = " ".join(c.value for c in at.caption)
    assert "engineer approval: **YES**" in cap and "required MISSING values: **0**" in cap and "engine 0.9.0" in cap
    assert "SYNTHETICALLY_VALIDATED" in cap and "LLM: none — offline" in cap
    texts = " ".join(str(getattr(e, "value", "")) for e in [*at.markdown, *at.caption, *at.info, *at.warning])
    assert not re.search(r"coming soon|próximamente", texts, re.I) and "TODO" not in texts
    assert "REAL_DATA_VALIDATED" not in texts.replace("not REAL_DATA_VALIDATED", "")
    assert all(b.label for b in at.button)  # no anonymous / dead buttons
    next(b for b in at.button if b.label == "RUN SIMULATION").click().run()
    assert not at.exception and any("COMPLETED — run" in s.value for s in at.success)
    next(b for b in at.button if b.label == "Evaluar (sin re-simular)").click().run()
    assert not at.exception
    next(b for b in at.button if b.label == "GENERATE REPORT").click().run()
    assert not at.exception and not at.error
