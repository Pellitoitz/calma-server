"""Requirement-by-requirement evaluation of one interpretation run against an explicit GOLD spec.

The evaluator never asks an LLM anything. It reads:
  * the gold spec (benchmarks/llm_semantic/gold/<case>.yaml): roles (process steps with accepted library components)
    and typed requirements;
  * the run outcome: ProcessDraft (as returned by the interpreter), compiled ISMS, questions/assumptions/custom rules.

Statuses: CORRECT WRONG INVENTED OMITTED MISSING_DETECTED AMBIGUITY_DETECTED CONFLICT_DETECTED
          UNSUPPORTED_CORRECTLY_DETECTED NOT_EVALUABLE
Error types: TOPOLOGY_ERROR COMPONENT_MATCH_ERROR PARAMETER_VALUE_ERROR UNIT_ERROR SEMANTIC_BASIS_ERROR
             RESOURCE_ASSIGNMENT_ERROR ROUTING_ERROR CARRIER_SEMANTICS_ERROR STRATEGY_ERROR PROTECTED_STATION_ERROR
             FEEDING_WIP_ERROR MISSING_NOT_DETECTED FALSE_MISSING AMBIGUITY_NOT_DETECTED CONTRADICTION_NOT_DETECTED
             INVENTED_VALUE SILENT_OMISSION UNSUPPORTED_RULE_APPROXIMATED OTHER
Severity: CRITICAL MAJOR MINOR (counted separately; never combined into a weighted score).
Visibility rule used for "detected vs not detected": a QUESTION to the engineer (required or optional) counts as
detection; an ASSUMPTION only makes the error visible (severity MAJOR instead of CRITICAL); nothing = silent.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

POSITIVE = {"CORRECT", "MISSING_DETECTED", "AMBIGUITY_DETECTED", "CONFLICT_DETECTED", "UNSUPPORTED_CORRECTLY_DETECTED"}
METRIC_OF_KIND = {
    "flow": "TOPOLOGY", "component": "COMPONENT_MATCH", "value": "PARAMETER_VALUE", "distribution": "PARAMETER_VALUE",
    "supply": "PARAMETER_VALUE", "basis": "SEMANTIC_BASIS", "shared_resource": "RESOURCE_ASSIGNMENT",
    "no_resource": "RESOURCE_ASSIGNMENT", "carrier": "CARRIER_SEMANTICS", "strategy": "STRATEGY", "routing": "ROUTING",
    "missing": "MISSING_DETECTION", "ambiguity": "AMBIGUITY_DETECTION", "conflict": "CONFLICT_DETECTION",
    "unsupported": "UNSUPPORTED_RULE_DETECTION",
}
# Detection ease for VALID_BUT_WRONG (rule-based, documented in the report; reviewable):
EASE = {"TOPOLOGY_ERROR": "EASY_TO_NOTICE", "COMPONENT_MATCH_ERROR": "EASY_TO_NOTICE", "SILENT_OMISSION": "MODERATE_TO_NOTICE",
        "PARAMETER_VALUE_ERROR": "MODERATE_TO_NOTICE", "RESOURCE_ASSIGNMENT_ERROR": "MODERATE_TO_NOTICE",
        "STRATEGY_ERROR": "MODERATE_TO_NOTICE", "CARRIER_SEMANTICS_ERROR": "MODERATE_TO_NOTICE",
        "ROUTING_ERROR": "MODERATE_TO_NOTICE", "FALSE_MISSING": "EASY_TO_NOTICE",
        "UNIT_ERROR": "HARD_TO_NOTICE", "SEMANTIC_BASIS_ERROR": "HARD_TO_NOTICE", "PROTECTED_STATION_ERROR": "HARD_TO_NOTICE",
        "FEEDING_WIP_ERROR": "HARD_TO_NOTICE", "MISSING_NOT_DETECTED": "HARD_TO_NOTICE",
        "AMBIGUITY_NOT_DETECTED": "HARD_TO_NOTICE", "CONTRADICTION_NOT_DETECTED": "HARD_TO_NOTICE",
        "INVENTED_VALUE": "HARD_TO_NOTICE", "UNSUPPORTED_RULE_APPROXIMATED": "HARD_TO_NOTICE", "OTHER": "MODERATE_TO_NOTICE"}
_REF = re.compile(r"^\$([a-z][a-z0-9_]*)$")
_WORDS = {"un": 1, "una": 1, "uno": 1, "one": 1, "a": None, "dos": 2, "two": 2, "tres": 3, "three": 3, "cuatro": 4, "four": 4,
          "cinco": 5, "five": 5, "seis": 6, "six": 6, "siete": 7, "seven": 7, "ocho": 8, "eight": 8, "nueve": 9, "nine": 9,
          "diez": 10, "ten": 10, "medio": 0.5, "half": 0.5, "mismo": 1, "misma": 1, "same": 1}
_TO_S = {"s": 1, "seg": 1, "sec": 1, "ms": 0.001, "min": 60, "h": 3600}


# ----------------------------------------------------------------------------- helpers
def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def text_numbers(text: str) -> set[float]:
    nums = {float(m.replace(",", ".")) for m in re.findall(r"\d+(?:[.,]\d+)?", text)}
    for w in re.findall(r"[a-z]+", norm(text)):
        if _WORDS.get(w) is not None:
            nums.add(float(_WORDS[w]))
    return nums


def grounded(value: float, unit: str, nums: set[float]) -> bool:
    """A value is grounded if it, or the same quantity in a common unit, appears in the text."""
    variants = {value}
    if unit in ("s", "h", "min"):
        sec = value * _TO_S.get(unit, 1)
        variants |= {sec, sec / 60, sec / 3600, sec * 1000}
    elif unit == "m":
        variants |= {value * 100, value * 1000, value / 1000}
    elif unit == "m/s":
        variants |= {value * 3.6}
    elif unit in ("fraction", ""):
        variants |= {value * 100}
    return any(any(math.isclose(v, n, rel_tol=1e-9, abs_tol=1e-9) for n in nums) for v in variants)


def to_seconds(q: Any) -> float | None:
    """Quantity/constant-distribution dict -> seconds (None if missing)."""
    if q is None:
        return None
    if isinstance(q, (int, float)):
        return float(q)
    v, unit = q.get("value"), q.get("unit", "s")
    if v is None or isinstance(v, str):
        return None
    return float(v) * _TO_S.get(unit, 1)


@dataclass
class Outcome:
    """What the system produced for one input (independent of the interpreter used)."""
    text: str
    schema_valid: bool
    compiles: bool
    verifier_status: str | None
    model: dict | None = None  # ISMS model_dump(mode="json")
    draft: dict | None = None
    questions: list[str] = field(default_factory=list)  # required questions + optional questions + LLM questions + unparsed
    assumptions: list[str] = field(default_factory=list)
    custom_rules: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    error: str | None = None
    llm_questions: list[str] = field(default_factory=list)  # questions written by the interpreter itself


def flag_texts(out: "Outcome") -> list[str]:
    """Texts that explicitly tell the engineer that a STEP or VALUE was not used / needs input: interpreter questions
    and unparsed sentences. Compiler-generated generic questions are excluded, and so are custom rules (they describe
    behaviour, not steps: a rule sentence that happens to contain 'bastidor' does not flag an omitted buffer)."""
    return out.llm_questions + out.unparsed


@dataclass
class ReqResult:
    case: str
    req: str
    kind: str
    metric: str
    description: str
    status: str
    error_type: str | None = None
    severity: str | None = None
    detail: str = ""
    evaluated: bool = True  # False when gold requires engineer review or not evaluable
    unit_sensitive: bool = False


@dataclass
class Evaluation:
    case: str
    results: list[ReqResult]
    grounding: list[dict]
    role_map: dict[str, str | None]
    semantically_correct: bool

    def as_dict(self) -> dict:
        return {"case": self.case, "results": [asdict(r) for r in self.results], "grounding": self.grounding,
                "role_map": self.role_map, "semantically_correct": self.semantically_correct}


# ----------------------------------------------------------------------------- model view
class View:
    def __init__(self, out: Outcome):
        self.out = out
        m = out.model or {}
        self.params = {p["id"]: p for p in m.get("parameters", [])}
        self.nodes = {n["id"]: n for n in m.get("nodes", [])}
        self.resources = {r["id"]: r for r in m.get("resources", [])}
        self.edges = m.get("edges", [])
        self.sim = m.get("simulation", {})
        self.flow = self._flow()

    def _flow(self) -> list[str]:
        """Node ids in flow order (BFS from the source)."""
        succ: dict[str, list[str]] = {}
        for e in self.edges:
            succ.setdefault(e["source"], []).append(e["target"])
        start = next((n for n, x in self.nodes.items() if x["component"] == "source"), None)
        seen, queue = [], [start] if start else []
        while queue:
            n = queue.pop(0)
            if n in seen or n is None:
                continue
            seen.append(n)
            queue += succ.get(n, [])
        return seen

    def r(self, v: Any) -> Any:
        """Resolve '$param' references (None if the parameter has no value)."""
        if isinstance(v, str) and _REF.match(v):
            p = self.params.get(_REF.match(v).group(1))
            return None if p is None else p.get("value")
        if isinstance(v, dict):
            return {k: self.r(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.r(x) for x in v]
        return v

    def pid(self, v: Any) -> str | None:
        if isinstance(v, str) and _REF.match(v):
            return _REF.match(v).group(1)
        if isinstance(v, dict) and isinstance(v.get("value"), str) and _REF.match(v["value"]):
            return _REF.match(v["value"]).group(1)
        return None

    def node_resources(self, nid: str) -> list[str]:
        return [u["resource"] for u in self.nodes[nid].get("params", {}).get("resources", []) or []]

    def operator_of(self, nid: str) -> dict | None:
        for rid in self.node_resources(nid):
            res = self.resources.get(rid)
            if res and res.get("kind") == "operator":
                return res
        return None


def align(gold: dict, v: View) -> tuple[dict[str, str | None], list[str], set[str]]:
    """Map gold roles (in flow order) to model nodes.
    1) strict: next node in flow order whose component is accepted for the role;
    2) loose fallback: a role still unmatched takes the unmatched model step at the same relative position between its
       matched neighbours (same behaviour family: buffer vs non-buffer). Loose matches are WRONG components, but their
       parameters are still evaluated (one error is not counted N times)."""
    steps = [n for n in v.flow if v.nodes[n]["component"] not in ("source", "sink")]
    extra_returns = [n for n in v.nodes if n not in v.flow and v.nodes[n]["component"] not in ("source", "sink")]
    mapping: dict[str, str | None] = {}
    pos = 0
    for role in gold["roles"]:
        hit = None
        for i in range(pos, len(steps)):
            if steps[i] in mapping.values():
                continue
            if v.nodes[steps[i]]["component"] in role["accept"]:
                hit, pos = steps[i], i + 1
                break
        if hit is None:  # out of order? search anywhere (topology will flag the order)
            hit = next((s for s in steps if s not in mapping.values() and v.nodes[s]["component"] in role["accept"]), None)
        mapping[role["role"]] = hit
    loose: set[str] = set()
    names = [r["role"] for r in gold["roles"]]
    for i, role in enumerate(gold["roles"]):
        if mapping[role["role"]] is not None:
            continue
        prev = next((mapping[names[j]] for j in range(i - 1, -1, -1) if mapping[names[j]]), None)
        nxt = next((mapping[names[j]] for j in range(i + 1, len(names)) if mapping[names[j]]), None)
        lo = steps.index(prev) + 1 if prev in steps else 0
        hi = steps.index(nxt) if nxt in steps else len(steps)
        is_buf = role["accept"] == ["buffer"]
        cand = [s for s in steps[lo:hi] if s not in mapping.values() and (v.nodes[s]["component"] == "buffer") == is_buf]
        if cand:
            mapping[role["role"]] = cand[0]
            loose.add(role["role"])
    extra = [s for s in steps + extra_returns if s not in mapping.values()]
    return mapping, extra, loose


def mentions(texts: list[str], keywords: list[str], min_hits: int = 1) -> str | None:
    kws = [norm(k) for k in keywords]
    for t in texts:
        nt = norm(t)
        if sum(1 for k in kws if k in nt) >= min_hits:
            return t
    return None


def mentions_values(texts: list[str], values: list[float]) -> str | None:
    for t in texts:
        nums = text_numbers(t)
        if all(any(math.isclose(v, n) for n in nums) for v in values):
            return t
    return None


# ----------------------------------------------------------------------------- field access
def field_value(spec: dict, v: View, roles: dict[str, str | None]) -> tuple[Any, str | None, str]:
    """Returns (value in the requirement's base unit or raw structure, parameter id, explanation)."""
    target, fld = spec.get("target"), spec.get("field")
    role = spec.get("role")
    if role:
        nid = roles.get(role)
        if nid is None:
            return "NO_NODE", None, f"role '{role}' not found in the model"
        node = v.nodes[nid]
        p = node.get("params", {})
        if fld == "process_time":
            return to_seconds(v.r(p.get("process_time"))), v.pid(p.get("process_time")), nid
        if fld == "work_units":
            return v.r(p.get("work_units", 1)), v.pid(p.get("work_units")), nid
        if fld == "capacity":
            return v.r(p.get("capacity")), v.pid(p.get("capacity")), nid
        if fld in ("load_time", "unload_time"):
            return to_seconds(v.r(p.get(fld))), v.pid(p.get(fld)), nid
        if fld == "yield_rate":
            return v.r(p.get("yield_rate", 1.0)), None, nid
        if fld == "operator_quantity":
            op = v.operator_of(nid)
            return (v.r(op["quantity"]) if op else "NO_OPERATOR"), (v.pid(op["quantity"]) if op else None), nid
        if fld == "distance":  # transport node distance
            return v.r(p.get("distance", {}).get("value") if isinstance(p.get("distance"), dict) else p.get("distance")), \
                v.pid(p.get("distance")), nid
        if fld == "speed":
            op = v.operator_of(nid)
            if op and op.get("travel"):
                return v.r(op["travel"]["speed"]["value"]), v.pid(op["travel"]["speed"]), nid
            sp = p.get("speed")
            return (v.r(sp["value"]) if isinstance(sp, dict) else None), v.pid(sp), nid
    if target == "horizon":
        h = v.sim.get("horizon", {})
        return to_seconds({"value": h.get("value"), "unit": h.get("unit", "h")}), None, "simulation.horizon"
    if target == "items_per_entity":
        pid = next((k for k in v.params if k.endswith("_per_unit")), None)
        return (v.params[pid]["value"] if pid else "NO_PARAM"), pid, pid or "-"
    if target == "carrier_quantity":
        car = next((r for r in v.resources.values() if r.get("kind") == "carrier"), None)
        return (v.r(car["quantity"]) if car else "NO_CARRIER"), (v.pid(car["quantity"]) if car else None), "carrier"
    if target == "wip_target":
        op = next((r for r in v.resources.values() if r.get("wip_target")), None)
        if not op:
            return "NO_STRATEGY", None, "-"
        t = op["wip_target"].get("target")
        return v.r(t), v.pid(t), op["id"]
    if target == "distance":
        a, b = roles.get(spec["between"][0]), roles.get(spec["between"][1])
        if a is None or b is None:
            return "NO_NODE", None, "role missing"
        for r in v.resources.values():
            for d in (r.get("travel") or {}).get("distances", []):
                if {d["a"], d["b"]} == {a, b}:
                    return v.r(d["distance"]["value"]), v.pid(d["distance"]), r["id"]
        for n in v.nodes.values():  # transport with explicit origin/destination
            p = n.get("params", {})
            if {p.get("origin"), p.get("destination")} == {a, b} and p.get("distance") is not None:
                return v.r(p["distance"]["value"]), v.pid(p["distance"]), n["id"]
        return "NO_DISTANCE", None, "no distance between the two roles"
    if target == "walking_speed":
        op = next((r for r in v.resources.values() if r.get("travel")), None)
        if not op:
            return "NO_TRAVEL", None, "-"
        return v.r(op["travel"]["speed"]["value"]), v.pid(op["travel"]["speed"]), op["id"]
    return "UNKNOWN_FIELD", None, f"{target}/{fld}"


# ----------------------------------------------------------------------------- requirement checks
def evaluate(case_id: str, gold: dict, out: Outcome) -> Evaluation:
    results: list[ReqResult] = []
    if not out.schema_valid or not out.compiles or out.model is None:
        for req in gold["requirements"]:
            results.append(ReqResult(case_id, req["id"], req["kind"], METRIC_OF_KIND[req["kind"]], req.get("description", ""),
                                     "NOT_EVALUABLE", "OTHER", None, out.error or "no model produced",
                                     evaluated=False))
        return Evaluation(case_id, results, [], {}, False)
    v = View(out)
    roles, extra, loose = align(gold, v)
    texts_q = out.questions + out.unparsed + out.custom_rules
    for req in gold["requirements"]:
        res = _check(case_id, req, gold, v, roles, extra, out, texts_q, loose)
        if req.get("gold_status") == "GOLD_REQUIRES_ENGINEER_REVIEW":
            res.evaluated = False
            res.detail = "[GOLD_REQUIRES_ENGINEER_REVIEW: not counted] " + res.detail
        results.append(res)
    ground = grounding_scan(out, v)
    for g in ground:  # an ungrounded value presented as USER_PROVIDED is a critical failure (§17)
        if g["verdict"] == "INVENTED":
            results.append(ReqResult(case_id, f"G:{g['parameter']}", "grounding", "INVENTED_DATA",
                                     f"grounding of {g['parameter']}", "INVENTED", "INVENTED_VALUE", "CRITICAL",
                                     f"value {g['value']} {g['unit']} not in the text but marked USER_PROVIDED"))
    ok = all(r.status in POSITIVE for r in results if r.evaluated)
    return Evaluation(case_id, results, ground, {**roles, **{f"{r}(loose)": True for r in loose}}, ok)


def _res(case, req, status, err=None, sev=None, detail=""):
    return ReqResult(case, req["id"], req["kind"], METRIC_OF_KIND[req["kind"]], req.get("description", ""), status,
                     err, sev if status not in POSITIVE else None, detail, unit_sensitive=bool(req.get("unit_sensitive")))


def _visibility(text_hit: str | None, assumption_hit: str | None, silent_sev: str = "CRITICAL") -> str:
    """An error made visible by an assumption is MAJOR; a silent one keeps the requirement's severity."""
    return "MAJOR" if assumption_hit else silent_sev


def _check(case, req, gold, v, roles, extra, out, texts_q, loose=frozenset()) -> ReqResult:
    k = req["kind"]
    sev = req.get("severity", "CRITICAL")
    flags = flag_texts(out)
    if k == "flow":
        want = [r["role"] for r in gold["roles"]]
        got_order = [n for n in v.flow if n in roles.values()]
        expected_order = [roles[r] for r in want if roles[r]]
        missing = [r for r in want if roles[r] is None]
        allowed = set(req.get("allow_extra", []))
        bad_extra = [e for e in extra if v.nodes[e]["component"] not in allowed]
        if not missing and got_order == expected_order and not bad_extra:
            return _res(case, req, "CORRECT", detail=f"steps in order (wrong components counted separately: {sorted(loose)})"
                        if loose else "")
        flagged = [r for r in missing if mentions(flags, gold_role(gold, r).get("keywords", [r]))]
        detail = f"missing roles {missing} (flagged: {flagged}); order {'OK' if got_order == expected_order else 'WRONG'}; " \
                 f"extra nodes {[(e, v.nodes[e]['component']) for e in bad_extra]}"
        return _res(case, req, "WRONG", "TOPOLOGY_ERROR", sev, detail)
    if k == "component":
        nid = roles.get(req["role"])
        role = gold_role(gold, req["role"])
        if nid and req["role"] in loose:
            return _res(case, req, "WRONG", "COMPONENT_MATCH_ERROR", sev,
                        f"step present as '{v.nodes[nid]['component']}' ({nid}); expected one of {role['accept']}")
        if nid:
            return _res(case, req, "CORRECT", detail=f"{nid} = {v.nodes[nid]['component']}")
        hit = mentions(flags, role.get("keywords", [req["role"]]))
        if hit:
            return _res(case, req, "OMITTED", "COMPONENT_MATCH_ERROR", "MAJOR", f"not modelled but flagged: «{hit[:120]}»")
        comps = [v.nodes[e]["component"] for e in extra]
        if comps:
            return _res(case, req, "WRONG", "COMPONENT_MATCH_ERROR", sev, f"no node with {role['accept']}; extra components {comps}")
        return _res(case, req, "OMITTED", "SILENT_OMISSION", "CRITICAL", "step not in the model and not flagged")
    if k in ("value", "missing", "conflict"):
        return _check_value(case, req, gold, v, roles, out, texts_q, sev)
    if k == "basis":
        nid = roles.get(req["role"])
        if nid is None:
            return _res(case, req, "OMITTED", "SILENT_OMISSION", sev, "role not in the model")
        wu, _, _ = field_value({"role": req["role"], "field": "work_units"}, v, roles)
        per_item = isinstance(v.nodes[nid].get("params", {}).get("work_units"), str) or (isinstance(wu, (int, float)) and wu != 1)
        got = "per_item" if per_item else "per_entity"
        if got == req["expect"]:
            return _res(case, req, "CORRECT", detail=f"{got} (work_units={wu})")
        # severity: basis lost but physical time per entity preserved -> MAJOR; physical time changed -> CRITICAL
        pair = next((r for r in gold["requirements"] if r["kind"] == "value" and r.get("role") == req["role"]
                     and r.get("field") == "process_time"), None)
        pt, _, _ = field_value({"role": req["role"], "field": "process_time"}, v, roles)
        preserved = False
        if pair and pt is not None and isinstance(wu, (int, float)):
            exp_entity = float(pair["expect"]) * ((pair.get("items") or 1) if pair.get("per") == "per_item" else 1)
            preserved = math.isclose(float(pt) * float(wu), exp_entity, rel_tol=1e-9)
        return _res(case, req, "WRONG", "SEMANTIC_BASIS_ERROR", "MAJOR" if preserved else "CRITICAL",
                    f"expected {req['expect']}, model {got} (work_units={wu}); time per entity "
                    f"{'preserved' if preserved else 'CHANGED'}")
    if k == "ambiguity":
        nid = roles.get(req["role"])
        hit = mentions(texts_q, req["keywords"], req.get("min_hits", 2))
        if hit:
            return _res(case, req, "AMBIGUITY_DETECTED", detail=f"question: «{hit[:160]}»")
        ass = mentions(out.assumptions, req["keywords"], req.get("min_hits", 2))
        pt, _, _ = field_value({"role": req["role"], "field": "process_time"}, v, roles) if nid else (None, None, None)
        if nid and pt is None:
            q = mentions(texts_q, gold_role(gold, req["role"]).get("keywords", []))
            if q:
                return _res(case, req, "WRONG", "AMBIGUITY_NOT_DETECTED", "MINOR",
                            f"value asked again but the ambiguity itself is not stated: «{q[:120]}»")
        return _res(case, req, "WRONG", "AMBIGUITY_NOT_DETECTED", _visibility(None, ass, sev),
                    ("resolved by a visible assumption: «" + ass[:140] + "»") if ass else "resolved silently")
    if k == "unsupported":
        hit = mentions(out.custom_rules, req["keywords"], req.get("min_hits", 2)) or \
            mentions(out.unparsed + out.questions, req["keywords"], req.get("min_hits", 2))
        if hit:
            return _res(case, req, "UNSUPPORTED_CORRECTLY_DETECTED", detail=f"«{hit[:160]}»")
        approx = [r["id"] + ":" + r.get("dispatch", "") for r in v.resources.values() if r.get("dispatch") in ("wip_target", "priority")]
        if approx and req.get("approximation_check", True):
            return _res(case, req, "WRONG", "UNSUPPORTED_RULE_APPROXIMATED", sev,
                        f"no custom rule / question; existing strategy applied: {approx}")
        return _res(case, req, "OMITTED", "SILENT_OMISSION", sev, "behaviour neither modelled nor flagged")
    if k == "shared_resource":
        ops = []
        for r in req["roles"]:
            nid = roles.get(r)
            op = v.operator_of(nid) if nid else None
            ops.append(op["id"] if op else None)
        if None in ops:
            return _res(case, req, "WRONG", "RESOURCE_ASSIGNMENT_ERROR", sev, f"roles {req['roles']} -> operators {ops}")
        same = len(set(ops)) == 1
        if same == req.get("same", True):
            if req.get("distinct_from"):
                other = [v.operator_of(roles[r])["id"] if roles.get(r) and v.operator_of(roles[r]) else None for r in req["distinct_from"]]
                if any(o in ops for o in other) or None in other:
                    return _res(case, req, "WRONG", "RESOURCE_ASSIGNMENT_ERROR", sev, f"{ops} vs distinct roles {other}")
            return _res(case, req, "CORRECT", detail=str(ops))
        return _res(case, req, "WRONG", "RESOURCE_ASSIGNMENT_ERROR", sev, f"roles {req['roles']} -> operators {ops}")
    if k == "no_resource":
        nid = roles.get(req["role"])
        if nid is None:
            return _res(case, req, "OMITTED", "SILENT_OMISSION", sev, "role missing")
        rs = v.node_resources(nid)
        return _res(case, req, "CORRECT") if not rs else _res(case, req, "WRONG", "RESOURCE_ASSIGNMENT_ERROR", sev,
                                                              f"automatic step uses {rs}")
    if k == "carrier":
        car = next((r for r in v.resources.values() if r.get("kind") == "carrier"), None)
        if not car:
            return _res(case, req, "WRONG", "CARRIER_SEMANTICS_ERROR", sev, "no carrier resource")
        seize = [n for n, x in v.nodes.items() if any(s["resource"] == car["id"] for s in x.get("seize", []))]
        rel = [n for n, x in v.nodes.items() if car["id"] in x.get("release", [])]
        ok = seize == [roles.get(req["seize"])] and rel == [roles.get(req["release"])]
        via = [x.get("release_via") for n, x in v.nodes.items() if x.get("release_via")]
        if req.get("return") == "immediate" and via:
            ok = False
        return _res(case, req, "CORRECT", detail=f"seize {seize} release {rel}") if ok else \
            _res(case, req, "WRONG", "CARRIER_SEMANTICS_ERROR", sev, f"seize {seize}, release {rel}, release_via {via}")
    if k == "strategy":
        nid = roles.get(req["operator_of"])
        op = v.operator_of(nid) if nid else None
        if op is None:
            return _res(case, req, "WRONG", "STRATEGY_ERROR", sev, "no operator found")
        rule = op.get("dispatch")
        if req["rule"] == "unspecified":  # nothing stated: must not invent a rule; FIFO visible or a question
            q = mentions(texts_q + out.assumptions, ["prioridad", "priority", "fifo"])
            if rule == "fifo" and q:
                return _res(case, req, "CORRECT", detail=f"fifo + «{q[:100]}»")
            return _res(case, req, "WRONG", "STRATEGY_ERROR", sev, f"dispatch {rule}; flagged: {bool(q)}")
        if rule != req["rule"]:
            return _res(case, req, "WRONG", "STRATEGY_ERROR", sev, f"expected {req['rule']}, got {rule}")
        if req["rule"] == "wip_target":
            wt = op.get("wip_target") or {}
            if req.get("protected") and wt.get("protected_node") != roles.get(req["protected"]):
                return _res(case, req, "WRONG", "PROTECTED_STATION_ERROR", "CRITICAL",
                            f"protected {wt.get('protected_node')} != {roles.get(req['protected'])}")
            if req.get("feeders") is not None:
                want = sorted(roles.get(r) or f"<{r}>" for r in req["feeders"])
                if sorted(wt.get("feeder_nodes", [])) != want:
                    return _res(case, req, "WRONG", "FEEDING_WIP_ERROR", "CRITICAL", f"feeders {wt.get('feeder_nodes')} != {want}")
        if req["rule"] == "priority" and req.get("order"):
            want = [roles.get(r) for r in req["order"]]
            prio = {n: v.nodes[n].get("priority", 0) for n in want if n}
            if None in want or sorted(want, key=lambda n: prio[n]) != want or len(set(prio.values())) < len(want):
                return _res(case, req, "WRONG", "STRATEGY_ERROR", sev, f"priorities {prio} vs order {want}")
        return _res(case, req, "CORRECT", detail=rule)
    if k == "routing":
        a = roles.get(req["from"])
        if a is None:
            return _res(case, req, "OMITTED", "SILENT_OMISSION", sev, "origin role missing")
        got = {e["target"]: v.r(e.get("probability")) for e in v.edges if e["source"] == a}
        want = {roles.get(t): p for t, p in req["to"].items()}
        if None not in want and got.keys() == want.keys() and all(
                got[t] is not None and math.isclose(float(got[t]), p) for t, p in want.items()):
            return _res(case, req, "CORRECT", detail=str(got))
        hit = mentions(out.custom_rules + out.unparsed + out.questions, req["keywords"], req.get("min_hits", 1))
        if hit:
            return _res(case, req, "UNSUPPORTED_CORRECTLY_DETECTED", detail=f"not representable, flagged: «{hit[:140]}»")
        return _res(case, req, "WRONG", "ROUTING_ERROR", sev, f"edges from {a}: {got}; expected {want}")
    if k == "distribution":
        nid = roles.get(req["role"]) if req.get("role") else next((n for n, x in v.nodes.items() if x["component"] == "source"), None)
        if nid is None:
            return _res(case, req, "OMITTED", "SILENT_OMISSION", sev, "role missing")
        p = v.nodes[nid].get("params", {})
        d = v.r(p.get(req["field"]))
        if not isinstance(d, dict):
            hit = mentions(texts_q, req.get("keywords", []))
            return _res(case, req, "WRONG", "PARAMETER_VALUE_ERROR", "MAJOR" if hit else sev,
                        f"no distribution ({d}); flagged: {bool(hit)}")
        exp = req["expect"]
        unit = _TO_S.get(d.get("unit", "s"), 1)
        ok = d.get("dist") == exp["dist"] and all(
            d.get(key) is not None and math.isclose(float(d[key]) * unit, val) for key, val in exp.items() if key != "dist")
        return _res(case, req, "CORRECT", detail=str(d)) if ok else \
            _res(case, req, "WRONG", "PARAMETER_VALUE_ERROR", sev, f"expected {exp}, got {d}")
    if k == "supply":
        src = next((x for x in v.nodes.values() if x["component"] == "source"), {})
        arr = src.get("params", {}).get("arrival", "infinite")
        return _res(case, req, "CORRECT", detail=arr) if arr == req["expect"] else \
            _res(case, req, "WRONG", "PARAMETER_VALUE_ERROR", sev, f"arrival {arr}")
    return _res(case, req, "NOT_EVALUABLE", "OTHER", None, f"unknown kind {k}")


def gold_role(gold: dict, role: str) -> dict:
    return next((r for r in gold["roles"] if r["role"] == role), {"role": role, "accept": [], "keywords": [role]})


def _check_value(case, req, gold, v, roles, out, texts_q, sev) -> ReqResult:
    k = req["kind"]
    val, pid, where = field_value(req, v, roles)
    prov = (v.params.get(pid) or {}).get("provenance") or {} if pid else {}
    status = prov.get("status")
    kw = req.get("keywords") or (gold_role(gold, req["role"]).get("keywords", []) if req.get("role") else [])
    if k == "conflict" and (isinstance(val, str) or val is None):  # no side taken, but the conflict is not stated either
        q = mentions_values(texts_q, req["values"])
        if q:
            return _res(case, req, "CONFLICT_DETECTED", detail=f"«{q[:160]}»")
        return _res(case, req, "WRONG", "CONTRADICTION_NOT_DETECTED", "MAJOR",
                    f"no value chosen ({val}); asked as missing or not represented, conflict not stated")
    if isinstance(val, str):  # structural absence (no node / no operator / no carrier ...)
        hit = mentions(flag_texts(out) if k != "missing" else texts_q, kw) if kw else None
        if k == "missing" and hit:
            return _res(case, req, "MISSING_DETECTED", detail=f"{val}; question «{hit[:120]}»")
        if hit:  # not represented, but the engineer is told about it
            return _res(case, req, "OMITTED", "PARAMETER_VALUE_ERROR", "MAJOR", f"{val}; flagged «{hit[:100]}»")
        return _res(case, req, "OMITTED", "SILENT_OMISSION", "CRITICAL", f"{val} ({where})")
    if k == "missing":
        if val is None:
            q = mentions(texts_q, kw) if kw else "(parameter without value -> asked by the compiler)"
            return _res(case, req, "MISSING_DETECTED", detail=f"{pid} = None; {('«' + q[:120] + '»') if q else 'asked'}")
        if status == "provided_by_client" and not grounded(float(val), (v.params.get(pid) or {}).get("unit", ""), text_numbers(out.text)):
            return _res(case, req, "INVENTED", "INVENTED_VALUE", "CRITICAL", f"{pid} = {val} presented as USER_PROVIDED")
        ass = mentions(out.assumptions, kw) if kw else None
        return _res(case, req, "WRONG", "MISSING_NOT_DETECTED", "MAJOR" if status in ("assumed", "default") else "CRITICAL",
                    f"{pid} = {val} ({status}); assumption: {bool(ass)}")
    if k == "conflict":
        q = mentions_values(texts_q, req["values"])
        if q:
            return _res(case, req, "CONFLICT_DETECTED", detail=f"«{q[:160]}»")
        ass = mentions_values(out.assumptions, req["values"])
        return _res(case, req, "WRONG", "CONTRADICTION_NOT_DETECTED", _visibility(None, ass, sev),
                    f"model uses {val} ({status}); {'visible assumption' if ass else 'silent choice'}")
    # k == "value"
    exp = float(req["expect"])
    if req.get("field") == "process_time" and val is not None:
        # physical time per ENTITY = written time x work units; the basis is judged by the 'basis' requirement
        wu = v.r(v.nodes[roles[req["role"]]].get("params", {}).get("work_units", 1))
        items = req.get("items") or 1
        exp_entity = exp * (items if req.get("per") == "per_item" else 1)
        if wu is None:
            return _res(case, req, "WRONG", "FALSE_MISSING", "MINOR", f"{pid}={val} but items per entity unknown")
        got_entity = float(val) * float(wu)
        if math.isclose(got_entity, exp_entity, rel_tol=1e-9):
            if status == "assumed":
                return _res(case, req, "WRONG", "OTHER", "MINOR", f"{val} x{wu} correct but downgraded to ASSUMED")
            return _res(case, req, "CORRECT", detail=f"{where}: {val} s x {wu} = {got_entity} s per entity")
        raw = req.get("raw")
        if raw is not None and (math.isclose(float(val), float(raw)) or math.isclose(got_entity, float(raw))):
            return _res(case, req, "WRONG", "UNIT_ERROR", "CRITICAL", f"{val} s: number as written ({raw}) without unit conversion")
        if math.isclose(float(val), exp):
            return _res(case, req, "WRONG", "SEMANTIC_BASIS_ERROR", "CRITICAL",
                        f"{val} s x {wu} = {got_entity} s per entity; expected {exp_entity} ({exp} {req.get('per')}, x{items})")
        return _res(case, req, "WRONG", "PARAMETER_VALUE_ERROR", sev, f"{where}: {val} s x {wu} = {got_entity} != {exp_entity}")
    if val is None:
        hit = mentions(texts_q, kw) if kw else None
        return _res(case, req, "WRONG", "FALSE_MISSING", "MINOR", f"{pid} has no value although the text gives it" +
                    (f"; asked «{hit[:80]}»" if hit else ""))
    val = float(val)
    per_item = req.get("per") == "per_item"
    if math.isclose(val, exp, rel_tol=1e-9, abs_tol=1e-9):
        if status == "assumed" and req.get("text_value", True):
            return _res(case, req, "WRONG", "OTHER", "MINOR", f"{val} correct but downgraded to ASSUMED (grounding false negative)")
        return _res(case, req, "CORRECT", detail=f"{where}: {val}")
    items = req.get("items")
    if items and (math.isclose(val, exp * items) or math.isclose(val, exp / items)):
        wrong_total = not (per_item and math.isclose(val, exp * items))
        return _res(case, req, "WRONG", "SEMANTIC_BASIS_ERROR", "MAJOR" if not wrong_total else "CRITICAL",
                    f"{val} vs expected {exp} per {req.get('per')} (x{items})")
    raw = req.get("raw")
    if raw is not None and math.isclose(val, float(raw)):
        return _res(case, req, "WRONG", "UNIT_ERROR", "CRITICAL", f"{val}: number as written ({raw}) without unit conversion; expected {exp}")
    return _res(case, req, "WRONG", "PARAMETER_VALUE_ERROR", sev, f"{where}: {val} != {exp}")


def grounding_scan(out: Outcome, v: View) -> list[dict]:
    """§17: provenance of every numeric parameter produced."""
    nums = text_numbers(out.text)
    rows = []
    for p in v.params.values():
        if p.get("value") is None:
            rows.append({"parameter": p["id"], "value": None, "unit": p.get("unit"), "status": "MISSING", "grounded": None,
                         "verdict": "OK"})
            continue
        st = ((p.get("provenance") or {}).get("status") or "none").upper()
        g = grounded(float(p["value"]), p.get("unit", ""), nums)
        if st == "PROVIDED_BY_CLIENT":
            verdict = "OK" if g else "INVENTED"
        elif st in ("MEASURED", "IMPORTED"):
            verdict = "WRONG_STATUS"
        else:
            verdict = "OK"
        rows.append({"parameter": p["id"], "value": p["value"], "unit": p.get("unit"),
                     "status": "USER_PROVIDED" if st == "PROVIDED_BY_CLIENT" else st, "grounded": g, "verdict": verdict})
    return rows
