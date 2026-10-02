"""Dataset storage inside a project. Nothing is ever overwritten.

    <project>/datasets/<name>/v0001/
        source/<original file>   byte-for-byte copy of the imported file (read-only), never modified
        dataset.json             DatasetMeta (immutable, read-only)
        observations.json        parsed observations (immutable, read-only)
        events.jsonl             APPEND-ONLY log: row actions, fits, decisions, applications to the model

A re-import of the same name with different content creates v0002. The same file imported again with the same
settings is detected as a DUPLICATE (the existing version is returned unless the engineer forces a new one).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from pathlib import Path

from .dataset import DatasetMeta, Event, Observation, parse_event


class DatasetError(ValueError):
    pass


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if not s:
        raise DatasetError("Nombre de dataset vacío.")
    return s[:60]


def _readonly(p: Path) -> None:
    try:
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:  # pragma: no cover - filesystems without permissions
        pass


class DatasetStore:
    def __init__(self, project_root: Path):
        self.root = project_root / "datasets"

    # ------------------------------------------------------------------ paths
    @staticmethod
    def split_id(dataset_id: str) -> tuple[str, int]:
        m = re.fullmatch(r"([a-z0-9_]+)@v(\d+)", dataset_id)
        if not m:
            raise DatasetError(f"Identificador de dataset inválido '{dataset_id}' (formato: nombre@vN).")
        return m.group(1), int(m.group(2))

    def dir(self, dataset_id: str) -> Path:
        name, v = self.split_id(dataset_id)
        d = self.root / name / f"v{v:04d}"
        if not (d / "dataset.json").exists():
            raise DatasetError(f"No existe el dataset '{dataset_id}'.")
        return d

    # ------------------------------------------------------------------ queries
    def list(self) -> list[DatasetMeta]:
        out = []
        if self.root.exists():
            for f in sorted(self.root.glob("*/v*/dataset.json")):
                out.append(DatasetMeta.model_validate_json(f.read_text(encoding="utf-8")))
        return out

    def meta(self, dataset_id: str) -> DatasetMeta:
        return DatasetMeta.model_validate_json((self.dir(dataset_id) / "dataset.json").read_text(encoding="utf-8"))

    def observations(self, dataset_id: str) -> list[Observation]:
        data = json.loads((self.dir(dataset_id) / "observations.json").read_text(encoding="utf-8"))
        return [Observation.model_validate(o) for o in data]

    def events(self, dataset_id: str) -> list[Event]:
        f = self.dir(dataset_id) / "events.jsonl"
        if not f.exists():
            return []
        return [parse_event(json.loads(line)) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]

    def next_version(self, name: str) -> int:
        d = self.root / slug(name)
        vs = [int(p.name[1:]) for p in d.glob("v*") if p.name[1:].isdigit()] if d.exists() else []
        return max(vs, default=0) + 1

    def find_duplicates(self, file_sha256: str, settings: dict) -> tuple[list[str], list[str]]:
        """(same file + same settings, same file + different settings)."""
        same, other = [], []
        for m in self.list():
            if m.file_sha256 != file_sha256:
                continue
            (same if import_settings(m) == settings else other).append(m.dataset_id)
        return same, other

    # ------------------------------------------------------------------ writes
    def create(self, meta: DatasetMeta, source: Path, observations: list[Observation]) -> DatasetMeta:
        d = self.root / meta.name / f"v{meta.version:04d}"
        if d.exists():
            raise DatasetError(f"{meta.dataset_id} ya existe y es inmutable.")
        (d / "source").mkdir(parents=True)
        dst = d / "source" / source.name
        shutil.copyfile(source, dst)
        _readonly(dst)
        (d / "dataset.json").write_text(meta.model_dump_json(indent=1), encoding="utf-8")
        _readonly(d / "dataset.json")
        (d / "observations.json").write_text(json.dumps([o.model_dump(mode="json") for o in observations], ensure_ascii=False),
                                             encoding="utf-8")
        _readonly(d / "observations.json")
        (d / "events.jsonl").touch()
        return meta

    def append(self, dataset_id: str, event: Event) -> Event:
        with (self.dir(dataset_id) / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
        return event


def import_settings(m: DatasetMeta) -> dict:
    return {"sheet": m.sheet, "delimiter": m.delimiter, "decimal": m.decimal, "header_row": m.header_row,
            "mapping": m.mapping.model_dump(), "quantity_type": m.quantity_type.value, "basis": m.basis.value}
