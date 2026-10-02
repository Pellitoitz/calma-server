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
    # (1.0 audit) the report no longer claims economics is "NOT IMPLEMENTED": it exists since engine 0.9.0
    for section in ["Executive summary", "Assumptions", "Verification and validation", "Results", "Diagnostics",
                    "Experiment", "Economic evaluation", "No economic evaluation of this run", "Validation status",
                    "Reproducibility", "not approved"]:
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
    run_btn = next(b for b in at.button if b.label == "RUN SIMULATION")
    assert run_btn.disabled  # AI-generated model: approval before the first run
    next(t for t in at.text_input if t.key == "run_approver").input("Engineer").run()
    next(b for b in at.button if b.key == "run_approve").click().run()
    assert not at.exception
    next(b for b in at.button if b.label == "RUN SIMULATION").click().run()
    assert not at.exception
    assert ("Units completed", "359") in [(m.label, m.value) for m in at.metric]
    at.chat_input[0].set_value("Prueba buffers entre 1 y 10").run()
    assert "10 escenarios" in at.chat_message[-1].markdown[0].value
    next(b for b in at.button if b.label == "GENERATE REPORT").click().run()
    assert not at.exception and not at.error


def test_cli_ai_orchestration_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text = ("Fuente infinita. Un operario monta una pieza. Después hay un buffer con capacidad 5. Una máquina procesa cada "
            "pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza durante 20 segundos. "
            "La inspección tiene prioridad sobre el montaje. Simular durante 8 horas. Prueba buffers de 1 a 10.")
    r = runner.invoke(cli, ["ai", "new", "CLI line", text, "--offline"])
    assert r.exit_code == 0, r.output
    assert "REUSE RATIO: 100%" in r.output and "MODEL BUILD PLAN" in r.output
    assert "Para poder ejecutar el modelo necesito 1 dato:" in r.output and "Manual assembly" in r.output
    slug = r.output.strip().splitlines()[-1].split(": ")[1]
    r = runner.invoke(cli, ["ai", "answer", slug, "param:manual_assembly_time=60"])
    assert r.exit_code == 0 and "No falta ningún dato obligatorio" in r.output, r.output
    r = runner.invoke(cli, ["ai", "run", slug])
    assert r.exit_code == 1 and "apruébalo" in r.output
    assert runner.invoke(cli, ["ai", "approve", slug, "--by", "Engineer"]).exit_code == 0
    r = runner.invoke(cli, ["ai", "run", slug])
    assert r.exit_code == 0 and "359" in r.output, r.output
    r = runner.invoke(cli, ["ai", "say", slug, "La inspección tarda 25 segundos porque lo hemos medido", "--yes"])
    assert "20.0 → 25.0" in r.output, r.output
    assert "AI 20.0 -> engineer 25.0" in runner.invoke(cli, ["ai", "corrections", slug]).output
    r = runner.invoke(cli, ["ai", "compare", "examples/02_shared_operator.yaml", f"{slug}@3"])
    assert r.exit_code == 0 and "STRUCTURAL EQUIVALENCE:    YES" in r.output and "RESULT EQUIVALENCE: YES" in r.output, r.output
    r = runner.invoke(cli, ["ai", "productivity", slug, "--manual-min", "240"])
    assert "TIME SAVED %" in r.output and "USER_PROVIDED" in r.output
    assert "offline-rules" in runner.invoke(cli, ["ai", "audit", slug]).output


def test_ui_answers_form_and_productivity(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=120)
    at.run()
    at.text_input[0].input("UI answers").run()
    next(b for b in at.button if b.label == "Create").click().run()
    at.chat_input[0].set_value("Fuente infinita. Un operario monta una pieza. Después hay un buffer con capacidad 5. Una máquina "
                               "procesa cada pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza "
                               "durante 20 segundos. Simular durante 8 horas.").run()
    msg = at.chat_message[-1].markdown[0].value
    assert "REUSE RATIO: 100%" in msg and "MODEL BUILD PLAN" in msg and "necesito 1 dato" in msg
    next(t for t in at.text_input if t.key == "ans_manual_assembly_time").input("60").run()
    next(b for b in at.button if b.label == "Apply answers").click().run()
    assert not at.exception
    assert not any(t.key == "ans_manual_assembly_time" for t in at.text_input)  # nothing missing any more
    assert any("TIME SAVED" in c.value for c in at.code)
