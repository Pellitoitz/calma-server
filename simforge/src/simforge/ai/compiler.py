"""Deterministic Draft -> ISMS compiler (library first, never invent).

1. SEARCH the library for each step (exact id -> keyword search -> generic core).
2. REUSE + CONFIGURE the component with the stated parameters.
3. Anything not stated becomes MISSING (blocking) or an explicit ASSUMPTION.
4. GROUNDING CHECK: every number must appear in the user's text; otherwise it
   is downgraded to 'assumed' and flagged (defence against hallucinated values).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain.behaviors import Behavior, ResourceUse
from ..domain.isms import (Assumption, DispatchRule, Edge, ExperimentSpec, Factor, ISMSModel, MissingInfo, ModelMeta, Node, Resource,
                           ResourceKind, SimulationSettings)
from ..domain.values import Provenance, ValueStatus
from ..library.registry import ComponentRegistry
from .schemas import DraftTime, ProcessDraft

_WORD_NUMBERS = {"un": 1, "una": 1, "uno": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3, "cuatro": 4, "four": 4,
                 "cinco": 5, "five": 5, "seis": 6, "six": 6, "siete": 7, "seven": 7, "ocho": 8, "eight": 8,
                 "nueve": 9, "nine": 9, "diez": 10, "ten": 10, "doce": 12, "veinte": 20, "treinta": 30}


def numbers_in(text: str) -> set[float]:
    nums = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)}
    for w in re.findall(r"[a-záéíóúñ]+", text.lower()):
        if w in _WORD_NUMBERS:
            nums.add(float(_WORD_NUMBERS[w]))
    if re.search(r"\b(el mismo|la misma|mismo|same)\b", text.lower()):
        nums.add(1.0)
    return nums


def _snake(s: str) -> str:
    s = s.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s or not s[0].isalpha():
        s = "n_" + s
    return s


@dataclass
class ParseOutcome:
    model: ISMSModel
    draft: ProcessDraft
    component_matches: list[dict] = field(default_factory=list)  # step -> component, how
    ungrounded: list[str] = field(default_factory=list)

    @property
    def reuse_ratio(self) -> float:
        """Share of process nodes built from specific library components (vs generic fallbacks)."""
        if not self.component_matches:
            return 0.0
        return sum(1 for m in self.component_matches if m["how"] != "generic_fallback") / len(self.component_matches)


def _dist(t: DraftTime, prov: Provenance) -> dict:
    d: dict = {"dist": t.dist, "unit": t.unit, "provenance": prov.model_dump(mode="json", exclude_none=True)}
    fields = {"constant": ["value"], "uniform": ["low", "high"], "triangular": ["low", "mode", "high"],
              "normal": ["mean", "std"], "lognormal": ["mean", "std"], "exponential": ["mean"]}[t.dist]
    for f in fields:
        d[f] = getattr(t, f)
    return d


def _time_numbers(t: DraftTime) -> list[float]:
    return [v for v in (t.value, t.low, t.mode, t.high, t.mean, t.std) if v is not None]


def compile_draft(draft: ProcessDraft, registry: ComponentRegistry, source_text: str, source: str = "chat") -> ParseOutcome:
    now = datetime.now(timezone.utc)
    stated = numbers_in(source_text)
    assumptions: list[Assumption] = []
    missing: list[MissingInfo] = []
    matches: list[dict] = []
    ungrounded: list[str] = []

    def grounded(value: float, what: str) -> bool:
        if value in stated:
            return True
        ungrounded.append(f"{what} = {value:g}")
        return False

    def prov(ok: bool, note: str | None = None) -> Provenance:
        return Provenance(status=ValueStatus.PROVIDED_BY_CLIENT if ok else ValueStatus.ASSUMED,
                          source=source, timestamp=now, note=note)

    def assume(text: str, path: str | None = None, origin: str = "ai") -> None:
        assumptions.append(Assumption(id=f"a{len(assumptions) + 1}", text=text, path=path, origin=origin))  # type: ignore[arg-type]

    # ---------------- resources ----------------
    resources: list[Resource] = []
    res_ids: dict[str, str] = {}
    for r in draft.resources:
        rid = _snake(r.id)
        res_ids[r.id] = rid
        qty = r.quantity
        if qty is None:
            qty = 1
            if r.kind == "carrier":
                missing.append(MissingInfo(question=f"¿Cuántas unidades de '{r.name}' hay?", path=f"resources.{rid}.quantity"))
            else:
                assume(f"Se asume 1 unidad de '{r.name}' (no se indicó cantidad).", f"resources.{rid}.quantity")
        elif not grounded(float(qty), f"cantidad de {r.name}"):
            assume(f"Cantidad de '{r.name}' = {qty} no aparece en la descripción: revisar.", f"resources.{rid}.quantity")
        resources.append(Resource(id=rid, name=r.name, kind=ResourceKind(r.kind), quantity=qty, provenance=prov(True)))

    # ---------------- source ----------------
    nodes: list[Node] = []
    src_params: dict = {"arrival": "infinite"}
    if draft.supply == "interarrival" and draft.interarrival:
        ok = all(grounded(v, "intervalo de llegadas") for v in _time_numbers(draft.interarrival))
        src_params = {"arrival": "interarrival", "interarrival": _dist(draft.interarrival, prov(ok))}
    elif draft.supply == "interarrival":
        missing.append(MissingInfo(question="¿Cada cuánto llegan las unidades?", path="nodes.source.params.interarrival"))
    elif draft.supply == "unknown":
        assume("Suministro infinito (la primera estación nunca espera material): no se indicó la llegada.", "nodes.source.params.arrival")
    nodes.append(Node(id="source", name="Source", component="source", params=src_params))

    # ---------------- steps ----------------
    used_ids = {"source", "sink"} | set(res_ids.values())
    step_ids: dict[str, str] = {}
    for i, s in enumerate(draft.steps):
        nid = _snake(s.id)
        while nid in used_ids:
            nid = f"{nid}_{i}"
        used_ids.add(nid)
        step_ids[s.id] = nid

        # library first
        how = "exact"
        comp = registry.get(s.component) if registry.has(s.component) else None
        if comp is None:
            hits = registry.search(f"{s.component} {s.name}")
            hits = [h for h in hits if h.behavior not in (Behavior.SOURCE, Behavior.SINK)]
            if hits:
                comp, how = hits[0], "search"
            else:
                comp = registry.get("manual_process" if s.resources else "machine")
                how = "generic_fallback"
                assume(f"No hay componente específico para '{s.name}': se usa '{comp.id}' genérico.", f"nodes.{nid}.component", "system")
        matches.append({"step": s.name, "node": nid, "component": comp.id, "version": comp.version, "how": how})

        params: dict = {}
        if comp.behavior is Behavior.BUFFER:
            if s.capacity is None:
                missing.append(MissingInfo(question=f"¿Qué capacidad tiene '{s.name}'?", path=f"nodes.{nid}.params.capacity"))
                params["capacity"] = 1
            else:
                if not grounded(float(s.capacity), f"capacidad de {s.name}"):
                    assume(f"Capacidad de '{s.name}' = {s.capacity} no aparece en la descripción: revisar.", f"nodes.{nid}.params.capacity")
                params["capacity"] = s.capacity
        else:
            if s.time is None or not _time_numbers(s.time):
                missing.append(MissingInfo(question=f"¿Cuánto dura '{s.name}'?", path=f"nodes.{nid}.params.process_time"))
            else:
                ok = all(grounded(v, f"tiempo de {s.name}") for v in _time_numbers(s.time))
                if not ok:
                    assume(f"El tiempo de '{s.name}' no aparece literalmente en la descripción: revisar.", f"nodes.{nid}.params.process_time")
                params["process_time"] = _dist(s.time, prov(ok))
            if s.capacity:
                params["capacity"] = s.capacity
            uses = []
            for r in s.resources:
                rid = res_ids.get(r, _snake(r))
                if rid not in {x.id for x in resources}:
                    resources.append(Resource(id=rid, name=r, quantity=1))
                    res_ids[r] = rid
                    assume(f"Recurso '{r}' creado con 1 unidad (no se describió).", f"resources.{rid}.quantity")
                uses.append({"resource": rid})
            if uses:
                params["resources"] = uses
            if s.yield_rate is not None:
                params["yield_rate"] = s.yield_rate
        nodes.append(Node(id=nid, name=s.name, component=comp.id, component_version=comp.version, params=params))

    nodes.append(Node(id="sink", name="Sink", component="sink"))
    edges = [Edge(source=a.id, target=b.id) for a, b in zip(nodes, nodes[1:])]

    # ---------------- shared resources & policies ----------------
    res_by_id = {r.id: r for r in resources}
    policies = {res_ids.get(p.resource, _snake(p.resource)): p for p in draft.policies}
    for r in resources:
        users = [n for n in nodes if any(u.get("resource") == r.id for u in n.params.get("resources", []))]
        if len(users) >= 2 and r.quantity <= len(users):
            pol = policies.get(r.id)
            if pol and pol.rule == "priority" and pol.priority_order:
                r.dispatch = DispatchRule.PRIORITY
                order = [step_ids.get(s, _snake(s)) for s in pol.priority_order]
                for n in users:
                    n.priority = order.index(n.id) if n.id in order else len(order)
            elif pol:
                r.dispatch = DispatchRule.FIFO
            else:
                names = ", ".join(n.name for n in users)
                assume(f"'{r.name}' es compartido por {names}: se asume FIFO (atiende la petición más antigua).",
                       f"resources.{r.id}.dispatch")
                missing.append(MissingInfo(
                    question=f"'{r.name}' hace {names}. Cuando varias tareas le requieren a la vez, ¿cuál tiene prioridad? "
                             "(p.ej. mantener alimentada la máquina / vaciar primero la inspección / FIFO)",
                    path=f"resources.{r.id}.dispatch", required=False))

    # ---------------- carrier loops (racks, pallets) ----------------
    for loop in draft.carrier_loops:
        rid = res_ids.get(loop.resource, _snake(loop.resource))
        a, b = step_ids.get(loop.seize_at), step_ids.get(loop.release_at)
        if rid in res_by_id and a and b:
            res_by_id[rid].kind = ResourceKind.CARRIER
            for n in nodes:
                if n.id == a:
                    n.seize = [ResourceUse(resource=rid)]
                if n.id == b:
                    n.release = [rid]
        else:
            missing.append(MissingInfo(question=f"¿En qué paso se carga y se libera '{loop.resource}'?", path=f"resources.{rid}"))
    for r in resources:
        if r.kind is ResourceKind.CARRIER and not any(u.resource == r.id for n in nodes for u in n.seize):
            missing.append(MissingInfo(question=f"¿En qué paso se carga y se libera '{r.name}'?", path=f"resources.{r.id}"))

    # ---------------- horizon ----------------
    if draft.horizon_value is None:
        horizon = {"value": 8, "unit": "h", "provenance": Provenance.assumed("default 8 h").model_dump(mode="json")}
        assume("Horizonte de simulación de 8 h (no se indicó).", "simulation.horizon")
    else:
        ok = grounded(draft.horizon_value, "horizonte")
        horizon = {"value": draft.horizon_value, "unit": draft.horizon_unit, "provenance": prov(ok).model_dump(mode="json")}

    # ---------------- experiments requested in the description ----------------
    experiments = []
    for ex in draft.experiments:
        path = _experiment_path(ex.target, nodes, resources)
        if path:
            vals = [int(v) if float(v).is_integer() else v for v in ex.values]
            experiments.append(ExperimentSpec(name=f"{ex.target} sweep", factors=[Factor(path=path, values=vals)]))
        else:
            missing.append(MissingInfo(question=f"No sé qué parámetro variar para '{ex.target}'.", required=False))

    for q in draft.missing_information:
        if not any(q.question == m.question for m in missing):
            missing.append(MissingInfo(question=q.question, required=q.required))
    for a in draft.assumptions:
        assume(a)
    if ungrounded:
        assume("Valores no encontrados literalmente en la descripción: " + "; ".join(ungrounded), None, "system")

    model = ISMSModel(
        meta=ModelMeta(name=draft.model_name or "Modelo", description=source_text[:500]),
        simulation=SimulationSettings.model_validate({"horizon": horizon}),
        resources=resources, nodes=nodes, edges=edges,
        assumptions=assumptions, missing=missing, experiments=experiments,
    )
    return ParseOutcome(model, draft, matches, ungrounded)


def _experiment_path(target: str, nodes: list[Node], resources: list[Resource]) -> str | None:
    t = target.lower()
    if any(k in t for k in ("bastidor", "rack", "palet", "pallet", "carrier")):
        carriers = [r for r in resources if r.kind is ResourceKind.CARRIER]
        return f"resources.{carriers[0].id}.quantity" if carriers else None
    if any(k in t for k in ("operari", "operator", "persona")):
        ops = [r for r in resources if r.kind is ResourceKind.OPERATOR]
        return f"resources.{ops[0].id}.quantity" if ops else None
    if "buffer" in t or "cola" in t:
        bufs = [n for n in nodes if n.component == "buffer"]
        return f"nodes.{bufs[0].id}.params.capacity" if bufs else None
    return None
