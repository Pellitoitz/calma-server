"""Light performance baseline (1.0). NOT an optimisation and NOT a commercial claim: it only detects gross future
regressions on the same kind of hardware.

    python scripts/release/perf_baseline.py            # measure and print
    python scripts/release/perf_baseline.py --write    # store docs/release/performance_baseline.json
    python scripts/release/perf_baseline.py --check    # FAIL if any model is > 10x slower than the stored baseline
"""

from __future__ import annotations

import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
BASELINE = ROOT / "docs" / "release" / "performance_baseline.json"
CASES = {  # size class -> (model, replications)
    "small": ("examples/01_simple_line.yaml", 1),
    "medium": ("examples/05_selective_soldering.yaml", 1),
    "representative": ("examples/1_0_golden_project/model.yaml", 5),
    "representative_stochastic": ("examples/03_machine_breakdowns.yaml", None),
}
FACTOR = 10.0


def measure() -> dict:
    from simforge import ENGINE_VERSION
    from simforge.domain.io import load_model
    from simforge.experiments.runner import run_simulation
    from simforge.library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default(None)
    out = {"engine_version": ENGINE_VERSION, "python": platform.python_version(), "machine": platform.machine(),
           "platform": platform.platform(terse=True), "cases": {}}
    for name, (f, reps) in CASES.items():
        m = load_model(ROOT / f)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            r = run_simulation(m, reg, replications=reps)
            times.append(time.perf_counter() - t0)
        tracemalloc.start()
        traced = run_simulation(m, reg, replications=1, trace=True, keep_records=True)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        out["cases"][name] = {"model": f, "replications": len(r.seeds), "best_runtime_s": round(min(times), 4),
                              "events_per_replication": len(traced.records[0].events or []),
                              "peak_memory_mb_traced_rep": round(peak / 2 ** 20, 2)}
    return out


def main(argv: list[str]) -> int:
    res = measure()
    print(json.dumps(res, indent=2))
    if "--write" in argv:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    if "--check" in argv:
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["cases"]
        bad = [k for k, v in res["cases"].items() if k in base and v["best_runtime_s"] > FACTOR * max(base[k]["best_runtime_s"], 0.01)]
        print("PERF " + ("FAIL: " + ", ".join(bad) if bad else f"PASS (no case > {FACTOR:g}x the stored baseline)"))
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
