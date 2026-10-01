"""Model VERIFICATION: is the model built correctly?

(Not to be confused with VALIDATION: does the model represent the real system
well enough? That is the engineer's call -> `Approval` in the ISMS.)

`verify()` never raises on model problems: it returns a report with
human-readable issues. `compile_model()` returns the typed, engine-ready
model or raises `ModelError` carrying that report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import networkx as nx
from pydantic import BaseModel, ValidationError

from ..domain.behaviors import Behavior, ServerParams, SourceParams, TransportParams
from ..domain.expressions import references, resolve
from ..domain.isms import DispatchRule, ISMSModel, Node, ResourceKind
from ..domain.units import Dimension
from ..domain.values import Constant, Normal
from ..library.registry import ComponentDef, ComponentRegistry


class Level(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Readiness(str, Enum):
    INCOMPLETE = "INCOMPLETE"  # required information missing
    CONFIGURED = "CONFIGURED"  # information complete, but structural errors remain
    EXECUTABLE = "EXECUTABLE"  # passes verification; can be simulated
    ENGINEER_APPROVED = "ENGINEER_APPROVED"  # engineer approved THIS exact model content


@dataclass
class Issue:
    level: Level
    code: str
    message: str
    path: str | None = None
    hint: str | None = None

    def __str__(self) -> str:
        loc = f" [{self.path}]" if self.path else ""
        hint = f" -> {self.hint}" if self.hint else ""
        return f"{self.level.value.upper():7} {self.code}{loc}: {self.message}{hint}"


@dataclass
class VerificationReport:
    issues: list[Issue] = field(default_factory=list)
    readiness: Readiness = Readiness.INCOMPLETE
    confirmed_values: int = 0
    assumed_values: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level is Level.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level is Level.WARNING]

    @property
    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.level is Level.INFO]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return f"{self.readiness.value}: {len(self.errors)} errors, {len(self.warnings)} warnings, {len(self.infos)} info"


class ModelError(Exception):
    def __init__(self, report: VerificationReport):
        self.report = report
        msgs = "\n".join(str(i) for i in report.errors)
        super().__init__(f"El modelo no es ejecutable:\n{msgs}")


# ---------------------------------------------------------------------------
# Compiled (engine-ready) model
# ---------------------------------------------------------------------------


@dataclass
class CompiledNode:
    node: Node
    component: ComponentDef
    behavior: Behavior
    params: BaseModel
    successors: list[tuple[str, float]]  # (target, probability)


@dataclass
class CompiledModel:
    model: ISMSModel
    nodes: dict[str, CompiledNode]
    horizon_s: float
    warmup_s: float
    component_versions: dict[str, str]  # component id -> version used


def _pydantic_msgs(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"] if not isinstance(x, int) or True)
        out.append(f"{loc}: {err['msg']}")
    return out


def _iter_durations(params: BaseModel):
    if isinstance(params, ServerParams):
        yield "process_time", params.process_time
        if params.failures:
            yield "failures.mtbf", params.failures.mtbf
            yield "failures.mttr", params.failures.mttr
    if isinstance(params, SourceParams):
        yield "interarrival", params.interarrival
    if isinstance(params, TransportParams):
        yield "load_time", params.load_time
        yield "unload_time", params.unload_time


def verify(model: ISMSModel, registry: ComponentRegistry) -> tuple[VerificationReport, CompiledModel | None]:
    rep = VerificationReport()
    add = lambda lvl, code, msg, path=None, hint=None: rep.issues.append(Issue(lvl, code, msg, path, hint))  # noqa: E731

    # ---- model parameters ('$name' references) ----------------------------
    pids = [p.id for p in model.parameters]
    for dup in {i for i in pids if pids.count(i) > 1}:
        add(Level.ERROR, "DUP_PARAMETER", f"Parámetro duplicado '{dup}'.", f"parameters.{dup}")
    for prm in model.parameters:
        if prm.value is not None and ((prm.min is not None and prm.value < prm.min) or (prm.max is not None and prm.value > prm.max)):
            add(Level.ERROR, "PARAM_RANGE", f"'{prm.id}' = {prm.value} fuera de rango [{prm.min}, {prm.max}].", f"parameters.{prm.id}")
    used_refs = set(references(model.model_dump_json()))
    for prm in model.parameters:
        if prm.id not in used_refs:
            add(Level.WARNING, "UNUSED_PARAMETER", f"El parámetro '{prm.id}' no se usa en el modelo.", f"parameters.{prm.id}")
    # custom logic is reported even when parameters are still missing
    for c in model.custom_rule_candidates:
        if c.status == "proposed":
            add(Level.ERROR, "CUSTOM_RULE_PENDING", f"Regla no disponible en la biblioteca: '{c.description}'. "
                "Decide: implementarla y validarla, o ejecutar sin ella (status: deferred).", f"custom_rule_candidates.{c.id}")
        elif c.status == "deferred":
            add(Level.WARNING, "CUSTOM_RULE_NOT_MODELLED", f"La regla '{c.description}' NO está modelada (aplazada por el ingeniero).",
                f"custom_rule_candidates.{c.id}")
    original = model
    resolved, problems = resolve(model)
    missing_uses: dict[str, list[str]] = {}
    for path, msg, is_missing in problems:
        if is_missing:
            missing_uses.setdefault(msg, []).append(path)
        else:
            add(Level.ERROR, "BAD_EXPRESSION", msg, path)
    for name, uses in missing_uses.items():
        prm = next(p for p in model.parameters if p.id == name)
        desc = f" ({prm.description})" if prm.description else ""
        add(Level.ERROR, "MISSING", f"Falta el valor del parámetro '{name}'{desc} [{prm.unit or '-'}]. Se usa en: {', '.join(uses)}.",
            f"parameters.{name}.value")
    if resolved is None:
        for m in model.missing:
            add(Level.ERROR if m.required else Level.WARNING, "MISSING", m.question, m.path)
        rep.readiness = Readiness.INCOMPLETE if any(i.code == "MISSING" and i.level is Level.ERROR for i in rep.issues) else Readiness.CONFIGURED
        add(Level.INFO, "CHECKS_PENDING", "El resto de comprobaciones se ejecutarán cuando todos los parámetros tengan valor.")
        return rep, None
    model = resolved

    # ---- simulation settings --------------------------------------------
    horizon = model.simulation.horizon.to_base(Dimension.TIME)
    warmup = model.simulation.warmup.to_base(Dimension.TIME)
    if horizon <= 0:
        add(Level.ERROR, "HORIZON", "El horizonte de simulación debe ser > 0.", "simulation.horizon")
    if warmup >= horizon > 0:
        add(Level.ERROR, "WARMUP", "El warm-up debe ser menor que el horizonte.", "simulation.warmup")
    if model.simulation.kind == "steady_state" and warmup == 0:
        add(Level.WARNING, "NO_WARMUP", "Simulación steady-state sin warm-up: los KPIs incluyen el transitorio inicial (sistema vacío).",
            "simulation.warmup", "Define un warm-up o usa kind=terminating.")

    # ---- ids --------------------------------------------------------------
    node_ids = [n.id for n in model.nodes]
    res_ids = [r.id for r in model.resources]
    for dup in {i for i in node_ids if node_ids.count(i) > 1}:
        add(Level.ERROR, "DUP_NODE", f"Id de nodo duplicado '{dup}'.", f"nodes.{dup}")
    for dup in {i for i in res_ids if res_ids.count(i) > 1}:
        add(Level.ERROR, "DUP_RESOURCE", f"Id de recurso duplicado '{dup}'.", f"resources.{dup}")
    clash = set(node_ids) & set(res_ids)
    for c in clash:
        add(Level.ERROR, "ID_CLASH", f"'{c}' se usa como nodo y como recurso.")
    resources = {r.id: r for r in model.resources}
    for r in model.resources:
        if not isinstance(r.quantity, int) or r.quantity < 0:
            add(Level.ERROR, "BAD_QUANTITY", f"La cantidad de '{r.id}' debe ser un entero >= 0 (es {r.quantity}).", f"resources.{r.id}.quantity")
    carrier_transports = {tid for n in model.nodes for tid in n.release_via.values()}

    # ---- missing information declared by the parser -----------------------
    for m in model.missing:
        add(Level.ERROR if m.required else Level.WARNING, "MISSING", m.question, m.path)
    for a in model.assumptions:
        if not a.accepted:
            add(Level.INFO, "ASSUMPTION", a.text, a.path, "Revisar y aceptar o corregir.")

    # ---- nodes & components ----------------------------------------------
    compiled: dict[str, CompiledNode] = {}
    comp_versions: dict[str, str] = {}
    stochastic = False
    for n in model.nodes:
        path = f"nodes.{n.id}"
        try:
            comp = registry.get(n.component, n.component_version)
        except KeyError as e:
            add(Level.ERROR, "UNKNOWN_COMPONENT", str(e.args[0]), path, "Busca un componente existente en la biblioteca o crea uno.")
            continue
        comp_versions[comp.id] = comp.version
        try:
            params = comp.resolve_params(n.params)
        except ValidationError as e:
            for msg in _pydantic_msgs(e):
                add(Level.ERROR, "BAD_PARAM", f"Nodo '{n.name or n.id}': parámetro inválido {msg}", f"{path}.params")
            continue
        compiled[n.id] = CompiledNode(n, comp, comp.behavior, params, [])

        for key, dist in _iter_durations(params):
            if dist is None:
                continue
            if not dist.is_deterministic:
                stochastic = True
            if dist.provenance and dist.provenance.status.value in ("assumed", "default"):
                rep.assumed_values += 1
            else:
                rep.confirmed_values += 1
            if isinstance(dist, Normal) and dist.mean - 2 * dist.std < 0:
                add(Level.WARNING, "NORMAL_TRUNCATED",
                    f"Nodo '{n.id}': {key} normal con media-2σ < 0; se trunca en 0 y la media real será mayor.",
                    f"{path}.params.{key}", "Considera lognormal o triangular.")
            if isinstance(dist, Constant) and dist.value == 0 and key == "process_time":
                add(Level.WARNING, "ZERO_TIME", f"Nodo '{n.id}': tiempo de proceso 0.", f"{path}.params.process_time")

        if isinstance(params, ServerParams):
            if params.process_time is None:
                add(Level.ERROR, "MISSING", f"Falta el tiempo de proceso del nodo '{n.name or n.id}'.",
                    f"{path}.params.process_time", "Indica un tiempo (p.ej. 60 s) o una distribución.")
            for use in params.resources:
                r = resources.get(use.resource)
                if r is None:
                    add(Level.ERROR, "UNKNOWN_RESOURCE",
                        f"El nodo '{n.name or n.id}' requiere '{use.resource}', pero dicho recurso no existe en esta versión del modelo.",
                        f"{path}.params.resources", "Añade el recurso o corrige la referencia.")
                elif r.quantity < use.quantity:
                    add(Level.ERROR, "RESOURCE_SHORT",
                        f"El nodo '{n.id}' requiere {use.quantity} × '{r.id}' pero sólo hay {r.quantity}: el nodo nunca podría procesar.",
                        f"resources.{r.id}.quantity")
                elif r.kind is ResourceKind.CARRIER:
                    add(Level.WARNING, "CARRIER_AS_RESOURCE",
                        f"'{r.id}' es un carrier (bastidor/palé) usado sólo durante el proceso de '{n.id}'. ¿Querías usar 'seize'/'release'?",
                        f"{path}.params.resources")
            if params.on_reject != "scrap":
                if params.on_reject not in node_ids:
                    add(Level.ERROR, "BAD_REJECT_ROUTE", f"on_reject de '{n.id}' apunta a '{params.on_reject}', que no existe.", f"{path}.params.on_reject")
            if params.yield_rate < 1 and params.on_reject == "scrap":
                add(Level.INFO, "SCRAP", f"'{n.id}' desecha {100 * (1 - params.yield_rate):.1f}% de las unidades.", f"{path}.params.yield_rate")
            if params.failures and params.ideal_cycle_time is None:
                pass  # OEE performance uses mean process time; flagged at KPI level
        elif n.seize or n.release:
            add(Level.ERROR, "SEIZE_UNSUPPORTED", f"'seize'/'release' sólo se soporta en nodos de proceso (server); '{n.id}' es {comp.behavior.value}.", path)

        if isinstance(params, TransportParams):
            for f in ("distance", "speed", "load_time", "unload_time"):
                if getattr(params, f) is None:
                    add(Level.ERROR, "MISSING", f"Falta '{f}' del transporte '{n.name or n.id}' (REQUIRED, no se asume).", f"{path}.params.{f}")
            for use in params.resources:
                r = resources.get(use.resource)
                if r is None:
                    add(Level.ERROR, "UNKNOWN_RESOURCE", f"El transporte '{n.id}' requiere '{use.resource}', que no existe.", f"{path}.params.resources")
                elif r.quantity < use.quantity:
                    add(Level.ERROR, "RESOURCE_SHORT", f"El transporte '{n.id}' requiere {use.quantity} × '{r.id}' pero sólo hay {r.quantity}.", f"resources.{r.id}.quantity")
            for f in ("origin", "destination"):
                v = getattr(params, f)
                if v is not None and v not in node_ids:
                    add(Level.ERROR, "BAD_TRANSPORT", f"{f} '{v}' del transporte '{n.id}' no existe.", f"{path}.params.{f}")
            if n.id in carrier_transports:
                if params.origin is None or params.destination is None:
                    add(Level.ERROR, "MISSING", f"El transporte de retorno '{n.id}' necesita origin y destination.", f"{path}.params")
                if model.successors(n.id) or model.predecessors(n.id):
                    add(Level.ERROR, "BAD_TRANSPORT", f"'{n.id}' devuelve carriers vacíos: no debe estar conectado al flujo de producto.", path)
            else:
                preds, succs = model.predecessors(n.id), model.successors(n.id)
                if params.origin and preds and params.origin not in [e.source for e in preds]:
                    add(Level.ERROR, "BAD_TRANSPORT", f"origin '{params.origin}' de '{n.id}' no coincide con su entrada.", f"{path}.params.origin")
                if params.destination and succs and params.destination not in [e.target for e in succs]:
                    add(Level.ERROR, "BAD_TRANSPORT", f"destination '{params.destination}' de '{n.id}' no coincide con su salida.", f"{path}.params.destination")
        elif n.id in carrier_transports:
            add(Level.ERROR, "BAD_TRANSPORT", f"release_via apunta a '{n.id}', que no es un transporte.", path)
        for rid, tid in n.release_via.items():
            if rid not in n.release:
                add(Level.ERROR, "BAD_RELEASE_VIA", f"'{n.id}' devuelve '{rid}' vía '{tid}' pero no lo libera (añádelo a release).", f"{path}.release_via")
            if tid not in node_ids:
                add(Level.ERROR, "BAD_RELEASE_VIA", f"El transporte '{tid}' no existe.", f"{path}.release_via")

        if isinstance(params, SourceParams) and params.arrival == "interarrival" and params.interarrival is None:
            add(Level.ERROR, "MISSING", f"La fuente '{n.id}' usa llegadas por intervalo pero falta 'interarrival'.", f"{path}.params.interarrival")

        for s in n.seize:
            r = resources.get(s.resource)
            if r is None:
                add(Level.ERROR, "UNKNOWN_RESOURCE", f"El nodo '{n.id}' toma '{s.resource}', que no existe.", f"{path}.seize")
            elif r.kind is not ResourceKind.CARRIER:
                add(Level.ERROR, "SEIZE_KIND", f"'seize' sólo admite carriers; '{r.id}' es {r.kind.value}.", f"{path}.seize")
            elif r.quantity < s.quantity:
                add(Level.ERROR, "RESOURCE_SHORT", f"'{n.id}' toma {s.quantity} × '{r.id}' pero sólo hay {r.quantity}.", f"resources.{r.id}.quantity")
        for rid in n.release:
            if rid not in resources:
                add(Level.ERROR, "UNKNOWN_RESOURCE", f"El nodo '{n.id}' libera '{rid}', que no existe.", f"{path}.release")

    for r in model.resources:
        if r.travel and not any(n.position for n in model.nodes):
            add(Level.WARNING, "TRAVEL_NO_POSITIONS", f"'{r.id}' tiene velocidad pero ningún nodo tiene posición: no habrá desplazamientos.", f"resources.{r.id}.travel")
        if r.home and r.home not in node_ids:
            add(Level.ERROR, "BAD_HOME", f"El nodo 'home' de '{r.id}' ('{r.home}') no existe.", f"resources.{r.id}.home")
        used = any(r.id in [u.resource for u in getattr(c.params, "resources", [])] for c in compiled.values()) or any(
            r.id in [s.resource for s in n.seize] for n in model.nodes)
        if r.dispatch is DispatchRule.WIP_TARGET:
            _check_wip_target(r, compiled, add)
        elif r.wip_target is not None:
            add(Level.WARNING, "WIP_TARGET_IGNORED", f"'{r.id}' define wip_target pero su dispatch es '{r.dispatch.value}'.", f"resources.{r.id}.dispatch")
        if not used:
            add(Level.WARNING, "UNUSED_RESOURCE", f"El recurso '{r.id}' no lo usa ningún nodo.", f"resources.{r.id}")

    # ---- graph -----------------------------------------------------------
    g = nx.DiGraph()
    g.add_nodes_from(node_ids)
    for i, e in enumerate(model.edges):
        if e.source not in node_ids or e.target not in node_ids:
            missing = e.source if e.source not in node_ids else e.target
            add(Level.ERROR, "BAD_EDGE", f"La conexión {e.source} → {e.target} referencia el nodo inexistente '{missing}'.", f"edges[{i}]")
            continue
        if e.source == e.target:
            add(Level.ERROR, "SELF_LOOP", f"El nodo '{e.source}' está conectado consigo mismo.", f"edges[{i}]")
        if g.has_edge(e.source, e.target):
            add(Level.ERROR, "DUP_EDGE", f"Conexión duplicada {e.source} → {e.target}.", f"edges[{i}]")
        g.add_edge(e.source, e.target)
    for n_id, c in compiled.items():
        if c.behavior is Behavior.SERVER and c.params.on_reject != "scrap" and c.params.on_reject in node_ids:
            g.add_edge(n_id, c.params.on_reject, reject=True)

    sources = [i for i, c in compiled.items() if c.behavior is Behavior.SOURCE]
    sinks = [i for i, c in compiled.items() if c.behavior is Behavior.SINK]
    if not sources:
        add(Level.ERROR, "NO_SOURCE", "El modelo no tiene ninguna fuente (Source).", hint="Añade un nodo 'source'.")
    if not sinks:
        add(Level.ERROR, "NO_SINK", "El modelo no tiene ninguna salida (Sink).", hint="Añade un nodo 'sink'.")

    for n_id, c in compiled.items():
        if n_id in carrier_transports:
            continue  # returns empty carriers: not part of the product flow
        outs = model.successors(n_id)
        ins = model.predecessors(n_id)
        label = c.node.name or n_id
        if c.behavior is Behavior.SOURCE and ins:
            add(Level.ERROR, "SOURCE_INPUT", f"La fuente '{label}' no puede tener entradas.", f"nodes.{n_id}")
        if c.behavior is Behavior.SINK and outs:
            add(Level.ERROR, "SINK_OUTPUT", f"La salida '{label}' no puede tener conexiones de salida.", f"nodes.{n_id}")
        if c.behavior is not Behavior.SINK and not outs:
            add(Level.ERROR, "DEAD_END", f"El nodo '{label}' no tiene salida: las unidades quedarían atrapadas.", f"nodes.{n_id}", "Conéctalo al siguiente paso o a un Sink.")
        is_reject_target = any(isinstance(x.params, ServerParams) and x.params.on_reject == n_id for x in compiled.values())
        if c.behavior is not Behavior.SOURCE and not ins and not is_reject_target:
            add(Level.ERROR, "ORPHAN", f"El nodo '{label}' no recibe unidades de ningún otro nodo.", f"nodes.{n_id}")
        # routing probabilities
        if len(outs) > 1:
            probs = [e.probability for e in outs]
            if any(p is None for p in probs):
                add(Level.ERROR, "ROUTING_PROB", f"'{label}' tiene {len(outs)} salidas: todas necesitan 'probability'.", f"nodes.{n_id}",
                    "Routing condicional/first-available: NOT IMPLEMENTED en v0.1.")
            elif abs(sum(probs) - 1) > 1e-6:
                add(Level.ERROR, "ROUTING_PROB", f"Las probabilidades de salida de '{label}' suman {sum(probs):.4f} (deben sumar 1).", f"nodes.{n_id}")
        elif len(outs) == 1 and outs[0].probability not in (None, 1.0):
            add(Level.ERROR, "ROUTING_PROB", f"'{label}' tiene una única salida con probabilidad {outs[0].probability}; debe ser 1 o vacía.", f"nodes.{n_id}")
        c.successors = [(e.target, 1.0 if e.probability is None else e.probability) for e in outs]

    if sources and sinks and not rep.errors:
        reach = set().union(*(nx.descendants(g, s) | {s} for s in sources))
        for n_id in node_ids:
            if n_id in carrier_transports:
                continue
            if n_id not in reach:
                add(Level.ERROR, "UNREACHABLE", f"El nodo '{n_id}' no es alcanzable desde ninguna fuente.", f"nodes.{n_id}")
            elif not any(t in sinks for t in nx.descendants(g, n_id) | {n_id}):
                add(Level.ERROR, "NO_PATH_TO_SINK", f"Desde '{n_id}' no existe ningún camino hasta un Sink.", f"nodes.{n_id}")
        # cycles must have a probabilistic exit (e.g. rework loops)
        for scc in nx.strongly_connected_components(g):
            if len(scc) > 1:
                leaves = any(t not in scc for s in scc for t in g.successors(s))
                if not leaves:
                    add(Level.ERROR, "CLOSED_LOOP", f"Bucle sin salida entre {sorted(scc)}.")
                else:
                    add(Level.INFO, "LOOP", f"Bucle (retrabajo/recirculación) entre {sorted(scc)}.")
        # infinite supply into an unlimited buffer -> unbounded WIP
        for s in sources:
            sp = compiled[s].params
            for tgt, _ in compiled[s].successors:
                tc = compiled.get(tgt)
                if sp.arrival == "infinite" and tc and tc.behavior is Behavior.BUFFER and tc.params.capacity is None:
                    add(Level.ERROR, "UNBOUNDED_WIP", f"Suministro infinito hacia el buffer ilimitado '{tgt}': WIP infinito.",
                        f"nodes.{tgt}.params.capacity", "Limita la capacidad del buffer o usa llegadas por intervalo.")
        # carriers seized must be released downstream (sink/scrap auto-release as safety net)
        for n in model.nodes:
            for s in n.seize:
                down = nx.descendants(g, n.id) | {n.id}
                if not any(s.resource in model.node(d).release for d in down if d in compiled):
                    add(Level.WARNING, "CARRIER_NOT_RELEASED",
                        f"'{s.resource}' se toma en '{n.id}' pero ningún nodo posterior lo libera; se liberará al llegar al Sink.",
                        f"nodes.{n.id}.seize")

    if stochastic and model.simulation.replications < 5:
        add(Level.WARNING, "FEW_REPLICATIONS",
            f"Modelo estocástico con {model.simulation.replications} replicación(es): los resultados no son concluyentes.",
            "simulation.replications", "Usa ≥ 10 replicaciones (30 recomendado).")

    # ---- readiness ---------------------------------------------------------
    missing = any(i.code == "MISSING" and i.level is Level.ERROR for i in rep.issues)
    if missing:
        rep.readiness = Readiness.INCOMPLETE
    elif rep.errors:
        rep.readiness = Readiness.CONFIGURED
    elif original.is_approved:
        rep.readiness = Readiness.ENGINEER_APPROVED
    else:
        rep.readiness = Readiness.EXECUTABLE
    if original.approval.approved and not original.is_approved:
        add(Level.WARNING, "APPROVAL_STALE", "El modelo cambió después de la aprobación del ingeniero: la aprobación ya no es válida.")

    if rep.errors:
        return rep, None
    return rep, CompiledModel(model, compiled, horizon, warmup, comp_versions)


def _check_wip_target(r, compiled: dict[str, CompiledNode], add) -> None:
    w = r.wip_target
    path = f"resources.{r.id}.wip_target"
    if w is None:
        add(Level.ERROR, "MISSING", f"'{r.id}' usa dispatch=wip_target pero no define 'wip_target'.", path)
        return
    if w.target is None:
        add(Level.ERROR, "MISSING", f"Falta el WIP objetivo ('target') de la estrategia de '{r.id}' (REQUIRED).", f"{path}.target")
    elif not isinstance(w.target, int) or w.target < 0:
        add(Level.ERROR, "BAD_PARAM", f"target de '{r.id}' debe ser entero >= 0 (es {w.target}).", f"{path}.target")
    if w.preempt_below is not None and (not isinstance(w.preempt_below, int) or w.preempt_below < 0
                                       or (isinstance(w.target, int) and w.preempt_below > w.target)):
        add(Level.ERROR, "BAD_PARAM", "preempt_below debe ser entero, >= 0 y <= target.", f"{path}.preempt_below")
    pn = compiled.get(w.protected_node)
    if pn is None:
        add(Level.ERROR, "BAD_WIP_TARGET", f"El nodo protegido '{w.protected_node}' no existe.", f"{path}.protected_node")
    elif pn.behavior is not Behavior.SERVER:
        add(Level.ERROR, "BAD_WIP_TARGET", f"El nodo protegido '{w.protected_node}' debe ser una estación (server).", f"{path}.protected_node")
    for nid in w.feed_nodes:
        if nid not in compiled:
            add(Level.ERROR, "BAD_WIP_TARGET", f"feed_nodes: '{nid}' no existe.", f"{path}.feed_nodes")
    users = {nid for nid, c in compiled.items() if r.id in [u.resource for u in getattr(c.params, "resources", [])]}
    for nid in w.feeder_nodes:
        if nid not in compiled:
            add(Level.ERROR, "BAD_WIP_TARGET", f"feeder_nodes: '{nid}' no existe.", f"{path}.feeder_nodes")
        elif nid not in users:
            add(Level.ERROR, "BAD_WIP_TARGET", f"feeder_nodes: '{nid}' no usa el recurso '{r.id}'.", f"{path}.feeder_nodes")
    if users and not (users - set(w.feeder_nodes)):
        add(Level.WARNING, "WIP_TARGET_NO_OTHER", f"Todas las tareas de '{r.id}' son feeder: la estrategia equivale a FIFO.", path)


def compile_model(model: ISMSModel, registry: ComponentRegistry) -> CompiledModel:
    rep, cm = verify(model, registry)
    if cm is None:
        raise ModelError(rep)
    return cm
