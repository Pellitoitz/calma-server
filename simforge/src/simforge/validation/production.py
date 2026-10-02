"""Verification of the `production` extension block (product mix, routes, product-specific times, setups).

Complements the frozen verifier (validation/verifier.py) without changing it. Every missing physical value is an
ERROR/MISSING: nothing is normalised, mirrored, averaged or defaulted.
"""

from __future__ import annotations

import networkx as nx

from ..domain.isms import ISMSModel
from ..domain.production import MIX_SUM_TOLERANCE, UNCONFIGURED, ExplicitSequence, ProbabilisticMix, ProductionSpec
from ..library.registry import ComponentRegistry
from .verifier import Issue, Level

_PLACEHOLDER = {"dist": "constant", "value": 1, "unit": "s"}


def _behavior(registry: ComponentRegistry, component: str) -> str | None:
    try:
        return registry.get(component).behavior.value
    except Exception:  # noqa: BLE001 - unknown component: the core verifier reports it
        return None


def visiting_products(model: ISMSModel, spec: ProductionSpec, registry: ComponentRegistry) -> dict[str, set[str]]:
    """node id -> products that can reach it (routes if declared, else graph reachability from their sources)."""
    out: dict[str, set[str]] = {n.id: set() for n in model.nodes}
    if spec.routes:
        for p, r in spec.routes.items():
            for nid in r.nodes:
                out.setdefault(nid, set()).add(p)
        return out
    g = nx.DiGraph()
    g.add_nodes_from(n.id for n in model.nodes)
    g.add_edges_from((e.source, e.target) for e in model.edges)
    for n in model.nodes:  # rework edges (on_reject) are part of the reachable set too
        rej = n.params.get("on_reject") if isinstance(n.params, dict) else None
        if rej and rej != "scrap" and rej in g:
            g.add_edge(n.id, rej)
    for src in spec.generation:
        if src not in g:
            continue
        for nid in nx.descendants(g, src) | {src}:
            out[nid] |= set(spec.produced_by(src))
    return out


def sources_reaching(model: ISMSModel, spec: ProductionSpec, node: str) -> set[str]:
    if spec.routes:
        return {r.nodes[0] for r in spec.routes.values() if node in r.nodes}
    g = nx.DiGraph()
    g.add_edges_from((e.source, e.target) for e in model.edges)
    return {s for s in spec.generation if s in g and node in nx.descendants(g, s) | {s}}


def required_transitions(model: ISMSModel, spec: ProductionSpec, node: str, visiting: set[str]) -> tuple[set, str]:
    """Setup transitions that CAN occur at `node` (from != to). With a single EXPLICIT_SEQUENCE source the order is the
    sequence order (initial -> first, consecutive changes, last -> first if repeat); otherwise every change between the
    keys that reach the node (+ initial). Returns (pairs, basis)."""
    st = spec.setups[node]
    key = {p: spec.products[p].setup_key for p in visiting if p in spec.products}
    keys = {k for k in key.values() if k}
    srcs = sources_reaching(model, spec, node)
    gens = [spec.generation.get(s) for s in srcs]
    if len(srcs) == 1 and isinstance(gens[0], ExplicitSequence):
        seq = [key[p] for p in gens[0].sequence if p in key and key[p]]
        pairs = set()
        prev = st.initial_state
        for k in seq:
            if k != prev:
                pairs.add((prev, k))
            prev = k
        if gens[0].repeat and seq and seq[-1] != seq[0]:
            pairs.add((seq[-1], seq[0]))
        return pairs, "sequence"
    frm = keys | {st.initial_state}
    return {(a, b) for a in frm for b in keys if a != b}, "all"


