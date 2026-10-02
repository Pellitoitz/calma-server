"""1.0 release readiness: real bugs found by the release audit (each test failed before its fix) and the release
contracts of persistence, lineage, cache, migrations, failed / interrupted runs, error taxonomy and the
reproducibility manifest."""

from __future__ import annotations

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from simforge.cli import app as cli
from simforge.domain.io import load_model
from simforge.domain.paths import set_value
from simforge.experiments.runner import run_simulation
from simforge.library.registry import ComponentRegistry
from simforge.persistence import db
from simforge.services.app import SimForgeApp

from .conftest import EXAMPLES


class MemCache:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def put(self, k, v):
        self.d[k] = v


@pytest.fixture
def sf(tmp_path):
    return SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)


# ------------------------------------------------------------------------------------------------ S1: cache
def test_cache_key_depends_on_the_component_definitions_used():
    """BUG S1 (fixed): a newer library version of a component (other defaults) reused cached KPIs of the old one:
    wrong physical result (59 instead of 118) with a run that claimed machine@9.0.0."""
    m = load_model(EXAMPLES / "01_simple_line.yaml")
    reg = ComponentRegistry.load_default(None)
    cache = MemCache()
    old = run_simulation(m, reg, cache=cache)
    reg2 = ComponentRegistry.load_default(None)
    c = reg2.get("machine")
    reg2.register(c.model_copy(update={"version": "9.0.0", "defaults": {**c.defaults, "capacity": 2}}))
    fresh = run_simulation(m, reg2)
    cached = run_simulation(m, reg2, cache=cache)
    assert old.kpis.mean("units_completed") == 59 and fresh.kpis.mean("units_completed") == 118
    assert cached.cache_hits == 0 and cached.kpis.mean("units_completed") == 118
    again = run_simulation(m, reg2, cache=cache)  # same physics + same library -> the cache is still used
    assert again.cache_hits == 1 and again.per_replication == cached.per_replication


def test_economics_change_still_hits_the_physical_cache():
    m = load_model(EXAMPLES / "01_simple_line.yaml")
    reg, cache = ComponentRegistry.load_default(None), MemCache()
    run_simulation(m, reg, cache=cache)
    from simforge.domain.io import model_from_dict
    with_econ = model_from_dict({**m.model_dump(mode="json", exclude_none=True), "economics": {"currency": "EUR"}})
    assert run_simulation(with_econ, reg, cache=cache).cache_hits == 1  # economics never invalidates the DES cache


# ------------------------------------------------------------------------------------------------ S1: lineage
def test_run_and_report_are_bound_to_the_version_actually_executed(sf):
    """BUG S1 (fixed): running a non-current model stored the run under the CURRENT version: run_model_of returned
    another model and the report described v2 next to the results of v1."""
    p = sf.create_project("lin")
    m1 = load_model(EXAMPLES / "01_simple_line.yaml")
    sf.save_model(p, m1, "v1")
    m2 = set_value(m1, "nodes.m2.params.process_time.value", 30)
    sf.save_model(p, m2, "v2")
    r = sf.run_simulation(p, model=m1)
    assert p.db.execute("SELECT model_version FROM runs WHERE run_id = ?", (r.run_id,)).fetchone()[0] == 1
    assert sf.run_model_of(p, r.run_id).content_hash() == r.model_hash
    md = sf.generate_report(p, run_id=r.run_id)["markdown"].read_text(encoding="utf-8")
    assert "constant(value=45" in md and "constant(value=30" not in md
    unsaved = set_value(m1, "nodes.m1.params.process_time.value", 50)
    r3 = sf.run_simulation(p, model=unsaved)
    with pytest.raises(ValueError, match="no guardado"):
        sf.run_model_of(p, r3.run_id)  # never silently replaced by the current version


def test_experiment_bound_to_its_version(sf):
    from simforge.experiments.runner import ExperimentSpec
    p = sf.create_project("exp")
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    sf.save_model(p, m, "v1")
    sf.save_model(p, set_value(m, "simulation.horizon.value", 2), "v2")
    spec = ExperimentSpec.model_validate({"name": "q", "factors": [{"path": "resources.operator_1.quantity", "values": [1, 2]}]})
    res = sf.run_experiment(p, spec, model=m)
    assert p.db.execute("SELECT model_version FROM experiments WHERE experiment_id = ?", (res.experiment_id,)).fetchone()[0] == 1


