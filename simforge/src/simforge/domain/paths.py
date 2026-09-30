"""Parameter paths: stable, human-readable addresses into an ISMS model.

    nodes.buffer_1.params.capacity
    nodes.assembly.params.process_time.value
    resources.operator_1.quantity
    simulation.horizon.value

Lists of identified objects (nodes, resources, entities) are addressed by id,
edges by index. Used by experiments, chat edit commands, diffs and history.
"""

from __future__ import annotations

import copy
from typing import Any

from .isms import ISMSModel

_ID_LISTS = {"nodes", "resources", "entities"}


class PathError(KeyError):
    def __str__(self) -> str:  # KeyError repr-quotes its message otherwise
        return str(self.args[0])


def _step(obj: Any, key: str, parent_key: str | None, create: bool) -> Any:
    if isinstance(obj, list):
        if parent_key in _ID_LISTS:
            for item in obj:
                if isinstance(item, dict) and item.get("id") == key:
                    return item
            raise PathError(f"No existe '{key}' en {parent_key}.")
        try:
            return obj[int(key)]
        except (ValueError, IndexError):
            raise PathError(f"Índice inválido '{key}' en {parent_key}.") from None
    if isinstance(obj, dict):
        if key not in obj:
            if create:
                obj[key] = {}
            else:
                raise PathError(f"No existe el campo '{key}'.")
        return obj[key]
    raise PathError(f"No se puede navegar dentro de '{parent_key}'.")


def get_value(model: ISMSModel, path: str) -> Any:
    data = model.model_dump(mode="json")
    cur: Any = data
    parent = None
    for key in path.split("."):
        cur = _step(cur, key, parent, create=False)
        parent = key
    return cur


def set_value(model: ISMSModel, path: str, value: Any) -> ISMSModel:
    """Return a NEW validated model with `path` set to `value` (models are treated as immutable)."""
    data = copy.deepcopy(model.model_dump(mode="json"))
    keys = path.split(".")
    cur: Any = data
    parent = None
    for key in keys[:-1]:
        cur = _step(cur, key, parent, create=False)
        parent = key
    last = keys[-1]
    if isinstance(cur, dict):
        in_params = len(keys) >= 4 and keys[0] == "nodes" and keys[2] == "params"
        if last not in cur and not in_params:
            raise PathError(f"El campo '{last}' no existe en '{'.'.join(keys[:-1])}'.")
        cur[last] = value
    elif isinstance(cur, list):
        cur[int(last)] = value
    else:
        raise PathError(f"No se puede asignar '{path}'.")
    return ISMSModel.model_validate(data)


def flatten(model: ISMSModel) -> dict[str, Any]:
    """Flatten to {path: leaf value} (lists of ids addressed by id)."""
    out: dict[str, Any] = {}

    def walk(obj: Any, prefix: str, parent_key: str | None) -> None:
        if isinstance(obj, dict):
            if not obj:
                out[prefix] = {}
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else k, k)
        elif isinstance(obj, list):
            if parent_key in _ID_LISTS and all(isinstance(i, dict) and "id" in i for i in obj):
                for item in obj:
                    walk({k: v for k, v in item.items() if k != "id"}, f"{prefix}.{item['id']}", None)
            elif obj and all(isinstance(i, (dict, list)) for i in obj):
                for i, item in enumerate(obj):
                    walk(item, f"{prefix}.{i}", None)
            else:
                out[prefix] = obj
        else:
            out[prefix] = obj

    walk(model.model_dump(mode="json", exclude={"approval"}), "", None)
    return out


def diff(a: ISMSModel, b: ISMSModel) -> list[tuple[str, Any, Any]]:
    """[(path, old, new)] for every changed leaf."""
    fa, fb = flatten(a), flatten(b)
    changes = []
    for p in sorted(set(fa) | set(fb)):
        if fa.get(p, "<absent>") != fb.get(p, "<absent>"):
            changes.append((p, fa.get(p, "<absent>"), fb.get(p, "<absent>")))
    return changes
