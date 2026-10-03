"""Release versioning contract (1.0.0-rc1). PRODUCT version (SimForge as a workbench) and ENGINE_VERSION (simulation
contract used for reproducibility / lineage) are independent. One source of truth for the product version:
`simforge.__version__` (PEP 440 form of "1.0.0-rc1"), read by the package metadata."""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

import simforge
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "1.0.0rc1"  # PEP 440 normalisation of 1.0.0-rc1
DISPLAY = "1.0.0-rc1"
ENGINE = "0.9.0"


def test_product_version_single_source_of_truth():
    assert simforge.__version__ == PRODUCT and str(Version(DISPLAY)) == PRODUCT
    v = Version(simforge.__version__)
    assert v.is_prerelease and v.pre == ("rc", 1) and v.release == (1, 0, 0)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in project["project"] and "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "simforge.__version__"}


def test_installed_metadata_matches_the_package():
    # the editable / installed distribution must identify the same product version (stale metadata = reinstall)
    assert importlib.metadata.version("simforge") == simforge.__version__


def test_engine_version_is_independent_of_the_product_version():
    from simforge.experiments.runner import cache_key
    assert simforge.ENGINE_VERSION == ENGINE and simforge.ENGINE_VERSION != simforge.__version__
    from simforge.domain.economics import ECONOMICS_ENGINE_VERSION
    assert ECONOMICS_ENGINE_VERSION == "0.9.0"
    k = cache_key("h", 1, "c")
    simforge.__version__, old = "9.9.9", simforge.__version__
    try:
        import simforge.experiments.runner as runner
        assert runner.cache_key("h", 1, "c") == k  # product version never enters physical cache identity
    finally:
        simforge.__version__ = old


def test_public_surfaces_show_the_same_product_version(tmp_path):
    from simforge.domain.io import load_model
    from simforge.reporting.manifest import build_manifest
    from simforge.services.app import SimForgeApp
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("v")
    sf.save_model(p, load_model(ROOT / "examples" / "01_simple_line.yaml"), "v1")
    r = sf.run_simulation(p)
    assert r.app_version == PRODUCT and r.engine_version == ENGINE
    man = build_manifest(p, r.run_id)
    assert man["simforge_version"] == PRODUCT and man["engine_version"] == ENGINE and man["current_engine_version"] == ENGINE
    md = sf.generate_report(p, run_id=r.run_id)["markdown"].read_text(encoding="utf-8")
    assert f"app {PRODUCT}" in md and f"{ENGINE}" in md
    ui = (ROOT / "src" / "simforge" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "__version__" in ui  # the UI header shows the product version next to the engine version


def test_docs_declare_rc1_consistently():
    notes = (ROOT / "docs" / "release" / "1.0.0-rc1_release_notes.md").read_text(encoding="utf-8")
    assert DISPLAY in notes and f"`{PRODUCT}`" in notes and "ENGINE_VERSION" in notes
    assert "NOT_EXECUTED" in notes and "READY_FOR_REAL_ECONOMIC_VALIDATION" in notes
    crit = (ROOT / "docs" / "release" / "1.0_release_criteria.md").read_text(encoding="utf-8")
    assert f"`{PRODUCT}`" in crit and not re.search(r"__version__` / pyproject \| `0\.1\.0`", crit)
    assert DISPLAY in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