def production_issues(model: ISMSModel, registry: ComponentRegistry, compiled=None) -> list[Issue]:
    spec: ProductionSpec | None = getattr(model, "production", None)
    if spec is None:
        return []
    out: list[Issue] = []

    def add(lvl, code, msg, path=None, hint=None):
        out.append(Issue(lvl, code, msg, path, hint))
    nodes = {n.id: n for n in model.nodes}
    beh = {n.id: _behavior(registry, n.component) for n in model.nodes}
    entity_ids = {e.id for e in model.entities}
    resources = {r.id: r for r in model.resources}
    edges = {(e.source, e.target) for e in model.edges}

    # ---- products (ProductType = ISMS EntityType)
    for p in spec.products:
        if p not in entity_ids:
            add(Level.ERROR, "PRODUCT_UNKNOWN", f"El producto '{p}' no está declarado en 'entities'.", f"production.products.{p}",
                "Declara el tipo de entidad (id, name) en entities.")

    def known(p, path):
        if p not in spec.products:
            add(Level.ERROR, "PRODUCT_UNKNOWN", f"'{p}' no es un producto declarado en production.products.", path)
            return False
        return True

    # ---- generation
    sources = [nid for nid, b in beh.items() if b == "source"]
    for s in sources:
        if s not in spec.generation:
            add(Level.ERROR, "PRODUCT_GENERATION_MISSING", f"La fuente '{s}' no declara qué productos genera.",
                f"production.generation.{s}", "PROBABILISTIC_MIX o EXPLICIT_SEQUENCE.")
        elif isinstance(nodes[s].params, dict) and nodes[s].params.get("entity_type"):
            add(Level.ERROR, "PRODUCT_GENERATION_AMBIGUOUS", f"La fuente '{s}' tiene entity_type y production.generation.",
                f"nodes.{s}.params.entity_type", "Usa sólo production.generation.")
    for s, g in spec.generation.items():
        path = f"production.generation.{s}"
        if beh.get(s) != "source":
            add(Level.ERROR, "PRODUCT_GENERATION_NOT_SOURCE", f"'{s}' no es una fuente.", path)
        if isinstance(g, ProbabilisticMix):
            for p, w in g.mix.items():
                known(p, f"{path}.mix.{p}")
                if w < 0:
                    add(Level.ERROR, "MIX_NEGATIVE", f"Probabilidad negativa para '{p}' ({w}).", f"{path}.mix.{p}")
            tot = sum(g.mix.values())
            if abs(tot - 1) > MIX_SUM_TOLERANCE:
                add(Level.ERROR, "MIX_SUM", f"El mix de '{s}' suma {tot:.10g} (debe sumar 1 ± {MIX_SUM_TOLERANCE:g}); "
                    "no se normaliza.", f"{path}.mix")
            if not any(w > 0 for w in g.mix.values()):
                add(Level.ERROR, "MIX_EMPTY", f"El mix de '{s}' no tiene ningún producto con probabilidad > 0.", f"{path}.mix")
        else:
            for i, p in enumerate(g.sequence):
                known(p, f"{path}.sequence[{i}]")
    produced = {p for s in spec.generation for p in spec.produced_by(s)}

    # ---- routes
    if spec.routes:
        for p in sorted(produced - set(spec.routes)):
            add(Level.ERROR, "MISSING", f"El producto '{p}' no tiene ruta (con routes declaradas, todos la necesitan).",
                f"production.routes.{p}")
        for p, r in spec.routes.items():
            path = f"production.routes.{p}.nodes"
            if not known(p, f"production.routes.{p}"):
                continue
            bad = [x for x in r.nodes if x not in nodes]
            if bad:
                add(Level.ERROR, "ROUTE_UNKNOWN_NODE", f"La ruta de '{p}' usa nodos inexistentes {bad}.", path)
                continue
            if beh[r.nodes[0]] != "source" or p not in spec.produced_by(r.nodes[0]):
                add(Level.ERROR, "ROUTE_BAD_START", f"La ruta de '{p}' debe empezar en una fuente que genere '{p}'.", path)
            if beh[r.nodes[-1]] != "sink":
                add(Level.ERROR, "ROUTE_BAD_END", f"La ruta de '{p}' debe terminar en un Sink.", path)
            for x in r.nodes[1:-1]:
                if beh[x] in ("source", "sink"):
                    add(Level.ERROR, "ROUTE_BAD_NODE", f"La ruta de '{p}' pasa por '{x}' ({beh[x]}) en mitad del recorrido.", path)
            for a, b in zip(r.nodes, r.nodes[1:]):
                if (a, b) not in edges:
                    add(Level.ERROR, "ROUTE_NO_EDGE", f"La ruta de '{p}' va de '{a}' a '{b}' pero no existe esa conexión.", path)
            for x in r.nodes:
                rej = nodes[x].params.get("on_reject") if isinstance(nodes[x].params, dict) else None
                if rej and rej != "scrap":
                    add(Level.ERROR, "ROUTE_REWORK_UNSUPPORTED", f"'{x}' reenvía rechazos a '{rej}': retrabajo fuera de ruta "
                        "no soportado con rutas por producto en 0.7.", f"nodes.{x}.params.on_reject")
        n_out: dict[str, int] = {}
        for e in model.edges:
            n_out[e.source] = n_out.get(e.source, 0) + 1
        for e in model.edges:
            if e.probability is not None and n_out[e.source] > 1:
                add(Level.ERROR, "ROUTING_AMBIGUOUS", f"La conexión {e.source}→{e.target} tiene probabilidad y el modelo "
                    "declara rutas por producto: el enrutado sería ambiguo.", "edges", "Quita las probabilidades o las rutas.")

    visit = visiting_products(model, spec, registry)

    # ---- product-specific processing (replaces the node's process_time, never mixed)
    for nid, table in spec.processing.items():
        path = f"production.processing.{nid}"
        if beh.get(nid) != "server":
            add(Level.ERROR, "PRODUCT_TIME_NOT_SERVER", f"'{nid}' no es una estación de proceso.", path)
            continue
        if isinstance(nodes[nid].params, dict) and nodes[nid].params.get("process_time") is not None:
            add(Level.ERROR, "PRODUCT_TIME_AMBIGUOUS", f"'{nid}' tiene process_time y tiempos por producto.",
                f"nodes.{nid}.params.process_time", "Usa sólo uno de los dos.")
        for p in table:
            known(p, f"{path}.{p}")
        for p in sorted(visit.get(nid, set()) - set(table)):
            add(Level.ERROR, "MISSING", f"Falta el tiempo de '{p}' en '{nid}' (no se usa el de otro producto).", f"{path}.{p}")

    # ---- setups
    av = getattr(model, "availability", None)
    gated_nodes: set[str] = set()
    if av is not None:
        from .availability import calendared_requirements
        gated_nodes = set(calendared_requirements(model, av, registry))
    for nid, st in spec.setups.items():
        path = f"production.setups.{nid}"
        if beh.get(nid) != "server":
            add(Level.ERROR, "SETUP_NOT_SERVER", f"'{nid}' no es una estación de proceso: no admite setups.", path)
            continue
        cap = nodes[nid].params.get("capacity", 1) if isinstance(nodes[nid].params, dict) else 1
        if compiled is not None and nid in compiled.nodes:
            cap = compiled.nodes[nid].params.capacity
        if cap != 1:
            add(Level.ERROR, "SETUP_SEMANTICS_UNSUPPORTED_FOR_MULTI_SLOT_NODE",
                f"'{nid}' tiene capacity = {cap}: setup por nodo o por slot es ambiguo; 0.7 sólo soporta setups con capacity 1.",
                f"nodes.{nid}.params.capacity")
        vis = visit.get(nid, set())
        for p in sorted(vis):
            if p in spec.products and not spec.products[p].setup_key:
                add(Level.ERROR, "MISSING", f"El producto '{p}' llega a '{nid}' (con setups) pero no tiene setup_key.",
                    f"production.products.{p}.setup_key")
        all_keys = {ps.setup_key for ps in spec.products.values() if ps.setup_key}
        if st.initial_state != UNCONFIGURED and st.initial_state not in all_keys:
            add(Level.ERROR, "SETUP_UNKNOWN_KEY", f"initial_state '{st.initial_state}' no es UNCONFIGURED ni una setup key declarada.",
                f"{path}.initial_state")
        used = [*st.by_target, *st.matrix, *st.from_unconfigured, *(t for r in st.matrix.values() for t in r)]
        for k in sorted(set(used) - all_keys):
            add(Level.ERROR, "SETUP_UNKNOWN_KEY", f"La setup key '{k}' de '{nid}' no pertenece a ningún producto.", path)
        for a, row in st.matrix.items():
            if a in row:
                d = row[a]
                if not (d.is_deterministic and d.mean_seconds() == 0):
                    add(Level.ERROR, "SETUP_DIAGONAL", f"{a}→{a} en '{nid}' no es 0: sólo hay setup cuando cambia la setup key.",
                        f"{path}.matrix.{a}.{a}", "Usa setup keys distintas si de verdad hay cambio.")
        pairs, basis = required_transitions(model, spec, nid, vis) if vis else (set(), "none")
        for a, b in sorted(pairs):
            if st.duration(a, b) is None:
                where = "from_unconfigured" if a == UNCONFIGURED else {"CONSTANT_CHANGEOVER": "constant",
                                                                       "TARGET_DEPENDENT": "by_target",
                                                                       "SEQUENCE_DEPENDENT": "matrix"}[st.mode]
                add(Level.ERROR, "SETUP_TRANSITION_MISSING", f"Falta el setup {a}→{b} en '{nid}' ({where}); no se completa "
                    "ni se refleja la matriz.", f"{path}.{where}")
        if basis == "sequence":
            add(Level.INFO, "SETUP_TRANSITIONS_FROM_SEQUENCE",
                f"'{nid}': transiciones requeridas según el orden de la secuencia explícita {sorted(pairs)}. Si en la "
                "ejecución aparece otra no definida (p. ej. por adelantamientos), la simulación se detiene con error.", path)
        for use in st.resources:
            r = resources.get(use.resource)
            if r is None:
                add(Level.ERROR, "UNKNOWN_RESOURCE", f"El setup de '{nid}' requiere '{use.resource}', que no existe.", f"{path}.resources")
            elif isinstance(r.quantity, int) and r.quantity < use.quantity:
                add(Level.ERROR, "RESOURCE_SHORT", f"El setup de '{nid}' requiere {use.quantity} × '{r.id}' y sólo hay {r.quantity}.",
                    f"{path}.resources")
            elif r.kind.value == "carrier":
                add(Level.ERROR, "SETUP_CARRIER_UNSUPPORTED", f"'{r.id}' es un carrier: no se usa como recurso de setup.", f"{path}.resources")
            elif r.dispatch.value == "wip_target":
                add(Level.ERROR, "SETUP_RESOURCE_WIP_TARGET_UNSUPPORTED",
                    f"'{r.id}' usa WIP_TARGET: la clasificación de tareas de setup no está definida en 0.7.", f"{path}.resources")
        setup_gated = nid in gated_nodes or (av is not None and (nid in av.nodes or any(u.resource in av.resources for u in st.resources)))
        if setup_gated and st.at_unavailability is None:
            add(Level.ERROR, "MISSING", f"'{nid}' tiene calendario: falta setups.{nid}.at_unavailability "
                "(FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART). No se hereda la política del proceso.", f"{path}.at_unavailability")
        if not setup_gated and st.at_unavailability is not None:
            add(Level.WARNING, "SETUP_POLICY_UNUSED", f"'{nid}': at_unavailability del setup sin calendario que lo active.", path)
        if av is not None:
            pol = av.operations.get(nid)
            if pol and pol.start_rule == "REQUIRE_FULL_WINDOW":
                add(Level.ERROR, "SETUP_START_RULE_UNSUPPORTED", f"'{nid}': REQUIRE_FULL_WINDOW con setups no está definido en 0.7.",
                    f"availability.operations.{nid}.start_rule")
    for nid in spec.setups:
        if nid not in nodes:
            add(Level.ERROR, "SETUP_NOT_SERVER", f"setups: el nodo '{nid}' no existe.", f"production.setups.{nid}")
    return out


def verification_view(core: ISMSModel, spec: ProductionSpec) -> tuple[ISMSModel, set[str], set[str]]:
    """Core view for the frozen verifier. Where the production block legitimately replaces a core field (product times
    instead of process_time; product routes instead of edge probabilities) a NEUTRAL placeholder is inserted so the
    frozen checks do not report it as missing. The placeholders are removed from the compiled model right after
    compilation (process_time = None, successors = []) so the engine can never use them."""
    data = core.model_dump(mode="json")
    timed, routed = set(), set()
    for n in data["nodes"]:
        if n["id"] in spec.processing and n.get("params", {}).get("process_time") is None:
            n.setdefault("params", {})["process_time"] = dict(_PLACEHOLDER)
            timed.add(n["id"])
    if spec.routes:
        outs: dict[str, list[dict]] = {}
        for e in data["edges"]:
            outs.setdefault(e["source"], []).append(e)
        for src, es in outs.items():
            if len(es) > 1 and all(e.get("probability") is None for e in es):
                share = [1 / len(es)] * len(es)
                share[-1] = 1 - sum(share[:-1])
                for e, w in zip(es, share):
                    e["probability"] = w
                routed.add(src)
    return type(core).model_validate(data), timed, routed
