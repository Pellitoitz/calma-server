"""Offline, deterministic interpreter (no LLM, no internet).

Handles simple LINEAR process descriptions and common edit commands in
Spanish/English. It produces exactly the same draft/plan schemas as the LLM
interpreter, so everything downstream (compiler, grounding, verifier) is
shared. Anything it does not understand becomes a question, never a guess.
"""

from __future__ import annotations

import json
import re

from ..domain.isms import ISMSModel, ResourceKind
from ..library.registry import ComponentRegistry
from .compiler import _WORD_NUMBERS, _snake
from .schemas import (DraftCarrierLoop, DraftExperiment, DraftPolicy, DraftQuestion, DraftResource, DraftStep, DraftTime,
                      EditOp, EditPlan, ProcessDraft)

_NUM = r"(\d+(?:[.,]\d+)?|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|one|two|three|four|five|six|seven|eight|nine|ten)"
_TIME_UNITS = {"s": "s", "seg": "s", "segs": "s", "segundo": "s", "segundos": "s", "sec": "s", "second": "s", "seconds": "s",
               "min": "min", "mins": "min", "minuto": "min", "minutos": "min", "minute": "min", "minutes": "min",
               "h": "h", "hora": "h", "horas": "h", "hour": "h", "hours": "h"}
_TIME_RE = re.compile(_NUM + r"\s*(segundos?|segs?|s|sec|seconds?|minutos?|mins?|minutes?|min|horas?|hours?|h)\b", re.I)
_OPERATOR_RE = re.compile(r"\b(operari[oa]s?|operators?|persona|trabajador(?:es)?|worker)\b", re.I)


def _num(tok: str) -> float:
    tok = tok.lower()
    return float(_WORD_NUMBERS[tok]) if tok in _WORD_NUMBERS else float(tok.replace(",", "."))


def _norm(t: str) -> str:
    t = t.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        t = t.replace(a, b)
    return t


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\b(despu[eé]s|luego|finalmente|a continuaci[oó]n|then|finally|afterwards)\b", r". \1", text, flags=re.I)
    parts = re.split(r"(?<!\d)[.;\n]+(?!\d)|,\s+|\s+y\s+(?=(?:un|una|el|la|luego|despu)\b)|\s+and\s+(?=(?:a|an|the)\b)", text)
    return [p.strip(" ,") for p in parts if p and p.strip(" ,")]


