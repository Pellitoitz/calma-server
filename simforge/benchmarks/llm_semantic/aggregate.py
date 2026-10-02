"""Aggregate the runs of one benchmark execution (runs/<label>/) into metrics + machine-readable results.

No weighted score: every metric is a separate ratio with its numerator/denominator, severities are counts.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluator import EASE, POSITIVE

HERE = Path(__file__).parent
PERTURBATIONS = {"P1": "A1", "P2": "B1", "P3": "F3"}
DIMENSIONS = ["topology", "components", "requirements", "missing", "assumption_paths", "custom_rules"]


def ratio(num: int, den: int) -> dict:
    return {"value": round(num / den, 4) if den else None, "num": num, "den": den}


def load(run_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "META.json").read_text())
    recs = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*__run*.json"))]
    return meta, recs


def aggregate(run_dir: Path) -> dict:
    meta, recs = load(run_dir)
    primary = [r for r in recs if r["repeat"] == 1 and r["family"] != "PERTURBATION"]
    rows = [res for r in primary for res in r["evaluation"]["results"]]
    ev = [x for x in rows if x["evaluated"]]

    def metric(name: str) -> dict:
        sel = [x for x in ev if x["metric"] == name]
        return ratio(sum(1 for x in sel if x["status"] in POSITIVE), len(sel))
    numeric = [g for r in primary for g in r["evaluation"]["grounding"] if g["value"] is not None]
    invented = [x for x in ev if x["status"] == "INVENTED"]
    m = {
        "SEMANTIC_REQUIREMENT_ACCURACY": ratio(sum(1 for x in ev if x["status"] in POSITIVE and x["kind"] != "grounding"),
                                               sum(1 for x in ev if x["kind"] != "grounding")),
        "SCHEMA_VALID_RATE": ratio(sum(r["schema_valid"] for r in primary), len(primary)),
        "COMPILE_RATE": ratio(sum(r["compiles"] for r in primary), len(primary)),
        "EXECUTABLE_RATE": ratio(sum(r["verifier_status"] == "EXECUTABLE" for r in primary), len(primary)),
        "SEMANTICALLY_CORRECT_RUNS": ratio(sum(r["semantically_correct"] for r in primary), len(primary)),
        "INVENTED_DATA_RATE": ratio(len(invented), len(numeric)),
        "SILENT_OMISSION_RATE": ratio(sum(1 for x in ev if x["error_type"] == "SILENT_OMISSION"), len(ev)),
        "MISSING_DETECTION_RECALL": metric("MISSING_DETECTION"),
        "AMBIGUITY_DETECTION_RATE": metric("AMBIGUITY_DETECTION"),
        "CONFLICT_DETECTION_RATE": metric("CONFLICT_DETECTION"),
        "UNSUPPORTED_RULE_DETECTION_RATE": metric("UNSUPPORTED_RULE_DETECTION"),
        "COMPONENT_MATCH_ACCURACY": metric("COMPONENT_MATCH"),
        "TOPOLOGY_ACCURACY": metric("TOPOLOGY"),
        "PARAMETER_VALUE_ACCURACY": metric("PARAMETER_VALUE"),
        "UNIT_ACCURACY": ratio(sum(1 for x in ev if x["unit_sensitive"] and x["status"] in POSITIVE),
                               sum(1 for x in ev if x["unit_sensitive"])),
        "SEMANTIC_BASIS_ACCURACY": metric("SEMANTIC_BASIS"),
        "RESOURCE_ASSIGNMENT_ACCURACY": metric("RESOURCE_ASSIGNMENT"),
        "STRATEGY_ACCURACY": metric("STRATEGY"),
        "CARRIER_SEMANTICS_ACCURACY": metric("CARRIER_SEMANTICS"),
        "ROUTING_ACCURACY": metric("ROUTING"),
    }
    severity = Counter(x["severity"] for x in ev if x["severity"])
    errors = Counter(x["error_type"] for x in ev if x["status"] not in POSITIVE and x["error_type"])
    by_family = defaultdict(lambda: {"evaluated": 0, "positive": 0, "CRITICAL": 0, "MAJOR": 0, "MINOR": 0})
    fam = {r["case"]: r["family"] for r in primary}
    for x in ev:
        f = by_family[fam[x["case"]]]
        f["evaluated"] += 1
        f["positive"] += x["status"] in POSITIVE
        if x["severity"]:
            f[x["severity"]] += 1
    # run-level matrix + VALID_BUT_WRONG
    matrix, vbw = [], []
    for r in primary:
        res = [x for x in r["evaluation"]["results"] if x["evaluated"]]
        sev = Counter(x["severity"] for x in res if x["severity"])
        matrix.append({"case": r["case"], "family": r["family"], "schema": r["schema_valid"], "compile": r["compiles"],
                       "verify": r["verifier_status"], "semantic": r["semantically_correct"],
                       "requirements_ok": sum(1 for x in res if x["status"] in POSITIVE), "requirements": len(res),
                       "critical": sev.get("CRITICAL", 0), "major": sev.get("MAJOR", 0), "minor": sev.get("MINOR", 0)})
        if r["schema_valid"] and r["compiles"] and r["verifier_status"] == "EXECUTABLE" and not r["semantically_correct"]:
            wrong = [x for x in res if x["status"] not in POSITIVE]
            vbw.append({"case": r["case"], "verifier": r["verifier_status"],
                        "wrong_requirements": [{"req": x["req"], "description": x["description"], "status": x["status"],
                                                "error": x["error_type"], "severity": x["severity"],
                                                "ease": EASE.get(x["error_type"] or "OTHER", "MODERATE_TO_NOTICE"),
                                                "detail": x["detail"]} for x in wrong]})
    for v in vbw:
        v["hard_to_notice"] = any(w["ease"] == "HARD_TO_NOTICE" for w in v["wrong_requirements"])
    # stability
    stab = {}
    for cid in sorted({r["case"] for r in recs if r["repeat"] > 1}):
        runs = sorted([r for r in recs if r["case"] == cid], key=lambda r: r["repeat"])
        sigs = [r["signature"] for r in runs]
        modal = Counter(json.dumps(s, sort_keys=True) for s in sigs).most_common(1)[0][0]
        stab[cid] = {"runs": len(runs),
                     "identical_semantic_interpretation_rate": ratio(sum(json.dumps(s, sort_keys=True) == modal for s in sigs), len(sigs)),
                     **{f"same_{d}": ratio(sum(s[d] == sigs[0][d] for s in sigs), len(sigs)) for d in DIMENSIONS}}
    # perturbations
    pert = {}
    by_case = {r["case"]: r for r in recs if r["repeat"] == 1}
    for p, base in PERTURBATIONS.items():
        if p in by_case and base in by_case:
            a, b = by_case[base]["signature"], by_case[p]["signature"]
            same_req = [x == y for x, y in zip(a["requirements"].values(), b["requirements"].values())]
            pert[p] = {"base": base, "same_topology": a["topology"] == b["topology"], "same_components": a["components"] == b["components"],
                       "same_requirement_statuses": ratio(sum(same_req), len(same_req)),
                       "base_correct": by_case[base]["semantically_correct"], "perturbed_correct": by_case[p]["semantically_correct"]}
    calls = [c for r in recs for c in r["llm_calls"]]
    lat = [c["latency_ms"] for c in calls if c.get("latency_ms") is not None]
    cost = [c["est_cost_usd"] for c in calls if c.get("est_cost_usd") is not None]
    usage = {"calls": len(calls), "input_tokens": sum(c["input_tokens"] or 0 for c in calls),
             "output_tokens": sum(c["output_tokens"] or 0 for c in calls),
             "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
             "repairs": sum(c["repairs"] or 0 for c in calls),
             "cost": ({"usd": round(sum(cost), 4), "basis": "ESTIMATE from simforge.ai.provider.PRICING (configured table, "
                                                             "'cached 2026-09'); not verified against an invoice"}
                      if cost and len(cost) == len(calls) else "NOT_AVAILABLE")}
    summary = {"meta": meta, "metrics": m, "severity_counts": dict(severity), "error_types": dict(errors),
               "by_family": dict(by_family), "matrix": matrix, "valid_but_wrong": vbw,
               "valid_but_wrong_hard_to_notice": [v["case"] for v in vbw if v["hard_to_notice"]],
               "stability": stab, "perturbation": pert, "usage": usage,
               "gold_review_pending": sorted({x["req"] for r in primary for x in r["evaluation"]["results"] if not x["evaluated"]
                                              and "GOLD_REQUIRES_ENGINEER_REVIEW" in x["detail"]})}
    out = run_dir.parents[1] / "results" / meta["label"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "semantic_results.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    with (out / "semantic_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["label", "provider", "model", "case", "repeat", "req", "kind", "metric", "description",
                                          "status", "error_type", "severity", "evaluated", "unit_sensitive", "detail"])
        w.writeheader()
        for r in recs:
            for x in r["evaluation"]["results"]:
                w.writerow({"label": meta["label"], "provider": meta["provider"], "model": meta["model"], "case": r["case"],
                            "repeat": r["repeat"], **{k: x[k] for k in ("req", "kind", "metric", "description", "status",
                                                                       "error_type", "severity", "evaluated", "unit_sensitive", "detail")}})
    return summary
