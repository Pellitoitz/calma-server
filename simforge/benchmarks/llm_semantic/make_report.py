"""Build reports/semantic_benchmark.md + results/semantic_results.{json,csv} from the aggregated runs.

    python benchmarks/llm_semantic/make_report.py

Claude results (provider = anthropic) are the subject of the benchmark. Any other provider (offline rules, mock) is
rendered in a separate, labelled section and NEVER reported as Claude results.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FAMILIES = ["A_PARAPHRASE", "B_UNITS_BASIS", "C_MISSING_AMBIGUITY", "D_CONTRADICTION", "E_UNSUPPORTED_RULE", "F_REALISTIC"]


def pct(m: dict) -> str:
    return "n/a (0 evaluated)" if m["value"] is None else f"{m['value']:.1%} ({m['num']}/{m['den']})"


def load_results() -> tuple[list[dict], list[dict]]:
    claude, other = [], []
    for d in sorted((HERE / "results").glob("*/semantic_results.json")):
        s = json.loads(d.read_text())
        (claude if s["meta"]["provider"] == "anthropic" else other).append(s)
    return claude, other


def gold_matrix() -> list[dict]:
    rows = []
    for g in sorted((HERE / "gold").glob("*.yaml")):
        gold = yaml.safe_load(g.read_text())
        case = yaml.safe_load((HERE / "cases" / g.name).read_text())
        for r in gold["requirements"]:
            rows.append({"case": gold["id"], "family": case["family"], "req": r["id"], "kind": r["kind"],
                         "description": r.get("description", ""), "expected": json.dumps({k: v for k, v in r.items() if k not in
                                                                                         ("id", "kind", "description")}, ensure_ascii=False),
                         "gold_status": r.get("gold_status", gold["gold_status"]), "gold_source": gold["gold_source"]})
    return rows


def render_results(s: dict, title: str) -> list[str]:
    m = s["metrics"]
    L = [f"## {title}", "", f"Run `{s['meta']['label']}` · provider `{s['meta']['provider']}` · model `{s['meta']['model']}` · "
         f"frozen: **{s['meta']['frozen']}** · commit `{s['meta']['commit'][:10]}`", "",
         "### Global", "", "| Metric | Value |", "|---|---|"]
    L += [f"| {k} | {pct(v)} |" for k, v in m.items()]
    L += ["", f"Severity counts (evaluated requirements): {json.dumps(s['severity_counts'])}",
          f"Error types: {json.dumps(s['error_types'])}", "", "### By family", "",
          "| Family | Correct/evaluated | CRITICAL | MAJOR | MINOR |", "|---|---|---|---|---|"]
    for f in FAMILIES:
        x = s["by_family"].get(f)
        if x:
            L.append(f"| {f} | {x['positive']}/{x['evaluated']} | {x['CRITICAL']} | {x['MAJOR']} | {x['MINOR']} |")
    L += ["", "### Summary matrix", "", "| CASE | SCHEMA | COMPILE | VERIFY | SEMANTIC | REQ OK | CRITICAL | MAJOR | MINOR |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in s["matrix"]:
        L.append(f"| {r['case']} | {'YES' if r['schema'] else 'NO'} | {'YES' if r['compile'] else 'NO'} | {r['verify']} | "
                 f"{'YES' if r['semantic'] else 'NO'} | {r['requirements_ok']}/{r['requirements']} | {r['critical']} | {r['major']} | {r['minor']} |")
    L += ["", "### VALID_BUT_WRONG (schema valid + compiles + verifier EXECUTABLE + semantically wrong)", ""]
    if not s["valid_but_wrong"]:
        L.append("None.")
    for v in s["valid_but_wrong"]:
        L.append(f"- **{v['case']}**{' — **HARD_TO_NOTICE**' if v['hard_to_notice'] else ''}")
        for w in v["wrong_requirements"]:
            L.append(f"  - `{w['req']}` {w['description']}: {w['status']} {w['error']} [{w['severity']}, {w['ease']}] — {w['detail'][:160]}")
    L += ["", "### Stability", ""]
    if not s["stability"]:
        L.append("No repeated runs.")
    for cid, st in s["stability"].items():
        L.append(f"- {cid}: identical semantic interpretation {pct(st['identical_semantic_interpretation_rate'])}; " +
                 ", ".join(f"{k} {pct(v)}" for k, v in st.items() if k.startswith("same_")))
    L += ["", "### Perturbation robustness", ""]
    for p, x in s["perturbation"].items():
        L.append(f"- {p} vs {x['base']}: same topology {x['same_topology']}, same components {x['same_components']}, "
                 f"same requirement statuses {pct(x['same_requirement_statuses'])}; base correct {x['base_correct']}, "
                 f"perturbed correct {x['perturbed_correct']}")
    u = s["usage"]
    L += ["", "### Tokens, latency, cost", "", f"Calls {u['calls']}, input tokens {u['input_tokens']}, output tokens "
          f"{u['output_tokens']}, average latency {u['avg_latency_ms']} ms, repairs {u['repairs']}, cost {u['cost']}", ""]
    return L


STATIC_RISKS = """\
Found by reading the frozen code (NOT measured with Claude; to be confirmed or refuted by the real run):

