"""LLM semantic benchmark runner: TEXT -> ProcessDraft -> library matching -> parameters -> questions -> compile -> ISMS.

Isolated path: interpreter.parse -> compile_draft -> verify. No project, no approval gate involved, no automatic fallback
to the offline interpreter (a failed LLM call is recorded as SCHEMA_VALID = NO), no DES run.

    # real Claude (key read by the Anthropic SDK from the environment; never printed or stored)
    export ANTHROPIC_API_KEY=...
    python benchmarks/llm_semantic/run_benchmark.py --provider anthropic --model claude-opus-5-5

    python benchmarks/llm_semantic/run_benchmark.py --provider offline     # deterministic rule interpreter (NOT Claude)
    python benchmarks/llm_semantic/run_benchmark.py --freeze               # (re)write FREEZE.json - only before a benchmark

The runner refuses to run if any frozen file (prompts, compiler, schemas, library, rules, matcher, verifier) changed
since FREEZE.json, unless --allow-unfrozen is given (results are then labelled UNFROZEN).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from evaluator import Outcome, evaluate  # noqa: E402

FROZEN = ["src/simforge/ai/prompts/process_parser_v1.txt", "src/simforge/ai/prompts/__init__.py", "src/simforge/ai/compiler.py",
          "src/simforge/ai/schemas.py", "src/simforge/ai/interpreter.py", "src/simforge/ai/context.py", "src/simforge/ai/provider.py",
          "src/simforge/ai/rule_based.py", "src/simforge/library/registry.py", "src/simforge/validation/verifier.py",
          "src/simforge/domain/isms.py", "src/simforge/domain/expressions.py",
          *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "src/simforge/library/components").glob("*.yaml")),
          *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "src/simforge/library/rules").glob("*.yaml"))]
STABILITY_CASES = ["A1", "B1", "C1", "E1", "F1"]
STABILITY_RUNS = 5


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def versions() -> dict:
    import simforge
    from simforge.ai.compiler import COMPILER_VERSION
    from simforge.ai.prompts import PARSE_PROMPT_VERSION
    from simforge.domain.isms import ISMS_VERSION
    from simforge.library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default()
    try:
        import anthropic
        sdk = anthropic.__version__
    except ImportError:
        sdk = "NOT_INSTALLED"
    lib_hash = hashlib.sha256("".join(sha(ROOT / f) for f in FROZEN if "/library/components/" in f).encode()).hexdigest()[:16]
    rules_hash = hashlib.sha256("".join(sha(ROOT / f) for f in FROZEN if "/library/rules/" in f).encode()).hexdigest()[:16]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        commit = "unknown"
    return {"commit": commit, "process_parser_version": PARSE_PROMPT_VERSION, "compiler_version": COMPILER_VERSION,
            "isms_version": ISMS_VERSION, "engine_version": simforge.ENGINE_VERSION,
            "library_version": {"components": {c.id: c.version for c in reg.all()}, "content_hash": lib_hash},
            "rules_library_version": {"rules": {r.id: r.version for r in reg.rules.values()}, "content_hash": rules_hash},
            "anthropic_sdk_version": sdk, "python": platform.python_version()}


def write_freeze() -> dict:
    data = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **versions(),
            "default_claude_model": os.environ.get("SIMFORGE_LLM_MODEL", "claude-opus-5-5"),
            "files": {f: sha(ROOT / f) for f in FROZEN}}
    (HERE / "FREEZE.json").write_text(json.dumps(data, indent=1, sort_keys=False))
    return data


def check_freeze() -> list[str]:
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    changed = [f for f, h in freeze["files"].items() if not (ROOT / f).exists() or sha(ROOT / f) != h]
    changed += [f for f in FROZEN if f not in freeze["files"]]
    return changed


def load_cases() -> dict[str, tuple[dict, dict]]:
    out = {}
    for p in sorted((HERE / "cases").glob("*.yaml")):
        case = yaml.safe_load(p.read_text())
        gold = yaml.safe_load((HERE / "gold" / p.name).read_text())
        out[case["id"]] = (case, gold)
    return out


# ----------------------------------------------------------------------------- one run
def make_interpreter(provider: str, model: str | None, audits: list):
    from simforge.ai.interpreter import LLMInterpreter, RuleBasedInterpreter
    from simforge.library.registry import ComponentRegistry
    reg = ComponentRegistry.load_default()
    if provider == "offline":
        return RuleBasedInterpreter(reg), reg
    if provider == "anthropic":
        from simforge.ai.provider import AnthropicProvider
        prov = AnthropicProvider(model=model)
    elif provider == "mock":
        from simforge.ai.provider import MockLLMProvider
        prov = MockLLMProvider(MOCK_RESPONDER)
    else:
        raise SystemExit(f"unknown provider {provider}")
    return LLMInterpreter(prov, reg, on_audit=audits.append), reg


MOCK_RESPONDER = None  # set by tests: (user_text, schema) -> dict


def run_one(case: dict, gold: dict, interp, reg, audits: list) -> dict:
    from simforge.ai.compiler import compile_draft
    from simforge.ai.provider import LLMError
    from simforge.validation.verifier import verify
    text = case["text"]
    n_audit = len(audits)
    t0 = time.perf_counter()
    rec: dict = {"case": case["id"], "family": case["family"]}
    draft = outcome = None
    try:
        draft = interp.parse(text)
        schema_valid = True
    except (LLMError, Exception) as e:  # noqa: BLE001 - recorded, never hidden
        schema_valid, err = False, f"{type(e).__name__}: {e}"
    compiles, status, model_dump, questions, assumptions, customs, unparsed = False, None, None, [], [], [], []
    if schema_valid:
        try:
            outcome = compile_draft(draft, reg, text, generated_by={"interpreter": interp.name,
                                                                    "prompt_version": getattr(interp, "prompt_version", None)})
            compiles = True
            report, _ = verify(outcome.model, reg)
            status = report.readiness.value
            m = outcome.model
            model_dump = m.model_dump(mode="json")
            questions = outcome.questions() + [x.question for x in m.missing if not x.required]
            assumptions = [a.text for a in m.assumptions]
            customs = [c.description for c in m.custom_rule_candidates]
            unparsed = list(draft.unparsed)
            err = None
        except Exception as e:  # noqa: BLE001
            err = f"compile: {type(e).__name__}: {e}"
    out = Outcome(text, schema_valid, compiles, status, model_dump, draft.model_dump(mode="json") if draft else None,
                  questions, assumptions, customs, unparsed, err,
                  llm_questions=[q.question for q in draft.missing_information] if draft else [])
    ev = evaluate(case["id"], gold, out)
    calls = [a.__dict__ for a in audits[n_audit:]]
    rec.update({
        "schema_valid": schema_valid, "compiles": compiles, "verifier_status": status, "error": err,
        "semantically_correct": ev.semantically_correct, "wall_s": round(time.perf_counter() - t0, 3),
        "interpreter": interp.name, "draft": out.draft, "model": model_dump, "questions": questions,
        "assumptions": assumptions, "custom_rules": customs, "unparsed": unparsed,
        "confidence_notes_dropped_by_compiler": (out.draft or {}).get("confidence_notes", []),
        "evaluation": ev.as_dict(), "llm_calls": [{k: c[k] for k in ("provider", "model", "prompt_version", "input_tokens",
                                                                    "output_tokens", "latency_ms", "repairs", "accepted",
                                                                    "validation_errors", "est_cost_usd")} for c in calls],
    })
    return rec


def signature(rec: dict) -> dict:
    """Semantic interpretation fingerprint (for stability / perturbation): independent of ids and wording."""
    ev = rec["evaluation"]
    roles = {r: n for r, n in ev["role_map"].items() if not r.endswith("(loose)")}
    loose = sorted(r[:-7] for r in ev["role_map"] if r.endswith("(loose)"))
    inv = {nid: role for role, nid in roles.items() if nid}
    m = rec.get("model") or {}
    nodes = {n["id"]: n for n in m.get("nodes", [])}
    params = {p["id"]: p for p in m.get("parameters", [])}
    missing = sorted({(inv.get(n["id"], n["component"]), k) for n in nodes.values()
                      for k, x in (n.get("params") or {}).items()
                      if isinstance(x, (str, dict)) and _pid(x) and params.get(_pid(x), {}).get("value") is None})
    return {
        "topology": [nodes[n]["component"] for n in _flow(m)] if m else None,
        "components": {r: (nodes[n]["component"] if n else None) for r, n in roles.items()},
        "loose_roles": loose,
        "requirements": {r["req"]: r["status"] for r in ev["results"]},
        "missing": missing,
        "assumption_paths": sorted({_role_path(a.get("path") or "", inv) for a in m.get("assumptions", [])}),
        "custom_rules": len(rec.get("custom_rules", [])),
    }


def _pid(x):
    v = x.get("value") if isinstance(x, dict) else x
    return v[1:] if isinstance(v, str) and v.startswith("$") else None


def _role_path(path: str, inv: dict) -> str:
    for nid, role in inv.items():
        path = path.replace(f"nodes.{nid}.", f"nodes.<{role}>.")
    return path


def _flow(m: dict) -> list[str]:
    succ = {}
    for e in m.get("edges", []):
        succ.setdefault(e["source"], []).append(e["target"])
    start = next((n["id"] for n in m.get("nodes", []) if n["component"] == "source"), None)
    seen, q = [], [start]
    while q:
        n = q.pop(0)
        if n and n not in seen:
            seen.append(n)
            q += succ.get(n, [])
    return seen


# ----------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["anthropic", "offline", "mock"], default="anthropic")
    ap.add_argument("--model", default=None, help="Claude model id (default SIMFORGE_LLM_MODEL or claude-opus-5-5)")
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--stability-runs", type=int, default=STABILITY_RUNS)
    ap.add_argument("--no-stability", action="store_true")
    ap.add_argument("--freeze", action="store_true", help="write FREEZE.json and exit")
    ap.add_argument("--allow-unfrozen", action="store_true")
    ap.add_argument("--label", default=None)
    ap.add_argument("--out-root", default=None, help="directory for runs/ and results/ (default: this benchmark folder)")
    args = ap.parse_args(argv)
    if args.freeze:
        d = write_freeze()
        print(f"FREEZE.json written: commit {d['commit'][:10]}, {len(d['files'])} files")
        return 0
    changed = check_freeze()
    if changed and not args.allow_unfrozen:
        print("REFUSED: frozen files changed since FREEZE.json (the benchmark must measure the frozen system):")
        for f in changed:
            print("  -", f)
        return 3
    if args.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        status = {"REAL_LLM_TEST": "BLOCKED_NO_API_KEY", "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        res_dir = (Path(args.out_root) if args.out_root else HERE) / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        (res_dir / "STATUS.json").write_text(json.dumps(status, indent=1))
        print("REAL_LLM_TEST = BLOCKED_NO_API_KEY (set ANTHROPIC_API_KEY in the environment; it is never printed or stored)")
        return 2
    model = args.model or os.environ.get("SIMFORGE_LLM_MODEL", "claude-opus-5-5")
    cases = load_cases()
    wanted = [c for c in (args.cases.split(",") if args.cases else cases) if c]
    audits: list = []
    interp, reg = make_interpreter(args.provider, model, audits)
    label = args.label or f"{args.provider}{'_' + model if args.provider == 'anthropic' else ''}_" \
                          f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    root = Path(args.out_root) if args.out_root else HERE
    run_dir = root / "runs" / label
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {"label": label, "provider": args.provider, "model": model if args.provider == "anthropic" else interp.name,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "frozen": not changed,
            "unfrozen_files": changed, **versions()}
    records = []
    plan = [(cid, 1) for cid in wanted]
    if not args.no_stability:
        plan += [(cid, k) for cid in STABILITY_CASES if cid in wanted for k in range(2, args.stability_runs + 1)]
    for cid, k in plan:
        case, gold = cases[cid]
        rec = run_one(case, gold, interp, reg, audits)
        rec["repeat"] = k
        rec["signature"] = signature(rec)
        (run_dir / f"{cid}__run{k}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str))
        records.append(rec)
        ok = sum(1 for r in rec["evaluation"]["results"] if r["evaluated"] and r["status"] in
                 ("CORRECT", "MISSING_DETECTED", "AMBIGUITY_DETECTED", "CONFLICT_DETECTED", "UNSUPPORTED_CORRECTLY_DETECTED"))
        n = sum(1 for r in rec["evaluation"]["results"] if r["evaluated"])
        print(f"{cid} run{k}: schema={rec['schema_valid']} compiles={rec['compiles']} verifier={rec['verifier_status']} "
              f"requirements {ok}/{n}")
    meta["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (run_dir / "META.json").write_text(json.dumps(meta, indent=1))
    from aggregate import aggregate
    summary = aggregate(run_dir)
    print(json.dumps({k: summary["metrics"][k] for k in ("SEMANTIC_REQUIREMENT_ACCURACY", "SCHEMA_VALID_RATE", "COMPILE_RATE")}, indent=1))
    print(f"run dir: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
