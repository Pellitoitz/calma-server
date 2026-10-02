"""Deterministic diagnostics: theoretical capacity (sanity checks) and bottleneck rules.

The analytics engine produces FACTS with EVIDENCE. The LLM (optionally) phrases
them; it never decides what the bottleneck is.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import networkx as nx

from ..domain.behaviors import Behavior, ServerParams, TransportParams
from ..validation.verifier import CompiledModel
from .kpis import ReplicatedKPIs


@dataclass
class Finding:
    code: str
    severity: str  # info | warning | flag
    subject: str
    message: str
    evidence: dict[str, float | str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapacityBound:
    subject: str
    kind: str  # station | resource | carrier_loop
    units_per_hour: float
    explanation: str


def visit_ratios(cm: CompiledModel) -> dict[str, float]:
    """Expected visits per unit created, including rework loops and scrap losses."""
    v = {n: 0.0 for n in cm.nodes}
    for _ in range(500):
        new = {n: 0.0 for n in cm.nodes}
        for n, c in cm.nodes.items():
            if c.behavior is Behavior.SOURCE:
                new[n] = 1.0
        for n, c in cm.nodes.items():
            flow = v[n]
            if flow == 0:
                continue
            good = flow
            if c.behavior is Behavior.SERVER:
                p: ServerParams = c.params  # type: ignore[assignment]
                good = flow * p.yield_rate
                if p.on_reject != "scrap":
                    new[p.on_reject] += flow * (1 - p.yield_rate)
            for tgt, prob in c.successors:
                new[tgt] += good * prob
        if all(abs(new[n] - v[n]) < 1e-12 for n in v):
            break
        v = new
    return v


def capacity_bounds(cm: CompiledModel) -> list[CapacityBound]:
    """Upper bounds on system throughput (units reaching sinks per hour).

    Ignores walking, blocking and variability, so the real value is always <=.
    """
    visits = visit_ratios(cm)
    out_frac = sum(visits[n] for n, c in cm.nodes.items() if c.behavior is Behavior.SINK) or 1.0
    bounds: list[CapacityBound] = []
    work_by_resource: dict[str, float] = {}
    for n, c in cm.nodes.items():
        if c.behavior is not Behavior.SERVER or visits[n] == 0:
            continue
        p: ServerParams = c.params  # type: ignore[assignment]
        mean = p.process_time.mean_seconds() * p.entity_time_factor() if p.process_time else 0.0
        avail = 1.0
        if p.failures:
            mtbf, mttr = p.failures.mtbf.mean_seconds(), p.failures.mttr.mean_seconds()
            avail = mtbf / (mtbf + mttr)
        if mean > 0:
            cap = p.capacity * 3600 / mean * avail / visits[n] * out_frac
            bounds.append(CapacityBound(n, "station", cap,
                                        f"{p.capacity} slot(s) × 3600 / {mean:.1f}s × availability {avail:.3f} / visits {visits[n]:.3f}"))
        for use in p.resources:
            work_by_resource[use.resource] = work_by_resource.get(use.resource, 0.0) + mean * visits[n] * use.quantity
    carrier_transports = {t for c in cm.nodes.values() for t in c.node.release_via.values()}
    for n, c in cm.nodes.items():
        if c.behavior is not Behavior.TRANSPORT:
            continue
        tp: TransportParams = c.params  # type: ignore[assignment]
        cycle = _trip_cycle(tp)
        per_unit = cycle / tp.capacity
        v = visits[n] if n not in carrier_transports else visits.get(_releasing_node(cm, n), 0)
        if cycle > 0 and v > 0:
            bounds.append(CapacityBound(n, "transport", tp.fleet * 3600 / per_unit / v * out_frac,
                                        f"{tp.fleet} vehicle(s) × {tp.capacity} unit(s)/trip / {cycle:.1f}s per trip (load+travel+unload+return)"))
        for use in tp.resources:
            work_by_resource[use.resource] = work_by_resource.get(use.resource, 0.0) + per_unit * v * use.quantity
    for rid, work in work_by_resource.items():
        units = cm.model.resource(rid).quantity
        if work > 0 and units > 0:
            bounds.append(CapacityBound(rid, "resource", units * 3600 / work * out_frac,
                                        f"{units} unit(s) × 3600 / {work:.1f}s of work per unit (walking ignored)"))
    # carrier loops (CONWIP): N carriers / minimum holding time per unit
    g = nx.DiGraph([(n, t) for n, c in cm.nodes.items() for t, _ in c.successors])
    for n, c in cm.nodes.items():
        for s in c.node.seize:
            hold = 0.0
            # sum of mean process times along the (first) path until the release node
            path_nodes = _path_to_release(g, cm, n, s.resource)
            for pn in path_nodes:
                pc = cm.nodes[pn]
                if pc.behavior is Behavior.SERVER and pc.params.process_time:
                    hold += pc.params.process_time.mean_seconds() * pc.params.entity_time_factor()
                elif pc.behavior is Behavior.TRANSPORT:
                    hold += _trip_cycle(pc.params, with_return=False)
                via = pc.node.release_via.get(s.resource)
                if via:  # empty carrier travels back before it can be reused
                    hold += _trip_cycle(cm.nodes[via].params, with_return=False)
                    path_nodes = [*path_nodes, via]
            if hold > 0:
                qty = cm.model.resource(s.resource).quantity
                bounds.append(CapacityBound(s.resource, "carrier_loop", qty / s.quantity * 3600 / hold,
                                            f"{qty} carrier(s) / {hold:.1f}s minimum holding time ({' → '.join(path_nodes)})"))
    bounds.sort(key=lambda b: b.units_per_hour)
    return bounds


def _trip_cycle(tp: TransportParams, with_return: bool = True) -> float:
    trip = tp.travel_seconds() if tp.distance is not None and tp.speed is not None else 0.0
    lu = (tp.load_time.mean_seconds() if tp.load_time else 0.0) + (tp.unload_time.mean_seconds() if tp.unload_time else 0.0)
    return lu + trip * (2 if (tp.return_empty and with_return) else 1)


def _releasing_node(cm: CompiledModel, transport: str) -> str:
    return next((n for n, c in cm.nodes.items() if transport in c.node.release_via.values()), "")


def _path_to_release(g: nx.DiGraph, cm: CompiledModel, start: str, resource: str) -> list[str]:
    targets = [n for n, c in cm.nodes.items() if resource in c.node.release]
    for t in targets:
        if t == start:
            return [start]
        if g.has_node(start) and g.has_node(t) and nx.has_path(g, start, t):
            return nx.shortest_path(g, start, t)
    return [start]


def diagnose(cm: CompiledModel, k: ReplicatedKPIs) -> list[Finding]:
    f: list[Finding] = []
    th = k.mean("throughput_per_hour")
    bounds = capacity_bounds(cm)

    # ---- sanity: simulated throughput vs theoretical maximum ----
    if bounds:
        b = bounds[0]
        f.append(Finding("THEORETICAL_CONSTRAINT", "info", b.subject,
                         f"Capacidad teórica máxima ≈ {b.units_per_hour:.1f} u/h, limitada por '{b.subject}' ({b.kind}).",
                         {"theoretical_max_per_hour": round(b.units_per_hour, 3), "simulated_per_hour": round(th, 3),
                          "calculation": b.explanation}))
        if th > b.units_per_hour * 1.02 + 0.01:
            f.append(Finding("SANITY_THROUGHPUT", "flag", b.subject,
                             f"El throughput simulado ({th:.1f} u/h) supera el máximo teórico ({b.units_per_hour:.1f} u/h). Revisar el modelo.",
                             {"simulated": th, "theoretical": b.units_per_hour}))
        elif b.units_per_hour > 0 and th < 0.5 * b.units_per_hour:
            f.append(Finding("LOW_EFFICIENCY", "warning", "system",
                             f"El sistema produce {th:.1f} u/h, < 50% del máximo teórico ({b.units_per_hour:.1f} u/h): "
                             "pérdidas importantes por bloqueos, esperas, desplazamientos o variabilidad.",
                             {"ratio": round(th / b.units_per_hour, 3)}))

    # ---- demand vs capacity (open systems) ----
    arrivals = 0.0
    for c in cm.nodes.values():
        if c.behavior is Behavior.SOURCE and c.params.arrival == "interarrival" and c.params.interarrival:
            arrivals += 3600 / c.params.interarrival.mean_seconds()
    if arrivals and bounds and arrivals > bounds[0].units_per_hour * 0.98:
        f.append(Finding("DEMAND_EXCEEDS_CAPACITY", "flag", bounds[0].subject,
                         f"Las llegadas ({arrivals:.1f} u/h) superan o igualan la capacidad teórica ({bounds[0].units_per_hour:.1f} u/h): "
                         "las colas crecen sin límite y los KPIs dependen del horizonte.",
                         {"arrivals_per_hour": round(arrivals, 3), "capacity_per_hour": round(bounds[0].units_per_hour, 3)}))

    # ---- Little's law consistency (informative) ----
    wip, lt = k.mean("avg_wip"), k.mean("avg_lead_time_s")
    if th > 0 and lt == lt and wip > 0:
        little = th / 3600 * lt
        dev = abs(little - wip) / wip
        f.append(Finding("LITTLE_LAW", "info" if dev < 0.15 else "warning", "system",
                         f"Ley de Little: TH×LT = {little:.2f} vs WIP medio = {wip:.2f} (desviación {dev:.0%})."
                         + ("" if dev < 0.15 else " Desviación alta: típico de simulaciones cortas o sin warm-up (transitorio)."),
                         {"th_x_lt": round(little, 3), "avg_wip": round(wip, 3)}))

    # ---- bottleneck rules ----
    servers = [n for n, c in cm.nodes.items() if c.behavior is Behavior.SERVER]
    if servers:
        util = {n: k.mean(f"node.{n}.utilization") + k.mean(f"node.{n}.down") for n in servers}
        top = max(util, key=util.get)  # type: ignore[arg-type]
        ev = {"utilization+down": round(util[top], 3)}
        preds = [e.source for e in cm.model.predecessors(top)]
        for p in preds:
            if cm.nodes[p].behavior is Behavior.BUFFER:
                ev[f"avg_queue_{p}"] = round(k.mean(f"node.{p}.avg_content"), 2)
            if cm.nodes[p].behavior is Behavior.SERVER:
                ev[f"blocked_{p}"] = round(k.mean(f"node.{p}.blocked"), 3)
        for s in [t for t, _ in cm.nodes[top].successors]:
            if cm.nodes[s].behavior is Behavior.SERVER:
                ev[f"starved_{s}"] = round(k.mean(f"node.{s}.starved"), 3)
        sev = "warning" if util[top] >= 0.85 else "info"
        f.append(Finding("BOTTLENECK_CANDIDATE", sev, top,
                         f"La estación más cargada es '{top}' ({util[top]:.0%} ocupada/averiada)."
                         + (" Probable cuello de botella entre las estaciones." if util[top] >= 0.85 else ""), ev))
        for n in servers:
            blk = k.mean(f"node.{n}.blocked")
            if blk >= 0.2:
                f.append(Finding("BLOCKING", "warning", n, f"'{n}' está bloqueada el {blk:.0%} del tiempo (aguas abajo lleno).",
                                 {"blocked": round(blk, 3)}))
            wr = k.mean(f"node.{n}.waiting_resource")
            if wr >= 0.2:
                res = [u.resource for u in cm.nodes[n].params.resources] + [s.resource for s in cm.nodes[n].node.seize]
                f.append(Finding("RESOURCE_CONTENTION", "warning", n,
                                 f"'{n}' espera recursos ({', '.join(res)}) el {wr:.0%} del tiempo.",
                                 {"waiting_resource": round(wr, 3), **{f"utilization_{r}": round(k.mean(f'resource.{r}.utilization'), 3) for r in res}}))
    for r in cm.model.resources:
        u = k.mean(f"resource.{r.id}.utilization")
        if u >= 0.9:
            f.append(Finding("RESOURCE_SATURATED", "warning", r.id, f"El recurso '{r.id}' está ocupado el {u:.0%} del tiempo.",
                             {"utilization": round(u, 3), "walking": round(k.mean(f"resource.{r.id}.walking"), 3)}))
    for n, c in cm.nodes.items():
        if c.behavior is Behavior.BUFFER and c.params.capacity:
            avg = k.mean(f"node.{n}.avg_content")
            if avg >= 0.7 * c.params.capacity:
                f.append(Finding("QUEUE_BUILDUP", "info", n, f"El buffer '{n}' está lleno de media al {avg / c.params.capacity:.0%}.",
                                 {"avg_content": round(avg, 2), "capacity": c.params.capacity}))
    return f
