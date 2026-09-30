"""Component library: reusable, versioned, documented building blocks.

A component = behaviour (executable primitive) + defaults + documentation +
metadata (tags, keywords, KPIs, validation status, changelog).

Two libraries are loaded and kept physically separate (IP protection):
  * core library   -> shipped with SimForge (src/simforge/library/components)
  * user library   -> your own components (e.g. ~/simforge_library), never
                      mixed with client project data.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.behaviors import BEHAVIOR_PARAMS, Behavior

CORE_DIR = Path(__file__).parent / "components"


class ValidationStatus(str, Enum):
    DRAFT = "draft"
    TESTED = "tested"  # covered by automated engine tests
    VALIDATED = "validated"  # validated by an engineer against a real system


class ChangelogEntry(BaseModel):
    version: str
    date: str | None = None
    author: str | None = None
    change: str


class ComponentDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = "1.0.0"
    name: str
    category: str  # core | manufacturing | electronics | logistics | custom
    behavior: Behavior
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)  # es/en synonyms for matching
    defaults: dict[str, Any] = Field(default_factory=dict)
    param_docs: dict[str, str] = Field(default_factory=dict)
    kpis: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.DRAFT
    tests: list[str] = Field(default_factory=list)
    changelog: list[ChangelogEntry] = Field(default_factory=list)
    origin: str = "core"  # core | user

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    def params_model(self) -> type[BaseModel]:
        return BEHAVIOR_PARAMS[self.behavior]

    def resolve_params(self, params: dict[str, Any]) -> BaseModel:
        """Merge library defaults with node params and validate against the behaviour schema."""
        return self.params_model().model_validate({**self.defaults, **params})

    def param_schema(self) -> dict[str, Any]:
        schema = self.params_model().model_json_schema()
        for name, prop in schema.get("properties", {}).items():
            if name in self.defaults:
                prop["x-component-default"] = self.defaults[name]
            if name in self.param_docs:
                prop["description"] = self.param_docs[name]
        return schema

    def to_markdown(self) -> str:
        """Auto-generated documentation from the schema."""
        lines = [
            f"### {self.name} (`{self.id}` v{self.version})",
            "",
            f"*Category:* {self.category} · *Behaviour:* `{self.behavior.value}` · *Status:* **{self.validation_status.value}**",
            "",
            self.description.strip(),
            "",
            "| Parameter | Type | Default | Description |",
            "|---|---|---|---|",
        ]
        schema = self.param_schema()
        for name, prop in schema.get("properties", {}).items():
            typ = prop.get("type") or ("distribution" if "anyOf" in prop or "oneOf" in prop else "object")
            default = self.defaults.get(name, prop.get("default", ""))
            lines.append(f"| `{name}` | {typ} | `{default}` | {prop.get('description', '')} |")
        if self.kpis:
            lines += ["", "*KPIs:* " + ", ".join(self.kpis)]
        if self.tags:
            lines += ["", "*Tags:* " + ", ".join(self.tags)]
        return "\n".join(lines)


def _norm(text: str) -> str:
    text = text.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        text = text.replace(a, b)
    return text


class ComponentRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, ComponentDef]] = {}

    # ---------------- loading ----------------
    @classmethod
    def load_default(cls, user_dir: Path | None = None) -> "ComponentRegistry":
        reg = cls()
        reg.load_dir(CORE_DIR, origin="core")
        if user_dir and user_dir.exists():
            reg.load_dir(user_dir, origin="user")
        return reg

    def load_dir(self, directory: Path, origin: str) -> None:
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            items = data.get("components", [data]) if isinstance(data, dict) else data
            for item in items:
                try:
                    self.register(ComponentDef.model_validate({**item, "origin": origin}))
                except ValidationError as e:
                    raise ValueError(f"Componente inválido en {path.name}: {e}") from e

    def register(self, comp: ComponentDef) -> None:
        # Defaults must be valid for the behaviour, otherwise the component is broken.
        comp.params_model().model_validate(comp.defaults)
        self._by_id.setdefault(comp.id, {})[comp.version] = comp

    # ---------------- queries ----------------
    def get(self, comp_id: str, version: str | None = None) -> ComponentDef:
        versions = self._by_id.get(comp_id)
        if not versions:
            raise KeyError(f"El componente '{comp_id}' no existe en la biblioteca.")
        if version is None:
            return versions[max(versions, key=_semver)]
        if version not in versions:
            raise KeyError(f"El componente '{comp_id}' no tiene versión {version} (disponibles: {', '.join(versions)}).")
        return versions[version]

    def has(self, comp_id: str) -> bool:
        return comp_id in self._by_id

    def all(self) -> list[ComponentDef]:
        return [self.get(cid) for cid in sorted(self._by_id)]

    def versions(self, comp_id: str) -> list[str]:
        return sorted(self._by_id.get(comp_id, {}), key=_semver)

    def search(self, query: str = "", category: str | None = None, behavior: Behavior | None = None) -> list[ComponentDef]:
        """Deterministic keyword matching (tags, keywords, name, id). Embeddings can come later."""
        words = [w for w in re.split(r"[\s,;/]+", _norm(query)) if len(w) > 2]
        scored: list[tuple[float, ComponentDef]] = []
        for comp in self.all():
            if category and comp.category != category:
                continue
            if behavior and comp.behavior != behavior:
                continue
            if not words:
                scored.append((0, comp))
                continue
            hay_strong = [_norm(k) for k in [comp.id.replace("_", " "), comp.name, *comp.keywords]]
            hay_weak = [_norm(t) for t in [*comp.tags, comp.description]]
            score = 0.0
            for w in words:
                if any(w == h or w in h.split() for h in hay_strong):
                    score += 3
                elif any(w in h for h in hay_strong):
                    score += 2
                elif any(w in h for h in hay_weak):
                    score += 0.5
            if score > 0:
                # prefer specific (non-core) components on ties
                scored.append((score + (0.1 if comp.category != "core" else 0), comp))
        scored.sort(key=lambda t: (-t[0], t[1].id))
        return [c for _, c in scored]

    def catalog(self) -> list[dict[str, Any]]:
        """Compact catalog for LLM context (ids + one-line descriptions, no client data)."""
        return [
            {"id": c.id, "behavior": c.behavior.value, "category": c.category, "summary": c.description.split("\n")[0][:140]}
            for c in self.all()
        ]


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def save_user_component(comp: ComponentDef, user_dir: Path) -> Path:
    """Persist a user component version as its own YAML file (one file per version)."""
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{comp.id}__{comp.version}.yaml"
    data = comp.model_dump(mode="json", exclude={"origin"})
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
