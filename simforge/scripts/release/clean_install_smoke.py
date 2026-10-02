"""Clean-machine install smoke (1.0): a NEW virtual environment, the package installed from this checkout, run from
another directory, empty workspace, no PYTHONPATH, no API key. Needs network access to the package index (or a
pre-populated pip cache / wheelhouse via PIP_FIND_LINKS). Prints PASS or FAIL.

    python scripts/release/clean_install_smoke.py [--keep]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORTED = (3, 11)


def main(argv: list[str]) -> int:
    if sys.version_info[:2] != SUPPORTED:
        print(f"CLEAN_INSTALL FAIL: Python {sys.version.split()[0]} — SimForge 1.0 supports Python 3.11 only")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="simforge-clean-"))
    venv, work, ws = tmp / "venv", tmp / "elsewhere", tmp / "workspace"
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "ANTHROPIC_API_KEY", "SIMFORGE_WORKSPACE",
                                                          "SIMFORGE_LIBRARY", "VIRTUAL_ENV")}
    env.update(SIMFORGE_WORKSPACE=str(ws), SIMFORGE_LIBRARY=str(tmp / "lib"), SIMFORGE_LOG_DIR=str(tmp / "logs"),
               HOME=str(tmp / "home"))
    bin_ = venv / ("Scripts" if os.name == "nt" else "bin")
    golden = ROOT / "examples" / "1_0_golden_project"
    steps = [
        ("venv", [sys.executable, "-m", "venv", str(venv)]),
        ("install", [str(bin_ / "python"), "-m", "pip", "install", "-q", f"{ROOT}[ui,data,dev]"]),
        ("entry point", [str(bin_ / "simforge"), "--help"]),
        ("example run", [str(bin_ / "simforge"), "run", str(ROOT / "examples" / "01_simple_line.yaml")]),
        ("project new", [str(bin_ / "simforge"), "project", "new", "Clean", "--model", str(golden / "model.yaml")]),
        ("approve", [str(bin_ / "simforge"), "project", "approve", "clean", "--by", "engineer"]),
        ("project run", [str(bin_ / "simforge"), "project", "run", "clean", "--reps", "2"]),
        ("migrations", [str(bin_ / "python"), "-c", "import sqlite3,sys; from simforge.persistence import db; "
                        f"c=db.connect(r'{ws / 'projects' / 'clean' / 'project.db'}'); "
                        "assert db.schema_version(c)==len(db.MIGRATIONS); print('schema', db.schema_version(c))"]),
        ("ui import", [str(bin_ / "python"), "-c", "from streamlit.testing.v1 import AppTest; import simforge.ui.views; "
                       "import simforge, os; p=os.path.join(os.path.dirname(simforge.__file__),'ui','app.py'); "
                       "at=AppTest.from_file(p, default_timeout=180); at.run(); assert not at.exception; print('ui ok')"]),
        ("package data", [str(bin_ / "python"), "-c", "from simforge.library.registry import ComponentRegistry as R; "
                          "r=R.load_default(None); assert r.get('machine'); print('library ok')"]),
    ]
    ok = True
    for name, cmd in steps:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=1800)
        good = p.returncode == 0 and "Traceback" not in p.stdout + p.stderr
        print(f"[{'ok' if good else 'FAIL'}] {name}")
        if not good:
            print((p.stdout + p.stderr)[-3000:])
            ok = False
            break
    if "--keep" not in argv:
        shutil.rmtree(tmp, ignore_errors=True)
    print("CLEAN_INSTALL " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
