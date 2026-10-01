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
from ..domain.units import UnitError, from_base, to_base
from ..library.registry import ComponentRegistry
from .compiler import _WORD_NUMBERS, _snake
from .schemas import (DraftCarrierLoop, DraftCustomRule, DraftExperiment, DraftItems, DraftPolicy, DraftQuestion, DraftResource,
                      DraftStep, DraftTime, EditOp, EditPlan, ProcessDraft)

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
    """Sentences, then clauses. A comma splits only when the sentence lists several timed steps
    ("montaje 120 s, después un buffer..., una selectiva 200 s"); enumerations such as
    "realiza montaje, transporte y revisión" stay together."""
    out: list[str] = []
    # '.' ends a sentence when followed by whitespace/end (so "capacidad 5. Una máquina" splits) but not inside "4.5"
    for sent in re.split(r"[;\n]+|\.(?=\s|$)", text):
        sent = sent.strip(" ,")
        if not sent:
            continue
        sent = re.sub(r",?\s+\b(despu[eé]s|luego|finalmente|a continuaci[oó]n|then|finally|afterwards)\b", r" | \1", sent, flags=re.I)
        many = len(_TIME_RE.findall(_norm(sent))) >= 2
        parts = re.split(r"\s*\|\s*" + (r"|,\s+|\s+y\s+(?=(?:un|una|el|la)\b)|\s+and\s+(?=(?:a|an|the)\b)" if many else ""), sent)
        out += [p.strip(" ,") for p in parts if p and p.strip(" ,")]
    return out


