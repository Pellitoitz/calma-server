"""Real-data validation of the calendar module (engine 0.6.0). A VALIDATION tool, not engine logic.

    python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY>

EXPECTED is computed INDEPENDENTLY from the plant's day-by-day schedule (input/calendar_rows.csv) with its own small
interval arithmetic: it never imports simforge.domain.calendar (the algorithm under test). SIMFORGE is the real engine:
the model the engineer built (input/model.yaml, calendars entered as weekly pattern + exceptions through CLI/UI) is
verified and run, and its timelines, state accounting and calendar transitions are compared with EXPECTED.

Outputs: expected/expected.json, simforge/simforge.json, comparison/{metrics,events,production}.csv, VALIDATION_REPORT.md.
The study can FAIL. Nothing is tuned to make it pass.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

STATUSES = ("NOT_TESTED", "REAL_DATA_TEST_INCOMPLETE", "REAL_DATA_VALIDATION_FAILED", "REAL_DATA_VALIDATED")
ROW_KINDS = {"SHIFT", "OVERTIME", "BREAK", "PLANNED_STOP", "HOLIDAY"}
CLASSES = ("CALENDAR_ERROR", "MODEL_SCOPE_DIFFERENCE", "PROCESS_TIME_DIFFERENCE", "FAILURE_MODEL_DIFFERENCE",
           "UNMODELLED_EVENT", "DATA_QUALITY", "UNKNOWN")
TRANSITION_EVENT = {("off_shift", "available"): "SHIFT_START", ("available", "off_shift"): "SHIFT_END",
                    ("available", "break"): "BREAK_START", ("break", "available"): "BREAK_END",
                    ("break", "off_shift"): "SHIFT_END", ("off_shift", "break"): "SHIFT_START"}
ENGINE_EVENT = {"PAUSE": "paused_by_calendar", "RESUME": "resume_process", "RESTART": "restart_lost_work",
                "OPERATION_END": "end_process", "OPERATION_START": "start_process"}


# ------------------------------------------------------------------ independent interval arithmetic (EXPECTED)
def _union(ivs):
    out = []
    for a, b in sorted(i for i in ivs if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _minus(xs, ys):
    res = []
    for a, b in _union(xs):
        pieces = [(a, b)]
        for c, d in _union(ys):
            pieces = [p for q in pieces for p in ((q[0], min(q[1], c)), (max(q[0], d), q[1])) if p[1] > p[0]] \
                if c < b and d > a else pieces
        res += pieces
    return _union(res)


def _inter(xs, ys):
    return _union([(max(a, c), min(b, d)) for a, b in _union(xs) for c, d in _union(ys) if min(b, d) > max(a, c)])


def _len(ivs):
    return sum(b - a for a, b in _union(ivs))


def _clip(ivs, a, b):
    return _inter(ivs, [(a, b)])


def _hms(text: str) -> dt.timedelta:
    parts = [int(x) for x in text.strip().split(":")]
    h, m, s = (parts + [0, 0])[:3]
    return dt.timedelta(hours=h, minutes=m, seconds=s)


def _el(t0: dt.datetime, x: dt.datetime) -> float:
    """Elapsed seconds. Converted to UTC first: Python subtracts aware datetimes that share a tzinfo as WALL-CLOCK
    times, which would silently lose/gain the DST hour."""
    utc = dt.timezone.utc
    return (x.astimezone(utc) - t0.astimezone(utc)).total_seconds()


def expected_from_rows(rows: list[dict], tz: ZoneInfo, t0: dt.datetime, t1: dt.datetime) -> dict:
    """Per resource: available/break intervals (seconds since t0) from explicit dated rows. A row's end <= start means
    it ends on the next civil day; times are local wall-clock in `tz` (DST-aware, elapsed in UTC)."""
    by_res: dict[str, dict[str, list]] = {}
    for r in rows:
        kind = r["kind"].strip().upper()
        if kind not in ROW_KINDS:
            raise ValueError(f"row kind '{kind}' not in {sorted(ROW_KINDS)}")
        res = by_res.setdefault(r["resource"].strip(), {"work": [], "stop": [], "holidays": []})
        day = dt.date.fromisoformat(r["date"].strip())
        if kind == "HOLIDAY":
            res["holidays"].append(day)
            continue
        start, end = _hms(r["start"]), _hms(r["end"])
        a = dt.datetime.combine(day, dt.time(), tz) + start
        b = dt.datetime.combine(day + dt.timedelta(days=1 if end <= start else 0), dt.time(), tz) + end
        iv = (_el(t0, a), _el(t0, b))
        (res["work"] if kind in ("SHIFT", "OVERTIME") else res["stop"]).append(iv)
    horizon = _el(t0, t1)
    out = {}
    for name, d in by_res.items():
        working = _clip(_union(d["work"]), 0, horizon)
        avail = _minus(working, d["stop"])
        brk = _inter(working, d["stop"])
        out[name] = {"available": avail, "break": brk, "holidays": [str(h) for h in d["holidays"]], "horizon": horizon}
    return out


def expected_events(avail, brk, horizon):
    """Label transitions of the expected partition (available / break / off_shift)."""
    pts = sorted({0.0, horizon, *[x for iv in avail + brk for x in iv]})

    def label(t):
        if any(a <= t < b for a, b in avail):
            return "available"
        return "break" if any(a <= t < b for a, b in brk) else "off_shift"
    ev, prev = [], label(0.0)
    for p in pts[1:-1]:
        cur = label(p)
        if cur != prev:
            ev.append((p, TRANSITION_EVENT[(prev, cur)]))
        prev = cur
    return ev


# --------------------------------------------------------------------------------------------- SIMFORGE side
def simforge_side(model_path: Path, study: dict, window: tuple[float, float]) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from simforge import ENGINE_VERSION
    from simforge.domain.calendar import AVAILABLE, BREAK, OFF_SHIFT
    from simforge.domain.io import load_model
    from simforge.experiments.runner import run_simulation
    from simforge.library.registry import ComponentRegistry
    from simforge.validation.semantics import verify_model
    reg = ComponentRegistry.load_default(None)
    m = load_model(model_path)
    rep, cm = verify_model(m, reg)
    out = {"engine_version": ENGINE_VERSION, "model_hash": m.content_hash(), "issues": [str(i) for i in rep.issues],
           "ok": cm is not None}
    av = getattr(m, "availability", None)
    out["availability_hash"] = av.calendar_hash() if av else None
    if av is not None:
        out["calendar_anchor"] = {"mode": av.mode, "start_date": str(av.start_date) if av.start_date else None,
                                  "start_time": av.start_time, "timezone": av.timezone}
    if cm is None or av is None:
        return out
    seed = int(study.get("seed", m.simulation.base_seed))
    res = run_simulation(m, reg, replications=1, base_seed=seed, trace=True, keep_records=True)
    rec = res.records[0]
    out.update({"seed": seed, "horizon_s": res.horizon_s, "warmup_s": res.warmup_s, "run_id": res.run_id,
                "units_completed": res.kpis.mean("units_completed"), "targets": {}})
    rt = cm.availability
    a, b = window
    events = rec.events or []
    for name, tgt in study["targets"].items():
        kind, tid = next(iter(tgt.items()))
        cid = (rt.resource_calendar if kind == "resource" else rt.node_calendar).get(tid)
        row = {"kind": kind, "id": tid, "calendar": cid}
        if cid is None:
            row["error"] = f"{kind} '{tid}' has no calendar in the model"
            out["targets"][name] = row
            continue
        tl = rt.timelines[cid]
        row.update({"planned_available_s": tl.time_in(AVAILABLE, a, b), "break_s": tl.time_in(BREAK, a, b),
                    "off_shift_s": tl.time_in(OFF_SHIFT, a, b), "calendar_time_s": b - a})
        if kind == "resource" and rec.availability and tid in rec.availability["resources"]:
            r = rec.availability["resources"][tid]
            n = max(1, r["units"])
            row["engine_planned_states_s"] = r["planned_states_s"] / n  # per unit: what the engine actually tracked
            st = rec.resource_state_time.get(tid, {})
            row["working_s"] = sum(v for k, v in st.items() if k.startswith(("working:", "transporting:"))) / n
            row["idle_available_s"] = st.get("idle", 0.0) / n
            row["outside_planned_s"] = sum(v for k, v in st.items() if k.startswith("outside_planned:")) / n
        if kind == "node" and tid in rec.node_state_time:
            st = rec.node_state_time[tid]
            row["paused_by_calendar_s"] = st.get("paused_by_calendar", 0.0)
            row["busy_outside_planned_s"] = st.get("busy_outside_planned", 0.0)
        row["transitions"] = [(e["t"], TRANSITION_EVENT[tuple(e["changed"][cid].split("->"))])
                              for e in events if e["event"] == "calendar" and cid in e.get("changed", {})
                              and tuple(e["changed"][cid].split("->")) in TRANSITION_EVENT]
        if kind == "node":
            row["operation_events"] = [(e["t"], e["event"]) for e in events if e["node"] == tid and e["event"] in ENGINE_EVENT.values()]
        out["targets"][name] = row
    out["completions"] = [d for _, _, d in rec.completions]
    return out


# ------------------------------------------------------------------------------------------------- comparison
def _read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def _write_csv(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r)) or ["empty"]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def run_study(study_dir: Path) -> dict:
    study = yaml.safe_load((study_dir / "input" / "study.yaml").read_text(encoding="utf-8"))
    missing = [k for k in ("study_id", "period_start", "period_end", "timezone", "targets", "calendar_confirmed_by")
               if not study.get(k)]
    rows = _read_csv(study_dir / "input" / "calendar_rows.csv")
    model_path = study_dir / "input" / "model.yaml"
    if not rows:
        missing.append("input/calendar_rows.csv (real day-by-day schedule)")
    if not model_path.exists():
        missing.append("input/model.yaml (SimForge model with the calendar entered by the engineer)")
    result: dict = {"study_id": study.get("study_id"), "synthetic": bool(study.get("synthetic")), "missing": missing}
    if missing:
        result["status"] = "REAL_DATA_TEST_INCOMPLETE" if rows or model_path.exists() else "NOT_TESTED"
        _report(study_dir, study, result)
        return result
    tz = ZoneInfo(study["timezone"])
    t0 = dt.datetime.fromisoformat(str(study["period_start"])).replace(tzinfo=tz)
    t1 = dt.datetime.fromisoformat(str(study["period_end"])).replace(tzinfo=tz)
    warm = float(study.get("warmup_s") or 0)
    horizon = _el(t0, t1)
    window = (warm, horizon)
    exp = expected_from_rows(rows, tz, t0, t1)
    (study_dir / "expected").mkdir(exist_ok=True)
    (study_dir / "expected" / "expected.json").write_text(json.dumps(exp, indent=1), encoding="utf-8")
    sf = simforge_side(model_path, study, window)
    (study_dir / "simforge").mkdir(exist_ok=True)
    (study_dir / "simforge" / "simforge.json").write_text(json.dumps(sf, indent=1, default=str), encoding="utf-8")
    config_errors = []
    if not sf["ok"]:
        config_errors.append("model does not verify: " + "; ".join(i for i in sf["issues"] if i.startswith("ERROR")))
    elif sf.get("horizon_s") != horizon:
        config_errors.append(f"model horizon {sf.get('horizon_s')} s != study period {horizon} s")
    anchor = sf.get("calendar_anchor") or {}
    if sf["ok"] and anchor.get("mode") != "dated":
        config_errors.append("real-data validation needs availability.mode 'dated' (real dates + timezone)")
    elif sf["ok"]:
        m0 = dt.datetime.combine(dt.date.fromisoformat(anchor["start_date"]), dt.time(), ZoneInfo(anchor["timezone"])) \
            + _hms(str(anchor.get("start_time") or "00:00"))
        if anchor["timezone"] != study["timezone"] or _el(t0, m0) != 0:
            config_errors.append(f"model calendar starts {m0.isoformat()} ({anchor['timezone']}) but the study period "
                                 f"starts {t0.isoformat()} ({study['timezone']})")
    metrics, events = [], []
    for name, tgt in (study["targets"] or {}).items():
        e = exp.get(name)
        s = (sf.get("targets") or {}).get(name)
        if e is None:
            config_errors.append(f"target '{name}' has no rows in calendar_rows.csv")
            continue
        if not s or "error" in s:
            config_errors.append((s or {}).get("error", f"target '{name}' not evaluated"))
            continue
        a, b = window
        ex = {"CALENDAR_TIME": b - a, "PLANNED_AVAILABLE_TIME": _len(_clip(e["available"], a, b)),
              "BREAK_TIME": _len(_clip(e["break"], a, b))}
        ex["OFF_SHIFT_TIME"] = ex["CALENDAR_TIME"] - ex["PLANNED_AVAILABLE_TIME"] - ex["BREAK_TIME"]
        got = {"CALENDAR_TIME": s["calendar_time_s"], "PLANNED_AVAILABLE_TIME": s["planned_available_s"],
               "BREAK_TIME": s["break_s"], "OFF_SHIFT_TIME": s["off_shift_s"]}
        for k in ex:
            diff = got[k] - ex[k]
            metrics.append({"target": name, "metric": k, "expected_s": round(ex[k], 3), "simforge_s": round(got[k], 3),
                            "difference_s": round(diff, 3), "status": "PASS" if abs(diff) < 1e-6 else "FAIL",
                            "classification": "" if abs(diff) < 1e-6 else "UNKNOWN"})
        if "engine_planned_states_s" in s:  # the engine's own state accounting must agree with the calendar
            diff = s["engine_planned_states_s"] - ex["PLANNED_AVAILABLE_TIME"]
            metrics.append({"target": name, "metric": "ENGINE_TRACKED_PLANNED_TIME", "expected_s": round(ex["PLANNED_AVAILABLE_TIME"], 3),
                            "simforge_s": round(s["engine_planned_states_s"], 3), "difference_s": round(diff, 3),
                            "status": "PASS" if abs(diff) < 1e-6 else "FAIL", "classification": "" if abs(diff) < 1e-6 else "UNKNOWN"})
        for k in ("working_s", "idle_available_s", "outside_planned_s", "paused_by_calendar_s", "busy_outside_planned_s"):
            if k in s:
                metrics.append({"target": name, "metric": k[:-2].upper() + "_TIME", "expected_s": "", "simforge_s": round(s[k], 3),
                                "difference_s": "", "status": "INFO (DES output, needs observed data)", "classification": ""})
        # structural events: expected transitions vs engine transitions, tolerance 0 s (both are exact definitions)
        exp_ev = [(t, k) for t, k in expected_events(e["available"], e["break"], e["horizon"]) if a <= t < b]
        sf_ev = [(t, k) for t, k in s["transitions"] if a <= t < b]
        for t, k in exp_ev:
            hit = min((x for x in sf_ev if x[1] == k), key=lambda x: abs(x[0] - t), default=None)
            delta = None if hit is None else hit[0] - t
            events.append({"target": name, "source": "PLAN (calendar_rows)", "event": k, "expected": _iso(t0, t),
                           "simforge": _iso(t0, hit[0]) if hit else "—", "delta_s": "" if delta is None else round(delta, 3),
                           "tolerance_s": 0, "status": "PASS" if delta is not None and abs(delta) < 1e-6 else "FAIL",
                           "classification": "" if delta is not None and abs(delta) < 1e-6 else "UNKNOWN"})
        for t, k in sf_ev:
            if not any(abs(t - x) < 1e-6 and k == y for x, y in exp_ev):
                events.append({"target": name, "source": "SIMFORGE only", "event": k, "expected": "—", "simforge": _iso(t0, t),
                               "delta_s": "", "tolerance_s": 0, "status": "FAIL", "classification": "UNKNOWN"})
    # observed real timestamps (PLC/MES/manual): tolerance = the declared precision of each record
    observed = _read_csv(study_dir / "input" / "observed_events.csv")
    for o in observed:
        name, kind = o["resource"].strip(), o["event"].strip().upper()
        s = (sf.get("targets") or {}).get(name) or {}
        ts = dt.datetime.fromisoformat(o["timestamp"].strip())
        ts = ts if ts.tzinfo else ts.replace(tzinfo=tz)
        t = _el(t0, ts)
        prec = float(o.get("precision_s") or 0)
        if kind in ENGINE_EVENT:
            cands = [x for x, ev in s.get("operation_events", []) if ev == ENGINE_EVENT[kind]]
        else:
            cands = [x for x, ev in s.get("transitions", []) if ev == kind]
        hit = min(cands, key=lambda x: abs(x - t), default=None)
        delta = None if hit is None else hit - t
        ok = delta is not None and abs(delta) <= prec + 1e-9
        events.append({"target": name, "source": f"OBSERVED ({o.get('source', '').strip() or 'unspecified'})", "event": kind,
                       "expected": ts.isoformat(), "simforge": _iso(t0, hit) if hit is not None else "—",
                       "delta_s": "" if delta is None else round(delta, 3), "tolerance_s": prec, "status": "PASS" if ok else "FAIL",
                       "classification": "" if ok else "UNKNOWN"})
    # production: secondary evidence only, never a validation criterion
    production = []
    for p in _read_csv(study_dir / "input" / "observed_production.csv"):
        a_ = _el(t0, dt.datetime.fromisoformat(p["from"].strip()).replace(tzinfo=tz))
        b_ = _el(t0, dt.datetime.fromisoformat(p["to"].strip()).replace(tzinfo=tz))
        sim = sum(1 for c in sf.get("completions", []) if a_ < c <= b_)
        production.append({"from": p["from"], "to": p["to"], "observed_units": p["units"], "simforge_units": sim,
                           "difference": sim - float(p["units"]), "classification": "UNKNOWN (secondary evidence)"})
    _write_csv(study_dir / "comparison" / "metrics.csv", metrics)
    _write_csv(study_dir / "comparison" / "events.csv", events)
    _write_csv(study_dir / "comparison" / "production.csv", production)
    regression = _regression()
    struct_fail = [m for m in metrics if m["status"] == "FAIL"] + [e for e in events if e["status"] == "FAIL"]
    policy = study.get("boundary_policy") or {}
    observed_boundary = any(e["event"] in ENGINE_EVENT for e in events if e["source"].startswith("OBSERVED"))
    if study.get("synthetic"):
        status = "NOT_TESTED"  # synthetic examples exercise the tool; they never validate anything with real data
    elif config_errors:
        status = "REAL_DATA_TEST_INCOMPLETE"
    elif struct_fail:
        status = "REAL_DATA_VALIDATION_FAILED"
    elif not (study.get("engineer_sign_off") or {}).get("name") or not regression["ok"]:
        status = "REAL_DATA_TEST_INCOMPLETE"
    else:
        status = "REAL_DATA_VALIDATED"
    result.update({"status": status, "config_errors": config_errors, "metrics": metrics, "events": events,
                   "production": production, "regression": regression, "simforge": {k: sf.get(k) for k in (
                       "engine_version", "model_hash", "availability_hash", "seed", "horizon_s", "warmup_s", "run_id")},
                   "issues": sf.get("issues", []), "observed_events": len(observed),
                   "boundary_policy": policy, "boundary_observed": observed_boundary, "t0": t0.isoformat()})
    _report(study_dir, study, result)
    return result


def _iso(t0: dt.datetime, t: float) -> str:
    return (t0.astimezone(dt.timezone.utc) + dt.timedelta(seconds=t)).astimezone(t0.tzinfo).isoformat()


def _regression() -> dict:
    """Legacy engine results must stay exactly as before (01-05). Checked at validation time and recorded."""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "src"))
    from simforge.domain.io import load_model
    from simforge.experiments.runner import run_simulation
    from simforge.library.registry import ComponentRegistry
    expected = {"01_simple_line.yaml": 59, "02_shared_operator.yaml": 359, "03_machine_breakdowns.yaml": 1889.05,
                "04_rework_routing.yaml": 477.5, "05_selective_soldering.yaml": 130}
    reg = ComponentRegistry.load_default(None)
    got = {f: run_simulation(load_model(root / "examples" / f), reg).kpis.mean("units_completed") for f in expected}
    return {"ok": all(abs(got[f] - v) < 1e-9 for f, v in expected.items()), "expected": expected, "got": got}


# ------------------------------------------------------------------------------------------------------ report
def _h(s) -> str:
    return f"{float(s) / 3600:.3f} h" if s not in ("", None) else "—"


def _report(study_dir: Path, study: dict, r: dict) -> None:
    L = [f"# Real Calendar Validation — {r.get('study_id') or '(sin id)'}", ""]
    if r.get("synthetic"):
        L += ["> **SYNTHETIC EXAMPLE — exercises the validation tool only. It validates NOTHING with real data.**", ""]
    L += [f"**Validation status: `{r['status']}`**", ""]
    if r.get("missing"):
        L += ["Missing inputs (validation cannot run):", ""] + [f"- {m}" for m in r["missing"]] + [""]
        (study_dir / "VALIDATION_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        return
    sf = r["simforge"]
    L += ["## Scope", "", f"Calendar module of SimForge engine {sf['engine_version']} on ONE anonymised case. Production, "
          "utilisation and WIP are secondary evidence; they are never used to declare the calendar validated.", "",
          "## Plant case", "", str(study.get("plant_case", "—")), "",
          "## Period", "", f"{study['period_start']} → {study['period_end']} ({study['timezone']}); warm-up "
          f"{study.get('warmup_s') or 0} s", "",
          "## Input data", "", f"- Schedule rows: input/calendar_rows.csv (source: {study.get('calendar_source', '—')}; "
          f"confirmed by: {study.get('calendar_confirmed_by')}; extracted: {study.get('extraction_date', '—')})",
          f"- Observed timestamps: {r['observed_events']} rows (input/observed_events.csv)",
          f"- Model: input/model.yaml — model_hash `{sf['model_hash']}`, availability_hash `{sf['availability_hash']}`, "
          f"engine {sf['engine_version']}, seed {sf['seed']}, horizon {sf['horizon_s']} s", "",
          "## Real calendar / SimForge calendar", "",
          "Expected availability is computed independently from the day-by-day rows (expected/expected.json); SimForge's "
          "from the engine timelines and state accounting (simforge/simforge.json).", ""]
    if r["config_errors"]:
        L += ["**Configuration errors (fix the inputs, not the engine):**", ""] + [f"- {c}" for c in r["config_errors"]] + [""]
    L += ["## Analytical expected availability vs SimForge availability", "", "| Target | Metric | Expected/Observed | SimForge | Difference | Status |",
          "|---|---|---|---|---|---|"]
    for m in r["metrics"]:
        L.append(f"| {m['target']} | {m['metric']} | {_h(m['expected_s'])} | {_h(m['simforge_s'])} | "
                 f"{m['difference_s'] if m['difference_s'] != '' else '—'} s | {m['status']} |")
    L += ["", "## Event comparison", "", "| Target | Source | Event | Expected | SimForge | Delta (s) | Tolerance (s) | Status |",
          "|---|---|---|---|---|---|---|---|"]
    for e in r["events"]:
        L.append(f"| {e['target']} | {e['source']} | {e['event']} | {e['expected']} | {e['simforge']} | {e['delta_s']} | "
                 f"{e['tolerance_s']} | {e['status']} |")
    L += ["", "## DES results (secondary evidence)", ""]
    if r["production"]:
        L += ["| From | To | Observed units | SimForge units | Difference | Classification |", "|---|---|---|---|---|---|"]
        L += [f"| {p['from']} | {p['to']} | {p['observed_units']} | {p['simforge_units']} | {p['difference']} | {p['classification']} |"
              for p in r["production"]]
    else:
        L.append("No observed production provided.")
    diffs = [m for m in r["metrics"] if m["status"] == "FAIL"] + [e for e in r["events"] if e["status"] == "FAIL"]
    L += ["", "## Differences and root-cause classification", ""]
    if diffs:
        L += [f"Each difference must be classified by the engineer as one of {', '.join(CLASSES)} (comparison/*.csv). "
              "Nothing is tuned to remove it.", ""]
        L += [f"- {d.get('target')}: {d.get('metric') or d.get('event')} — {d.get('classification')}" for d in diffs]
    else:
        L.append("No structural differences.")
    pol = r["boundary_policy"] or {}
    L += ["", "## Boundary behavior observed", "",
          f"Declared policy for `{pol.get('operation', '—')}`: **{pol.get('policy', 'MISSING')}** "
          f"(confirmed by: {pol.get('confirmed_by', '—')}).",
          "Observed in real data: " + ("YES (see OBSERVED PAUSE/RESUME/RESTART/OPERATION_END rows)" if r["boundary_observed"]
                                        else "NO → the boundary policy stays NOT_OBSERVED_IN_REAL_DATA."), "",
          "## Engine regression at validation time", "",
          f"01–05 = {r['regression']['got']} → {'PASS' if r['regression']['ok'] else 'FAIL'}", "",
          "## Validation issues reported by SimForge", ""] + [f"- {i}" for i in r["issues"]] + [""]
    so = study.get("engineer_sign_off") or {}
    L += ["## Limitations", "", "- Valid only for this case, period and calendar; not for the whole plant.",
          "- Contracts not observed in this data keep SYNTHETICALLY_VALIDATED.", "",
          "## Validation status", "", f"`{r['status']}`" + (" (synthetic example)" if r.get("synthetic") else ""), "",
          "## Engineer sign-off", "", f"Name: {so.get('name') or '—'} · Date: {so.get('date') or '—'} · Notes: {so.get('notes') or '—'}", ""]
    (study_dir / "VALIDATION_REPORT.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    out = run_study(Path(sys.argv[1]))
    print(out["status"])
    for c in out.get("missing", []) + out.get("config_errors", []):
        print("  -", c)
