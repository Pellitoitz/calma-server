"""Real-data validation of Economics 0.9.0. A VALIDATION tool, not engine logic. It never changes Economics.

    python scripts/validation/economic_validation.py validation_studies/economics/<CASE>

Principle: the real data validate the model; the model never corrects the data to validate itself.

Three levels, never mixed (docs/validation/economic_real_data_validation.md):

A) ARITHMETIC REPRODUCTION — SimForge Economics (evaluate_run on an "observed run" whose KPIs are the OBSERVED
   physical drivers) vs the INDEPENDENT REFERENCE CALCULATOR of this file (explicit products/sums written here; it
   never imports simforge.economics). Same drivers, same inputs, same formula -> equality up to float representation.
B) INPUT REPRESENTATIVENESS — the independent calculation (observed drivers x documented inputs) vs the company's
   own reference figure (payroll, invoice, controlling...), with a JUSTIFIED tolerance and concept checks (economic
   concept, included components, period, currency, method). Only an INDEPENDENT_REFERENCE can pass it.
C) END-TO-END REPRESENTATIVENESS — SimForge with SIMULATED physical drivers vs the same reference. Gated by the
   validation status of the simulated drivers and by the mandatory scope question.

A capability is REAL_DATA_VALIDATED only for the capabilities actually exercised, in this case and this period,
never for "Economics" as a whole. Synthetic data never yield REAL_DATA_VALIDATED. Sign-off cannot override a failure.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "1.0"

CAPABILITIES = (
    "LABOR_PAID_TIME", "LABOR_PLANNED_TIME", "LABOR_BUSY_TIME", "MACHINE_TIME_COST", "ENERGY_COST",
    "ENERGY_CONSUMPTION_FROM_DECLARED_POWER", "MATERIAL_COST", "SCRAP_COST", "REPAIR_LABOR_COST", "PM_LABOR_COST",
    "PER_FAILURE_COST", "PER_PM_COST", "DOWNTIME_DECLARED_COST", "REVENUE", "COST_PER_PRODUCED_UNIT",
    "COST_PER_GOOD_UNIT", "ANNUALIZATION", "CAPEX", "SCENARIO_DELTA", "EVALUATED_SAVINGS", "SIMPLE_PAYBACK",
    "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX", "REPLICATION_ECONOMIC_UNCERTAINTY")
UNSUPPORTED_BY_PROTOCOL = {"REPLICATION_ECONOMIC_UNCERTAINTY": "needs several observed periods; not in protocol 1.0"}
CAP_STATUSES = ("REAL_DATA_VALIDATED", "NOT_OBSERVED", "NOT_APPLICABLE", "FAILED", "INCOMPLETE")
SOURCE_TYPES = ("PAYROLL", "HR", "ERP", "ACCOUNTING", "ENERGY_INVOICE", "ENERGY_METER", "MACHINE_COST_RECORD",
                "MAINTENANCE_RECORD", "PURCHASE_ORDER", "QUOTE", "INVOICE", "APPROVED_INVESTMENT", "MATERIAL_PRICE_LIST",
                "PRODUCTION_RECORD", "PRODUCTION_CALENDAR", "OPERATING_PLAN", "MES", "PLC", "ENGINEER_CONFIRMED",
                "SIMFORGE_EXPORT", "OTHER")
EVIDENCE = ("REAL_SOURCE_INPUT", "INDEPENDENT_REFERENCE", "DERIVED_REFERENCE", "ENGINEER_CONFIRMED", "SYNTHETIC")
DRIVER_CLASSES = ("MEASURED", "VALIDATED_MODEL_OUTPUT", "RECONSTRUCTED", "ASSUMED", "MISSING")
DRIVER_OK = ("MEASURED", "VALIDATED_MODEL_OUTPUT")
EVENT_STATUS = ("OBSERVED", "NO_EVENT", "MISSING_DATA")
DIFF_CLASSES = ("ROUNDING", "SOURCE_PRECISION", "PHYSICAL_DRIVER_DIFFERENCE", "ECONOMIC_INPUT_DIFFERENCE",
                "BASIS_DIFFERENCE", "FORMULA_DEFINITION_DIFFERENCE", "PERIOD_DIFFERENCE", "COVERAGE_DIFFERENCE",
                "MISSING_DATA", "MODEL_SCOPE_DIFFERENCE", "POSSIBLE_SOFTWARE_BUG", "UNCLASSIFIED")
NOT_LIKE_FOR_LIKE = ("BASIS_DIFFERENCE", "FORMULA_DEFINITION_DIFFERENCE", "PERIOD_DIFFERENCE", "COVERAGE_DIFFERENCE",
                     "MISSING_DATA", "MODEL_SCOPE_DIFFERENCE")
TOLERANCE_BASES = ("ROUNDING", "SOURCE_PRECISION", "TIME_RESOLUTION", "MONETARY_RESOLUTION", "METHOD")
ANNUALIZATION_SOURCES = ("PRODUCTION_CALENDAR", "OPERATING_PLAN", "PRODUCTION_RECORD", "ERP", "MES")
CATEGORIES = ("labor", "machine", "energy", "energy_power", "material", "scrap", "maintenance", "downtime", "revenue", "capex")
UNIT_OF_BASIS = {"PER_PAID_HOUR": "/h", "PER_PLANNED_HOUR": "/h", "PER_BUSY_HOUR": "/h", "PER_PROCESSING_HOUR": "/h",
                 "PER_SETUP_HOUR": "/h", "PER_OPERATING_HOUR": "/h", "PER_CALENDAR_HOUR": "/h",
                 "PER_CORRECTIVE_DOWNTIME_HOUR": "/h", "PER_KWH": "/kWh", "PER_GOOD_UNIT": "/unit",
                 "PER_SCRAP_UNIT": "/unit", "PER_CONSUMED_UNIT": "/unit", "PER_CYCLE": "/cycle", "PER_FAILURE": "/failure",
                 "PER_PM": "/PM", "FIXED_PER_RUN": "", "FIXED": ""}
# economic concept of a labor REFERENCE -> the only labor basis that represents it
LABOR_CONCEPT_BASIS = {"PAYROLL_COST": "PER_PAID_HOUR", "PLANNED_CAPACITY_COST": "PER_PLANNED_HOUR",
                       "ACTIVITY_COST": "PER_BUSY_HOUR"}  # INCREMENTAL_LABOR_COST etc.: no 0.9 basis -> BASIS_DIFFERENCE
LABOR_CAP_BASIS = {"LABOR_PAID_TIME": "PER_PAID_HOUR", "LABOR_PLANNED_TIME": "PER_PLANNED_HOUR", "LABOR_BUSY_TIME": "PER_BUSY_HOUR"}
REQUIRED_METHOD = {"SIMPLE_PAYBACK": "SIMPLE_PAYBACK", "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX": "ANNUAL_SAVINGS_OVER_INCREMENTAL_CAPEX"}
COMPARISON_CAPS = ("SCENARIO_DELTA", "EVALUATED_SAVINGS", "SIMPLE_PAYBACK", "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX")
CAP_CATEGORIES = {
    "LABOR_PAID_TIME": ("labor",), "LABOR_PLANNED_TIME": ("labor",), "LABOR_BUSY_TIME": ("labor",),
    "MACHINE_TIME_COST": ("machine",), "ENERGY_COST": ("energy", "energy_power"),
    "ENERGY_CONSUMPTION_FROM_DECLARED_POWER": ("energy_power",), "MATERIAL_COST": ("material",), "SCRAP_COST": ("scrap",),
    "REPAIR_LABOR_COST": ("maintenance",), "PM_LABOR_COST": ("maintenance",), "PER_FAILURE_COST": ("maintenance",),
    "PER_PM_COST": ("maintenance",), "DOWNTIME_DECLARED_COST": ("downtime",), "REVENUE": ("revenue",), "CAPEX": ("capex",)}
COST_CATEGORIES = ("labor", "machine", "energy", "material", "scrap", "maintenance", "downtime")
MAINT_CAP = {"REPAIR_LABOR_COST": "REPAIR_LABOR", "PM_LABOR_COST": "PM_LABOR", "PER_FAILURE_COST": "PER_FAILURE",
             "PER_PM_COST": "PER_PM"}
EXACT_REL, EXACT_ABS = 1e-9, 1e-9  # level A: same numbers, same formula -> float representation only
PERSONAL = [re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), re.compile(r"\b[A-Z]{2}\d{2}(?:\s?\w{4}){3,7}\b")]  # e-mail, IBAN
TOTAL_CAPS = ("COST_PER_PRODUCED_UNIT", "COST_PER_GOOD_UNIT", "ANNUALIZATION") + COMPARISON_CAPS


# ------------------------------------------------------------------------------------------------ loading
def _num(x):
    if x is None:
        return None
    x = str(x).strip()
    return None if x == "" else float(x)


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def load_case(d: Path) -> dict:
    i = Path(d) / "input"
    case = yaml.safe_load((i / "case.yaml").read_text(encoding="utf-8")) or {}
    q = case.get("unrepresented_costs")
    if isinstance(q, dict) and isinstance(q.get("answer"), bool):  # YAML 1.1 reads YES / NO as booleans
        q["answer"] = "YES" if q["answer"] else "NO"
    return {"dir": Path(d), "case": case, "sources": _csv(i / "sources.csv"), "inputs": _csv(i / "economic_inputs.csv"),
            "drivers": _csv(i / "physical_drivers.csv"), "references": _csv(i / "references.csv"),
            "classifications": _csv(i / "classifications.csv")}


def scenarios(c: dict) -> dict[str, dict]:
    """name -> physical config. Single-scenario cases use `physical:` (scenario 'baseline')."""
    case = c["case"]
    if case.get("scenarios"):
        return dict(case["scenarios"])
    return {"baseline": case.get("physical") or {}}


def _sc(row) -> str:
    return row.get("scenario") or "baseline"


def _date(x):
    try:
        return dt.date.fromisoformat(str(x)) if x not in (None, "") else None
    except ValueError:
        return "INVALID"


# ------------------------------------------------------------------------------------------------ config checks
def check_config(c: dict) -> tuple[list[str], list[str]]:
    """Structural errors (the study cannot be evaluated) and warnings."""
    case, errors, warns = c["case"], [], []
    for k in ("case_id", "case_name", "data_nature", "company_anonymized", "process_anonymized", "period_start",
              "period_end", "currency", "economic_question", "economic_scope"):
        if case.get(k) in (None, "", []):
            errors.append(f"case.yaml: '{k}' is required")
    if case.get("data_nature") not in ("REAL", "SYNTHETIC_DEMO"):
        errors.append("case.yaml: data_nature must be REAL or SYNTHETIC_DEMO")
    ps, pe = _date(case.get("period_start")), _date(case.get("period_end"))
    if "INVALID" in (ps, pe) or (ps and pe and pe < ps):
        errors.append("case.yaml: invalid period")
    for cap in case.get("economic_scope") or []:
        if cap not in CAPABILITIES:
            errors.append(f"economic_scope: unknown capability {cap}")
    for cap in (case.get("not_applicable") or {}):
        if cap not in CAPABILITIES or not str(case["not_applicable"][cap]).strip():
            errors.append(f"not_applicable.{cap}: unknown capability or empty reason")
    q = case.get("unrepresented_costs") or {}
    if q.get("answer") not in ("YES", "NO", "UNKNOWN"):
        errors.append("case.yaml: unrepresented_costs.answer (YES / NO / UNKNOWN) is mandatory")
    elif q["answer"] == "YES" and not q.get("concepts"):
        errors.append("unrepresented_costs: answer YES needs the list of concepts")
    for name, ph in scenarios(c).items():
        if not ph.get("model"):
            errors.append(f"scenario {name}: physical model file required")
        elif not (c["dir"] / "input" / ph["model"]).exists():
            errors.append(f"scenario {name}: model file {ph['model']} not found")
        if _num(ph.get("window_h")) is None or _num(ph.get("window_h")) <= 0:
            errors.append(f"scenario {name}: window_h (observed period hours) > 0 required")
    src_ids = set()
    for s in c["sources"]:
        sid = s.get("source_id")
        if not sid or sid in src_ids:
            errors.append(f"sources: missing or duplicated source_id {sid!r}")
        src_ids.add(sid)
        if s.get("source_type") not in SOURCE_TYPES:
            errors.append(f"source {sid}: source_type must be one of {SOURCE_TYPES}")
        if s.get("evidence_class") not in EVIDENCE:
            errors.append(f"source {sid}: evidence_class must be one of {EVIDENCE}")
        for k in ("source_reference", "represents", "confirmed_by_role", "extraction_date"):
            if not s.get(k):
                errors.append(f"source {sid}: '{k}' is required (what the source REALLY represents)")
    seen = set()
    for r in c["inputs"]:
        rid = r.get("economic_input_id")
        if not rid or rid in seen:
            errors.append(f"economic_inputs: missing or duplicated id {rid!r}")
        seen.add(rid)
        if r.get("category") not in CATEGORIES:
            errors.append(f"input {rid}: category must be one of {CATEGORIES}")
            continue
        if r.get("source_id") not in src_ids:
            errors.append(f"input {rid}: source_id {r.get('source_id')!r} not registered in sources.csv")
        if _sc(r) not in scenarios(c):
            errors.append(f"input {rid}: unknown scenario {_sc(r)}")
        try:
            v = _num(r.get("value"))
        except ValueError:
            errors.append(f"input {rid}: value must be a number or blank (MISSING)")
            continue
        if v is not None and (not math.isfinite(v) or v < 0):
            errors.append(f"input {rid}: value must be finite and >= 0")
        if r["category"] == "energy_power":
            if r.get("unit") != "kW" or r.get("state") not in ("PROCESSING", "SETUP"):
                errors.append(f"input {rid}: declared power needs unit kW and state PROCESSING | SETUP")
        else:
            if r.get("currency") != case.get("currency"):
                errors.append(f"input {rid}: currency {r.get('currency')} != case currency {case.get('currency')} (no FX)")
            b = r.get("basis")
            if b not in UNIT_OF_BASIS:
                errors.append(f"input {rid}: basis {b!r} is not a 0.9 basis")
            elif r.get("unit") != f"{case.get('currency')}{UNIT_OF_BASIS[b]}":
                errors.append(f"input {rid}: unit {r.get('unit')!r} inconsistent with basis {b} "
                              f"(expected {case.get('currency')}{UNIT_OF_BASIS[b]})")
        if r.get("provenance") not in ("measured", "provided_by_client", "estimated", "assumed", "calculated", "imported"):
            errors.append(f"input {rid}: provenance must be a SimForge provenance status (not 'default')")
        if _num(r.get("precision")) is None:
            errors.append(f"input {rid}: precision (resolution of the value) is required")
        if _date(r.get("effective_date")) in (None, "INVALID"):
            errors.append(f"input {rid}: effective_date required")
    for d in c["drivers"]:
        did = d.get("driver_id")
        if d.get("classification") not in DRIVER_CLASSES:
            errors.append(f"driver {did}: classification must be one of {DRIVER_CLASSES}")
        es = d.get("event_status")
        if es not in EVENT_STATUS:
            errors.append(f"driver {did}: event_status must be one of {EVENT_STATUS}")
        v = d.get("value", "")
        if es == "MISSING_DATA" and v != "":
            errors.append(f"driver {did}: MISSING_DATA must have an empty value (missing is not zero)")
        if es == "NO_EVENT" and _num(v) != 0:
            errors.append(f"driver {did}: NO_EVENT means a record exists and shows 0 events (value 0)")
        if es == "OBSERVED" and v == "":
            errors.append(f"driver {did}: OBSERVED needs a value (use MISSING_DATA otherwise)")
        if d.get("source_id") not in src_ids:
            errors.append(f"driver {did}: source_id not registered")
        if _num(d.get("resolution")) is None:
            errors.append(f"driver {did}: resolution required")
    for r in c["references"]:
        rid = r.get("reference_id")
        if r.get("capability") not in CAPABILITIES:
            errors.append(f"reference {rid}: unknown capability {r.get('capability')}")
        if r.get("source_id") not in src_ids:
            errors.append(f"reference {rid}: source_id not registered")
        if _num(r.get("value")) is None:
            errors.append(f"reference {rid}: value required (a reference without a value is no reference)")
    a = case.get("annualization")
    if a is not None and (_num(a.get("runs_per_year")) is None or a.get("source_id") not in src_ids):
        errors.append("annualization: runs_per_year and a registered source_id are required")
    blob = json.dumps({k: c[k] for k in ("case", "sources", "inputs", "drivers", "references", "classifications")},
                      default=str)
    for p in PERSONAL:
        if p.search(blob):
            errors.append("possible personal / confidential data (e-mail or bank account) in the study: anonymise it")
    return errors, warns


# ------------------------------------------------------------------------------------------------ independent reference calculator
# Deliberately minimal and explicit: products and sums written here. It does not import simforge.economics.
def _model_struct(c: dict, scenario: str) -> dict:
    ph = scenarios(c)[scenario]
    m = yaml.safe_load((c["dir"] / "input" / ph["model"]).read_text(encoding="utf-8"))
    units = {r["id"]: float(r.get("quantity", 1)) for r in m.get("resources", [])}
    slots = {n["id"]: float((n.get("params") or {}).get("capacity", 1) or 1) for n in m.get("nodes", [])}
    return {"units": units, "slots": slots, "window_h": float(ph["window_h"])}


def _drivers(c: dict, scenario: str) -> dict[str, dict]:
    return {d["kpi"]: d for d in c["drivers"] if _sc(d) == scenario}


def _dv(drv: dict, key: str):
    """(value, resolution, row) of an observed driver; value None = MISSING_DATA / not provided."""
    d = drv.get(key)
    if d is None:
        return None, 0.0, None
    return _num(d.get("value")), _num(d.get("resolution")) or 0.0, d


def _qty(row: dict, drv: dict, st: dict) -> tuple[float | None, float, list]:
    """Physical quantity of one input row: (value, resolution bound, drivers used)."""
    cat, b, t, W = row["category"], row.get("basis"), row.get("resource_or_node"), st["window_h"]
    used: list = []

    def get(*keys):
        tot, res = 0.0, 0.0
        for k in keys:
            v, r, d = _dv(drv, k)
            used.append(d or {"kpi": k, "classification": "MISSING", "event_status": "MISSING_DATA"})
            if v is None:
                return None, 0.0
            tot, res = tot + v, res + r
        return tot, res
    if cat == "labor":
        if b == "PER_PAID_HOUR":
            rule = row.get("paid_time")
            if rule == "CALENDAR_WINDOW":
                return W * st["units"][t], 0.0, used
            if rule == "PLANNED_AVAILABLE":
                return (*get(f"resource.{t}.planned_available_h"), used)
            if rule == "DECLARED":
                h = _num(row.get("declared_paid_hours_per_unit"))
                return (None if h is None else h * st["units"][t]), 0.0, used
            return None, 0.0, used
        if b == "PER_PLANNED_HOUR":
            return (*get(f"resource.{t}.planned_available_h"), used)
        if b == "PER_BUSY_HOUR":
            keys = [k for k in (f"resource.{t}.{x}_h" for x in ("working", "walking", "transporting", "outside_planned"))
                    if k in drv]
            return (*get(*(keys or [f"resource.{t}.working_h"])), used)
    if cat == "machine":
        if b == "PER_PROCESSING_HOUR":
            return (*get(f"node.{t}.processing_h"), used)
        if b == "PER_SETUP_HOUR":
            return (*get(f"node.{t}.setup_time_h"), used)
        if b == "PER_OPERATING_HOUR":
            return (*get(f"node.{t}.processing_h", f"node.{t}.setup_time_h"), used)
        if b == "PER_PLANNED_HOUR":
            if f"node.{t}.planned_available_h" in drv:
                return (*get(f"node.{t}.planned_available_h"), used)
            return W * st["slots"][t], 0.0, used
        if b == "PER_CALENDAR_HOUR":
            return W * st["slots"][t], 0.0, used
        if b == "PER_CYCLE":
            return (*get(f"node.{t}.processed"), used)
        if b == "FIXED_PER_RUN":
            return 1.0, 0.0, used
    if cat in ("material", "revenue"):
        p = row.get("product")
        if b == "PER_GOOD_UNIT":
            return (*get(f"product.{p}.completed" if p else "units_completed"), used)
        if b == "PER_CONSUMED_UNIT":
            return (*get("units_completed", "units_scrapped"), used)
    if cat == "scrap":
        return (*get("units_scrapped"), used)
    if cat == "maintenance":
        k = row.get("kind")
        if k == "REPAIR_LABOR":
            return (*get(f"resource.{row.get('resource')}.task_h.{t}#repair"), used)
        if k == "PM_LABOR":
            return (*get(f"resource.{row.get('resource')}.task_h.{t}#pm"), used)
        if k == "PER_FAILURE":
            return (*get(f"node.{t}.failure_count"), used)
        if k == "PER_PM":
            return (*get(f"node.{t}.preventive_maintenance_count"), used)
    if cat == "downtime":
        return (*get(f"node.{t}.corrective_downtime_h"), used)
    return None, 0.0, used


def _kwh(c: dict, scenario: str, node: str, drv: dict, st: dict):
    tot, res, used = 0.0, 0.0, []
    for r in c["inputs"]:
        if _sc(r) == scenario and r["category"] == "energy_power" and r.get("resource_or_node") == node:
            key = f"node.{node}.processing_h" if r["state"] == "PROCESSING" else f"node.{node}.setup_time_h"
            v, rr, d = _dv(drv, key)
            used.append(d or {"kpi": key, "classification": "MISSING", "event_status": "MISSING_DATA"})
            kw = _num(r.get("value"))
            if v is None or kw is None:
                return None, 0.0, used
            tot += kw * v
            res += kw * rr + v * (_num(r.get("precision")) or 0.0)
    return tot, res, used


def reference_lines(c: dict, scenario: str) -> list[dict]:
    """Independent cost / revenue of every input row: value = rate x quantity, with its error bound."""
    st, drv, out = _model_struct(c, scenario), _drivers(c, scenario), []
    for r in c["inputs"]:
        if _sc(r) != scenario or r["category"] in ("energy_power", "capex"):
            continue
        rate, prec = _num(r.get("value")), _num(r.get("precision")) or 0.0
        if r["category"] == "energy":
            for node in sorted({x["resource_or_node"] for x in c["inputs"] if _sc(x) == scenario and x["category"] == "energy_power"}):
                q, qres, used = _kwh(c, scenario, node, drv, st)
                out.append({"row": r, "target": node, "qty": q, "value": None if q is None or rate is None else rate * q,
                            "bound": 0.0 if q is None or rate is None else rate * qres + q * prec, "drivers": used})
            continue
        q, qres, used = _qty(r, drv, st)
        out.append({"row": r, "target": r.get("product") or r.get("resource_or_node") or "run", "qty": q,
                    "value": None if q is None or rate is None else rate * q,
                    "bound": 0.0 if q is None or rate is None else rate * qres + q * prec, "drivers": used})
    return out


def _cap_lines(cap: str, lines: list[dict], target: str | None) -> list[dict]:
    def ok(ln):
        r = ln["row"]
        if cap in LABOR_CAP_BASIS:
            sel = r["category"] == "labor" and r.get("basis") == LABOR_CAP_BASIS[cap]
        elif cap in MAINT_CAP:
            sel = r["category"] == "maintenance" and r.get("kind") == MAINT_CAP[cap]
        elif cap == "MACHINE_TIME_COST":
            sel = r["category"] == "machine"
        elif cap == "ENERGY_COST":
            sel = r["category"] == "energy"
        elif cap == "MATERIAL_COST":
            sel = r["category"] == "material"
        elif cap == "SCRAP_COST":
            sel = r["category"] == "scrap"
        elif cap == "DOWNTIME_DECLARED_COST":
            sel = r["category"] == "downtime"
        elif cap == "REVENUE":
            sel = r["category"] == "revenue"
        else:
            sel = False
        return sel and (target in (None, "", "*") or ln["target"] == target)
    return [ln for ln in lines if ok(ln)]


def _total(lines: list[dict]):
    cost = [ln for ln in lines if ln["row"]["category"] in COST_CATEGORIES]
    if any(ln["value"] is None for ln in cost):
        return None, 0.0
    return sum(ln["value"] for ln in cost), sum(ln["bound"] for ln in cost)


def _capex(c: dict, scenario: str):
    rows = [r for r in c["inputs"] if _sc(r) == scenario and r["category"] == "capex"]
    if not rows or any(_num(r.get("value")) is None for r in rows):
        return None
    return sum(_num(r["value"]) for r in rows)


def reference_value(c: dict, cap: str, scenario: str, target: str | None) -> dict:
    """Independent value of one capability: {value, bound, drivers, inputs, reason}."""
    if cap in COMPARISON_CAPS:
        names = list(scenarios(c))
        if len(names) != 2:
            return {"value": None, "reason": "needs exactly two scenarios (baseline, alternative)"}
        both = [reference_lines(c, s) for s in names]
        allines = both[0] + both[1]
        (tb, bb), (ta, ba) = (_total(x) for x in both)
        if tb is None or ta is None:
            return {"value": None, "reason": "a cost input or driver is MISSING", "lines": allines}
        if cap == "SCENARIO_DELTA":
            return {"value": ta - tb, "bound": ba + bb, "lines": allines}
        if cap == "EVALUATED_SAVINGS":
            return {"value": tb - ta, "bound": ba + bb, "lines": allines}
        a = c["case"].get("annualization") or {}
        n = _num(a.get("runs_per_year"))
        cb, ca = _capex(c, names[0]), _capex(c, names[1])
        if n is None or cb is None or ca is None:
            return {"value": None, "reason": "annualization or CAPEX missing / undeclared (never 0)", "lines": allines}
        inc, sav = ca - cb, (tb - ta) * n
        if inc <= 0:
            return {"value": None, "reason": "incremental CAPEX <= 0: undefined", "lines": allines}
        if cap == "SIMPLE_PAYBACK":
            return {"value": inc / sav if sav > 0 else None, "reason": "" if sav > 0 else "savings <= 0: NOT_REACHED",
                    "lines": allines}
        return {"value": sav / inc, "lines": allines}
    lines = reference_lines(c, scenario)
    if cap in ("COST_PER_PRODUCED_UNIT", "COST_PER_GOOD_UNIT", "ANNUALIZATION"):
        t, b = _total(lines)
        if t is None:
            return {"value": None, "reason": "a cost input or driver is MISSING", "lines": lines}
        drv = _drivers(c, scenario)
        if cap == "ANNUALIZATION":
            n = _num((c["case"].get("annualization") or {}).get("runs_per_year"))
            return {"value": None if n is None else t * n, "bound": 0.0 if n is None else b * n, "lines": lines,
                    "reason": "" if n is not None else "no annualization rule"}
        g, gr, _ = _dv(drv, "units_completed")
        s, sr, _ = _dv(drv, "units_scrapped")
        den, dres = (g, gr) if cap == "COST_PER_GOOD_UNIT" else ((None, 0) if g is None or s is None else (g + s, gr + sr))
        if not den:
            return {"value": None, "reason": "zero or missing denominator: UNDEFINED_METRIC", "lines": lines}
        return {"value": t / den, "bound": b / den + t * dres / den ** 2, "lines": lines}
    if cap == "CAPEX":
        v = _capex(c, scenario)
        return {"value": v, "bound": 0.0, "reason": "" if v is not None else "CAPEX missing / undeclared"}
    if cap == "ENERGY_CONSUMPTION_FROM_DECLARED_POWER":
        q, res, used = _kwh(c, scenario, target, _drivers(c, scenario), _model_struct(c, scenario))
        return {"value": q, "bound": res, "drivers": used, "reason": "" if q is not None else "power or hours MISSING"}
    sel = _cap_lines(cap, lines, target)
    if not sel:
        return {"value": None, "reason": "no input for this capability / target", "lines": sel}
    if any(ln["value"] is None for ln in sel):
        return {"value": None, "reason": "an input value or a physical driver is MISSING", "lines": sel}
    return {"value": sum(ln["value"] for ln in sel), "bound": sum(ln["bound"] for ln in sel), "lines": sel}


# ------------------------------------------------------------------------------------------------ SimForge side
def _simforge():
    sys.path.insert(0, str(ROOT / "src"))
    from simforge.domain.economics import EconomicsSpec
    from simforge.domain.io import load_model
    from simforge.economics import compare_evaluations, evaluate_run
    from simforge.experiments.runner import SimulationResult, run_simulation
    from simforge.library.registry import ComponentRegistry
    from simforge.validation.semantics import verify_model
    return {"EconomicsSpec": EconomicsSpec, "load_model": load_model, "compare_evaluations": compare_evaluations,
            "evaluate_run": evaluate_run, "SimulationResult": SimulationResult, "run_simulation": run_simulation,
            "ComponentRegistry": ComponentRegistry, "verify_model": verify_model}


def economics_spec(c: dict, scenario: str):
    """The 0.9 economic assumptions of one scenario, built 1:1 from economic_inputs.csv (nothing added)."""
    sf = _simforge()
    case, d = c["case"], {"currency": c["case"]["currency"]}

    def money(r):
        return {"value": _num(r.get("value")), "currency": r["currency"], "basis": r["basis"], "reference": r["source_id"],
                "effective_date": r.get("effective_date") or None, "provenance": {"status": r["provenance"], "source": r["source_id"]}}
    for r in c["inputs"]:
        if _sc(r) != scenario:
            continue
        cat, t = r["category"], r.get("resource_or_node")
        if cat == "labor":
            x = {"resource": t, "rate": money(r)}
            if r.get("paid_time"):
                x["paid_time"] = r["paid_time"]
            if _num(r.get("declared_paid_hours_per_unit")) is not None:
                x["declared_paid_hours_per_unit"] = _num(r["declared_paid_hours_per_unit"])
            d.setdefault("labor", []).append(x)
        elif cat in ("machine", "downtime"):
            d.setdefault(cat, []).append({"node": t, "rate": money(r)})
        elif cat == "energy":
            d.setdefault("energy", {})["price"] = money(r)
        elif cat == "energy_power":
            d.setdefault("energy", {}).setdefault("power_kw", {}).setdefault(t, {})[r["state"]] = _num(r["value"])
        elif cat in ("material", "scrap", "revenue"):
            x = {"rate": money(r)}
            if r.get("product"):
                x["product"] = r["product"]
            d.setdefault(cat, []).append(x)
        elif cat == "maintenance":
            x = {"kind": r["kind"], "node": t, "rate": money(r)}
            if r.get("resource"):
                x["resource"] = r["resource"]
            d.setdefault("maintenance", []).append(x)
        elif cat == "capex":
            d.setdefault("capex", []).append({"category": t, "amount": money(r)})
    a = case.get("annualization")
    if a:
        d["annualization"] = {"mode": "REPEAT_RUN", "runs_per_year": _num(a["runs_per_year"])}
    return sf["EconomicsSpec"].model_validate(d)


def observed_run(c: dict, scenario: str):
    """A stored-run object whose KPIs ARE the observed drivers (economics reads only these). processing_h is converted
    to the KPI SimForge stores (utilization = processing_h / (slots x window))."""
    sf = _simforge()
    ph = scenarios(c)[scenario]
    m = sf["load_model"](c["dir"] / "input" / ph["model"])
    _, cm = sf["verify_model"](m, sf["ComponentRegistry"].load_default(None))
    W = float(ph["window_h"])
    k: dict[str, float] = {}
    for key, d in _drivers(c, scenario).items():
        v = _num(d.get("value"))
        if v is None:
            continue  # MISSING_DATA stays absent (never 0)
        if key.endswith(".processing_h"):
            nid = key.split(".")[1]
            slots = int(getattr(cm.nodes[nid].params, "capacity", 1) or 1)
            k[f"node.{nid}.utilization"] = v / (slots * W)
        else:
            k[key] = v
    run = sf["SimulationResult"](
        run_id=f"observed-{c['case']['case_id']}-{scenario}", model_name=m.meta.name, model_hash=m.content_hash(),
        component_versions={}, engine="observed", engine_version="observed", app_version="validation", seeds=[0],
        started_at="observed", wall_time_s=0.0, horizon_s=W * 3600, warmup_s=0.0, kpis={}, per_replication=[k], findings=[])
    return run, m


def simforge_value(ev, cmp, cap: str, target: str | None) -> tuple[float | None, str]:
    """The value SimForge Economics reports for a capability (from an evaluation or a comparison)."""
    if cap in COMPARISON_CAPS:
        if cmp is None:
            return None, "no comparison"
        if cap == "SCENARIO_DELTA":
            return cmp.cost_deltas["evaluated_total_common"].get("mean"), ""
        if cap == "EVALUATED_SAVINGS":
            return cmp.savings.get("mean"), ""
        if cap == "SIMPLE_PAYBACK":
            return cmp.payback.get("years"), cmp.payback.get("status", "")
        r = cmp.annual_return_on_incremental_capex
        return r.get("value"), r.get("status", "")
    if cap in ("COST_PER_PRODUCED_UNIT", "COST_PER_GOOD_UNIT"):
        u = ev.unit_costs[cap.lower()]
        return (u["mean"], "") if isinstance(u, dict) else (None, str(u))
    if cap == "ANNUALIZATION":
        a = ev.annualized
        return (a["evaluated_total_cost"]["mean"], "") if a.get("status") == "AVAILABLE" else (None, a.get("status", ""))
    if cap == "CAPEX":
        k = ev.capex
        return (k["total"], "") if k["status"] == "COMPLETE" else (None, k["status"])
    if cap == "ENERGY_CONSUMPTION_FROM_DECLARED_POWER":
        ln = next((x for x in ev.lines if x.line_id == f"energy.{target}"), None)
        return (ln.quantity["mean"], "") if ln and ln.quantity else (None, "no kWh line")

    def sel(ln):
        if cap in LABOR_CAP_BASIS:
            return ln.category == "labor" and ln.basis == LABOR_CAP_BASIS[cap] and target in (None, "", "*", ln.target)
        if cap in MAINT_CAP:
            kind_basis = {"REPAIR_LABOR": "#repair", "PM_LABOR": "#pm"}
            k = MAINT_CAP[cap]
            if k in kind_basis:
                return ln.category == "maintenance" and ln.target.endswith(kind_basis[k]) and \
                    (target in (None, "", "*") or ln.target.split("@")[1].startswith(f"{target}#"))
            return ln.category == "maintenance" and ln.basis == k and target in (None, "", "*", ln.target)
        cat = {"MACHINE_TIME_COST": "machine", "ENERGY_COST": "energy", "MATERIAL_COST": "material", "SCRAP_COST": "scrap",
               "DOWNTIME_DECLARED_COST": "downtime", "REVENUE": "revenue"}[cap]
        return ln.category == cat and ln.status != "MEMO" and target in (None, "", "*", ln.target)
    lines = [ln for ln in ev.lines if sel(ln)]
    if not lines:
        return None, "no SimForge line"
    bad = [ln for ln in lines if ln.status not in ("INCLUDED", "REVENUE")]
    if bad:
        return None, f"line status {bad[0].status}"
    return sum(ln.value["mean"] for ln in lines), ""


def run_simforge(c: dict, simulated: bool):
    """Evaluations per scenario (+ comparison). simulated=False: observed drivers (level A); True: SimForge DES (level C)."""
    sf = _simforge()
    evs, models = {}, {}
    for name, ph in scenarios(c).items():
        spec = economics_spec(c, name)
        if simulated:
            sim = ph.get("simulated_run")
            if not sim:
                return None
            m = sf["load_model"](c["dir"] / "input" / ph["model"])
            run = sf["run_simulation"](m, sf["ComponentRegistry"].load_default(None), replications=sim.get("replications"),
                                       base_seed=sim.get("base_seed"))
        else:
            run, m = observed_run(c, name)
        evs[name], models[name] = sf["evaluate_run"](run, m, spec), m
    names = list(evs)
    cmp = sf["compare_evaluations"](evs[names[0]], evs[names[1]], models[names[0]], models[names[1]]) if len(names) == 2 else None
    return evs, cmp


# ------------------------------------------------------------------------------------------------ checks
def _sources(c):
    return {s["source_id"]: s for s in c["sources"]}


def _inputs_of(c, cap, scenario):
    cats = CAP_CATEGORIES.get(cap, COST_CATEGORIES if cap in TOTAL_CAPS else ())
    rows = [r for r in c["inputs"] if r["category"] in cats and (cap in COMPARISON_CAPS or _sc(r) == scenario)]
    if cap in LABOR_CAP_BASIS:
        rows = [r for r in rows if r.get("basis") == LABOR_CAP_BASIS[cap]]
    if cap in MAINT_CAP:
        rows = [r for r in rows if r.get("kind") == MAINT_CAP[cap]]
    if cap in COMPARISON_CAPS and cap in ("SIMPLE_PAYBACK", "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX"):
        rows += [r for r in c["inputs"] if r["category"] == "capex"]
    return rows


def evidence_check(c: dict, ref: dict, cap: str) -> tuple[str, list[str]]:
    """INDEPENDENT | DERIVED | CIRCULAR | ENGINEER_CONFIRMED | SYNTHETIC, with reasons."""
    src = _sources(c)
    s = src.get(ref["source_id"], {})
    if s.get("source_type") == "SIMFORGE_EXPORT":
        return "CIRCULAR", ["the reference is a SimForge output: SimForge cannot be validated against itself"]
    if s.get("evidence_class") == "SYNTHETIC":
        return "SYNTHETIC", ["synthetic reference"]
    used = {r["source_id"] for r in _inputs_of(c, cap, _sc(ref))}
    if s.get("evidence_class") == "INDEPENDENT_REFERENCE" and ref["source_id"] in used:
        return "DERIVED", ["the same source provides the inputs AND the reference (real, not independent): arithmetic "
                           "consistency only"]
    if s.get("evidence_class") == "INDEPENDENT_REFERENCE":
        return "INDEPENDENT", []
    if s.get("evidence_class") == "DERIVED_REFERENCE":
        return "DERIVED", ["reference derived from the same data (arithmetic consistency only)"]
    if s.get("evidence_class") == "ENGINEER_CONFIRMED":
        return "ENGINEER_CONFIRMED", ["engineer-confirmed figure, not an independent record"]
    return "DERIVED", [f"source evidence_class {s.get('evidence_class')} is not a reference"]


def concept_check(c: dict, ref: dict, cap: str) -> list[tuple[str, str]]:
    """Definition mismatches (auto-classified, never 'fixed'): [(class, detail)]."""
    out, case = [], c["case"]
    if cap in LABOR_CAP_BASIS:
        concept = ref.get("economic_concept")
        if LABOR_CONCEPT_BASIS.get(concept) != LABOR_CAP_BASIS[cap]:
            out.append(("BASIS_DIFFERENCE", f"reference concept {concept!r} is not represented by {LABOR_CAP_BASIS[cap]} "
                                            "(busy != paid; nothing is reinterpreted)"))
    if cap in REQUIRED_METHOD and ref.get("method") != REQUIRED_METHOD[cap]:
        out.append(("FORMULA_DEFINITION_DIFFERENCE", f"reference method {ref.get('method')!r} != {REQUIRED_METHOD[cap]} "
                                                     "(e.g. discounted payback is not simple payback)"))
    ps, pe = str(ref.get("period_start") or case["period_start"]), str(ref.get("period_end") or case["period_end"])
    if (ps, pe) != (str(case["period_start"]), str(case["period_end"])):
        out.append(("PERIOD_DIFFERENCE", f"reference period {ps}..{pe} != case period"))
    if cap not in ("SIMPLE_PAYBACK", "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX", "ENERGY_CONSUMPTION_FROM_DECLARED_POWER") \
            and ref.get("currency") and ref["currency"] != case["currency"]:
        out.append(("MODEL_SCOPE_DIFFERENCE", "reference currency differs (no FX in 0.9)"))
    inc_ref = {x for x in (ref.get("included_components") or "").split(";") if x}
    if inc_ref:
        inc_in = set()
        for r in _inputs_of(c, cap, _sc(ref)):
            inc_in |= {x for x in (r.get("included_components") or "").split(";") if x}
        if inc_ref - inc_in:
            out.append(("COVERAGE_DIFFERENCE", f"reference includes {sorted(inc_ref - inc_in)} not contained in the inputs"))
    return out


def double_count_risk(c: dict, scenario: str) -> list[str]:
    """Machine rates that already contain a component also valued as its own line."""
    rows = [r for r in c["inputs"] if _sc(r) == scenario]
    cats = {r["category"] for r in rows}
    out = []
    for r in rows:
        if r["category"] == "machine":
            inc = {x for x in (r.get("included_components") or "").split(";") if x}
            for comp, cat in (("energy", "energy"), ("maintenance", "maintenance"), ("labor", "labor")):
                if comp in inc and cat in cats:
                    out.append(f"machine rate {r['economic_input_id']} includes {comp} AND {cat} is valued separately")
    return out


def tolerance_check(ref: dict, derived: float | None) -> tuple[float | None, list[str]]:
    """Justified absolute tolerance or (None, reasons). No universal percentage."""
    errs = []
    basis, reason = ref.get("tolerance_basis"), (ref.get("tolerance_reason") or "").strip()
    abs_t, rel_t = _num(ref.get("absolute_tolerance")), _num(ref.get("relative_tolerance"))
    if rel_t is not None and (basis != "METHOD" or not reason):
        errs.append("relative_tolerance only with tolerance_basis METHOD and an explicit reason")
    if abs_t is None and rel_t is None:
        if derived is None:
            return None, ["no tolerance declared and none derivable from the source resolutions"]
        return derived, []
    if basis not in TOLERANCE_BASES or not reason:
        errs.append(f"tolerance needs tolerance_basis in {TOLERANCE_BASES} and a tolerance_reason")
    if abs_t is not None and derived is not None and basis != "METHOD" and abs_t > derived * (1 + 1e-9) + 1e-12:
        errs.append(f"declared tolerance {abs_t:g} exceeds the bound derived from the resolutions ({derived:g})")
    if errs:
        return None, errs
    tol = abs_t if abs_t is not None else 0.0
    if rel_t is not None:
        tol = max(tol, abs(_num(ref["value"])) * rel_t)
    return tol, []


# ------------------------------------------------------------------------------------------------ evaluation
def evaluate_case(c: dict, regression: dict | None = None) -> dict:
    errors, warns = check_config(c)
    case = c["case"]
    out = {"case_id": case.get("case_id"), "protocol_version": PROTOCOL_VERSION, "config_errors": errors,
           "warnings": warns, "metrics": [], "differences": [], "capabilities": {}, "status": None,
           "regression": {"ok": None}}
    if errors:
        out["status"] = "CONFIG_INVALID"
        out["statement"] = "No validation statement: the study configuration is invalid."
        return out
    synthetic = case["data_nature"] != "REAL" or any(s["evidence_class"] == "SYNTHETIC" for s in c["sources"])
    signed = bool((case.get("signoff") or {}).get("reviewed") and (case.get("signoff") or {}).get("scope_accepted")
                  and (case.get("signoff") or {}).get("role") and (case.get("signoff") or {}).get("date"))
    unrep = case["unrepresented_costs"]["answer"]
    obs = run_simforge(c, simulated=False)
    sim = run_simforge(c, simulated=True)
    sim_drivers_ok = all((ph.get("simulated_run") or {}).get("drivers_validation") == "VALIDATED_MODEL_OUTPUT"
                         for ph in scenarios(c).values())
    cls = {r["difference_id"]: r for r in c["classifications"]}
    src = _sources(c)
    ann = case.get("annualization")

    def diff(did, level, cap, auto_class, detail, material=True):
        r = cls.get(did, {})
        klass = r.get("class") if r.get("class") in DIFF_CLASSES else auto_class
        rec = {"difference_id": did, "level": level, "capability": cap, "class": klass, "auto_class": auto_class,
               "detail": detail, "material": (r.get("material", "yes" if material else "no") or "yes").lower() == "yes",
               "resolved": (r.get("resolved", "no") or "no").lower() == "yes", "explanation": r.get("explanation", "")}
        out["differences"].append(rec)
        return rec

    for ref in c["references"]:
        cap, sc, target = ref["capability"], _sc(ref), ref.get("target") or None
        rid = ref["reference_id"]
        base = {"reference_id": rid, "capability": cap, "scenario": sc, "target": target or "*"}
        if cap in UNSUPPORTED_BY_PROTOCOL:
            out["metrics"].append({**base, "level": "-", "result": "INCOMPLETE", "reason": UNSUPPORTED_BY_PROTOCOL[cap]})
            continue
        indep = reference_value(c, cap, sc, target)
        limits: list[str] = []
        # inputs: MISSING, synthetic, effective date
        for r in _inputs_of(c, cap, sc):
            if _num(r.get("value")) is None:
                limits.append(f"input {r['economic_input_id']} MISSING (never 0)")
            if src[r["source_id"]]["evidence_class"] == "SYNTHETIC":
                limits.append(f"input {r['economic_input_id']} is SYNTHETIC")
            ed = _date(r.get("effective_date"))
            if isinstance(ed, dt.date) and ed > _date(case["period_end"]):
                limits.append(f"input {r['economic_input_id']} effective after the period")
        # physical drivers
        drivers = [d for ln in indep.get("lines") or [] for d in ln["drivers"]] + list(indep.get("drivers") or [])
        for d in drivers:
            if d.get("classification") not in DRIVER_OK:
                limits.append(f"physical driver {d.get('kpi')} is {d.get('classification')} ({d.get('event_status')})")
        if cap in ("ANNUALIZATION", "SIMPLE_PAYBACK", "ANNUAL_RETURN_ON_INCREMENTAL_CAPEX"):
            if not ann or src.get(ann["source_id"], {}).get("source_type") not in ANNUALIZATION_SOURCES:
                limits.append("runs_per_year without a real planning / production source (never inferred)")
        risks = double_count_risk(c, sc) if cap in ("MACHINE_TIME_COST", "ENERGY_COST", "REPAIR_LABOR_COST",
                                                    "PM_LABOR_COST") + TOTAL_CAPS else []
        limits += [f"possible double count: {x}" for x in risks]
        # LEVEL A: SimForge (observed drivers) vs independent calculator
        ev_o = obs[0][sc] if cap not in COMPARISON_CAPS else None
        sf_o, why_o = simforge_value(ev_o, obs[1], cap, target)
        iv = indep.get("value")
        if sf_o is None or iv is None:
            ra = "INCOMPLETE"
            ra_reason = f"SimForge: {why_o or 'n/a'} · reference calc: {indep.get('reason', '')}"
            if sf_o is None and iv is None and (why_o in ("NOT_REACHED", "UNDEFINED_METRIC")):
                ra_reason = f"both undefined ({why_o}) — consistent, nothing to validate numerically"
        else:
            tol_a = EXACT_ABS + EXACT_REL * max(abs(iv), abs(sf_o))
            ra = "PASS" if abs(sf_o - iv) <= tol_a else "FAIL"
            ra_reason = f"|{sf_o:.10g} - {iv:.10g}| <= {tol_a:.3g}" if ra == "PASS" else "arithmetic mismatch"
            if ra == "FAIL":
                diff(f"A:{rid}", "A", cap, "POSSIBLE_SOFTWARE_BUG", f"SimForge {sf_o!r} vs independent {iv!r}")
        out["metrics"].append({**base, "level": "A", "simforge": sf_o, "reference_calc": iv, "reference": None,
                               "tolerance": None, "result": ra, "reason": ra_reason})
        # LEVEL B: independent calculation vs company reference
        evid, evid_why = evidence_check(c, ref, cap)
        concepts = concept_check(c, ref, cap)
        refv = _num(ref["value"])
        derived = None if iv is None or "bound" not in indep else indep["bound"] + (_num(ref.get("reference_precision")) or 0.0) / 2
        tol, tol_err = tolerance_check(ref, derived)  # payback / return: no derivable bound -> a declared, justified one
        if evid == "CIRCULAR":
            rb, rb_reason = "INCOMPLETE", "; ".join(evid_why)
        elif concepts:
            rb, rb_reason = "NOT_COMPARABLE", "; ".join(d for _, d in concepts)
            for k, d in concepts:
                diff(f"B:{rid}:{k}", "B", cap, k, d)
        elif iv is None:
            rb, rb_reason = "INCOMPLETE", indep.get("reason", "")
        elif tol is None:
            rb, rb_reason = "INCOMPLETE", "; ".join(tol_err)
        else:
            rb = "PASS" if abs(iv - refv) <= tol else "FAIL"
            rb_reason = f"|{iv:.6g} - {refv:.6g}| = {abs(iv - refv):.6g} vs tolerance {tol:.6g}"
            if rb == "FAIL":
                diff(f"B:{rid}", "B", cap, "UNCLASSIFIED", f"independent {iv!r} vs reference {refv!r} (tol {tol:g})")
        out["metrics"].append({**base, "level": "B", "simforge": None, "reference_calc": iv, "reference": refv,
                               "tolerance": tol, "evidence": evid, "evidence_notes": evid_why, "result": rb, "reason": rb_reason,
                               "limits": limits})
        # LEVEL C: SimForge with simulated drivers vs company reference
        if sim is None:
            rc, rc_reason, sf_s = "NOT_EXECUTED", "no simulated_run declared", None
        else:
            sf_s, why_s = simforge_value(sim[0][sc] if cap not in COMPARISON_CAPS else None, sim[1], cap, target)
            if not sim_drivers_ok:
                rc, rc_reason = "INCOMPLETE", "simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited)"
            elif unrep == "UNKNOWN":
                rc, rc_reason = "INCOMPLETE", "unrepresented costs UNKNOWN: no end-to-end representativeness claim"
            elif sf_s is None or evid != "INDEPENDENT" or concepts or tol is None:
                rc, rc_reason = "INCOMPLETE", why_s or "reference not independent / not like-for-like / tolerance"
            else:
                rc = "PASS" if abs(sf_s - refv) <= tol else "FAIL"
                rc_reason = f"|{sf_s:.6g} - {refv:.6g}| vs tolerance {tol:.6g}"
                if rc == "FAIL":
                    diff(f"C:{rid}", "C", cap, "PHYSICAL_DRIVER_DIFFERENCE", f"simulated {sf_s!r} vs reference {refv!r}")
        out["metrics"].append({**base, "level": "C", "simforge": sf_s, "reference_calc": None, "reference": refv,
                               "tolerance": tol, "result": rc, "reason": rc_reason})

    # capability matrix
    exercised = {cap for cap in CAPABILITIES if any(_inputs_of(c, cap, s) for s in scenarios(c))
                 and cap not in TOTAL_CAPS + ("ANNUALIZATION",)}
    for cap in CAPABILITIES:
        ms = [m for m in out["metrics"] if m["capability"] == cap]
        reasons: list[str] = []
        ds = [d for d in out["differences"] if d["capability"] == cap]
        if cap in (case.get("not_applicable") or {}):
            status, reasons = "NOT_APPLICABLE", [str(case["not_applicable"][cap])]
        elif cap in UNSUPPORTED_BY_PROTOCOL:
            status = "INCOMPLETE" if ms else "NOT_OBSERVED"
            reasons = [UNSUPPORTED_BY_PROTOCOL[cap]] if ms else ["not exercised by this case"]
        elif not ms:
            requested = cap in exercised or cap in case["economic_scope"] or (cap == "ANNUALIZATION" and ann)
            status = "INCOMPLETE" if requested else "NOT_OBSERVED"
            reasons = ["requested / exercised but no reference result"] if requested else ["not exercised by this case"]
        else:
            a = [m for m in ms if m["level"] == "A"]
            b = [m for m in ms if m["level"] == "B"]
            cc = [m for m in ms if m["level"] == "C"]
            failed = [d for d in ds if d["class"] not in NOT_LIKE_FOR_LIKE] + [d for d in ds if d["material"] and not d["resolved"]]
            if any(m["result"] == "FAIL" for m in ms) and failed:
                status = "FAILED"
                reasons = sorted({f"{d['difference_id']}: {d['class']} — {d['detail']}" for d in failed})
            elif any(m["result"] == "FAIL" for m in ms):
                status = "INCOMPLETE"
                reasons = ["difference beyond tolerance classified as not like-for-like (never PASS)"]
            elif a and b and all(m["result"] == "PASS" for m in a + b):
                if synthetic:
                    status, reasons = "INCOMPLETE", ["synthetic evidence: cannot be REAL_DATA_VALIDATED"]
                elif not signed:
                    status, reasons = "INCOMPLETE", ["no engineer sign-off"]
                elif any(m.get("limits") for m in b):
                    status, reasons = "INCOMPLETE", sorted({x for m in b for x in m["limits"]})
                elif any(m.get("evidence") != "INDEPENDENT" for m in b):
                    status, reasons = "INCOMPLETE", ["reference not independent (arithmetic consistency only)"]
                else:
                    status = "REAL_DATA_VALIDATED"
                    reasons = ["levels A+B" + ("+C" if cc and all(m["result"] == "PASS" for m in cc) else
                                               " (end-to-end C: " + ", ".join(sorted({m["result"] for m in cc})) + ")")]
            else:
                status = "INCOMPLETE"
                reasons = sorted({f"{m['level']}: {m['result']} — {m['reason']}" for m in ms if m["result"] != "PASS"}
                                 | {x for m in b for x in m.get("limits", [])})
        out["capabilities"][cap] = {"status": status, "reasons": reasons}
    # dependencies: a total / comparison metric is never validated on top of a FAILED component, and nothing is
    # validated outside the declared economic_scope
    scope = case["economic_scope"]
    comp_caps = [k for k in CAP_CATEGORIES if k != "CAPEX" and k != "REVENUE" and k != "ENERGY_CONSUMPTION_FROM_DECLARED_POWER"]
    failed_components = [k for k in comp_caps if out["capabilities"][k]["status"] == "FAILED"]
    for k, v in out["capabilities"].items():
        if v["status"] != "REAL_DATA_VALIDATED":
            continue
        if k in TOTAL_CAPS and failed_components:
            v["status"], v["reasons"] = "INCOMPLETE", [f"depends on FAILED component(s) {failed_components}"]
        elif k not in scope:
            v["status"], v["reasons"] = "INCOMPLETE", ["passed, but not in the declared economic_scope (no claim)"]
    st = {k: v["status"] for k, v in out["capabilities"].items()}
    reg = regression if regression is not None else _regression()
    out["regression"] = reg
    if synthetic:
        out["status"] = "SYNTHETIC_DEMO_NOT_A_VALIDATION"
    elif any(st[k] == "FAILED" for k in scope):
        out["status"] = "REAL_DATA_STUDY_FAILED"
    elif not reg["ok"] or not signed or any(st[k] != "REAL_DATA_VALIDATED" for k in scope) or \
            any(d["material"] and not d["resolved"] for d in out["differences"] if d["capability"] in scope):
        out["status"] = "REAL_DATA_STUDY_INCOMPLETE"
    else:
        out["status"] = "REAL_DATA_STUDY_VALID_FOR_SCOPE"
    out["statement"] = statement(c, out)
    return out


def statement(c: dict, out: dict) -> str:
    case = c["case"]
    ok = [k for k, v in out["capabilities"].items() if v["status"] == "REAL_DATA_VALIDATED"]
    not_ok = [k for k in CAPABILITIES if k not in ok]
    bases = sorted({r.get("basis") or r["category"] for r in c["inputs"]
                    if any(r["category"] in CAP_CATEGORIES.get(k, COST_CATEGORIES) for k in ok)})
    q = case["unrepresented_costs"]
    tail = {"YES": f" Costs not represented in the data: {', '.join(q.get('concepts') or [])}.",
            "UNKNOWN": " Unrepresented costs UNKNOWN: no end-to-end representativeness claim.", "NO": ""}[q["answer"]]
    if out["status"] == "SYNTHETIC_DEMO_NOT_A_VALIDATION":
        head = "SYNTHETIC DEMO: no capability is REAL_DATA_VALIDATED (format demonstration only)."
    elif ok:
        head = (f"REAL_DATA_VALIDATED for [{', '.join(ok)}] in case [{case['case_id']}] during "
                f"[{case['period_start']}..{case['period_end']}], using [{', '.join(bases)}].")
    else:
        head = "No capability is REAL_DATA_VALIDATED by this study."
    return f"{head} Not validated by this study: [{', '.join(not_ok)}].{tail}"


def _regression() -> dict:
    """Legacy engine results must stay exactly as before (01-05). Checked and recorded."""
    sf = _simforge()
    from simforge.domain.io import load_model
    expected = {"01_simple_line.yaml": 59, "02_shared_operator.yaml": 359, "03_machine_breakdowns.yaml": 1889.05,
                "04_rework_routing.yaml": 477.5, "05_selective_soldering.yaml": 130}
    reg = sf["ComponentRegistry"].load_default(None)
    got = {f: sf["run_simulation"](load_model(ROOT / "examples" / f), reg).kpis.mean("units_completed") for f in expected}
    return {"ok": all(abs(got[f] - v) < 1e-9 for f, v in expected.items()), "expected": expected, "got": got}


# ------------------------------------------------------------------------------------------------ report
def _w(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r}) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def report(c: dict, out: dict) -> str:
    case = c["case"]
    L = [f"# Economic validation report — {case.get('case_id')}", "",
         f"Protocol {PROTOCOL_VERSION} · status **{out['status']}**", "",
         "> " + out.get("statement", ""), ""]
    if out["config_errors"]:
        return "\n".join(L + ["## Configuration errors", ""] + [f"- {e}" for e in out["config_errors"]]) + "\n"
    q = case["unrepresented_costs"]
    L += ["## A. Case identification", f"- {case['case_name']} · company {case['company_anonymized']} · process "
          f"{case['process_anonymized']} · data_nature {case['data_nature']}", "",
          "## B. Scope", f"- question: {case['economic_question']}", f"- capabilities requested: {case['economic_scope']}",
          f"- unrepresented costs: {q['answer']} {q.get('concepts') or ''}", "",
          "## C. Period", f"- {case['period_start']} .. {case['period_end']} · currency {case['currency']}", "",
          "## D. Physical drivers", "| scenario | kpi | value | resolution | classification | event_status | source |", "|---|---|---|---|---|---|---|"]
    L += [f"| {_sc(d)} | {d['kpi']} | {d['value'] or '—'} | {d['resolution']} | {d['classification']} | {d['event_status']} | {d['source_id']} |"
          for d in c["drivers"]]
    L += ["", "## E. Economic inputs", "| id | scenario | category | target | value | unit | basis | concept | included | source |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['economic_input_id']} | {_sc(r)} | {r['category']} | {r.get('resource_or_node', '')} | {r.get('value') or 'MISSING'} | "
          f"{r.get('unit', '')} | {r.get('basis', '')} | {r.get('economic_concept', '')} | {r.get('included_components', '')} | {r['source_id']} |"
          for r in c["inputs"]]
    L += ["", "## F. Sources", "| id | type | reference (anonymised) | represents | evidence | confirmed by |", "|---|---|---|---|---|---|"]
    L += [f"| {s['source_id']} | {s['source_type']} | {s['source_reference']} | {s['represents']} | {s['evidence_class']} | "
          f"{s['confirmed_by_role']} |" for s in c["sources"]]
    L += ["", "## G. Evidence independence"]
    L += [f"- {m['reference_id']} ({m['capability']}): {m['evidence']} {'; '.join(m['evidence_notes'])}"
          for m in out["metrics"] if m["level"] == "B"]
    L += ["", "## H. Capabilities exercised", "- " + ", ".join(sorted({m["capability"] for m in out["metrics"]})) or "- none"]
    for lvl, title in (("A", "I. Arithmetic reproduction (level A)"), ("B", "J. Input representativeness (level B)"),
                       ("C", "K. End-to-end comparison (level C)")):
        L += ["", f"## {title}", "| ref | capability | scenario | target | SimForge | reference calc | reference | tol | result | reason |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {m['reference_id']} | {m['capability']} | {m['scenario']} | {m['target']} | {m.get('simforge')} | "
              f"{m.get('reference_calc')} | {m.get('reference')} | {m.get('tolerance')} | {m['result']} | {m['reason']} |"
              for m in out["metrics"] if m["level"] == lvl]
    L += ["", "## L. Differences", "| id | level | capability | class | material | resolved | detail |", "|---|---|---|---|---|---|---|"]
    L += [f"| {d['difference_id']} | {d['level']} | {d['capability']} | {d['class']} | {d['material']} | {d['resolved']} | {d['detail']} |"
          for d in out["differences"]]
    L += ["", "## M. Engineer classifications"]
    L += [f"- {r['difference_id']}: {r.get('class')} · {r.get('explanation', '')}" for r in c["classifications"]] or ["- none"]
    L += ["", "## N. Missing data"]
    L += [f"- driver {d['kpi']} ({_sc(d)}): MISSING_DATA" for d in c["drivers"] if d["event_status"] == "MISSING_DATA"]
    L += [f"- input {r['economic_input_id']}: value MISSING" for r in c["inputs"] if _num(r.get("value")) is None]
    L += ["", "## O. Out-of-scope concepts", f"- {', '.join(case.get('out_of_scope') or []) or 'none declared'}",
          f"- semantic gaps: {case.get('semantic_gaps') or 'none declared'}", "",
          "## P. Capability matrix", "| capability | status | reasons |", "|---|---|---|"]
    L += [f"| {k} | {v['status']} | {'; '.join(v['reasons'])} |" for k, v in out["capabilities"].items()]
    s = case.get("signoff") or {}
    L += ["", "## Q. Final scoped statement", "", out["statement"], "",
          f"Engineer sign-off: {s.get('role', '—')} · {s.get('date', '—')} · reviewed {s.get('reviewed')} · scope accepted "
          f"{s.get('scope_accepted')} (sign-off confirms review and scope; it never turns a discrepancy into a PASS).",
          f"Software regression 01–05: {'OK' if out['regression']['ok'] else 'FAILED'}."]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    d = Path(argv[0])
    c = load_case(d)
    out = evaluate_case(c)
    _w(d / "comparison" / "metrics.csv", out["metrics"])
    _w(d / "comparison" / "differences.csv", out["differences"])
    _w(d / "comparison" / "capabilities.csv", [{"capability": k, **v} for k, v in out["capabilities"].items()])
    (d / "comparison" / "summary.json").write_text(json.dumps({k: out[k] for k in ("case_id", "status", "statement",
                                                                                   "config_errors", "regression")},
                                                              indent=2, default=str), encoding="utf-8")
    (d / "VALIDATION_REPORT.md").write_text(report(c, out), encoding="utf-8")
    print(f"{out['status']}\n{out['statement']}")
    return 0 if out["status"] != "CONFIG_INVALID" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
