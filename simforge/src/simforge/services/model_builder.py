"""Model building without YAML (1.1-B): structural builder (C01), distribution editor (C02), transport editor (C03).

Typed operations on the ISMS model (the single source of truth). Every operation returns a NEW validated model; the
input is never mutated. Streamlit (Model tab) calls these functions; tests call the same functions.

Contracts (fixed, tested):
  * Only what the engineer DECLARES is written. No physical default is filled in: an absent value stays absent and the
    existing verifier reports it as MISSING. `Node.params` is hashed verbatim, so writing a default would also change
    the content hash.
  * Distribution unit: NOT DECLARED (the domain applies its existing default "s") is kept distinct from DECLARED "s".
  * Order: nodes, edges and resources keep the explicit construction order. The order is part of the existing
    content_hash; nothing is re-sorted (canonicalisation is a separate post-1.1 decision).
  * Unknown components / fields, duplicate ids, invalid values and dangling references are rejected (BuilderError);
    nothing is "fixed" automatically.
  * Blocks this editor does not handle (production, maintenance, availability/calendars, economics, experiments,
    custom rules...) are carried over untouched.
  * Approval stays bound to the content hash (no second mechanism): a semantic edit leaves the new content unapproved.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from ..domain.behaviors import BEHAVIOR_PARAMS, Behavior, TransportParams
from ..domain.isms import ISMSModel
from ..domain.isms_ext import SimModel
from ..domain.units import TIME_UNITS
from ..domain.values import Duration
from ..library.registry import ComponentRegistry

DOMAIN_DEFAULT_TIME_UNIT = "s"  # existing domain default of a distribution unit (values._Dist.unit); never written
UI_PROVENANCE = {"status": "provided_by_client", "source": "ui"}  # same convention as the 1.0 parameter editor


class BuilderError(ValueError):
    """An operation was refused; the model is unchanged."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------------------------ helpers
def _data(model: ISMSModel) -> dict[str, Any]:
    return copy.deepcopy(model.model_dump(mode="json"))


