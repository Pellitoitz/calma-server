"""Deterministic Draft -> ISMS compiler (v2): library first, never invent.

    interpretation (ProcessDraft, from rules or an LLM)
      -> component / resource-type / strategy MATCHING against the library
      -> PARAMETER MAPPING: every number becomes a traceable model parameter
         (USER_PROVIDED, ASSUMED, DEFAULT, CALCULATED or MISSING)
      -> MISSING-INFORMATION detection (grouped questions)
      -> MODEL ASSEMBLY (ISMS, generic engine behaviours only)
      -> BUILD PLAN + MATCHING REPORT for the engineer

Grounding: a number claimed as user-provided must appear in the text; otherwise it is downgraded
to ASSUMED and reported. Prototype mode may use library defaults (status DEFAULT, always listed);
strict mode (default) leaves them MISSING.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..domain.behaviors import Behavior
from ..domain.io import model_from_dict
from ..domain.isms import ISMSModel
from ..library.registry import ComponentRegistry
from .schemas import DraftStep, DraftTime, ProcessDraft

COMPILER_VERSION = "compiler_v2"

_WORD_NUMBERS = {"un": 1, "una": 1, "uno": 1, "one": 1, "a": 1, "an": 1, "dos": 2, "two": 2, "tres": 3, "three": 3,
                 "cuatro": 4, "four": 4, "cinco": 5, "five": 5, "seis": 6, "six": 6, "siete": 7, "seven": 7, "ocho": 8,
                 "eight": 8, "nueve": 9, "nine": 9, "diez": 10, "ten": 10, "doce": 12, "veinte": 20, "treinta": 30}

STATUS_LABEL = {"measured": "MEASURED", "provided_by_client": "USER_PROVIDED", "imported": "IMPORTED", "assumed": "ASSUMED",
                "calculated": "CALCULATED", "default": "DEFAULT", "estimated": "ESTIMATED"}


def numbers_in(text: str) -> set[float]:
    nums = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)}
    for w in re.findall(r"[a-záéíóúñ]+", text.lower()):
        if w in _WORD_NUMBERS and w not in ("a",):
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


# ------------------------------------------------------------------------------------------------
@dataclass
class Match:
    element: str  # what the user described
    kind: str  # component | resource_type | strategy | custom
    match_id: str | None
    version: str | None
    how: str  # exact | keyword | generic | engine_rule | not_found
    node: str | None = None

    @property
    def reused(self) -> bool:
        return self.kind != "custom" and self.match_id is not None


@dataclass
class BuildPlan:
    entities: list[str]
    resources: list[str]
    process: list[str]
    rules: list[str]
    experiments: list[str]
    custom_logic: list[str]

    def to_text(self) -> str:
        L = ["MODEL BUILD PLAN", "", "Entities:"] + [f"- {e}" for e in self.entities]
        L += ["", "Resources:"] + [f"- {r}" for r in self.resources] or ["- none"]
        L += ["", "Process:", "\n→ ".join(self.process)]
        L += ["", "Rules:"] + ([f"- {r}" for r in self.rules] or ["- none"])
        L += ["", "Experiment:"] + ([f"- {e}" for e in self.experiments] or ["- none"])
        L += ["", "Custom logic:"] + ([f"- {c}" for c in self.custom_logic] or ["- none"])
        return "\n".join(L)


@dataclass
class ParseOutcome:
    model: ISMSModel
    draft: ProcessDraft
    matches: list[Match] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)
    plan: BuildPlan | None = None

    @property
    def component_matches(self) -> list[dict]:  # backward compatible view (process nodes)
        return [{"step": m.element, "node": m.node, "component": m.match_id, "version": m.version,
                 "how": "generic_fallback" if m.how == "generic" else m.how} for m in self.matches if m.kind == "component"]

    @property
    def reused_count(self) -> int:
        return sum(1 for m in self.matches if m.reused)

    @property
    def custom_count(self) -> int:
        return sum(1 for m in self.matches if not m.reused)

    @property
    def reuse_ratio(self) -> float:
        return self.reused_count / len(self.matches) if self.matches else 0.0

    def matching_report(self) -> str:
        w = max([len(m.element) for m in self.matches] + [18])
        L = [f"{'PROCESS ELEMENT':<{w}}  MATCH", ""]
        for m in self.matches:
            match = f"{m.match_id} v{m.version}" if m.match_id else "— NOT FOUND (custom rule candidate)"
            L.append(f"{m.element:<{w}}  {match}  [{m.kind}, {m.how}]")
        L += ["", f"REUSED COMPONENTS: {self.reused_count}", f"CUSTOM COMPONENTS: {self.custom_count}",
              f"REUSE RATIO: {self.reuse_ratio:.0%}"]
        return "\n".join(L)

    def questions(self) -> list[str]:
        qs = [f"{p.description or p.id} ({p.unit})" if p.unit else (p.description or p.id)
              for p in self.model.parameters if p.value is None]
        qs += [m.question for m in self.model.missing if m.required]
        return qs

    def questions_text(self) -> str:
        qs = self.questions()
        opt = [m.question for m in self.model.missing if not m.required]
        if not qs and not opt:
            return "No falta ningún dato obligatorio."
        L = [f"Para poder ejecutar el modelo necesito {len(qs)} dato{'s' if len(qs) != 1 else ''}:"] if qs else []
        L += [f"{i}. {q}" for i, q in enumerate(qs, 1)]
        if opt:
            L += ["", "Opcional (hay un supuesto aplicado, confírmalo o corrígelo):"] + [f"- {q}" for q in opt]
        return "\n".join(L)


# ------------------------------------------------------------------------------------------------
def _time_numbers(t: DraftTime) -> list[float]:
    return [v for v in (t.value, t.low, t.mode, t.high, t.mean, t.std) if v is not None]


class _Builder:
    def __init__(self, draft: ProcessDraft, registry: ComponentRegistry, text: str, source: str, prototype: bool):
        self.d, self.reg, self.text, self.source, self.prototype = draft, registry, text, source, prototype
        self.stated = numbers_in(text)
        self.now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.params: dict[str, dict] = {}
        self.assumptions: list[dict] = []
        self.missing: list[dict] = []
        self.matches: list[Match] = []
        self.ungrounded: list[str] = []

    # ---- traceable parameters ----
    def param(self, pid: str, value: float | None, unit: str, desc: str, status: str = "user", note: str | None = None,
              role: str = "fixed", what: str | None = None, default_key: str | None = None) -> str:
        """Register a parameter and return its '$ref'. status: user | assumed | calculated | default."""
        pid = _snake(pid)
        prov: dict[str, Any] | None = None
        if value is None and default_key and self.prototype and default_key in self.reg.defaults:
            dflt = self.reg.defaults[default_key]
            value, status = dflt["value"], "default"
            note = f"library default ({dflt['justification']})"
            self.assume(f"{desc} = {value} {unit} (DEFAULT de biblioteca, modo prototipo): {dflt['justification']}",
                        f"parameters.{pid}.value", "library_default")
        if value is not None:
            if status == "user" and float(value) not in self.stated:
                self.ungrounded.append(f"{what or desc} = {value:g}")
                status = "assumed"
                note = "value not found in the description"
            prov = {"status": {"user": "provided_by_client", "assumed": "assumed", "calculated": "calculated",
                               "default": "default"}[status], "source": self.source if status == "user" else status,
                    "timestamp": self.now}
            if note:
                prov["note"] = note
        self.params[pid] = {"id": pid, "value": value, "unit": unit, "description": desc, "role": role,
                            **({"provenance": prov} if prov else {})}
        return f"${pid}"

    def assume(self, text: str, path: str | None = None, origin: str = "ai") -> None:
        self.assumptions.append({"id": f"a{len(self.assumptions) + 1}", "text": text, "path": path, "origin": origin})

    def ask(self, question: str, path: str | None = None, required: bool = True) -> None:
        if not any(m["question"] == question for m in self.missing):
            self.missing.append({"question": question, "path": path, "required": required})

    # ---- library matching ----
    def match_step(self, s: DraftStep) -> tuple[Any, str]:
        if self.reg.has(s.component):
            return self.reg.get(s.component), "exact"
        hits = [h for h in self.reg.search(f"{s.component} {s.name}") if h.behavior not in (Behavior.SOURCE, Behavior.SINK)]
        if hits:
            return hits[0], "keyword"
        return self.reg.get("manual_process" if s.resources else "machine"), "generic"

    def _rule(self, binding: str):
        return self.reg.rule_by_binding(binding)


def compile_draft(draft: ProcessDraft, registry: ComponentRegistry, source_text: str, source: str = "description",
                  prototype: bool = False, generated_by: dict | None = None) -> ParseOutcome:
    b = _Builder(draft, registry, source_text, source, prototype)
    d = draft

    # ------------------------------------------------------------ steps -> nodes
    used: set[str] = {"source", "sink"}
    step_id: dict[str, str] = {}
    nodes: list[dict] = []
    for i, s in enumerate(d.steps):
        nid = _snake(s.id)
        while nid in used:
            nid = f"{nid}_{i}"
        used.add(nid)
        step_id[s.id] = nid
    res_ids: dict[str, str] = {r.id: _snake(r.id) for r in d.resources}
    for r in d.resources:
        while res_ids[r.id] in used:
            res_ids[r.id] += "_res"
        used.add(res_ids[r.id])

    def rid(name: str) -> str:
        return res_ids.get(name, _snake(name))

    items = d.items
    items_ref = None
    if any(s.time_basis == "per_item" for s in d.steps):
        name = (items.item_name if items else "items")
        items_ref = b.param(f"{_snake(name)}_per_unit", items.per_entity if items else None, _snake(name),
                            f"Número de {name} por unidad/bastidor", what=f"{name} por unidad")

    nodes.append({"id": "source", "name": "Source", "component": "source"})
    if d.supply == "interarrival" and d.interarrival:
        ok = all(v in b.stated for v in _time_numbers(d.interarrival))
        if not ok:
            b.ungrounded.append("intervalo de llegadas")
        nodes[0]["params"] = {"arrival": "interarrival", "interarrival": _dist(d.interarrival, b.source if ok else "assumed")}
    elif d.supply == "interarrival":
        b.ask("¿Cada cuánto llegan las unidades?", "nodes.source.params.interarrival")
    else:
        nodes[0]["params"] = {"arrival": "infinite"}
        if d.supply == "unknown":
            b.assume("Suministro infinito (la primera estación nunca espera material): no se indicó la llegada.", "nodes.source.params.arrival")
    b.matches.append(Match("Suministro / fuente", "component", "source", registry.get("source").version, "exact", "source"))

    operator_tasks: list[str] = []
    transports: list[str] = []
    for s in d.steps:
        nid = step_id[s.id]
        comp, how = b.match_step(s)
        b.matches.append(Match(s.name, "component", comp.id, comp.version, how, nid))
        if how == "generic":
            b.assume(f"No hay componente específico para '{s.name}': se usa '{comp.id}' genérico.", f"nodes.{nid}.component", "system")
        node: dict[str, Any] = {"id": nid, "name": s.name, "component": comp.id, "component_version": comp.version, "params": {}}
        p = node["params"]
        if comp.behavior is Behavior.BUFFER:
            p["capacity"] = b.param(f"{nid}_capacity", s.capacity, "units", f"Capacidad de '{s.name}'", what=f"capacidad de {s.name}")
        elif comp.behavior is Behavior.TRANSPORT:
            transports.append(nid)
            per_trip = s.units_per_trip if s.units_per_trip is not None else s.capacity
            if per_trip is None:
                p["capacity"] = 1
                b.assume(f"'{s.name}': 1 unidad por viaje (no se indicó).", f"nodes.{nid}.params.capacity")
            else:
                p["capacity"] = b.param(f"{nid}_units_per_trip", per_trip, "units", f"Unidades por viaje en '{s.name}'")
            p["load_time"] = {"dist": "constant", "unit": "s", "value": b.param(
                f"{nid}_load_time", s.load_time_s, "s", f"Tiempo de carga en '{s.name}'", default_key="load_time")}
            p["unload_time"] = {"dist": "constant", "unit": "s", "value": b.param(
                f"{nid}_unload_time", s.unload_time_s, "s", f"Tiempo de descarga en '{s.name}'", default_key="unload_time")}
            p["reserve_destination"] = True
            b.assume(f"'{s.name}': el viaje empieza sólo cuando hay sitio en el destino (evita que el operario espere cargado).",
                     f"nodes.{nid}.params.reserve_destination")
            p["return_empty"] = False
            uses = [{"resource": rid(r)} for r in s.resources]
            if uses:
                p["resources"] = uses
                operator_tasks.append(nid)
            node["_distance"] = s.distance_m
            node["_speed"] = s.speed_m_s
        else:
            if s.time is None or not _time_numbers(s.time):
                per = f" por {items.item_name.rstrip('s')}" if (s.time_basis == "per_item" and items) else ""
                p["process_time"] = {"dist": "constant", "unit": "s",
                                     "value": b.param(f"{nid}_time", None, "s", f"Tiempo de proceso de '{s.name}'{per}")}
            else:
                t = s.time
                unit = t.unit
                if t.dist == "constant":
                    p["process_time"] = {"dist": "constant", "unit": unit,
                                         "value": b.param(f"{nid}_time", t.value, unit, f"Tiempo de '{s.name}'"
                                                          + (" por " + (items.item_name if items else "item") if s.time_basis == "per_item" else ""),
                                                          what=f"tiempo de {s.name}")}
                else:  # non-constant: keep the distribution, ground every number
                    ok = all(v in b.stated for v in _time_numbers(t))
                    if not ok:
                        b.ungrounded.append(f"tiempo de {s.name}")
                    p["process_time"] = _dist(t, b.source if ok else "assumed")
            if s.time_basis == "per_item":
                p["work_units"] = items_ref
            if s.capacity:
                p["capacity"] = b.param(f"{nid}_stations", s.capacity, "stations", f"Puestos en paralelo de '{s.name}'")
            if s.resources:
                p["resources"] = [{"resource": rid(r)} for r in s.resources]
                operator_tasks.append(nid)
            if s.yield_rate is not None:
                p["yield_rate"] = s.yield_rate
        nodes.append(node)
    nodes.append({"id": "sink", "name": "Sink", "component": "sink"})
    b.matches.append(Match("Salida / fin", "component", "sink", registry.get("sink").version, "exact", "sink"))
    flow = [n["id"] for n in nodes]
    edges = [{"source": a, "target": c} for a, c in zip(flow, flow[1:])]

    # ------------------------------------------------------------ resources
    resources: list[dict] = []
    used_res = {u["resource"] for n in nodes for u in n.get("params", {}).get("resources", [])}
    for r in d.resources:
        rr = rid(r.id)
        rt = b._rule(f"resource:{r.kind}")
        users = [n for n in nodes if any(u["resource"] == rr for u in n.get("params", {}).get("resources", []))]
        label = f"{r.name} ({r.kind}{', compartido' if len(users) > 1 else ''})"
        b.matches.append(Match(label, "resource_type", rt.id if rt else None, rt.version if rt else None,
                               "engine_rule" if rt else "not_found", rr))
        res: dict[str, Any] = {"id": rr, "name": r.name, "kind": r.kind}
        if r.kind == "carrier":
            exp = next((e for e in d.experiments if _target_kind(e.target) == "carrier"), None)
            if r.quantity is not None:
                res["quantity"] = b.param(f"{rr}_count", r.quantity, "units", f"Número de {r.name}", what=f"número de {r.name}")
            elif exp:
                base = int(exp.values[0])
                res["quantity"] = b.param(f"{rr}_count", base, "units", f"Número de {r.name}", status="assumed",
                                          note="baseline = first experiment level", role="decision_variable")
                b.assume(f"Número de {r.name} del caso base = {base} (primer nivel del experimento); el experimento lo varía.",
                         f"parameters.{rr}_count.value")
            else:
                res["quantity"] = b.param(f"{rr}_count", None, "units", f"Número de {r.name} disponibles")
        else:
            if r.quantity is not None:
                res["quantity"] = b.param(f"{rr}_count", r.quantity, "units", f"Número de {r.name}", what=f"número de {r.name}")
            else:
                res["quantity"] = b.param(f"{rr}_count", 1, "units", f"Número de {r.name}", status="assumed",
                                          note="quantity not stated")
                b.assume(f"Se asume 1 unidad de '{r.name}' (no se indicó cantidad).", f"parameters.{rr}_count.value")
        if rr not in used_res and r.kind != "carrier":
            b.ask(f"'{r.name}' no está asignado a ninguna tarea: ¿qué hace?", f"resources.{rr}", required=False)
        resources.append(res)

    # ------------------------------------------------------------ carrier loops
    for loop in d.carrier_loops:
        rr = rid(loop.resource)
        a, c = step_id.get(loop.seize_at), step_id.get(loop.release_at)
        if not (a and c and any(x["id"] == rr for x in resources)):
            b.ask(f"¿En qué paso se carga y en cuál se libera '{loop.resource}'?", f"resources.{rr}")
            continue
        na = next(n for n in nodes if n["id"] == a)
        nc = next(n for n in nodes if n["id"] == c)
        na["seize"] = [{"resource": rr}]
        nc["release"] = [rr]
        if loop.return_mode == "transport":
            tid = f"{rr}_return"
            nc["release_via"] = {rr: tid}
            carrier_ops = nc.get("params", {}).get("resources", [])
            comp = registry.get("rack_transport")
            b.matches.append(Match(f"Retorno de {loop.resource} vacíos", "component", comp.id, comp.version, "keyword", tid))
            nodes.append({"id": tid, "name": f"Retorno de {loop.resource}", "component": comp.id, "component_version": comp.version,
                          "params": {"origin": c, "destination": a, "capacity": 1, "return_empty": False,
                                     "load_time": {"dist": "constant", "unit": "s", "value": b.param(
                                         f"{tid}_load_time", None, "s", f"Tiempo de carga de un {loop.resource} vacío", default_key="load_time")},
                                     "unload_time": {"dist": "constant", "unit": "s", "value": b.param(
                                         f"{tid}_unload_time", None, "s", f"Tiempo de descarga de un {loop.resource} vacío", default_key="unload_time")},
                                     **({"resources": carrier_ops} if carrier_ops else {})},
                          "_distance": None, "_speed": None})
            transports.append(tid)
            if carrier_ops:
                operator_tasks.append(tid)
        elif loop.return_mode == "unknown":
            b.ask(f"¿Cómo vuelven los {loop.resource} vacíos al inicio? (disponibles inmediatamente al liberarse, o con un transporte)",
                  f"nodes.{c}.release_via")

    # ------------------------------------------------------------ layout & walking (linear-layout assumption)
    by_id = {n["id"]: n for n in nodes}
    order = {nid: i for i, nid in enumerate(flow)}
    travel_needed = bool(transports) and any(by_id[t].get("params", {}).get("resources") for t in transports)
    walking_ref = None
    distances: list[dict] = []
    if travel_needed:
        points: list[str] = []
        for t in transports:
            tp = by_id[t]["params"]
            if t in order:
                i = order[t]
                tp.setdefault("origin", flow[i - 1])
                tp.setdefault("destination", flow[i + 1])
        for nid in operator_tasks:
            if nid in order and nid not in transports:  # a transport is walked to at its ORIGIN, it is not a place
                points.append(nid)
        for t in transports:
            tp = by_id[t]["params"]
            points += [tp["origin"], tp["destination"]]
        pts = sorted(dict.fromkeys(points), key=lambda x: order.get(x, 1e9))
        seg: dict[tuple[str, str], str] = {}
        stated_by_transport = {}
        for t in transports:
            tp = by_id[t]["params"]
            if by_id[t].get("_distance") is not None:
                stated_by_transport[(tp["origin"], tp["destination"])] = by_id[t]["_distance"]
        for a, c in zip(pts, pts[1:]):
            val = stated_by_transport.get((a, c))
            seg[(a, c)] = b.param(f"dist_{a}__{c}", val, "m", f"Distancia {by_id[a]['name']} ↔ {by_id[c]['name']}",
                                  what=f"distancia {a}-{c}")
        if len(pts) > 2:
            b.assume("Layout lineal en el orden del flujo: la distancia entre dos puntos no consecutivos es la suma de los tramos.",
                     "resources")

        def dist_expr(x: str, y: str) -> str:
            i, j = sorted((pts.index(x), pts.index(y)))
            parts = [seg[(pts[k], pts[k + 1])] for k in range(i, j)]
            return " + ".join(parts) if parts else "0"

        for i, a in enumerate(pts):
            for c in pts[i + 1:]:
                distances.append({"a": a, "b": c, "distance": {"value": dist_expr(a, c), "unit": "m"}})
        op_res = [r for r in d.resources if r.kind == "operator"]
        speed_val = op_res[0].walking_speed_m_s if op_res else None
        walking_ref = b.param("operator_walking_speed", speed_val, "m/s", "Velocidad del operario andando",
                              default_key="operator_walking_speed")
        for t in transports:
            n = by_id[t]
            tp = n["params"]
            tp["distance"] = {"value": dist_expr(tp["origin"], tp["destination"]), "unit": "m"}
            if n.get("_speed") is not None:
                tp["speed"] = {"value": b.param(f"{t}_speed", n["_speed"], "m/s", f"Velocidad en '{n['name']}'"), "unit": "m/s"}
            else:
                tp["speed"] = {"value": walking_ref, "unit": "m/s"}
                b.assume(f"'{n['name']}': velocidad cargado = velocidad andando del operario.", f"nodes.{t}.params.speed")
        for r in resources:
            if r["kind"] == "operator":
                r["travel"] = {"speed": {"value": walking_ref, "unit": "m/s"}, "distances": distances}
                r["home"] = operator_tasks[0] if operator_tasks and operator_tasks[0] in order else None
                if r["home"] is None:
                    r.pop("home")
                else:
                    b.assume(f"El operario empieza en '{by_id[r['home']]['name']}'.", f"resources.{r['id']}.home")
    else:
        for t in transports:
            tp = by_id[t]["params"]
            tp["distance"] = {"value": b.param(f"{t}_distance", by_id[t].get("_distance"), "m", f"Distancia de '{by_id[t]['name']}'"), "unit": "m"}
            tp["speed"] = {"value": b.param(f"{t}_speed", by_id[t].get("_speed"), "m/s", f"Velocidad de '{by_id[t]['name']}'",
                                            default_key="carrying_speed"), "unit": "m/s"}
        if any(len([n for n in nodes if any(u["resource"] == r["id"] for u in n.get("params", {}).get("resources", []))]) > 1
               for r in resources if r["kind"] == "operator"):
            b.assume("Los desplazamientos del operario entre puestos no se modelan (no se indicaron distancias).", "resources")
    for n in nodes:
        n.pop("_distance", None)
        n.pop("_speed", None)

    # ------------------------------------------------------------ dispatch policies
    rules_text: list[str] = []
    policies = {rid(p.resource): p for p in d.policies}
    for r in resources:
        if r["kind"] == "carrier":
            continue
        users = [n["id"] for n in nodes if any(u["resource"] == r["id"] for u in n.get("params", {}).get("resources", []))]
        pol = policies.get(r["id"])
        if pol and pol.rule == "wip_target":
            rule = b._rule("dispatch:wip_target")
            prot = step_id.get(pol.protected_step or "")
            feeders = [step_id[x] for x in pol.feeder_steps if x in step_id and step_id[x] in users]
            if prot is None:
                b.ask("¿Qué estación debe mantener alimentada la estrategia de WIP objetivo?", f"resources.{r['id']}.wip_target")
                continue
            first_feeder = min((order[f] for f in feeders if f in order), default=None)
            feed_nodes = [nid for nid in flow if first_feeder is not None and first_feeder < order[nid] < order[prot]
                          and nid not in feeders and by_id[nid]["component"] != "source"]
            if not feed_nodes:
                feed_nodes = [nid for nid in flow if order[nid] < order[prot] and by_id[nid]["component"] == "buffer"] or [prot]
            r["dispatch"] = "wip_target"
            r["wip_target"] = {"protected_node": prot, "feed_nodes": feed_nodes, "feeder_nodes": feeders or [users[0]],
                               "target": b.param("wip_target", pol.target, "units", "WIP objetivo delante de la estación protegida",
                                                 what="WIP objetivo"),
                               "count_feeder_in_process": True, "unblock_protected": True, "preempt_below": None}
            b.assume(f"WIP que alimenta '{by_id[prot]['name']}' = contenido de {', '.join(by_id[x]['name'] for x in feed_nodes)} "
                     "+ unidades en proceso en las tareas alimentadoras.", f"resources.{r['id']}.wip_target.feed_nodes")
            b.assume("El operario no interrumpe una tarea a medias (sin preemption); si la estación protegida está bloqueada, "
                     "atiende primero aguas abajo.", f"resources.{r['id']}.wip_target")
            b.matches.append(Match(f"Regla del operario: WIP objetivo ({by_id[prot]['name']})", "strategy", rule.id, rule.version,
                                   "keyword", r["id"]))
            rules_text.append(f"{r['name']}: {rule.name} (protege {by_id[prot]['name']}, objetivo "
                              f"{'MISSING' if pol.target is None else pol.target})")
        elif pol and pol.rule == "priority" and pol.priority_order:
            rule = b._rule("dispatch:priority")
            r["dispatch"] = "priority"
            order_ids = [step_id.get(s, _snake(s)) for s in pol.priority_order]
            for n in nodes:
                if n["id"] in users:
                    n["priority"] = order_ids.index(n["id"]) if n["id"] in order_ids else len(order_ids)
            b.matches.append(Match("Regla del operario: prioridad fija", "strategy", rule.id, rule.version, "keyword", r["id"]))
            rules_text.append(f"{r['name']}: {rule.name} ({' > '.join(order_ids)})")
        elif len(users) > 1:
            rule = b._rule("dispatch:fifo")
            r["dispatch"] = "fifo"
            if pol is None:
                names = ", ".join(by_id[u]["name"] for u in users)
                b.assume(f"'{r['name']}' es compartido por {names}: se asume FIFO (atiende la petición más antigua).",
                         f"resources.{r['id']}.dispatch")
                b.ask(f"'{r['name']}' hace {names}. Cuando varias tareas le requieren a la vez, ¿cuál tiene prioridad? "
                      "(p.ej. mantener alimentada la máquina / vaciar primero la inspección / FIFO)", f"resources.{r['id']}.dispatch",
                      required=False)
            b.matches.append(Match("Regla del operario: FIFO", "strategy", rule.id, rule.version,
                                   "keyword" if pol else "engine_rule", r["id"]))
            rules_text.append(f"{r['name']}: FIFO")

    # ------------------------------------------------------------ custom rules & unparsed text
    candidates = []
    for i, c in enumerate(d.custom_rules, 1):
        cid = f"rule_{i}"
        candidates.append({"id": cid, "description": c.description, "reason_not_found": c.reason,
                           "expected_behavior": c.description, "status": "proposed"})
        b.matches.append(Match(c.description[:60], "custom", None, None, "not_found", cid))
    for u in d.unparsed:
        b.ask(f"No he usado esta frase: «{u}». Si describe algo del proceso, reformúlala o añádelo a mano.", None, required=False)

    # ------------------------------------------------------------ experiments
    experiments = []
    for ex in d.experiments:
        kind = _target_kind(ex.target)
        path = None
        if kind == "carrier":
            car = next((r for r in resources if r["kind"] == "carrier"), None)
            if car and isinstance(car["quantity"], str) and car["quantity"].startswith("$"):
                path = f"parameters.{car['quantity'][1:]}.value"
            elif car:
                path = f"resources.{car['id']}.quantity"
        elif kind == "operator":
            op = next((r for r in resources if r["kind"] == "operator"), None)
            path = f"parameters.{op['id']}_count.value" if op else None
        elif kind == "buffer":
            buf = next((n for n in nodes if n["component"] == "buffer"), None)
            path = f"parameters.{buf['id']}_capacity.value" if buf else None
        if path:
            vals = [int(v) if float(v).is_integer() else v for v in ex.values]
            experiments.append({"name": f"{ex.target} {vals[0]}..{vals[-1]}", "factors": [{"path": path, "values": vals}]})
        else:
            b.ask(f"No sé qué parámetro variar para '{ex.target}'.", None, required=False)

    # ------------------------------------------------------------ horizon, draft-level notes
    if d.horizon_value is None:
        horizon = {"value": 8, "unit": "h", "provenance": {"status": "assumed", "note": "default 8 h"}}
        b.assume("Horizonte de simulación de 8 h (no se indicó).", "simulation.horizon")
    else:
        ok = d.horizon_value in b.stated
        if not ok:
            b.ungrounded.append(f"horizonte = {d.horizon_value:g}")
        horizon = {"value": d.horizon_value, "unit": d.horizon_unit,
                   "provenance": {"status": "provided_by_client" if ok else "assumed", "source": source}}
    for q in d.missing_information:
        b.ask(q.question, None, q.required)
    for a in d.assumptions:
        b.assume(a)
    if b.ungrounded:
        b.assume("Valores no encontrados literalmente en la descripción (marcados ASSUMED): " + "; ".join(b.ungrounded), None, "system")

    entities = [{"id": "unit", "name": "Unit"}]
    if items:
        entities = [{"id": "unit", "name": "Unit", "description": f"contains {items.item_name}"}]
    data = {
        "meta": {"name": d.model_name or "Modelo", "description": source_text[:500], "origin": "ai_generated",
                 "generated_by": {**(generated_by or {}), "compiler": COMPILER_VERSION, "prototype_mode": prototype,
                                  "at": b.now}},
        "simulation": {"horizon": horizon},
        "entities": entities,
        "parameters": list(b.params.values()),
        "resources": resources, "nodes": nodes, "edges": edges,
        "assumptions": b.assumptions, "missing": b.missing, "experiments": experiments,
        "custom_rule_candidates": candidates,
    }
    model = model_from_dict(data)

    def show(v: Any) -> str:
        if isinstance(v, str) and v.startswith("$") and v[1:] in b.params:
            val = b.params[v[1:]]["value"]
            return "MISSING" if val is None else f"{val:g}"
        return str(v)

    plan = BuildPlan(
        entities=[f"Unit{' (contiene ' + items.item_name + ')' if items else ''}"]
        + [f"{r['name']} (carrier, {show(r['quantity'])})" for r in resources if r["kind"] == "carrier"],
        resources=[f"{r['name']} ({r['kind']}, {show(r['quantity'])})" for r in resources if r["kind"] != "carrier"],
        process=[by_id[n]["name"] for n in flow] + [n["name"] for n in nodes if n["id"] not in order],
        rules=rules_text,
        experiments=[f"{e['factors'][0]['path']} = {e['factors'][0]['values']}" for e in experiments],
        custom_logic=[c["description"] for c in candidates],
    )
    return ParseOutcome(model, draft, b.matches, b.ungrounded, plan)


def _dist(t: DraftTime, source: str) -> dict:
    d: dict = {"dist": t.dist, "unit": t.unit,
               "provenance": {"status": "assumed" if source == "assumed" else "provided_by_client", "source": source}}
    fields = {"constant": ["value"], "uniform": ["low", "high"], "triangular": ["low", "mode", "high"],
              "normal": ["mean", "std"], "lognormal": ["mean", "std"], "exponential": ["mean"]}[t.dist]
    for f in fields:
        d[f] = getattr(t, f)
    return d


def _target_kind(target: str) -> str | None:
    t = target.lower()
    if any(k in t for k in ("bastidor", "rack", "palet", "pallet", "carrier", "utillaje")):
        return "carrier"
    if any(k in t for k in ("operari", "operator", "persona", "trabajador", "worker")):
        return "operator"
    if any(k in t for k in ("buffer", "cola", "queue", "pulmon")):
        return "buffer"
    return None


def parameter_inventory(model: ISMSModel) -> list[dict[str, Any]]:
    """Every model parameter with its classification (MEASURED, USER_PROVIDED, ... MISSING)."""
    rows = []
    for p in model.parameters:
        status = "MISSING" if p.value is None else STATUS_LABEL.get(p.provenance.status.value if p.provenance else "", "UNSPECIFIED")
        rows.append({"parameter": p.id, "value": p.value, "unit": p.unit, "status": status, "description": p.description,
                     "source": (p.provenance.source if p.provenance else None),
                     "note": (p.provenance.note if p.provenance else None)})
    return rows
