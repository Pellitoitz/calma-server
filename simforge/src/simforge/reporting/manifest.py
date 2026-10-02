"""Reproducibility manifest of one stored run (1.0): everything needed to identify and re-run it, consolidated from
the stored run, the model version it was executed on, its datasets and its economic evaluations. Nothing is
recomputed and nothing is duplicated beyond identifiers.

    simforge project manifest <project> <run_id> [-o manifest.json]
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

MANIFEST_VERSION = "1"


def _block_hash(model, key: str) -> str | None:
    block = getattr(model, key, None)
    if block is None:
        return None
    blob = json.dumps(block.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _datasets(model) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(x: Any, path: str) -> None:
        if isinstance(x, dict):
            d = (x.get("provenance") or {}).get("data") if isinstance(x.get("provenance"), dict) else None
            if d:
                out.append({"parameter": path, **{k: d.get(k) for k in (
                    "dataset_id", "dataset_version", "content_hash", "source_file", "column", "decision", "derivation",
                    "fit_id", "n_used", "n_excluded", "decided_by", "decided_at")}})
            for k, v in x.items():
                if k != "provenance":
                    walk(v, f"{path}.{k}" if path else k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}.{v['id'] if isinstance(v, dict) and 'id' in v else i}")
    walk(model.model_dump(mode="json", exclude={"approval": True, "meta": True}), "")
    return out


def build_manifest(project, run_id: str) -> dict[str, Any]:
    from .. import ENGINE_VERSION, __version__
    run = project.load_run(run_id)
    row = project.db.execute("SELECT model_version FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    version = row[0] if row else None
    model = project.load_version(version) if version is not None else None
    if model is not None and model.content_hash() != run.model_hash:
        model = None  # never describe another model
    ap = model.approval if model is not None else None
    evals = []
    for e in project.evaluations(run_id):
        ev = project.load_evaluation(e["evaluation_id"])
        evals.append({"evaluation_id": ev.evaluation_id, "economic_hash": ev.economic_hash,
                      "economics_engine_version": ev.economics_engine_version, "status": ev.status,
                      "formula_ids": sorted({ln.formula_id for ln in ev.lines}), "approved_by": e.get("approved_by")})
    return {
        "manifest_version": MANIFEST_VERSION,
        "simforge_version": __version__, "current_engine_version": ENGINE_VERSION,
        "engine": run.engine, "engine_version": run.engine_version, "app_version": run.app_version,
        "project": project.meta.slug, "run_id": run.run_id, "started_at": run.started_at,
        "model_version": version, "model_name": run.model_name, "physical_model_hash": run.model_hash,
        "approval": {"approved": bool(model is not None and model.is_approved),
                     "by": ap.by if ap and ap.approved else None,
                     "at": str(ap.at) if ap and ap.approved and ap.at else None,
                     "model_hash": ap.model_hash if ap and ap.approved else None},
        "availability_hash": run.availability_hash,
        "production_hash": _block_hash(model, "production") if model is not None else None,
        "maintenance_hash": _block_hash(model, "maintenance") if model is not None else None,
        "seeds": run.seeds, "replications": len(run.seeds), "horizon_s": run.horizon_s, "warmup_s": run.warmup_s,
        "component_versions": dict(sorted(run.component_versions.items())),
        "datasets": _datasets(model) if model is not None else [],
        "economic_evaluations": evals,
        "notes": ("engine_version fixes the simulation semantics (calendars 0.6, products/setups 0.7, maintenance 0.8); "
                  "re-run = same model version + same seeds + same engine version + same component definitions."),
    }