# ------------------------------------------------------------------------------------------------ S2: migrations
def test_failed_migration_is_atomic_and_retryable(tmp_path, monkeypatch):
    """BUG S2 (fixed): a migration failing half-way left its first statements applied and unrecorded: the project
    could never be opened again ('table already exists')."""
    path = tmp_path / "p.db"
    db.connect(path).close()
    n = len(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + ["CREATE TABLE extra_a (x INTEGER); CREATE TABLE extra_b (y INTEGER;"])
    with pytest.raises(sqlite3.Error):
        db.connect(path)
    conn = sqlite3.connect(path)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name = 'extra_a'").fetchall()
    assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == list(range(1, n + 1))
    conn.close()
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:n] + ["CREATE TABLE extra_a (x INTEGER); CREATE TABLE extra_b (y INTEGER);"])
    db.connect(path).close()  # fixed migration applies cleanly
    backups = list(tmp_path.glob("p.db.pre-migration-v*.bak"))
    assert backups and sqlite3.connect(backups[0]).execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == n


def test_migrations_from_empty_and_from_each_historical_version(tmp_path):
    for k in range(0, len(db.MIGRATIONS) + 1):
        path = tmp_path / f"h{k}.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        for i, sql in enumerate(db.MIGRATIONS[:k], start=1):
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (i,))
        if k >= 1:
            conn.execute("INSERT INTO history(ts, actor, action) VALUES ('t', 'user', 'kept')")
        conn.commit()
        conn.close()
        c = db.connect(path)
        assert db.schema_version(c) == len(db.MIGRATIONS)
        assert db.migrate(c) == len(db.MIGRATIONS)  # idempotent
        if k >= 1:
            assert c.execute("SELECT action FROM history").fetchone()[0] == "kept"  # no data lost
        c.close()


