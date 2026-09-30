from pathlib import Path

import pytest
from typer.testing import CliRunner

from simforge.cli import app as cli
from simforge.domain.io import load_model
from simforge.experiments.runner import run_experiment, run_simulation
from simforge.reporting.report import build_markdown, experiment_csv, markdown_to_html, results_csv
from simforge.validation.verifier import verify

from .conftest import EXAMPLES

runner = CliRunner()


def test_cli_validate_run_experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    ex = str(EXAMPLES / "02_shared_operator.yaml")
    r = runner.invoke(cli, ["validate", ex])
    assert r.exit_code == 0 and "EXECUTABLE" in r.output
    r = runner.invoke(cli, ["run", ex, "--trace-dir", str(tmp_path / "trace")])
    assert r.exit_code == 0 and "359" in r.output
    assert list((tmp_path / "trace").glob("decisions_*.csv"))
    r = runner.invoke(cli, ["experiment", ex, "--csv", str(tmp_path / "e.csv")])
    assert r.exit_code == 0 and (tmp_path / "e.csv").read_text().count("\n") == 11
    r = runner.invoke(cli, ["experiment", ex, "--factor", "resources.operator_1.quantity=1,2"])
    assert r.exit_code == 0


def test_cli_rejects_bad_model(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("meta: {name: x}\nnodes: [{id: m, component: machine}]\n")
    r = runner.invoke(cli, ["validate", str(bad)])
    assert r.exit_code == 1 and "NO_SOURCE" in r.output


def test_cli_parse_offline(tmp_path):
    out = tmp_path / "m.yaml"
    r = runner.invoke(cli, ["parse", "--offline", "Una máquina de 30 s, luego una cola de 4, y un test de 25 s. Simula 2 horas.", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert load_model(out).simulation.horizon.value == 2


def test_report_contents(registry):
    m = load_model(EXAMPLES / "05_selective_soldering.yaml")
    rep, _ = verify(m, registry)
    res = run_simulation(m, registry)
    exp = run_experiment(m, m.experiments[0], registry)
    md = build_markdown(m, rep, res, exp, "demo")
    for section in ["Executive summary", "Assumptions", "Verification and validation", "Results", "Diagnostics",
                    "Experiment", "Economic impact", "NOT IMPLEMENTED", "Reproducibility", "not approved"]:
        assert section in md, section
    assert f"{res.kpis.mean('throughput_per_hour'):.2f}" in md  # numbers come from the engine
    html = markdown_to_html(md)
    assert "<table>" in html and "<script" not in html
    assert results_csv(res).startswith("metric,")
    assert experiment_csv(exp).count("\n") == 11


def test_ui_flow_headless(tmp_path, monkeypatch):
    """Drives the real Streamlit app: create project, describe, run, chat edit, experiment, report."""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    app_file = Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"
    at = AppTest.from_file(str(app_file), default_timeout=120)
    at.run()
    at.text_input[0].input("UI test").run()
    next(b for b in at.button if b.label == "Create").click().run()
    assert not at.exception
    at.chat_input[0].set_value("Fuente infinita. Un operario realiza montaje durante 60 segundos. Existe un buffer de 5 unidades. "
                               "Una máquina tarda 45 segundos. El mismo operario inspecciona durante 20 segundos. Simular 8 horas.").run()
    assert "Model v1 created" in at.chat_message[-1].markdown[0].value
    next(b for b in at.button if b.label == "RUN SIMULATION").click().run()
    assert not at.exception
    assert ("Units completed", "359") in [(m.label, m.value) for m in at.metric]
    at.chat_input[0].set_value("Prueba buffers entre 1 y 10").run()
    assert "10 escenarios" in at.chat_message[-1].markdown[0].value
    next(b for b in at.button if b.label == "GENERATE REPORT").click().run()
    assert not at.exception and not at.error