| # | Risk | Where | Expected effect | Root-cause class |
|---|---|---|---|---|
| S1 | `ProcessDraft.confidence_notes` is never copied to the model: anything the LLM writes there (doubts, contradictions) never reaches the engineer | `ai/compiler.py` (only `missing_information`, `assumptions`, `custom_rules`, `unparsed` are used) | conflicts/ambiguities "noticed" by Claude but invisible | COMPILER_LIMITATION |
| S2 | The draft has no way to say "basis unknown": `time_basis` is `per_entity` or `per_item`, default `per_entity` | `ai/schemas.py` DraftStep | an ambiguous time is forced to a basis; only a free-text question can save it | SCHEMA_LIMITATION |
| S3 | No field for contradictions; the prompt does not ask to detect them | `process_parser_v1.txt` | contradictions resolved by picking one value | PROMPT_FAILURE / SCHEMA_LIMITATION |
| S4 | Linear draft: no branches, no rework loops, no breakdowns (MTBF/MTTR), no product mix | `ai/schemas.py` ("Branching is not supported by the V1 parser") | F2/F4/E4 can only be flagged, never modelled | SCHEMA_LIMITATION |
| S5 | Distributions: only process times and interarrival; yield exists, failures do not | `ai/schemas.py` DraftTime/DraftStep | stochastic statements partially representable | SCHEMA_LIMITATION |
| S6 | Grounding marks a correct converted value (e.g. 30 s x 4 = 120 s) as ASSUMED, not CALCULATED | `ai/compiler.py` _Builder.param | correct values shown as assumptions (noise in the approval screen) | COMPILER_LIMITATION |
| S7 | Operator priority not stated -> FIFO applied as an assumption + optional question (by design) | `ai/compiler.py` | acceptable if visible; counted as correct only when visible | — |
"""


def main() -> None:
    claude, other = load_results()
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    status_file = HERE / "results" / "STATUS.json"
    status = json.loads(status_file.read_text()) if status_file.exists() else {}
    real = "EXECUTED" if claude else status.get("REAL_LLM_TEST", "NOT_RUN")
    cases = [yaml.safe_load(p.read_text()) for p in sorted((HERE / "cases").glob("*.yaml"))]
    gm = gold_matrix()
    # machine-readable top-level results
    top = {"REAL_LLM_TEST": real, "freeze": {k: v for k, v in freeze.items() if k != "files"},
           "claude": [c for c in claude], "non_claude_runs": [{"label": o["meta"]["label"], "provider": o["meta"]["provider"],
                                                              "model": o["meta"]["model"], "metrics": o["metrics"]} for o in other]}
    (HERE / "results" / "semantic_results.json").write_text(json.dumps(top, indent=1, ensure_ascii=False, default=str))
    with (HERE / "results" / "semantic_results.csv").open("w", newline="", encoding="utf-8") as f:
        rows = []
        for d in sorted((HERE / "results").glob("*/semantic_results.csv")):
            rows += list(csv.DictReader(d.open(encoding="utf-8")))
        fields = ["label", "provider", "model", "case", "repeat", "req", "kind", "metric", "description", "status", "error_type",
                  "severity", "evaluated", "unit_sensitive", "detail"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with (HERE / "results" / "gold_requirement_matrix.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(gm[0]))
        w.writeheader()
        w.writerows(gm)
    # report
    L = ["# LLM semantic benchmark — TEXT → ProcessDraft → library → parameters → questions → ISMS", "",
         f"**REAL_LLM_TEST = {real}**", ""]
    if not claude:
        L += ["No Claude result exists. Nothing in this report is a Claude measurement. To run it:", "", "```bash",
              "cd simforge", "export ANTHROPIC_API_KEY=...   # never committed, never printed",
              f"python benchmarks/llm_semantic/run_benchmark.py --provider anthropic --model {freeze['default_claude_model']}",
              "python benchmarks/llm_semantic/make_report.py", "```", "",
              f"Calls: 27 inputs + {4 * 5} stability repeats = 47 parse calls (+ repairs, max 2 per call).", ""]
    L += ["## 1. Commit and versions (FREEZE.json)", "", "| Item | Value |", "|---|---|"]
    for k in ("commit", "frozen_at", "process_parser_version", "compiler_version", "isms_version", "engine_version",
              "anthropic_sdk_version", "default_claude_model"):
        L.append(f"| {k} | `{freeze[k]}` |")
    L += [f"| library | {len(freeze['library_version']['components'])} components, content hash `{freeze['library_version']['content_hash']}` |",
          f"| rules library | {freeze['rules_library_version']['rules']}, hash `{freeze['rules_library_version']['content_hash']}` |",
          f"| frozen files | {len(freeze['files'])} (sha256 in FREEZE.json; the runner refuses to run if any changed) |", "",
          "## 2. Configuration", "",
          "- Isolated path: `interpreter.parse → compile_draft → verify` (no project, no approval gate, no DES run, no automatic fallback "
          "to the offline interpreter: a failed LLM call is SCHEMA_VALID = NO).",
          "- Prompt `process_parser_v1` unchanged; repairs: max 2 (existing LLMInterpreter behaviour).",
          "- Temperature not set (not supported by current models); stability measured instead.",
          "- Cost: only from the configured pricing table `simforge.ai.provider.PRICING` ('cached 2026-09'), labelled ESTIMATE; "
          "NOT_AVAILABLE if the model is not in the table.", "",
          "## 3. Cases", "", "| Case | Family | Title | Purpose | Gold source |", "|---|---|---|---|---|"]
    gsrc = {r["case"]: r["gold_source"] for r in gm}
    for c in cases:
        L.append(f"| {c['id']} | {c['family']} | {c['title']} | {c['purpose']} | {gsrc[c['id']][:80]} |")
    review = [r for r in gm if r["gold_status"] == "GOLD_REQUIRES_ENGINEER_REVIEW"]
    L += ["", f"Requirement matrix: {len(gm)} requirements in `results/gold_requirement_matrix.csv` "
          f"({sum(1 for r in gm if not r['case'].startswith('P'))} in the 24 cases, {sum(1 for r in gm if r['case'].startswith('P'))} in perturbations). "
          f"Excluded from accuracy (GOLD_REQUIRES_ENGINEER_REVIEW): " + ", ".join(f"`{r['req']}` ({r['description'][:60]})" for r in review), "",
          "Gold independence: every gold is an explicit, human-reviewable spec written BEFORE its text (spec-first), derived from "
          "validated manual models where they exist (A: examples/02 + MVP 359; F1: selective model validated by hand; F2: examples/04). "
          "The gold was authored with an AI assistant in the development session, NOT by the system under test; it still needs an "
          "engineer's review before the numbers are trusted.", ""]
    L += ["## 4. Claude results", ""]
    if claude:
        for s in claude:
            L += render_results(s, f"Claude — {s['meta']['model']}")
    else:
        L += [f"**{real}** — sections 4-17 of the requested report (global results, by family, valid outputs, semantic correctness, "
              "valid-but-wrong, invented data, silent omissions, missing, ambiguity, conflicts, unsupported rules, stability, "
              "perturbation, latency, tokens, cost) will be generated from the real run by this same script.", ""]
    L += ["## 5. Predicted risk areas (static analysis of the frozen code)", "", STATIC_RISKS]
    if other:
        L += ["## 6. Non-Claude reference runs (harness validation — NOT Claude)", "",
              "The deterministic offline interpreter is the product's fallback path. It was run to validate the evaluator end to end "
              "and to measure that fallback. Its numbers say NOTHING about Claude.", ""]
        for s in other:
            L += render_results(s, f"Reference: {s['meta']['provider']} ({s['meta']['model']})")
    L += ["## 7. Instrument revisions (all before any Claude run)", "",
          "- Evaluator: 'flagged' omissions only count interpreter questions and unparsed sentences (a generic compiler question "
          "containing a step word, or a custom-rule sentence, is not a warning about an omitted step).",
          "- Evaluator: positional fallback alignment so a wrong component is one COMPONENT_MATCH_ERROR and its parameters are still "
          "evaluated (no cascading N errors).",
          "- Evaluator: process-time requirement = physical time per entity; basis requirement separate (MAJOR if the physical time is "
          "preserved, CRITICAL if it changes).",
          "- Evaluator: a conflict where no value was chosen = CONTRADICTION_NOT_DETECTED MAJOR (not a silent wrong value).",
          "- Gold D3 topology marked GOLD_REQUIRES_ENGINEER_REVIEW (the text does not place the inspection before/after the machine).",
          "- Gold keywords: 'espera' removed from buffer synonyms (false flag).", "",
          "## 8. Limitations", "",
          "- 24 cases (+3 perturbations): enough to find failure modes, not to estimate rates with tight confidence intervals.",
          "- Ease-of-detection (EASY/MODERATE/HARD) is a documented rule per error type, not a usability study.",
          "- Requirement accuracy counts consequences separately per requirement; the per-case CRITICAL list is the better read.",
          "- Gold authored in the same development session (see §3); engineer review pending.",
          "- The open DES tie-break decision (loaded transport vs empty rack return) does not affect this text→ISMS benchmark.", ""]
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / "semantic_benchmark.md").write_text("\n".join(L), encoding="utf-8")
    print(HERE / "reports" / "semantic_benchmark.md")


if __name__ == "__main__":
    main()