# ------------------------------------------------------------------------------------------------ failed / interrupted runs
def test_failed_and_interrupted_runs_are_never_completed(sf, monkeypatch):
    p = sf.create_project("crash")
    sf.save_model(p, load_model(EXAMPLES / "01_simple_line.yaml"), "v1")
    import simforge.services.app as svc

    def boom(*a, **k):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(svc, "run_simulation", boom)
    with pytest.raises(RuntimeError):
        sf.run_simulation(p)
    assert p.runs() == [] and p.history(1)[0]["action"] == "run_failed"
    assert "RuntimeError: engine exploded" in p.history(1)[0]["result"]

    def interrupt(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(svc, "run_simulation", interrupt)
    with pytest.raises(KeyboardInterrupt):
        sf.run_simulation(p)
    assert p.runs() == [] and p.history(1)[0]["action"] == "run_interrupted"


# ------------------------------------------------------------------------------------------------ CLI error taxonomy
def test_cli_errors_are_categorised_without_raw_traceback(tmp_path, monkeypatch):
    from simforge import cli as climod
    monkeypatch.setenv("SIMFORGE_LOG_DIR", str(tmp_path / "logs"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("meta: {name: x}\nnodes: [{id: m, component: machine, nope: 1}]\n")
    code, out = climod.run_cli(["run", str(bad)])
    assert code == 1 and out.startswith("MODEL_VALIDATION_ERROR") and "Traceback" not in out
    code, out = climod.run_cli(["run", str(tmp_path / "missing.yaml")])
    assert code == 1 and out.startswith(("PERSISTENCE_ERROR", "MODEL_VALIDATION_ERROR")) and "Traceback" not in out
    monkeypatch.setattr(climod, "_registry", lambda: (_ for _ in ()).throw(ZeroDivisionError("x")))
    code, out = climod.run_cli(["run", str(EXAMPLES / "01_simple_line.yaml")])
    assert code == 70 and out.startswith("INTERNAL_ERROR") and "Traceback" not in out
    log = next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
    assert "Traceback" in log and "ZeroDivisionError" in log  # kept for diagnosis
    assert climod.run_cli(["--help"])[0] == 0


@pytest.mark.parametrize("exc,cat", [
    ("ModelError", "MODEL_VALIDATION_ERROR"), ("ApprovalRequired", "ENGINEER_DECISION_REQUIRED"),
    ("EconomicsError", "ECONOMICS_ERROR"), ("ProjectError", "PERSISTENCE_ERROR"), ("DatasetError", "DATA_ERROR"),
    ("MissingParameter", "MISSING_INPUT"), ("DeadlockError", "SIMULATION_ERROR"), ("KeyError", "INTERNAL_ERROR")])
def test_error_taxonomy(exc, cat):
    from simforge import errors
    from simforge.data.store import DatasetError
    from simforge.domain.expressions import MissingParameter
    from simforge.economics.evaluate import EconomicsError
    from simforge.engine.des.engine import DeadlockError
    from simforge.persistence.project import ProjectError
    from simforge.services.app import ApprovalRequired
    from simforge.validation.verifier import ModelError, VerificationReport
    make = {"ModelError": lambda: ModelError(VerificationReport()), "ApprovalRequired": lambda: ApprovalRequired("x"),
            "EconomicsError": lambda: EconomicsError("x"), "ProjectError": lambda: ProjectError("x"),
            "DatasetError": lambda: DatasetError("x"), "MissingParameter": lambda: MissingParameter("p"),
            "DeadlockError": lambda: DeadlockError("x"), "KeyError": lambda: KeyError("x")}
    assert errors.classify(make[exc]()) == cat


# ------------------------------------------------------------------------------------------------ manifest
def test_reproducibility_manifest(sf):
    from simforge.reporting.manifest import build_manifest
    p = sf.create_project("man")
    m = load_model(EXAMPLES / "05_selective_soldering.yaml")
    sf.save_model(p, m, "v1")
    sf.approve_model(p, by="eng")
    r = sf.run_simulation(p)
    man = build_manifest(p, r.run_id)
    for k in ("manifest_version", "simforge_version", "engine", "engine_version", "run_id", "model_version",
              "physical_model_hash", "approval", "availability_hash", "production_hash", "maintenance_hash", "seeds",
              "horizon_s", "warmup_s", "replications", "component_versions", "datasets", "economic_evaluations"):
        assert k in man, k
    assert man["approval"]["approved"] is True and man["approval"]["model_hash"] == man["physical_model_hash"]
    assert man["physical_model_hash"] == r.model_hash and man["seeds"] == r.seeds and man["model_version"] == 2
    json.dumps(man, allow_nan=False)
    res = CliRunner().invoke(cli, ["project", "manifest", p.meta.slug, r.run_id], env={"SIMFORGE_WORKSPACE": str(sf.workspace.root)})
    assert res.exit_code == 0 and json.loads(res.output)["run_id"] == r.run_id


def test_report_states_economics_and_validation_status_truthfully(sf):
    """BUG S2 (fixed): the report said 'Economic impact: NOT IMPLEMENTED (economics layer pending)' although the
    economics layer exists since 0.9.0 (false statement in a user-facing deliverable)."""
    from tests.test_economics import full_model
    p = sf.create_project("rep")
    sf.save_model(p, full_model(), "v1")
    sf.approve_model(p, by="eng")
    r = sf.run_simulation(p)
    ev = sf.evaluate_economics(p, r.run_id)
    md = sf.generate_report(p, run_id=r.run_id)["markdown"].read_text(encoding="utf-8")
    assert "NOT IMPLEMENTED in v0.1" not in md and "economics layer pending" not in md
    assert ev.evaluation_id in md and "evaluated_total_cost" in md and "NOT a full production cost" in md
    assert "SYNTHETICALLY_VALIDATED" in md and "REAL_DATA_VALIDATED" not in md.replace("not REAL_DATA_VALIDATED", "")
    for k in ("horizon", "warm-up", "replications", "seeds", "model_hash", "engine"):
        assert k in md.split("## Reproducibility")[1]