class RuleBasedInterpreter:
    name = "offline-rules"

    def __init__(self, registry: ComponentRegistry):
        self.registry = registry

    # ------------------------------------------------------------------ parse
    def parse(self, text: str) -> ProcessDraft:
        d = ProcessDraft(model_name="Modelo")
        low = _norm(text)
        d.confidence_notes.append("Interpretado por el parser OFFLINE (reglas): sólo procesos lineales sencillos.")

        m = re.search(r"(?:simul\w*|turno de|horizonte de|shift of|during)\s+(?:durante\s+)?" + _NUM + r"\s*(horas?|hours?|h|minutos?|min)\b", low)
        if m:
            d.horizon_value, d.horizon_unit = _num(m.group(1)), _TIME_UNITS[m.group(2)]  # type: ignore[assignment]
        if re.search(r"(fuente|suministro|supply|source)\s+(infinit|ilimitad|unlimited)|infinite supply|sin limite de material", low):
            d.supply = "infinite"
        m = re.search(r"(?:llega|arriv\w*)\D{0,30}cada\s+" + _NUM + r"\s*(segundos?|s|minutos?|min)\b", low)
        if m:
            d.supply = "interarrival"
            d.interarrival = DraftTime(dist="exponential" if "media" in low or "mean" in low else "constant",
                                       value=_num(m.group(1)), mean=_num(m.group(1)), unit=_TIME_UNITS[m.group(2)])  # type: ignore[arg-type]

        # racks / bastidores
        m = re.search(_NUM + r"\s+(bastidores|racks|palets|pallets|utillajes)", low)
        carrier_id = None
        if m:
            carrier_id = "racks"
            d.resources.append(DraftResource(id=carrier_id, name=m.group(2), kind="carrier", quantity=int(_num(m.group(1)))))

        operator_ids: list[str] = []
        pending_ops: list[tuple[str, str]] = []  # (operator, sentence) without a time: "el mismo operario hace X y Y"
        prev_op: str | None = None
        for sent in _sentences(text):
            s = _norm(sent)
            op_here = None
            if _OPERATOR_RE.search(s):
                if re.search(r"\b(otro|segundo|another|second)\b", s) and prev_op:
                    op_here = f"operator_{len(operator_ids) + 1}"
                elif re.search(r"\b(mismo|misma|same)\b", s) and prev_op:
                    op_here = prev_op
                else:
                    op_here = prev_op or f"operator_{len(operator_ids) + 1}"
                if op_here not in operator_ids:
                    operator_ids.append(op_here)
                    qty = None
                    mq = re.search(_NUM + r"\s+operari", s)
                    if mq and _num(mq.group(1)) > 1:
                        qty = int(_num(mq.group(1)))
                    elif re.search(r"\b(un|una|el|la|mismo)\s+operari|\ban operator\b|\bone operator\b", s):
                        qty = 1
                    d.resources.append(DraftResource(id=op_here, name=op_here.replace("_", " ").title(), kind="operator", quantity=qty))
                prev_op = op_here

            mb = re.search(r"\b(buffer|cola|pulmon|queue)\b(?:\s+(?:de|con capacidad(?: para| de)?|of|with capacity(?: of)?|para))?\s*" + _NUM + r"?", s)
            if mb and not _TIME_RE.search(s):
                cap = _num(mb.group(2)) if mb.group(2) else None
                idx = sum(1 for st in d.steps if st.component == "buffer") + 1
                d.steps.append(DraftStep(id=f"buffer_{idx}", name=f"Buffer {idx}", component="buffer",
                                         capacity=int(cap) if cap is not None else None))
                continue

            mt = _TIME_RE.search(s)
            if op_here and not mt:
                pending_ops.append((op_here, s))
            if not mt or re.search(r"simul|turno|horizonte|shift", s) and not re.search(r"monta|inspecc|revis|maquina|proces|sold|test", s):
                continue
            hits = [c for c in self.registry.search(s) if c.behavior.value == "server"]
            if hits:
                comp = hits[0]
                name = comp.name
            else:
                comp = self.registry.get("manual_process" if op_here else "machine")
                name = comp.name
                d.assumptions.append(f"Paso '{sent[:40]}' interpretado como '{comp.id}' genérico.")
            sid = _snake(comp.id)
            n_same = sum(1 for st in d.steps if st.id.startswith(sid))
            if n_same:
                sid, name = f"{sid}_{n_same + 1}", f"{name} {n_same + 1}"
            val, unit = _num(mt.group(1)), _TIME_UNITS[mt.group(2).lower()]
            d.steps.append(DraftStep(id=sid, name=name, component=comp.id, time=DraftTime(dist="constant", value=val, unit=unit),  # type: ignore[arg-type]
                                     resources=[op_here] if op_here else []))

        # operators assigned in a separate sentence ("el mismo operario realiza montaje y revisión")
        for op, sent in pending_ops:
            for st in d.steps:
                if st.component != "buffer" and op not in st.resources and any(w in sent for w in _keywords(self.registry, st.component)):
                    st.resources.append(op)

        # priorities: "la prioridad es <step>" / "mantener alimentada la <machine>"
        mp = re.search(r"prioridad\w*\s+(?:es\s+)?(?:a\s+|de\s+)?(.{0,60})|priorit\w*\s+(.{0,60})", low)
        if mp and operator_ids:
            target = _norm(mp.group(1) or mp.group(2) or "")
            op = operator_ids[0]
            op_steps = [st for st in d.steps if op in st.resources]
            named = [st for st in d.steps if st.component != "buffer" and any(w in target for w in _keywords(self.registry, st.component))]
            ranked = [st for st in named if op in st.resources]
            if not ranked and named and re.search(r"aliment|feed|starv|parad|ocupad", target):
                # keep an automatic machine fed -> the operator's tasks upstream of it go first
                pos = d.steps.index(named[0])
                ranked = [st for st in op_steps if d.steps.index(st) < pos]
            if ranked and len(op_steps) >= 2:
                order = [r.id for r in ranked] + [st.id for st in op_steps if st not in ranked]
                d.policies.append(DraftPolicy(resource=op, rule="priority", priority_order=order))
                d.assumptions.append(f"Prioridad del operario interpretada como: {' > '.join(order)}.")

        if carrier_id:
            procs = [st for st in d.steps if st.component != "buffer"]
            if len(procs) >= 2:
                d.carrier_loops.append(DraftCarrierLoop(resource=carrier_id, seize_at=procs[0].id, release_at=procs[-1].id))
                d.assumptions.append(f"Los {carrier_id} se cargan en '{procs[0].name}' y se liberan tras '{procs[-1].name}'.")

        me = re.search(r"(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM + r"\s+(bastidores|racks|operari\w*|buffers?)", low) or \
            re.search(r"(bastidores|racks|operari\w*|buffers?)\s+(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM, low)
        if me:
            g = me.groups()
            if g[0] in ("bastidores", "racks") or g[0].startswith(("operari", "buffer")):
                target, lo, hi = g[0], _num(g[1]), _num(g[2])
            else:
                lo, hi, target = _num(g[0]), _num(g[1]), g[2]
            d.experiments.append(DraftExperiment(target=target, values=[float(v) for v in range(int(lo), int(hi) + 1)]))

        if not d.steps:
            d.missing_information.append(DraftQuestion(question="No he identificado ningún paso con tiempo de proceso. Describe cada paso con su duración (p.ej. 'montaje 60 segundos')."))
        names = [st.name for st in d.steps]
        d.model_name = " → ".join(names[:4]) if names else "Modelo"
        return d

    # ------------------------------------------------------------------ edits
    def plan_edit(self, text: str, model: ISMSModel) -> EditPlan:
        s = _norm(text)
        ops: list[EditOp] = []
        buffers = [n for n in model.nodes if n.component == "buffer"]
        operators = [r for r in model.resources if r.kind is ResourceKind.OPERATOR]
        carriers = [r for r in model.resources if r.kind is ResourceKind.CARRIER]

        if re.search(r"cuello de botella|bottleneck|restriccion", s):
            return EditPlan(operations=[EditOp(intent="explain_bottleneck")], explanation="Diagnóstico de cuello de botella")
        if re.search(r"por que .*esper|why .*wait|espera el operario", s):
            return EditPlan(operations=[EditOp(intent="explain_waiting")], explanation="Análisis de esperas")
        if re.search(r"version anterior|\bdeshac\w*|\bundo\b|\brevert\w*", s):
            return EditPlan(operations=[EditOp(intent="revert")], explanation="Volver a la versión anterior")
        if re.search(r"compar\w* con (el )?baseline|vs baseline", s):
            return EditPlan(operations=[EditOp(intent="compare_baseline")], explanation="Comparar con baseline")

        # experiments: "prueba buffers entre 1 y 10"
        me = re.search(r"(bastidores|racks|operari\w*|buffers?|colas?)\D{0,20}?(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM, s) or \
            re.search(r"(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM + r"\s+(bastidores|racks|operari\w*|buffers?)", s)
        if me and re.search(r"prueb|experiment|estudi|barr|sweep|try|test", s):
            g = me.groups()
            target, lo, hi = (g[0], g[1], g[2]) if not g[0][0].isdigit() and g[0] not in _WORD_NUMBERS else (g[2], g[0], g[1])
            path = self._target_path(target, buffers, operators, carriers)
            if not path:
                return EditPlan(question=f"No encuentro '{target}' en el modelo.")
            vals = list(range(int(_num(lo)), int(_num(hi)) + 1))
            return EditPlan(operations=[EditOp(intent="experiment", factor_path=path, values_json=json.dumps(vals))],
                            explanation=f"Experimento: {path} = {vals[0]}..{vals[-1]}")

        # horizon
        mh = re.search(r"simul\w*\s+" + _NUM + r"\s*(horas?|h|minutos?|min)\b", s)
        if mh:
            ops.append(EditOp(intent="set", path="simulation.horizon", value_json=json.dumps({"value": _num(mh.group(1)), "unit": _TIME_UNITS[mh.group(2)]})))
        mr = re.search(_NUM + r"\s+replicacion|replications?\s*(?:=|a)?\s*" + _NUM, s)
        if mr:
            ops.append(EditOp(intent="set", path="simulation.replications", value_json=str(int(_num(mr.group(1) or mr.group(2))))))

        # operators: "pon dos operarios"
        mo = re.search(r"(?:pon|usa|con|set|use|anade|añade)\s+" + _NUM + r"\s+operari", s)
        if mo and operators:
            ops.append(EditOp(intent="set", path=f"resources.{operators[0].id}.quantity", value_json=str(int(_num(mo.group(1))))))
        mc = re.search(r"(?:pon|usa|con|set|use)\s+" + _NUM + r"\s+(?:bastidores|racks)", s)
        if mc and carriers:
            ops.append(EditOp(intent="set", path=f"resources.{carriers[0].id}.quantity", value_json=str(int(_num(mc.group(1))))))

        # buffer capacity: "cambia el buffer a 8"
        mb = re.search(r"(buffer|cola)\w*\s*(?:\w+\s){0,2}?(?:a|en|=|to|de)\s+" + _NUM + r"\b(?!\s*(?:s|seg|min))", s)
        if mb and buffers:
            target = next((b for b in buffers if b.id in s or _norm(b.name) in s), buffers[0])
            ops.append(EditOp(intent="set", path=f"nodes.{target.id}.params.capacity", value_json=str(int(_num(mb.group(2))))))

        # process time: "reduce montaje a 50 segundos"
        mt = _TIME_RE.search(s)
        if mt and not mh:
            for n in model.nodes:
                if n.component in ("source", "sink", "buffer"):
                    continue
                keys = {_norm(n.name), n.id.replace("_", " "), *(_keywords(self.registry, n.component))}
                if any(k and len(k) > 3 and k in s for k in keys):
                    dist = {"dist": "constant", "value": _num(mt.group(1)), "unit": _TIME_UNITS[mt.group(2).lower()]}
                    ops.append(EditOp(intent="set", path=f"nodes.{n.id}.params.process_time", value_json=json.dumps(dist)))
                    break

        if re.search(r"^\s*(ejecuta|simula|run|lanza)\b", s) and not ops:
            return EditPlan(operations=[EditOp(intent="run")], explanation="Ejecutar simulación")
        if not ops:
            return EditPlan(question="No he entendido la petición con el intérprete offline. Ejemplos: 'cambia el buffer a 8', "
                                     "'pon dos operarios', 'reduce montaje a 50 segundos', 'prueba buffers entre 1 y 10', "
                                     "'¿dónde está el cuello de botella?'. Para lenguaje libre configura ANTHROPIC_API_KEY.")
        return EditPlan(operations=ops, explanation="; ".join(f"{o.path} → {o.value_json}" for o in ops))

    @staticmethod
    def _target_path(target: str, buffers, operators, carriers) -> str | None:
        if target.startswith(("buffer", "cola")) and buffers:
            return f"nodes.{buffers[0].id}.params.capacity"
        if target.startswith("operari") and operators:
            return f"resources.{operators[0].id}.quantity"
        if target in ("bastidores", "racks") and carriers:
            return f"resources.{carriers[0].id}.quantity"
        return None


def _keywords(registry: ComponentRegistry, comp_id: str) -> list[str]:
    try:
        c = registry.get(comp_id)
    except KeyError:
        return []
    return [_norm(k) for k in [*c.keywords, c.name] if len(k) > 3]
