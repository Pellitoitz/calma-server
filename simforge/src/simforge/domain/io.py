"""Load/save ISMS models as YAML or JSON."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from .isms import ISMSModel


class ModelFormatError(ValueError):
    pass


def model_from_dict(data: dict) -> ISMSModel:
    try:
        return ISMSModel.model_validate(data)
    except ValidationError as e:
        lines = [f"  - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ModelFormatError("El fichero no cumple el esquema ISMS:\n" + "\n".join(lines)) from None


def load_model(path: str | Path) -> ISMSModel:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)
    if isinstance(data, dict) and "model" in data and "meta" not in data:
        data = data["model"]  # project-style wrapper
    return model_from_dict(data)


def dump_model(model: ISMSModel, fmt: str = "yaml") -> str:
    data = model.model_dump(mode="json", exclude_none=True)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def save_model(model: ISMSModel, path: str | Path) -> None:
    p = Path(path)
    p.write_text(dump_model(model, "json" if p.suffix == ".json" else "yaml"), encoding="utf-8")
