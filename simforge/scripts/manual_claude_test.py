"""MANUAL test against the real Claude API. Not part of CI (CI never depends on an LLM provider).

    export ANTHROPIC_API_KEY=...        # or put it in .env (git-ignored); NEVER in code
    python scripts/manual_claude_test.py [--model claude-sonnet-5-5] [--keep]

Runs the two acceptance descriptions (MVP line, selective soldering) through the LLM interpreter with the
same deterministic compiler, verifier and engine used offline, and prints: matching report, build plan,
grouped questions, validation, and the AI audit (tokens, estimated cost, latency, repairs).
For the MVP it also approves, runs and compares the result with the offline interpretation.

The API key is read by the Anthropic SDK from the environment. This script never prints, logs or stores it:
it only reports whether a key is present.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

MVP = ("Fuente infinita. Un operario monta una pieza durante 60 segundos. Después hay un buffer con capacidad 5. "
       "Una máquina procesa cada pieza durante 45 segundos. Finalmente el mismo operario inspecciona cada pieza durante "
       "20 segundos. Simular durante 8 horas.")
SELECTIVE = ("Tengo un proceso de soldadura selectiva. Los circuitos se montan manualmente en bastidores. Hay un número "
             "limitado de bastidores. Después del montaje los bastidores se transportan hasta la selectiva. Existe un buffer "
             "de entrada. La selectiva procesa los bastidores. Después pasan a revisión y limpieza. El mismo operario realiza "
             "montaje, transporte y revisión. Quiero que el operario mantenga alimentada la selectiva utilizando una estrategia "
             "de WIP objetivo. Quiero probar entre 1 y 10 bastidores durante un turno de 8 horas.")


def _load_dotenv() -> None:
    env = Path(__file__).parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.strip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="Claude model id (default: SIMFORGE_LLM_MODEL or claude-opus-5-5)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary workspace")
    args = ap.parse_args()
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (environment or .env). Nothing sent.")
        return 2
    print("API key present: yes (value never printed)")

    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
    from simforge.ai.provider import AnthropicProvider
    from simforge.services.app import SimForgeApp
    from simforge.validation.equivalence import compare_model_specs

    ws = Path(tempfile.mkdtemp(prefix="simforge_manual_"))
    provider = AnthropicProvider(model=args.model)
    app = SimForgeApp(workspace=ws / "ws", library_dir=ws / "lib", provider=provider)
    offline = SimForgeApp(workspace=ws / "ws_offline", library_dir=ws / "lib", provider=None)
    total_cost = 0.0
    try:
        for name, text in (("mvp", MVP), ("selective", SELECTIVE)):
            print(f"\n{'=' * 80}\n{name.upper()}  ({provider.model})\n{'=' * 80}")
            p = app.create_project(name)
            pr = app.parse_process(p, text)
            o = pr.outcome
            print(f"interpreter: {pr.interpreter}   readiness: {pr.report.readiness.value}")
            print(o.matching_report())
            print(o.plan.to_text() if o.plan else "")
            print(o.questions_text())
            if o.ungrounded:
                print("UNGROUNDED (numbers not in the text, downgraded to assumptions):", o.ungrounded)
            for a in p.audit_log():
                cost = a["est_cost_usd"] or 0.0
                total_cost += cost
                print(f"AUDIT {a['purpose']}: {a['provider']}/{a['model']} prompt={a['prompt_version']} accepted={bool(a['accepted'])} "
                      f"repairs={a['repairs']} tokens={a['input_tokens']}+{a['output_tokens']} cost=${cost:.4f} "
                      f"latency={a['latency_ms'] or 0:.0f} ms")
                if a["validation_errors"] not in (None, "[]"):
                    print("      validation errors:", a["validation_errors"])
            if name == "mvp" and pr.report.ok:
                ref = offline.parse_process(offline.create_project("ref"), text).outcome.model
                cmp = compare_model_specs(ref, o.model, app.registry)
                print("\nLLM model vs offline model:", "STRUCTURALLY EQUIVALENT" if cmp.structurally_equivalent else "DIFFERENT")
                if not cmp.structurally_equivalent:
                    print(cmp.to_text())
                app.approve_model(p, by="manual-test")
                res = app.run_simulation(p)
                print(f"units_completed = {res.kpis.mean('units_completed'):.0f} (hand calculation, FIFO operator: 359)")
        print(f"\nTOTAL estimated cost: ${total_cost:.4f}")
    finally:
        if args.keep:
            print(f"workspace kept at {ws}")
        else:
            shutil.rmtree(ws, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