class RuleBasedInterpreter:
    name = "offline-rules"
    prompt_version = "offline_rules_v2"  # versioned like LLM prompts: recorded with every generated model

    def __init__(self, registry: ComponentRegistry):
        self.registry = registry

    # ------------------------------------------------------------------ parse
    def parse(self, text: str) -> ProcessDraft:
        """Clause-by-clause interpretation. Every clause is either consumed by a rule, turned into a
        custom-rule candidate, or reported as unparsed (never silently dropped)."""
        d = ProcessDraft(model_name="Modelo")
        low = _norm(text)
        d.confidence_notes.append("Interpretado por el intérprete OFFLINE (reglas deterministas ES/EN).")
        consumed_spans: list[tuple[int, int]] = []

        def take(m: re.Match | None) -> re.Match | None:
            if m:
                consumed_spans.append(m.span())
            return m

        # ---------------- global facts (whole text) ----------------
        m = take(re.search(r"(?:simul\w*|turno de|horizonte de|shift of|simulate|during|durante)\s+(?:durante\s+|for\s+|un turno de\s+|an?\s+)?"
                           + _NUM + r"[\s-]*(horas?|hours?|h|minutos?|min)\b", low))
        if m:
            d.horizon_value, d.horizon_unit = _num(m.group(1)), _TIME_UNITS[m.group(2)]  # type: ignore[assignment]
        if take(re.search(r"(fuente|suministro|supply|source)\s+(es\s+|is\s+)?(infinit\w*|ilimitad\w*|unlimited|siempre disponible|always available)"
                          r"|infinite supply|sin limite de material", low)):
            d.supply = "infinite"
        m = take(re.search(r"(?:llega\w*|arriv\w*)\D{0,30}(?:cada|every)\s+" + _NUM + r"\s*(segundos?|s|minutos?|min|seconds?|minutes?)\b", low))
        if m:
            d.supply = "interarrival"
            d.interarrival = DraftTime(dist="constant", value=_num(m.group(1)), unit=_TIME_UNITS[m.group(2)])  # type: ignore[arg-type]

        exp = take(re.search(r"(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM + r"\s+(bastidores|racks|palets|pallets|operari\w*|operators?|buffers?|colas?)", low)
                   or re.search(r"(bastidores|racks|palets|pallets|operari\w*|operators?|buffers?|colas?)\D{0,25}(?:entre|de|between|from)\s+" + _NUM + r"\s+(?:y|a|and|to)\s+" + _NUM, low))
        exp_span = exp.span() if exp else (-1, -1)
        if exp:
            g = exp.groups()
            target, lo, hi = (g[2], g[0], g[1]) if g[0][0].isdigit() or g[0] in _WORD_NUMBERS else (g[0], g[1], g[2])
            d.experiments.append(DraftExperiment(target=target, values=[float(v) for v in range(int(_num(lo)), int(_num(hi)) + 1)]))

        carrier_word = re.search(r"\b(bastidores?|racks?|palets?|pallets?|utillajes?|fixtures?)\b", low)
        carrier_id = None
        if carrier_word:
            carrier_id = "racks" if carrier_word.group(1).startswith(("bastidor", "rack")) else _snake(carrier_word.group(1).rstrip("s"))
            qty = None
            for mq in re.finditer(_NUM + r"\s+(bastidores|racks|palets|pallets|utillajes|fixtures)\b", low):
                if not (exp_span[0] <= mq.start() < exp_span[1]):
                    qty = int(_num(mq.group(1)))
                    consumed_spans.append(mq.span())
            d.resources.append(DraftResource(id=carrier_id, name=carrier_word.group(1).rstrip("s") + "s" if not carrier_word.group(1).endswith("s")
                                             else carrier_word.group(1), kind="carrier", quantity=qty))
            take(re.search(r"(numero|cantidad) (limitad[oa]|finit[oa]) de (bastidores|racks|palets)|limited number of (racks|pallets)", low))

        mi = re.search(r"(circuitos?|placas?|pcbs?|piezas?|parts?|boards?|circuits?)\b[^.]{0,40}?(?:en|on|in)\s+(?:los\s+|the\s+)?(bastidores|racks|palets|pallets)", low)
        mip = take(re.search(_NUM + r"\s+(circuitos?|placas?|pcbs?|piezas?|boards?|circuits?)\s+(?:por|per)\s+(bastidor|rack|palet|pallet)", low))
        if mip or mi:
            item = (mip.group(2) if mip else mi.group(1)).rstrip("s")
            d.items = DraftItems(item_name=item + "s", per_entity=int(_num(mip.group(1))) if mip else None)

        mn = take(re.search(r"(?:tengo|tenemos|es|i have|we have|this is)\s+(?:un|una|an?)\s+(?:proceso|linea|celula|process|line|cell)\s+(?:de|of)\s+([a-z ]{3,40})", low)
                  or re.search(r"(?:i have|we have|this is)\s+an?\s+([a-z ]{3,40}?)\s+(?:process|line|cell)\b", low))
        if mn:
            d.model_name = mn.group(1).strip().capitalize()
        wip = take(re.search(r"(wip objetivo|objetivo de wip|wip target|target wip)(?:\s+(?:de|of|=)\s+" + _NUM + r")?", low))
        protect = take(re.search(r"(?:mantenga|mantener|mantiene|keep)\s+(?:siempre\s+)?alimentad[ao]\s+(?:la |el |a |the )?([a-z ]{3,40}?)(?=\s+(?:utiliz|usando|using|con|with)|$|[.,])"
                                 r"|(?:keep|keeps)\s+(?:the\s+)?([a-z ]{3,40}?)\s+fed", low))

        # ---------------- clause loop ----------------
        operator_ids: list[str] = []
        prev_op: str | None = None
        assignments: list[tuple[str, str]] = []
        step_clauses: list[tuple[DraftStep, str]] = []

        def new_op(clause: str) -> str:
            nonlocal prev_op
            if re.search(r"\b(otro|segundo|another|second)\b", clause) and prev_op:
                op = f"operator_{len(operator_ids) + 1}"
            elif re.search(r"\b(mismo|misma|same)\b", clause) and prev_op:
                op = prev_op
            else:
                op = prev_op or f"operator_{len(operator_ids) + 1}"
            if op not in operator_ids:
                operator_ids.append(op)
                mq = re.search(_NUM + r"\s+(?:operari|operators?|trabajador|workers?)", clause)
                qty = int(_num(mq.group(1))) if mq and _num(mq.group(1)) > 1 else (
                    1 if re.search(r"\b(un|una|el|la|mismo|misma|one|an|the|same)\s+(operari|trabajador|persona|operator|worker)", clause) else None)
                speed = re.search(_NUM + r"\s*m/s", clause)
                d.resources.append(DraftResource(id=op, name="Operario" if op == "operator_1" else op.replace("_", " ").title(),
                                                 kind="operator", quantity=qty, walking_speed_m_s=_num(speed.group(1)) if speed else None))
            prev_op = op
            return op

        for clause in _sentences(text):
            c = _norm(clause)
            if re.match(r"(si|cuando|siempre que|en caso de|if|when|whenever|unless|in case)\b", c):
                # conditional behaviour: never turned into a plain station, never dropped
                d.custom_rules.append(DraftCustomRule(description=clause.strip(), reason="ninguna regla de la biblioteca la cubre"))
                continue
            if mn and re.match(r"(tengo|tenemos|es|i have|we have|this is)\s+(un|una|an?)\b", c) and not _TIME_RE.search(c):
                continue  # model name ("Tengo un proceso de ...")
            op_here = new_op(c) if _OPERATOR_RE.search(c) else None
            tm = _TIME_RE.search(c)
            if any(k in c for k in ("simul", "turno", "horizonte", "shift")) and not re.search(r"\b(monta|inspecc|revis|proces|sold|transport)", c):
                tm = None  # horizon clause, already consumed globally
            # buffers / queues
            mb = re.search(r"\b(buffer|cola|pulmon|almacen intermedio|queue|stock intermedio)\b(?:\s+de\s+(entrada|salida|input|output))?", c)
            if mb and not tm:
                cap = re.search(r"(?:capacidad|capacity|de|of|para|for)\s+(?:para\s+|de\s+|of\s+)?" + _NUM + r"(?!\s*(?:s|seg|min|h)\b)", c[mb.end():]) \
                    or re.search(_NUM + r"\s+(?:unidades|units|piezas|parts|bastidores|racks)", c)
                idx = sum(1 for st in d.steps if st.component == "buffer") + 1
                qual = mb.group(2)
                name = f"Buffer de {qual}" if qual else f"Buffer {idx}"
                d.steps.append(DraftStep(id=_snake(name) if qual else f"buffer_{idx}", name=name, component="buffer",
                                         capacity=int(_num(cap.group(1))) if cap else None))
                continue
            # transports
            mt = re.search(r"\b(se\s+)?(transporta\w*|traslada\w*|lleva\w*|mueve\w*|transport\w*|carr(?:y|ies|ied)|moved?|taken)\b", c)
            if mt and not re.search(r"\b(realiza|hace|does|performs)\b.*\b(transporte|transport)\b.*,|\by\b.*transporte", c) and not (
                    op_here and re.search(r"\b(montaje|revision|inspeccion|assembly|review)\b", c) and re.search(r"\btransporte?\b", c)):
                n = sum(1 for st in d.steps if st.component in ("transport", "rack_transport")) + 1
                dist = re.search(_NUM + r"\s*(?:m|metros|meters)\b(?!/)", c)
                spd = re.search(_NUM + r"\s*m/s", c)
                ld = re.search(r"(?:carga|load\w*)\D{0,12}" + _NUM + r"\s*(?:s|seg\w*|seconds?)\b", c)
                ul = re.search(r"(?:descarga|unload\w*)\D{0,12}" + _NUM + r"\s*(?:s|seg\w*|seconds?)\b", c)
                comp = "rack_transport" if carrier_id else "transport"
                st = DraftStep(id=f"transport_{n}", name=f"Transporte {n}", component=comp,
                               distance_m=_num(dist.group(1)) if dist else None, speed_m_s=_num(spd.group(1)) if spd else None,
                               load_time_s=_num(ld.group(1)) if ld else None, unload_time_s=_num(ul.group(1)) if ul else None,
                               resources=[op_here] if op_here else [])
                d.steps.append(st)
                step_clauses.append((st, c))
                continue
            # operator assignment ("el mismo operario realiza montaje, transporte y revisión")
            if op_here and not tm and len(re.findall(r"\b(montaje|monta|ensambl\w*|revision|revisa|inspecc\w*|transporte|limpieza|assembly|review|inspection|transport)\b", c)) >= 2:
                assignments.append((op_here, c))
                continue
            # stations (library components with behaviour 'server')
            hits = [h for h in self.registry.search(c) if h.behavior.value == "server"]
            verb = re.search(r"\b(monta\w*|procesa\w*|realiza\w*|inspecc\w*|revisa\w*|suelda\w*|pasan a|pasa a|se hace|process\w*|assembl\w*|inspect\w*|review\w*|tarda|takes)\b", c)
            if hits and (tm or verb):
                comp, name = self._station(hits, c, clause, d)
                sid = _snake(comp.id)
                n_same = sum(1 for s in d.steps if s.id.startswith(sid))
                if n_same:
                    sid, name = f"{sid}_{n_same + 1}", f"{name} {n_same + 1}"
                time = None
                basis = "per_entity"
                if tm:
                    time = DraftTime(dist="constant", value=_num(tm.group(1)), unit=_TIME_UNITS[tm.group(2).lower()])  # type: ignore[arg-type]
                    if re.search(r"(?:por|per|/)\s*(?:circuito|circuit|placa|board|pieza)", c) and d.items is not None:
                        basis = "per_item"
                if time is None and d.items is not None:
                    # "la selectiva procesa los bastidores" -> per carrier; otherwise the time is asked per item
                    carrier_only = re.search(r"\b(bastidor\w*|racks?|palet\w*|pallets?|carros?)\b", c) and not re.search(
                        r"\b(circuit\w*|placa\w*|boards?|piezas?|items?)\b", c)
                    basis = "per_entity" if carrier_only else "per_item"
                st = DraftStep(id=sid, name=name, component=comp.id, time=time, resources=[op_here] if op_here else [], time_basis=basis)  # type: ignore[arg-type]
                d.steps.append(st)
                step_clauses.append((st, c))
                continue
            if _consumed_fact(c):
                continue
            if re.search(r"\b(si|cuando|siempre que|salvo|excepto|prioriza\w*|regla|if|when|unless|always|never|nunca)\b", c):
                # conditional logic is never dropped, even in a clause that also names the operator
                d.custom_rules.append(DraftCustomRule(description=clause.strip(), reason="ninguna regla de la biblioteca la cubre"))
            elif not (op_here or any(s[0] <= text.lower().find(clause.lower()[:10]) < s[1] for s in consumed_spans)):
                d.unparsed.append(clause.strip())

        # ---------------- post-processing ----------------
        for op, c in assignments:
            for st in d.steps:
                if st.component == "buffer" or op in st.resources:
                    continue
                kws = _keywords(self.registry, st.component) + (["transporte", "transport", "traslado"] if st.component in ("transport", "rack_transport") else [])
                if any(k in c for k in kws) or ("limpieza" in c and "limpieza" in _norm(st.name)):
                    st.resources.append(op)
        # a transport is performed by the operator only if stated; otherwise ask
        for st in d.steps:
            if st.component in ("transport", "rack_transport") and not st.resources:
                d.missing_information.append(DraftQuestion(question=f"¿Quién realiza '{st.name}'? (el operario u otro recurso)", required=False))
        # carrier loop: seize where the carrier is first used, release at the last processing step
        if carrier_id:
            procs = [st for st in d.steps if st.component not in ("buffer", "transport", "rack_transport")]
            if procs:
                seize = next((st for st, c in step_clauses if carrier_word and carrier_word.group(1)[:5] in c and st in procs), procs[0])
                mode = "unknown"
                if re.search(r"(vuelv|retorn|regres|return)\w*", low):
                    mode = "transport" if re.search(r"(vuelv|retorn|regres|return)\w*[^.]{0,40}(transport|llev|carr)", low) else "immediate"
                elif re.search(r"disponibles?\s+(de nuevo|nuevamente|otra vez)|available again", low):
                    mode = "immediate"
                d.carrier_loops.append(DraftCarrierLoop(resource=carrier_id, seize_at=seize.id, release_at=procs[-1].id, return_mode=mode))  # type: ignore[arg-type]
                d.assumptions.append(f"Cada unidad toma un {carrier_id.rstrip('s')} en '{seize.name}' y lo libera al terminar '{procs[-1].name}'.")
        # strategy
        if wip and operator_ids:
            prot = None
            if protect:
                target_txt = (protect.group(1) or protect.group(2) or "").strip()
                prot = next((st for st in d.steps if st.component not in ("buffer", "transport", "rack_transport")
                             and any(k in target_txt for k in _keywords(self.registry, st.component))), None)
            op = operator_ids[0]
            feeders = []
            if prot:
                pi = d.steps.index(prot)
                feeders = [st.id for st in d.steps[:pi] if op in st.resources]
            d.policies.append(DraftPolicy(resource=op, rule="wip_target", protected_step=prot.id if prot else None, feeder_steps=feeders,
                                          target=int(_num(wip.group(2))) if wip.group(2) else None))
        else:
            self._static_priority(d, low, operator_ids)
        if not d.steps:
            d.missing_information.append(DraftQuestion(question="No he identificado ningún paso del proceso. Describe cada paso (p.ej. 'montaje 60 segundos')."))
        if d.items is not None and any(st.time_basis == "per_item" for st in d.steps):
            d.assumptions.append(f"Tiempos de proceso expresados por {d.items.item_name.rstrip('s')} (× {d.items.item_name} por unidad).")
        if d.model_name == "Modelo":
            names = [st.name for st in d.steps if st.component != "buffer"]
            d.model_name = " → ".join(names[:4]) if names else "Modelo"
        return d

    def _station(self, hits, c: str, clause: str, d: ProcessDraft):
        """Pick the component for a station clause. 'revisión y limpieza' (two station keywords joined by y/and)
        becomes ONE step named after both, using the component mentioned first."""
        mentioned = []
        for h in hits[:3]:
            pos = [c.find(k) for k in _keywords(self.registry, h.id) if k in c]
            if pos:
                mentioned.append((min(pos), h))
        mentioned.sort(key=lambda t: t[0])
        if len(mentioned) >= 2 and re.search(r"\b(y|and|e)\b", c[mentioned[0][0]:]):
            first, second = mentioned[0][1], mentioned[1][1]
            words = re.findall(r"[a-záéíóúñ]+", clause.lower())
            def word_for(comp):
                return next((w for w in words if any(_norm(w).startswith(k[:6]) for k in _keywords(self.registry, comp.id))), comp.name)
            name = f"{word_for(first).capitalize()} y {word_for(second)}"
            d.assumptions.append(f"'{name}' se modela como un único paso ({first.id}).")
            return first, name
        comp = mentioned[0][1] if mentioned else hits[0]
        return comp, comp.name

    def _static_priority(self, d: ProcessDraft, low: str, operator_ids: list[str]) -> None:
        mp = re.search(r"prioridad\w*\s+(?:es\s+)?(?:a\s+|de\s+)?(.{0,60})|priorit\w*\s+(.{0,60})", low)
        if not (mp and operator_ids):
            return
        target = _norm(mp.group(1) or mp.group(2) or "")
        op = operator_ids[0]
        op_steps = [st for st in d.steps if op in st.resources]
        named = [st for st in d.steps if st.component != "buffer" and any(w in target for w in _keywords(self.registry, st.component))]
        ranked = [st for st in named if op in st.resources]
        if not ranked and named and re.search(r"aliment|feed|starv|parad|ocupad", target):
            pos = d.steps.index(named[0])
            ranked = [st for st in op_steps if d.steps.index(st) < pos]
        if ranked and len(op_steps) >= 2:
            order = [r.id for r in ranked] + [st.id for st in op_steps if st not in ranked]
            d.policies.append(DraftPolicy(resource=op, rule="priority", priority_order=order))
            d.assumptions.append(f"Prioridad del operario interpretada como: {' > '.join(order)}.")

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

        # buffer capacity: "cambia el buffer de entrada de 3 a 5" / "cambia el buffer a 8"
        mft = re.search(r"(buffer|cola)\w*\D{0,30}?\b(?:de|from)\s+" + _NUM + r"\s+(?:a|to)\s+" + _NUM + r"\b(?!\s*(?:s|seg|min))", s)
        if mft and buffers:
            target = next((b for b in buffers if b.id in s or _norm(b.name) in s), buffers[0])
            ops.append(EditOp(intent="set", path=f"nodes.{target.id}.params.capacity", value_json=str(int(_num(mft.group(3)))),
                              expected_json=str(int(_num(mft.group(2))))))
        mb = None if mft else re.search(r"(buffer|cola)\w*\s*(?:\w+\s){0,2}?(?:a|en|=|to|de)\s+" + _NUM + r"\b(?!\s*(?:s|seg|min))", s)
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

        if not ops and not mh and not mr:
            op = self._parameter_edit(s, model)
            if isinstance(op, str):
                return EditPlan(question=op)
            if op:
                ops.append(op)

        if re.search(r"^\s*(ejecuta|simula|run|lanza)\b", s) and not ops:
            return EditPlan(operations=[EditOp(intent="run")], explanation="Ejecutar simulación")
        if not ops:
            return EditPlan(question="No he entendido la petición con el intérprete offline. Ejemplos: 'cambia el buffer a 8', "
                                     "'pon dos operarios', 'reduce montaje a 50 segundos', 'prueba buffers entre 1 y 10', "
                                     "'¿dónde está el cuello de botella?'. Para lenguaje libre configura ANTHROPIC_API_KEY.")
        return EditPlan(operations=ops, explanation="; ".join(f"{o.path} → {o.value_json}" for o in ops))

    def _parameter_edit(self, s: str, model: ISMSModel) -> EditOp | str | None:
        """Generic edit on a named model parameter: 'la velocidad del operario es 1.0 m/s', 'distancia montaje-buffer 8 m'.
        Returns an EditOp, a clarification question (ambiguous), or None."""
        nums = list(re.finditer(_NUM + r"\s*(m/s|km/h|metros|meters|cm|mm|km|m|segundos|seconds|seg|ms|s|minutos|minutes|min|horas|hours|h)?(?![a-z/])", s))
        if not nums or not model.parameters:
            return None
        mft = re.search(r"\b(?:de|from)\s+" + _NUM + r"\s*\S*\s+(?:a|to)\s+" + _NUM, s)
        words = {w for w in re.findall(r"[a-z]+", s) if len(w) > 2 and w not in _STOP}
        req = words | {_PARAM_SYN[w] for w in words if w in _PARAM_SYN}
        scored = []
        for prm in model.parameters:
            vocab = _param_vocab(self.registry, model, prm.id)
            role = req & set(prm.id.split("_")) & _ROLES  # the role word must name the parameter itself
            if not role:
                continue
            scored.append((len(req & vocab), prm))
        if not scored:
            return None
        scored.sort(key=lambda t: -t[0])
        best = [p for sc, p in scored if sc == scored[0][0]]
        if len(best) > 1:
            return "¿Qué parámetro quieres cambiar? " + ", ".join(p.id for p in best)
        prm = best[0]
        m = nums[-1]
        value = _num(m.group(1))
        unit = _UNIT_WORDS.get(m.group(2) or "", m.group(2))
        if unit and prm.unit and unit != prm.unit:
            try:
                value = from_base(to_base(value, unit), prm.unit)
            except (UnitError, KeyError):
                return f"No puedo convertir {unit} a {prm.unit} para '{prm.id}'."
        op = EditOp(intent="set", path=f"parameters.{prm.id}.value", value_json=json.dumps(value))
        if mft:
            op.expected_json = json.dumps(_num(mft.group(1)))
        return op

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


_STOP = {"del", "los", "las", "the", "que", "por", "para", "con", "una", "uno", "and", "pon", "cambia", "change", "set",
         "esta", "son", "are", "ahora", "now", "valor", "value"}
_PARAM_SYN = {"velocidad": "speed", "andando": "walking", "camina": "walking", "distancia": "dist", "distance": "dist",
              "metros": "dist", "carga": "load", "cargar": "load", "descarga": "unload", "descargar": "unload",
              "capacidad": "capacity", "objetivo": "target", "tiempo": "time", "duracion": "time", "tarda": "time",
              "circuitos": "per", "placas": "per", "circuits": "per", "boards": "per", "items": "per",
              "operario": "operator", "trabajador": "operator", "worker": "operator", "operarios": "count",
              "bastidores": "racks", "rack": "racks", "bastidor": "racks", "distances": "dist", "loading": "load",
              "unloading": "unload", "walk": "walking"}
_ROLES = {"speed", "dist", "load", "unload", "capacity", "wip", "target", "time", "per", "count", "racks"}
_UNIT_WORDS = {"metros": "m", "km/h": "km/h", "meters": "m", "segundos": "s", "seconds": "s", "seg": "s", "minutos": "min", "minutes": "min",
               "horas": "h", "hours": "h"}


def _param_vocab(registry: ComponentRegistry, model: ISMSModel, pid: str) -> set[str]:
    """Words that can name a parameter: its id tokens + names/keywords of the nodes it belongs to or is used in."""
    vocab = set(pid.split("_"))
    ref = f"${pid}"
    for n in model.nodes:
        if n.id in pid or ref in n.model_dump_json():
            vocab |= set(re.findall(r"[a-z]+", _norm(n.name))) | set(n.id.split("_"))
            for k in _keywords(registry, n.component):
                vocab |= set(k.split())
    for r in model.resources:
        if r.id in pid or ref in r.model_dump_json():
            vocab |= set(re.findall(r"[a-z]+", _norm(r.name))) | {r.kind.value}
    return vocab


_FACT_PATTERNS = [r"\b(simul|turno|horizonte|shift|simulate)", r"\b(fuente|suministro|supply|source)\b",
                  r"\b(quiero probar|probar entre|prueba|study|test between|try)\b", r"\b(wip objetivo|wip target|alimentad)",
                  r"\b(numero limitado|limited number|hay \d+ (bastidores|racks))", r"\bcircuitos? por\b|\bper rack\b",
                  r"\b(bastidores|racks)\b"]


def _consumed_fact(clause: str) -> bool:
    """Clauses that only state global facts handled by the global pass (horizon, supply, experiment, strategy...)."""
    return any(re.search(p, clause) for p in _FACT_PATTERNS)
