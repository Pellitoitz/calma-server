"""Project storage.

    <workspace>/projects/<slug>/
        project.json            project metadata (baseline, scenarios, privacy terms)
        versions/v0001.yaml     IMMUTABLE model snapshots (git-friendly, human-readable)
        reports/                generated reports
        runs/<run_id>/          debug traces (event log, operator decisions) as CSV
        attachments/            client files (never sent to an LLM)
        project.db              SQLite: versions index, runs, experiments, history, cache, LLM usage

Client data lives in the workspace; the component library lives elsewhere.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..domain.io import dump_model, load_model
from ..domain.isms import ISMSModel
from ..experiments.runner import ExperimentResult, SimulationResult
from .db import connect

PROJECT_FORMAT = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "project"


class ProjectMeta(BaseModel):
    format: int = PROJECT_FORMAT
    slug: str
    name: str
    description: str = ""
    created_at: str = Field(default_factory=_now)
    current_version: int | None = None
    baseline_version: int | None = None
    scenarios: dict[str, int] = Field(default_factory=dict)  # scenario name -> version
    sensitive_terms: dict[str, str] = Field(default_factory=dict)  # real term -> placeholder (anonymisation)
    manual_model_estimated_hours: float | None = None  # productivity tracking


@dataclass
class VersionInfo:
    version: int
    created_at: str
    author: str | None
    message: str | None
    parent: int | None
    content_hash: str
    label: str | None


class ProjectError(ValueError):
    pass


class Project:
    def __init__(self, root: Path):
        self.root = root
        if not (root / "project.json").exists():
            raise ProjectError(f"'{root}' no es un proyecto SimForge (falta project.json).")
        self.meta = ProjectMeta.model_validate_json((root / "project.json").read_text(encoding="utf-8"))
        self.db = connect(root / "project.db")

    # ------------------------------------------------------------------ meta
    def save_meta(self) -> None:
        (self.root / "project.json").write_text(self.meta.model_dump_json(indent=2), encoding="utf-8")

    @property
    def name(self) -> str:
        return self.meta.name

    # -------------------------------------------------------------- versions
    def save_version(self, model: ISMSModel, message: str = "", author: str = "engineer", label: str | None = None) -> int:
        """Store a new immutable snapshot and make it current. Returns the version number."""
        row = self.db.execute("SELECT MAX(version) FROM model_versions").fetchone()
        v = (row[0] or 0) + 1
        fname = f"versions/v{v:04d}.yaml"
        (self.root / "versions").mkdir(exist_ok=True)
        path = self.root / fname
        if path.exists():  # should never happen: versions are immutable
            raise ProjectError(f"La versión {v} ya existe y es inmutable.")
        path.write_text(dump_model(model), encoding="utf-8")
        self.db.execute(
            "INSERT INTO model_versions(version, created_at, author, message, parent, content_hash, label, file) VALUES (?,?,?,?,?,?,?,?)",
            (v, _now(), author, message, self.meta.current_version, model.content_hash(), label, fname))
        self.db.commit()
        self.meta.current_version = v
        self.save_meta()
        return v

    def load_version(self, version: int | None = None) -> ISMSModel:
        v = version or self.meta.current_version
        if v is None:
            raise ProjectError("El proyecto todavía no tiene ningún modelo guardado.")
        return load_model(self.root / f"versions/v{v:04d}.yaml")

    def current_model(self) -> ISMSModel | None:
        return self.load_version() if self.meta.current_version else None

    def versions(self) -> list[VersionInfo]:
        rows = self.db.execute("SELECT version, created_at, author, message, parent, content_hash, label FROM model_versions ORDER BY version")
        return [VersionInfo(*r) for r in rows]

    def checkout(self, version: int) -> ISMSModel:
        """Make an old version current (no data is lost: versions are immutable)."""
        m = self.load_version(version)
        self.meta.current_version = version
        self.save_meta()
        self.log("system", "checkout", result=f"current version -> v{version}")
        return m

    def set_baseline(self, version: int) -> None:
        self.load_version(version)
        self.meta.baseline_version = version
        self.save_meta()
        self.db.execute("UPDATE model_versions SET label = 'baseline' WHERE version = ?", (version,))
        self.db.commit()
        self.log("user", "set_baseline", result=f"baseline = v{version}")

    def create_scenario(self, name: str, model: ISMSModel, message: str = "") -> int:
        if self.meta.baseline_version is None:
            raise ProjectError("Define primero un baseline: los escenarios se derivan del baseline.")
        v = self.save_version(model, message or f"scenario {name}", label=f"scenario:{name}")
        self.meta.scenarios[name] = v
        self.save_meta()
        return v

    # ------------------------------------------------------------------ runs
    def save_run(self, result: SimulationResult, model_version: int | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO runs(run_id, model_version, model_hash, created_at, replications, engine, engine_version, app_version, result_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (result.run_id, model_version, result.model_hash, result.started_at, len(result.seeds), result.engine,
             result.engine_version, result.app_version, json.dumps(result.to_dict())))
        self.db.commit()
        for rec in result.records:  # debug traces -> CSV
            d = self.root / "runs" / result.run_id
            d.mkdir(parents=True, exist_ok=True)
            if rec.events:
                _write_csv(d / f"events_seed{rec.seed}.csv", rec.events)
            if rec.decisions:
                rows = [{**x, "candidates": json.dumps(x["candidates"]), "units": ",".join(x["units"])} for x in rec.decisions]
                _write_csv(d / f"decisions_seed{rec.seed}.csv", rows)
        if self.metric("time_to_first_run_s") is None:
            first = self.db.execute("SELECT MIN(created_at) FROM model_versions").fetchone()[0]
            if first:
                delta = datetime.fromisoformat(result.started_at) - datetime.fromisoformat(first)
                self.record_metric("time_to_first_run_s", max(0.0, delta.total_seconds()))

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT run_id, model_version, created_at, replications FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def load_run(self, run_id: str) -> SimulationResult:
        row = self.db.execute("SELECT result_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise ProjectError(f"No existe la ejecución '{run_id}'.")
        return SimulationResult.from_dict(json.loads(row[0]))

    def save_experiment(self, result: ExperimentResult, model_version: int | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO experiments(experiment_id, model_version, created_at, name, result_json) VALUES (?,?,?,?,?)",
                        (result.experiment_id, model_version, result.started_at, result.spec.name, json.dumps(result.to_dict())))
        self.db.commit()

    def experiments(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT experiment_id, model_version, created_at, name FROM experiments ORDER BY created_at DESC")
        return [dict(r) for r in rows]

    def load_experiment(self, exp_id: str) -> ExperimentResult:
        row = self.db.execute("SELECT result_json FROM experiments WHERE experiment_id = ?", (exp_id,)).fetchone()
        if not row:
            raise ProjectError(f"No existe el experimento '{exp_id}'.")
        return ExperimentResult.from_dict(json.loads(row[0]))

    # ------------------------------------------------------- cache (ResultCache)
    def get(self, key: str) -> dict[str, float] | None:
        row = self.db.execute("SELECT kpis_json FROM result_cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, kpis: dict[str, float]) -> None:
        self.db.execute("INSERT OR REPLACE INTO result_cache(key, kpis_json, created_at) VALUES (?,?,?)", (key, json.dumps(kpis), _now()))
        self.db.commit()

    # --------------------------------------------------------- history / metrics
    def log(self, actor: str, action: str, request: str | None = None, interpretation: str | None = None,
            change: Any = None, result: str | None = None) -> None:
        self.db.execute("INSERT INTO history(ts, actor, action, request, interpretation, change_json, result) VALUES (?,?,?,?,?,?,?)",
                        (_now(), actor, action, request, interpretation, json.dumps(change, default=str) if change is not None else None, result))
        self.db.commit()

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT ts, actor, action, request, interpretation, change_json, result FROM history ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def log_llm_usage(self, provider: str, model: str, purpose: str, input_tokens: int, output_tokens: int,
                      est_cost_usd: float | None, sent_chars: int) -> None:
        self.db.execute("INSERT INTO llm_usage(ts, provider, model, purpose, input_tokens, output_tokens, est_cost_usd, sent_chars) VALUES (?,?,?,?,?,?,?,?)",
                        (_now(), provider, model, purpose, input_tokens, output_tokens, est_cost_usd, sent_chars))
        self.db.commit()

    def llm_usage_summary(self) -> dict[str, Any]:
        r = self.db.execute("SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(est_cost_usd),0) FROM llm_usage").fetchone()
        return {"requests": r[0], "input_tokens": r[1], "output_tokens": r[2], "est_cost_usd": round(r[3], 4)}

    def record_metric(self, key: str, value: float, note: str | None = None) -> None:
        self.db.execute("INSERT INTO metrics(key, value, ts, note) VALUES (?,?,?,?)", (key, value, _now(), note))
        self.db.commit()

    def metric(self, key: str) -> float | None:
        r = self.db.execute("SELECT value FROM metrics WHERE key = ? ORDER BY ts DESC LIMIT 1", (key,)).fetchone()
        return r[0] if r else None

    def metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.db.execute("SELECT key, value FROM metrics ORDER BY ts"):
            out[r[0]] = r[1]
        out["versions"] = len(self.versions())
        out["runs"] = self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        out["ai_edits"] = self.db.execute("SELECT COUNT(*) FROM history WHERE actor = 'ai'").fetchone()[0]
        out["manual_edits"] = self.db.execute("SELECT COUNT(*) FROM history WHERE actor = 'user' AND action = 'edit'").fetchone()[0]
        return out

    def close(self) -> None:
        self.db.close()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


@dataclass
class Workspace:
    root: Path
    _open: dict[str, Project] = field(default_factory=dict)

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    def create_project(self, name: str, description: str = "") -> Project:
        slug = slugify(name)
        base, i = slug, 2
        while (self.projects_dir / slug).exists():
            slug, i = f"{base}_{i}", i + 1
        root = self.projects_dir / slug
        for sub in ("versions", "reports", "runs", "attachments"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        meta = ProjectMeta(slug=slug, name=name, description=description)
        (root / "project.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        p = Project(root)
        p.log("user", "create_project", result=name)
        return p

    def list_projects(self) -> list[ProjectMeta]:
        if not self.projects_dir.exists():
            return []
        out = []
        for d in sorted(self.projects_dir.iterdir()):
            f = d / "project.json"
            if f.exists():
                out.append(ProjectMeta.model_validate_json(f.read_text(encoding="utf-8")))
        return out

    def open_project(self, slug: str) -> Project:
        return Project(self.projects_dir / slug)

    def export_project(self, slug: str, dest: Path, include_attachments: bool = False) -> Path:
        """Portable .simproject (zip). Never contains secrets: .env/API keys live outside projects."""
        root = self.projects_dir / slug
        dest = dest if dest.suffix == ".simproject" else dest.with_suffix(".simproject")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in root.rglob("*"):
                rel = f.relative_to(root)
                if f.is_dir() or (rel.parts[0] == "attachments" and not include_attachments):
                    continue
                if f.name in (".env",) or f.suffix in (".key",):
                    continue
                z.write(f, rel.as_posix())
        return dest

    def import_project(self, archive: Path) -> Project:
        with zipfile.ZipFile(archive) as z:
            meta = ProjectMeta.model_validate_json(z.read("project.json"))
            slug, base, i = meta.slug, meta.slug, 2
            while (self.projects_dir / slug).exists():
                slug, i = f"{base}_{i}", i + 1
            root = self.projects_dir / slug
            root.mkdir(parents=True)
            for name in z.namelist():
                target = (root / name).resolve()
                if not str(target).startswith(str(root.resolve())):
                    raise ProjectError(f"Ruta insegura en el paquete: {name}")
            z.extractall(root)
        meta.slug = slug
        (root / "project.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        return Project(root)

    def delete_project(self, slug: str) -> None:
        shutil.rmtree(self.projects_dir / slug)
