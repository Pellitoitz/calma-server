"""SimForge 1.0 release check. Coordinates every release-readiness check and ends with PASS or FAIL — never
"probably okay". Run from a source checkout with the dev environment (Python 3.11):

    python scripts/release/check_release.py                 # everything (incl. clean install: needs the package index)
    python scripts/release/check_release.py --manifest out.json   # also write the release manifest

Checks: Python contract · ruff · FREEZE · regression 01-05 · full pytest (no API key in the environment) · release
suite (golden workflow, save/load, migrations, CLI + UI smoke) · performance (gross regressions only) · clean install
· release documents present · no false validation claim · no secrets in tracked files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
REQUIRED_DOCS = [
    "docs/release/1.0_feature_freeze.md", "docs/release/1.0_capability_matrix.md", "docs/release/1.0_gap_analysis.md",
    "docs/release/1.0_release_criteria.md", "docs/release/1.0_stabilization_policy.md",
    "docs/release/1.0.0-rc1_release_notes.md", "KNOWN_LIMITATIONS.md", "CHANGELOG.md", "docs/user/01_getting_started.md",
    "docs/user/tutorial_end_to_end.md", "docs/user/13_validation_status.md", "docs/user/15_limitations.md",
    "examples/README.md", "examples/1_0_golden_project/README.md",
]
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}|ANTHROPIC_API_KEY\s*=\s*['\"]?sk-|-----BEGIN [A-Z ]*PRIVATE KEY-----")
FALSE_CLAIMS = [re.compile(p, re.I) for p in (
    r"simforge(?: economics)? (?:está|is) (?:industrially )?validad[oa] con datos reales",
    r"simforge (?:is|está) (?:fully |industrially )?validated(?! by| per| only| for)")]
NEGATION = re.compile(r"prohibid|forbidden|never|nunca|\bno\b|\bnot\b|ninguna|ningún|none", re.I)
# a capability-status cell claiming REAL_DATA_VALIDATED is only searched in the release / user status documents
STATUS_DOCS = ("docs/release/", "docs/user/", "README.md", "KNOWN_LIMITATIONS.md", "CHANGELOG.md", "examples/")
STATUS_CELL = re.compile(r"\|\s*REAL_DATA_VALIDATED\s*\|")


def sh(cmd: list[str], env: dict | None = None, timeout: int = 3600) -> tuple[bool, str]:
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode == 0, (p.stdout + p.stderr)


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "SIMFORGE_DEBUG")}


def check_python():
    ok = sys.version_info[:2] == (3, 11)
    return ok, f"Python {sys.version.split()[0]} (supported: 3.11)"


def check_ruff():
    ok, out = sh([PY, "-m", "ruff", "check", "src", "tests", "scripts"])
    return ok, out.strip().splitlines()[-1] if out.strip() else ""


def check_freeze():
    ok, out = sh([PY, "-c", "import sys; sys.argv=['x']; import run_benchmark as r; d=r.check_freeze(); print(d); "
                  "sys.exit(1 if d else 0)"], env={**clean_env(), "PYTHONPATH": str(ROOT / "benchmarks" / "llm_semantic")})
    return ok, "FREEZE " + out.strip().splitlines()[-1]


def check_regression():
    code = ("import statistics; from simforge.domain.io import load_model; from simforge.experiments.runner import run_simulation; "
            "from simforge.library.registry import ComponentRegistry as R; r=R.load_default(None); "
            "fs=['01_simple_line','02_shared_operator','03_machine_breakdowns','04_rework_routing','05_selective_soldering']; "
            "g=[round(statistics.mean(k['units_completed'] for k in run_simulation(load_model(f'examples/{f}.yaml'), r).per_replication), 2) for f in fs]; "
            "print(g); import sys; sys.exit(0 if g==[59, 359, 1889.05, 477.5, 130] else 1)")
    ok, out = sh([PY, "-c", code], env=clean_env())
    return ok, "01-05 " + out.strip().splitlines()[-1]


def check_pytest():
    ok, out = sh([PY, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:warnings"], env=clean_env(), timeout=7200)
    return ok, out.strip().splitlines()[-1]


def check_release_suite():
    ok, out = sh([PY, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:warnings", "-m", "release"], env=clean_env())
    return ok, out.strip().splitlines()[-1]


def check_perf():
    ok, out = sh([PY, "scripts/release/perf_baseline.py", "--check"], env=clean_env())
    return ok, out.strip().splitlines()[-1]


def check_clean_install():
    ok, out = sh([PY, "scripts/release/clean_install_smoke.py"], env=clean_env(), timeout=3600)
    return ok, out.strip().splitlines()[-1]


def check_docs():
    missing = [d for d in REQUIRED_DOCS if not (ROOT / d).exists()]
    users = sorted((ROOT / "docs" / "user").glob("[0-9][0-9]_*.md"))
    ok = not missing and len(users) >= 15
    return ok, f"missing {missing}" if missing else f"{len(users)} user guides + release docs present"


def _tracked() -> list[Path]:
    ok, out = sh(["git", "ls-files"])
    return [ROOT / f for f in out.splitlines()] if ok else []


def check_claims():
    hits = []
    for f in _tracked():
        if f.suffix in (".md", ".py", ".txt") and f.exists() and "test" not in f.name and f.name != "check_release.py":
            rel = str(f.relative_to(ROOT))
            for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                if NEGATION.search(ln):
                    continue  # definitions and prohibitions ("PROHIBITED to state ...") are not claims
                if any(p.search(ln) for p in FALSE_CLAIMS) or (rel.startswith(STATUS_DOCS) and STATUS_CELL.search(ln)):
                    hits.append(f"{rel}: {ln.strip()[:100]}")
    return not hits, "; ".join(hits[:5]) or "no global / false validation claim found"


def check_secrets():
    hits = [str(f.relative_to(ROOT)) for f in _tracked() if f.exists() and f.is_file() and f.stat().st_size < 5_000_000
            and any("FAKE" not in m.group(0).upper() for m in SECRET.finditer(f.read_text(encoding="utf-8", errors="ignore")))]
    env_files = [str(f.relative_to(ROOT)) for f in _tracked() if f.name == ".env"]
    return not (hits or env_files), f"secrets in {hits + env_files}" if hits or env_files else "no secrets / .env tracked"


CHECKS = [("python_3_11", check_python), ("ruff", check_ruff), ("freeze", check_freeze), ("regression_01_05", check_regression),
          ("docs", check_docs), ("validation_claims", check_claims), ("secrets", check_secrets),
          ("release_suite", check_release_suite), ("pytest_full", check_pytest), ("performance", check_perf),
          ("clean_install", check_clean_install)]


def main(argv: list[str]) -> int:
    results = {}
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001 - a check that cannot run is a FAIL, never a skip
            ok, detail = False, f"{type(e).__name__}: {e}"
        results[name] = {"pass": ok, "detail": detail}
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<18} {detail}", flush=True)
    passed = all(r["pass"] for r in results.values())
    if "--manifest" in argv:
        sys.path.insert(0, str(ROOT / "src"))
        import simforge
        commit = sh(["git", "rev-parse", "HEAD"])[1].strip()
        dirty = bool(sh(["git", "status", "--porcelain"])[1].strip())
        man = {"simforge_version": simforge.__version__, "engine_version": simforge.ENGINE_VERSION, "git_commit": commit,
               "working_tree_dirty": dirty, "python": sys.version.split()[0], "checks": results,
               "release_check": "PASS" if passed else "FAIL"}
        Path(argv[argv.index("--manifest") + 1]).write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"RELEASE CHECK: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