def _rebuild(data: dict[str, Any]) -> SimModel:
    try:
        return SimModel.model_validate(data)
    except ValidationError as e:
        raise BuilderError("; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())) from None


def _node(data: dict[str, Any], node_id: str) -> dict[str, Any]:
    for n in data["nodes"]:
        if n["id"] == node_id:
            return n
    raise BuilderError(f"No existe el nodo '{node_id}'.")


def _has_expression(x: Any) -> bool:
    if isinstance(x, str):
        return "$" in x
    if isinstance(x, dict):
        return any(_has_expression(v) for v in x.values())
    if isinstance(x, list):
        return any(_has_expression(v) for v in x)
    return False


def behavior_of(registry: ComponentRegistry, component: str) -> Behavior:
    if not registry.has(component):
        raise BuilderError(f"Componente desconocido '{component}' (no está en la biblioteca).")
    return registry.get(component).behavior


def validate_params(registry: ComponentRegistry, component: str, params: dict[str, Any]) -> None:
    """Validate node params against the component's behaviour schema (extra='forbid'), merged with the library
    defaults exactly as the engine resolves them. Values with '$parameter' expressions are resolved by the existing
    verifier later; for them only unknown fields are checked here."""
    comp = registry.get(component) if registry.has(component) else None
    if comp is None:
        raise BuilderError(f"Componente desconocido '{component}' (no está en la biblioteca).")
    cls = BEHAVIOR_PARAMS[comp.behavior]
    unknown = sorted(set(params) - set(cls.model_fields))
    if unknown:
        raise BuilderError(f"Campo(s) desconocido(s) para '{component}' ({comp.behavior.value}): {', '.join(unknown)}.")
    if _has_expression(params):
        return
    try:
        comp.resolve_params(params)
    except ValidationError as e:
        raise BuilderError("; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())) from None


def _check_param_refs(data: dict[str, Any], node_id: str, params: dict[str, Any]) -> None:
    nodes = {n["id"] for n in data["nodes"]}
    resources = {r["id"] for r in data["resources"]}
    for use in params.get("resources", []) or []:
        rid = use.get("resource") if isinstance(use, dict) else None
        if rid is not None and rid not in resources:
            raise BuilderError(f"El nodo '{node_id}' usa el recurso '{rid}', que no existe.")
    for key in ("origin", "destination"):
        v = params.get(key)
        if isinstance(v, str) and v not in nodes:
            raise BuilderError(f"'{key}' del nodo '{node_id}' apunta a un nodo inexistente ('{v}').")
    rej = params.get("on_reject")
    if isinstance(rej, str) and rej != "scrap" and rej not in nodes:
        raise BuilderError(f"'on_reject' del nodo '{node_id}' apunta a un nodo inexistente ('{rej}').")


# ------------------------------------------------------------------------------------------------ model
def new_model(name: str, horizon: dict[str, Any], description: str = "", warmup: dict[str, Any] | None = None,
              replications: int | None = None, base_seed: int | None = None) -> SimModel:
    """Empty model. The horizon is required (no 8 h default from the builder); the other settings are written only
    when declared."""
    if not (name or "").strip():
        raise BuilderError("El modelo necesita un nombre.")
    if not horizon or horizon.get("value") in (None, "") or not horizon.get("unit"):
        raise BuilderError("El horizonte es obligatorio (valor y unidad).")
    sim: dict[str, Any] = {"horizon": horizon}
    for k, v in (("warmup", warmup), ("replications", replications), ("base_seed", base_seed)):
        if v is not None:
            sim[k] = v
    meta = {"name": name.strip(), **({"description": description} if description else {})}
    return _rebuild({"meta": meta, "simulation": sim})


# ------------------------------------------------------------------------------------------------ nodes (C01)
def add_node(model: ISMSModel, registry: ComponentRegistry, node_id: str, component: str, name: str | None = None,
             params: dict[str, Any] | None = None, priority: int | None = None) -> SimModel:
    """Append a node (construction order is kept). Only the declared fields are written."""
    data = _data(model)
    if any(n["id"] == node_id for n in data["nodes"]):
        raise BuilderError(f"Ya existe un nodo con id '{node_id}'.")
    behavior_of(registry, component)
    params = dict(params or {})
    validate_params(registry, component, params)
    _check_param_refs(data, node_id, params)
    node: dict[str, Any] = {"id": node_id, "component": component}
    if name:
        node["name"] = name
    if params:
        node["params"] = params
    if priority is not None:
        node["priority"] = priority
    data["nodes"].append(node)
    return _rebuild(data)


_UNSET: Any = object()


def update_node(model: ISMSModel, registry: ComponentRegistry, node_id: str, *, name: Any = _UNSET,
                params: Any = _UNSET, priority: Any = _UNSET) -> SimModel:
    """Replace the given attributes of a node (params as a whole: keys not in `params` are removed)."""
    data = _data(model)
    n = _node(data, node_id)
    if name is not _UNSET:
        n["name"] = name or ""
    if params is not _UNSET:
        params = dict(params or {})
        validate_params(registry, n["component"], params)
        _check_param_refs(data, node_id, params)
        n["params"] = params
    if priority is not _UNSET:
        n["priority"] = int(priority)
    return _rebuild(data)


def set_node_params(model: ISMSModel, registry: ComponentRegistry, node_id: str, changes: dict[str, Any]) -> SimModel:
    """Set (value) or remove (None -> NOT DECLARED, reported as MISSING when required) individual params; the other
    params of the node are kept as they are."""
    n = next((x for x in model.nodes if x.id == node_id), None)
    if n is None:
        raise BuilderError(f"No existe el nodo '{node_id}'.")
    params = copy.deepcopy(n.params)
    for k, v in changes.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return update_node(model, registry, node_id, params=params)


def node_references(model: ISMSModel, node_id: str) -> list[str]:
    """Paths (outside the node itself and the edges) that name `node_id`: transports, carriers, operator homes,
    dispatch strategies, calendars, production, maintenance, economics... Conservative exact-string scan."""
    skip_keys = {"unit", "dist", "status", "basis", "kind", "dispatch", "arrival", "discipline", "batch", "mode", "method",
                 "bound_type", "note", "name", "description", "message", "currency", "category", "metric", "role",
                 "component", "component_version", "isms_version", "reason", "text", "question", "source_file"}
    data = model.model_dump(mode="json", exclude={"meta": True, "approval": True, "edges": True})
    data["nodes"] = [n for n in data["nodes"] if n["id"] != node_id]
    out: list[str] = []

    def walk(x: Any, path: str, key: str | None) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}" if path else k
                if k == node_id:
                    out.append(p)
                walk(v, p, k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}.{v['id'] if isinstance(v, dict) and 'id' in v else i}", key)
        elif isinstance(x, str) and x == node_id and key not in skip_keys:
            out.append(path)
    walk(data, "", None)
    return out


def remove_node(model: ISMSModel, node_id: str, cascade_edges: bool = False) -> SimModel:
    """Remove a node. Its connections are removed only with an explicit cascade; any other reference refuses the
    removal (nothing is deleted silently)."""
    data = _data(model)
    _node(data, node_id)
    edges = [e for e in data["edges"] if node_id in (e["source"], e["target"])]
    if edges and not cascade_edges:
        raise BuilderError(f"El nodo '{node_id}' tiene {len(edges)} conexión(es): quítalas antes o confirma el borrado en "
                           "cascada de sus conexiones.")
    refs = node_references(model, node_id)
    if refs:
        raise BuilderError(f"El nodo '{node_id}' está referenciado en: {', '.join(refs)}. Elimina esas referencias antes.")
    data["nodes"] = [n for n in data["nodes"] if n["id"] != node_id]
    data["edges"] = [e for e in data["edges"] if node_id not in (e["source"], e["target"])]
    return _rebuild(data)


# ------------------------------------------------------------------------------------------------ edges (C01)
def add_edge(model: ISMSModel, registry: ComponentRegistry, source: str, target: str,
             probability: float | str | None = None) -> SimModel:
    data = _data(model)
    s, t = _node(data, source), _node(data, target)
    if source == target:
        raise BuilderError("Una conexión no puede unir un nodo consigo mismo.")
    if any(e["source"] == source and e["target"] == target for e in data["edges"]):
        raise BuilderError(f"La conexión {source} → {target} ya existe.")
    if behavior_of(registry, s["component"]) is Behavior.SINK:
        raise BuilderError(f"'{source}' es un sumidero (sink): no puede tener salidas.")
    if behavior_of(registry, t["component"]) is Behavior.SOURCE:
        raise BuilderError(f"'{target}' es una fuente (source): no puede tener entradas.")
    edge: dict[str, Any] = {"source": source, "target": target}
    if probability is not None:
        edge["probability"] = probability
    data["edges"].append(edge)
    return _rebuild(data)


def update_edge(model: ISMSModel, source: str, target: str, probability: float | str | None) -> SimModel:
    """Set (or, with None, remove = not declared) the routing probability of an existing connection."""
    data = _data(model)
    e = next((x for x in data["edges"] if x["source"] == source and x["target"] == target), None)
    if e is None:
        raise BuilderError(f"No existe la conexión {source} → {target}.")
    e["probability"] = probability
    return _rebuild(data)


def remove_edge(model: ISMSModel, source: str, target: str) -> SimModel:
    data = _data(model)
    before = len(data["edges"])
    data["edges"] = [e for e in data["edges"] if not (e["source"] == source and e["target"] == target)]
    if len(data["edges"]) == before:
        raise BuilderError(f"No existe la conexión {source} → {target}.")
    return _rebuild(data)


# ------------------------------------------------------------------------------------------------ resources
def add_resource(model: ISMSModel, resource_id: str, quantity: int | str, kind: str | None = None,
                 name: str | None = None) -> SimModel:
    """Append a resource. The quantity is required (no default of 1 from the builder)."""
    data = _data(model)
    if any(r["id"] == resource_id for r in data["resources"]):
        raise BuilderError(f"Ya existe un recurso con id '{resource_id}'.")
    if quantity is None or quantity == "":
        raise BuilderError("La cantidad del recurso es obligatoria.")
    if isinstance(quantity, (int, float)) and (quantity < 0 or float(quantity) != int(quantity)):
        raise BuilderError("La cantidad del recurso debe ser un entero >= 0.")
    res: dict[str, Any] = {"id": resource_id, "quantity": int(quantity) if isinstance(quantity, (int, float)) else quantity}
    if kind:
        res["kind"] = kind
    if name:
        res["name"] = name
    data["resources"].append(res)
    return _rebuild(data)


def remove_resource(model: ISMSModel, resource_id: str) -> SimModel:
    data = _data(model)
    if not any(r["id"] == resource_id for r in data["resources"]):
        raise BuilderError(f"No existe el recurso '{resource_id}'.")
    users = [n["id"] for n in data["nodes"]
             if any(isinstance(u, dict) and u.get("resource") == resource_id for u in (n.get("params") or {}).get("resources", []) or [])
             or any(u["resource"] == resource_id for u in n.get("seize", []))]
    if users:
        raise BuilderError(f"El recurso '{resource_id}' se usa en: {', '.join(users)}. Quítalo de esos nodos antes.")
    data["resources"] = [r for r in data["resources"] if r["id"] != resource_id]
    return _rebuild(data)


# ------------------------------------------------------------------------------------------------ distributions (C02)
_DURATION = TypeAdapter(Duration)
_COMMON = {"dist", "unit", "provenance", "truncation"}
DISTRIBUTIONS: dict[str, list[str]] = {
    cls.model_fields["dist"].default: [f for f in cls.model_fields if f not in _COMMON]
    for cls in Duration.__origin__.__args__  # type: ignore[attr-defined]
}
TIME_UNIT_CHOICES = TIME_UNITS


class DistributionForm(_Strict):
    """Editor representation of a duration distribution. unit = None means NOT DECLARED (domain default applies)."""
    family: str
    params: dict[str, int | float | list[int | float]]  # numbers kept as declared (60 stays 60: params are hashed verbatim)
    unit: str | None = None
    truncation: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    @property
    def unit_declared(self) -> bool:
        return self.unit is not None

    @property
    def effective_unit(self) -> str:
        return self.unit if self.unit is not None else DOMAIN_DEFAULT_TIME_UNIT


def distribution_to_form(raw: dict[str, Any]) -> DistributionForm:
    """Model value -> editor form. Unknown keys are an error (never dropped)."""
    if not isinstance(raw, dict) or raw.get("dist") not in DISTRIBUTIONS:
        raise BuilderError(f"Distribución no soportada: {raw!r}.")
    fam = raw["dist"]
    unknown = sorted(set(raw) - _COMMON - set(DISTRIBUTIONS[fam]))
    if unknown:
        raise BuilderError(f"Campo(s) desconocido(s) en la distribución '{fam}': {', '.join(unknown)}.")
    return DistributionForm(family=fam, params={k: raw[k] for k in DISTRIBUTIONS[fam] if k in raw}, unit=raw.get("unit"),
                            truncation=raw.get("truncation"), provenance=raw.get("provenance"))


def _semantic(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k != "provenance"}


def distribution_from_form(form: DistributionForm, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Editor form -> model value (validated by the domain). Only declared fields are written: an undeclared unit stays
    undeclared. Provenance: kept as is when nothing semantic changed; a semantic edit is an explicit engineer action and
    is recorded with the 1.0 UI convention (provided_by_client / ui) instead of keeping a provenance that no longer
    describes the value (e.g. a dataset link)."""
    if form.family not in DISTRIBUTIONS:
        raise BuilderError(f"Distribución no soportada '{form.family}'. Soportadas: {', '.join(DISTRIBUTIONS)}.")
    unknown = sorted(set(form.params) - set(DISTRIBUTIONS[form.family]))
    if unknown:
        raise BuilderError(f"Parámetro(s) desconocido(s) para '{form.family}': {', '.join(unknown)}.")
    raw: dict[str, Any] = {"dist": form.family, **{k: form.params[k] for k in DISTRIBUTIONS[form.family] if k in form.params}}
    if form.unit is not None:
        raw["unit"] = form.unit
    if form.truncation is not None:
        raw["truncation"] = form.truncation
    if previous is not None and _semantic(previous) == raw:
        if previous.get("provenance") is not None:
            raw["provenance"] = previous["provenance"]
    elif form.provenance is not None and (previous is None or form.provenance != previous.get("provenance")):
        raw["provenance"] = form.provenance  # provenance explicitly given by the caller
    elif previous is not None and previous.get("provenance") is not None:
        raw["provenance"] = dict(UI_PROVENANCE)
    try:
        _DURATION.validate_python(raw)
    except ValidationError as e:
        raise BuilderError("; ".join(f"{'.'.join(str(x) for x in err['loc'][1:]) or form.family}: {err['msg']}"
                                     for err in e.errors())) from None
    return raw


def set_distribution(model: ISMSModel, registry: ComponentRegistry, node_id: str, param: str,
                     form: DistributionForm | None) -> SimModel:
    """Set a duration param of a node (process_time, interarrival, load_time, unload_time...) from the editor;
    None removes it (NOT DECLARED -> MISSING where required)."""
    n = next((x for x in model.nodes if x.id == node_id), None)
    if n is None:
        raise BuilderError(f"No existe el nodo '{node_id}'.")
    if form is None:
        return set_node_params(model, registry, node_id, {param: None})
    return set_node_params(model, registry, node_id, {param: distribution_from_form(form, n.params.get(param))})


# ------------------------------------------------------------------------------------------------ transport (C03)
TRANSPORT_FIELDS: list[str] = list(TransportParams.model_fields)
TRANSPORT_QUANTITIES = {"distance": "length", "speed": "speed"}
TRANSPORT_DURATIONS = ("load_time", "unload_time")


def set_transport(model: ISMSModel, registry: ComponentRegistry, node_id: str, changes: dict[str, Any]) -> SimModel:
    """Transport editor: set (value) or remove (None) existing TransportParams fields of a transport node.
    distance/speed are {value, unit} quantities; load_time/unload_time are distributions (dict or DistributionForm).
    Unknown fields, dangling origin/destination/resource references and invalid values are refused."""
    n = next((x for x in model.nodes if x.id == node_id), None)
    if n is None:
        raise BuilderError(f"No existe el nodo '{node_id}'.")
    if behavior_of(registry, n.component) is not Behavior.TRANSPORT:
        raise BuilderError(f"'{node_id}' no es un transporte ({n.component}).")
    unknown = sorted(set(changes) - set(TRANSPORT_FIELDS))
    if unknown:
        raise BuilderError(f"Campo(s) desconocido(s) del transporte: {', '.join(unknown)}.")
    resolved: dict[str, Any] = {}
    for k, v in changes.items():
        if isinstance(v, DistributionForm):
            v = distribution_from_form(v, n.params.get(k))
        if k in TRANSPORT_QUANTITIES and isinstance(v, dict):
            prev = n.params.get(k)
            if isinstance(prev, dict) and {a: b for a, b in prev.items() if a != "provenance"} == v and prev.get("provenance"):
                v = {**v, "provenance": prev["provenance"]}
        resolved[k] = v
    return set_node_params(model, registry, node_id, resolved)


# ------------------------------------------------------------------------------------------------ inspection
class NodeSummary(_Strict):
    position: int
    id: str
    component: str
    behavior: Literal["source", "sink", "buffer", "server", "transport", "unknown"]
    name: str
    declared_params: list[str]


def summarize_nodes(model: ISMSModel, registry: ComponentRegistry) -> list[NodeSummary]:
    out = []
    for i, n in enumerate(model.nodes):
        b = registry.get(n.component).behavior.value if registry.has(n.component) else "unknown"
        out.append(NodeSummary(position=i, id=n.id, component=n.component, behavior=b, name=n.name,
                               declared_params=sorted(n.params)))
    return out
