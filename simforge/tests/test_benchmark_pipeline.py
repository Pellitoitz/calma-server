"""Benchmark pipeline. The repository template must stay INCOMPLETE (no invented data);
the pipeline is exercised on a temporary copy filled with SYNTHETIC values."""

import csv
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from simforge.benchmark.bench import BenchmarkSpec, compare, load_reference, run_engine, write_outputs, BenchmarkNotReady
from simforge.cli import app as cli

BENCH = Path(__file__).parents[1] / "benchmarks" / "selective_soldering"
SYNTHETIC = {"circuits_per_rack": 10, "n_operators": 1, "assembly_stations": 1, "t_selective2_per_circuit": 5,
             "branch2_share": 0.2, "wip_target": 2, "operator_speed": 1.0, "d_assembly_review": 4,
             "t_rack_load": 2, "t_rack_unload": 2}


def test_repository_template_has_no_invented_data(registry):
    spec = BenchmarkSpec.load(BENCH / "benchmark.yaml")
    ref = load_reference(BENCH / spec.reference_csv, spec)
    assert sorted(ref) == list(range(1, 11))
    assert all(v is None for row in ref.values() for v in row.values()), "AnyLogic results must be imported, never invented"
    with pytest.raises(BenchmarkNotReady) as e:
        run_engine(spec, BENCH, registry)
    missing = {i.path.split(".")[1] for i in e.value.report.errors if i.code == "MISSING"}
    assert {"circuits_per_rack", "operator_speed", "d_assembly_review", "branch2_share", "wip_target"} <= missing
    model = yaml.safe_load((BENCH / "model.yaml").read_text())
    given = {p["id"]: p["value"] for p in model["parameters"]}
    assert (given["t_assembly_per_circuit"], given["t_review_per_circuit"], given["t_selective_per_circuit"]) == (6, 2, 5)


@pytest.fixture
def synthetic_bench(tmp_path):
    d = tmp_path / "bench"
    shutil.copytree(BENCH, d)
    m = yaml.safe_load((d / "model.yaml").read_text())
    for p in m["parameters"]:
        if p["id"] in SYNTHETIC:
            p["value"] = SYNTHETIC[p["id"]]
            p["provenance"] = {"status": "assumed", "note": "SYNTHETIC test value"}
    (d / "model.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    return d


def test_synthetic_benchmark_runs_all_scenarios(synthetic_bench, registry):
    spec = BenchmarkSpec.load(synthetic_bench / "benchmark.yaml")
    exp = run_engine(spec, synthetic_bench, registry)
    assert [s.factors[spec.factor.path] for s in exp.scenarios] == list(range(1, 11))
    assert all(s.result is not None for s in exp.scenarios)
    for s in exp.scenarios:
        k = s.result.kpis
        assert k.mean("avg_wip") <= s.factors[spec.factor.path] + 1 + 1e-9  # racks cap WIP (+1 waiting for a rack)
        assert abs(k.mean("node.rack_return.trips") - k.mean("units_completed")) <= s.factors[spec.factor.path]
    paths = write_outputs(spec, synthetic_bench, exp, registry)
    rows = list(csv.DictReader(paths["comparison_csv"].open()))
    assert len(rows) == 10 * len(spec.metrics) and {r["status"] for r in rows} == {"NO_REFERENCE"}


def test_error_formulas_and_statuses():
    spec = BenchmarkSpec.load(BENCH / "benchmark.yaml")
    engine = [{"racks": 1, "production": 110.0, "production__ci95": None, "avg_wip": 2.0},
              {"racks": 2, "production": 100.0, "production__ci95": None, "avg_wip": 0.3}]
    # SYNTHETIC reference values, only to check the formulas
    reference = {1.0: {"production": 100.0, "avg_wip": 2.0}, 2.0: {"production": None, "avg_wip": 0.0}}
    rows = {(r["scenario"], r["metric"]): r for r in compare(spec, engine, reference, deterministic=True)}
    r = rows[(1, "production")]
    assert r["abs_error"] == 10.0 and r["rel_error_pct"] == pytest.approx(10.0) and r["status"] == "DIFF"
    assert "randomness excluded" in r["noise_check"]
    assert rows[(1, "avg_wip")]["status"] == "OK"
    assert rows[(2, "production")]["status"] == "NO_REFERENCE"
    z = rows[(2, "avg_wip")]
    assert z["rel_error_pct"] is None and z["status"] == "DIFF_REF_ZERO"


def test_cli_benchmark_flow(synthetic_bench):
    runner = CliRunner()
    r = runner.invoke(cli, ["benchmark", "status", str(BENCH / "benchmark.yaml")])
    assert r.exit_code == 1 and "INCOMPLETE" in r.output
    r = runner.invoke(cli, ["benchmark", "run", str(synthetic_bench / "benchmark.yaml"), "--trace-scenario", "3"])
    assert r.exit_code == 0, r.output
    assert (synthetic_bench / "results" / "trace_racks_3" / "decisions.csv").exists()
    md = (synthetic_bench / "results" / "comparison.md").read_text()
    assert "NOT PROVIDED" in md and "Cause checklist" in md
    # refuses to overwrite a reference CSV that already has values
    ref = synthetic_bench / "anylogic_results.csv"
    ref.write_text(ref.read_text().replace("1,,", "1,999,", 1))
    r = runner.invoke(cli, ["benchmark", "template", str(synthetic_bench / "benchmark.yaml")])
    assert r.exit_code == 1


def test_ui_and_report_handle_parameter_expressions(synthetic_bench, tmp_path, monkeypatch, registry):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from simforge.domain.io import load_model
    from simforge.reporting.report import build_markdown
    from simforge.services.app import SimForgeApp
    from simforge.validation.verifier import verify

    model = load_model(synthetic_bench / "model.yaml")
    md = build_markdown(model, verify(model, registry)[0], None)
    assert "Model parameters" in md and "circuits_per_rack" in md
    monkeypatch.setenv("SIMFORGE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SIMFORGE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = SimForgeApp(provider=None)
    p = app.create_project("bench ui")
    app.save_model(p, model, "synthetic")
    at = AppTest.from_file(str(Path(__file__).parents[1] / "src" / "simforge" / "ui" / "app.py"), default_timeout=180)
    at.session_state["project"] = p.meta.slug
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "RUN SIMULATION").click().run()
    assert not at.exception and not at.error
