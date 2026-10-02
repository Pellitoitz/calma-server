"""Real-data validation of the calendar module (engine 0.6.0). A VALIDATION tool, not engine logic.

    python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY>

Two questions, never mixed:

A) STRUCTURAL CALENDAR VALIDATION — does SimForge reproduce exactly the calendar it was configured with?
   EXPECTED is computed INDEPENDENTLY from the day-by-day schedule (input/calendar_rows.csv, PLANNED or
   RECONSTRUCTED evidence) with this file's own interval arithmetic; it never imports simforge.domain.calendar.
   SIMFORGE is the real engine running input/model.yaml (calendar entered as weekly pattern + exceptions).
   Tolerance 0 s: both sides are definitions.
B) OPERATIONAL REPRESENTATIVENESS — does that calendar represent what really happened? OBSERVED evidence
   (input/observed_events.csv, input/observed_metrics.csv) is compared with the PLANNED calendar at the declared
   temporal resolution. A first cycle at 06:04 after a 06:00 shift start is not a calendar error.

REAL_DATA_VALIDATED is only ever stated for the capabilities actually exercised, in this case, during this period
(capability coverage + coverage gate). Nothing is tuned to make a study pass.
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
CAP_STATUSES = ("REAL_DATA_VALIDATED", "NOT_OBSERVED_IN_REAL_DATA", "REAL_DATA_VALIDATION_FAILED", "NOT_APPLICABLE")
EVIDENCE_TYPES = ("PLANNED", "OBSERVED", "RECONSTRUCTED")
SOURCE_TYPES = ("PLC", "MES", "ERP", "SHIFT_SHEET", "HR_SCHEDULE", "MANUAL_OBSERVATION", "ENGINEER_CONFIRMATION", "OTHER")
CLOCK_STATUSES = ("CONFIRMED_SYNCED", "KNOWN_OFFSET", "UNKNOWN")
RESOLUTION_S = {"SECOND": 1, "MINUTE": 60, "FIVE_MINUTES": 300, "FIFTEEN_MINUTES": 900, "HOUR": 3600}
ROW_KINDS = {"SHIFT", "OVERTIME", "EXTRA_SHIFT", "BREAK", "PLANNED_STOP", "HOLIDAY", "OFF"}
WORK_KINDS = {"SHIFT", "OVERTIME", "EXTRA_SHIFT"}
CLASSES = ("CALENDAR_ERROR", "MODEL_SCOPE_DIFFERENCE", "PROCESS_TIME_DIFFERENCE", "FAILURE_MODEL_DIFFERENCE",
           "UNMODELLED_EVENT", "DATA_QUALITY", "SOURCE_CLOCK_DIFFERENCE", "UNKNOWN")
CALENDAR_EVENTS = ("SHIFT_START", "SHIFT_END", "BREAK_START", "BREAK_END")
OPERATIONAL_EVENTS = ("FIRST_PROCESS_START", "LAST_PROCESS_END", "FIRST_UNIT_COMPLETED", "LAST_UNIT_COMPLETED",
                      "OPERATION_START", "OPERATION_END", "PAUSE", "RESUME", "RESTART")
END_EVENTS = ("OPERATION_END", "LAST_PROCESS_END", "FIRST_UNIT_COMPLETED", "LAST_UNIT_COMPLETED")
STREAMS = ("observed_events", "observed_metrics", "failures")
TRANSITION_EVENT = {("off_shift", "available"): "SHIFT_START", ("available", "off_shift"): "SHIFT_END",
                    ("available", "break"): "BREAK_START", ("break", "available"): "BREAK_END",
                    ("break", "off_shift"): "SHIFT_END", ("off_shift", "break"): "SHIFT_START"}
SIM_POLICY_EVENT = {"PAUSE_RESUME": "paused_by_calendar", "STOP_RESTART": "restart_lost_work"}
SIM_OP_EVENTS = ("start_process", "end_process", "paused_by_calendar", "resume_process", "restart_lost_work")
POLICIES = ("FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART")
# capability -> where it is validated synthetically (engine 0.6.0 + closure)
CAPABILITIES = {
    "shift_start_end": "test_calendars.py", "breaks": "test_calendars.py", "multiple_shifts": "test_calendars.py",
    "overnight_shift": "test_calendars.py", "holiday": "test_calendars.py", "overtime": "test_calendars.py",
    "extra_shift": "test_calendars.py", "calendar_day": "test_calendars_closure.py (E)",
    "shifts_starting_on_date": "test_calendars_closure.py (E)", "FINISH_CURRENT": "test_calendars.py",
    "PAUSE_RESUME": "test_calendars_closure.py (A-D + preventive)", "STOP_RESTART": "test_calendars_closure.py (I)",
    "DST_spring": "test_calendars_closure.py (F)", "DST_autumn": "test_real_calendar_validation.py (fall DST)",
    "source_calendar": "test_calendars_closure.py (J)", "machine_operator_calendar_intersection": "test_calendars.py",
}


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
    it ends on the next civil day; times are local wall-clock in `tz` (DST-aware, elapsed in UTC). HOLIDAY / OFF rows
    carry no times: they only state that the day is known and not worked."""
    by_res: dict[str, dict] = {}
    for r in rows:
        kind = r["kind"].strip().upper()
        if kind not in ROW_KINDS:
            raise ValueError(f"row kind '{kind}' not in {sorted(ROW_KINDS)}")
        res = by_res.setdefault(r["resource"].strip(), {"work": [], "stop": [], "holidays": [], "rows": []})
        day = dt.date.fromisoformat(r["date"].strip())
        info = {"date": str(day), "kind": kind, "overnight": False}
        res["rows"].append(info)
        if kind in ("HOLIDAY", "OFF"):
            if kind == "HOLIDAY":
                res["holidays"].append(str(day))
            continue
        start, end = _hms(r["start"]), _hms(r["end"])
        info["overnight"] = end <= start
        a = dt.datetime.combine(day, dt.time(), tz) + start
        b = dt.datetime.combine(day + dt.timedelta(days=1 if end <= start else 0), dt.time(), tz) + end
        (res["work"] if kind in WORK_KINDS else res["stop"]).append((_el(t0, a), _el(t0, b)))
    horizon = _el(t0, t1)
    out = {}
    for name, d in by_res.items():
        working = _clip(_union(d["work"]), 0, horizon)
        out[name] = {"available": _minus(working, d["stop"]), "break": _inter(working, d["stop"]),
                     "holidays": d["holidays"], "rows": d["rows"], "horizon": horizon}
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


def dst_transitions(tz: ZoneInfo, t0: dt.datetime, t1: dt.datetime) -> list[tuple[float, str]]:
    """Instants (seconds since t0) where the UTC offset of `tz` changes inside the period: spring (+) / autumn (-)."""
    out, utc = [], dt.timezone.utc
    a, b = t0.astimezone(utc), t1.astimezone(utc)
    t, prev = a, a.astimezone(tz).utcoffset()
    while t < b:
        t += dt.timedelta(minutes=15)
        off = t.astimezone(tz).utcoffset()
        if off != prev:
            out.append(((t - a).total_seconds(), "DST_spring" if off > prev else "DST_autumn"))
            prev = off
    return out


# --------------------------------------------------------------------------------------------- SIMFORGE side
def simforge_side(model_path: Path, study: dict, window: tuple[float, float], days: list[tuple[str, float, float]]) -> dict:
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
    out["node_resources"] = {n.id: [r["resource"] for r in (n.params.get("resources") or [])
                                    if isinstance(r, dict) and "resource" in r] for n in m.nodes}
    out["components"] = {n.id: n.component for n in m.nodes}
    if av is not None:
        out["calendar_anchor"] = {"mode": av.mode, "start_date": str(av.start_date) if av.start_date else None,
                                  "start_time": av.start_time, "timezone": av.timezone}
        out["policies"] = {n: p.at_unavailability for n, p in av.operations.items() if p.at_unavailability}
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
        cal = av.calendar(cid)
        row.update({"planned_available_s": tl.time_in(AVAILABLE, a, b), "break_s": tl.time_in(BREAK, a, b),
                    "off_shift_s": tl.time_in(OFF_SHIFT, a, b), "calendar_time_s": b - a,
                    "daily": {d: {"available": tl.time_in(AVAILABLE, x, y), "break": tl.time_in(BREAK, x, y)} for d, x, y in days},
                    "has_overnight": cal.has_overnight,
                    "non_working_days": [(str(e.date), e.scope) for e in cal.exceptions if e.type == "NON_WORKING_DAY"]})
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
            row["operation_events"] = [(e["t"], e["event"]) for e in events if e["node"] == tid and e["event"] in SIM_OP_EVENTS]
        out["targets"][name] = row
    out["completions"] = [d for _, _, d in rec.completions]
    return out


# ------------------------------------------------------------------------------------------------- helpers
def _read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(fh)
                if any((v or "").strip() for v in r.values())]


def _write_csv(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r)) or ["empty"]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _resolution(text: str) -> float | None:
    t = (text or "").strip().upper()
    if t in RESOLUTION_S:
        return float(RESOLUTION_S[t])
    try:
        return float(t) if float(t) > 0 else None
    except ValueError:
        return None


def _finer_than(seconds_of_day: float, res: float) -> bool:
    """A time carrying more precision than its declared resolution (e.g. 06:00:30 declared at MINUTE)."""
    return res > 1 and abs(seconds_of_day / res - round(seconds_of_day / res)) > 1e-9


def _iso(t0: dt.datetime, t: float) -> str:
    return (t0.astimezone(dt.timezone.utc) + dt.timedelta(seconds=t)).astimezone(t0.tzinfo).isoformat()


def _in(t, ivs, tol=0.0):
    return any(a - tol <= t < b + tol for a, b in ivs)


def _nearest(t, pts):
    return min(pts, key=lambda x: abs(x - t), default=None)


def _dates_between(f, t):
    a, b = dt.date.fromisoformat(str(f)[:10]), dt.date.fromisoformat(str(t)[:10])
    return [str(a + dt.timedelta(days=i)) for i in range((b - a).days + 1)]


# ------------------------------------------------------------------------------------------------- study
def run_study(study_dir: Path) -> dict:
    study = yaml.safe_load((study_dir / "input" / "study.yaml").read_text(encoding="utf-8")) or {}
    missing = [k for k in ("study_id", "period_start", "period_end", "timezone", "targets", "sources") if not study.get(k)]
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
    a, b = window = (warm, horizon)
    days, d = [], t0.date()
    while dt.datetime.combine(d, dt.time(), tz) < t1:
        x = max(a, _el(t0, dt.datetime.combine(d, dt.time(), tz)))
        y = min(b, _el(t0, dt.datetime.combine(d + dt.timedelta(days=1), dt.time(), tz)))
        if y > x:
            days.append((str(d), x, y))
        d += dt.timedelta(days=1)
    config_errors, gate, config_notes = [], [], []

    # ---- sources (evidence strength) and provenance of every calendar row
    sources = study.get("sources") or {}
    for sid, s in sources.items():
        if s.get("source_type") not in SOURCE_TYPES:
            config_errors.append(f"source '{sid}': source_type must be one of {SOURCE_TYPES}")
        if s.get("clock_sync_status") not in CLOCK_STATUSES:
            config_errors.append(f"source '{sid}': clock_sync_status must be one of {CLOCK_STATUSES}")
        if s.get("clock_sync_status") == "KNOWN_OFFSET" and s.get("known_offset_s") in (None, ""):
            config_errors.append(f"source '{sid}': KNOWN_OFFSET requires known_offset_s")
    for i, r in enumerate(rows, start=2):
        if (r.get("evidence_type") or "").upper() not in ("PLANNED", "RECONSTRUCTED"):
            config_errors.append(f"calendar_rows.csv line {i}: evidence_type must be PLANNED or RECONSTRUCTED "
                                 "(OBSERVED times belong in observed_events.csv)")
        src = r.get("source_ref")
        if src not in sources:
            config_errors.append(f"calendar_rows.csv line {i}: source_ref '{src}' is not declared in study.yaml sources")
        elif not sources[src].get("confirmed_by_role"):
            config_errors.append(f"source '{src}': confirmed_by_role is required for calendar data")
        res = _resolution(r.get("temporal_resolution", ""))
        if res is None:
            config_errors.append(f"calendar_rows.csv line {i}: temporal_resolution missing/invalid")
        elif r.get("kind", "").upper() not in ("HOLIDAY", "OFF"):
            for f in ("start", "end"):
                if _finer_than(_hms(r[f]).total_seconds(), res):
                    config_errors.append(f"calendar_rows.csv line {i}: {f} {r[f]} is more precise than its declared "
                                         f"resolution {r['temporal_resolution']} (DATA_QUALITY)")
    kinds_by_day: dict[tuple, set] = {}
    for r in rows:
        kinds_by_day.setdefault((r.get("resource"), r.get("date")), set()).add(r.get("kind", "").upper())
    for (res_, d_), ks in kinds_by_day.items():
        if ks & {"OFF", "HOLIDAY"} and ks & WORK_KINDS:
            config_errors.append(f"calendar_rows.csv: {res_} {d_} is both non-working (OFF/HOLIDAY) and worked (DATA_QUALITY)")
    if study.get("additional_constraints") is None:
        config_errors.append("additional_constraints not answered (use [] only if the plant confirmed there are none)")
    try:
        exp = expected_from_rows(rows, tz, t0, t1)
        ignored = sorted(set(exp) - set(study["targets"]))
        if ignored:  # rows of elements that are not study targets are neither validated nor counted
            config_notes.append(f"calendar rows ignored (not study targets): {', '.join(ignored)}")
        exp = {k: v for k, v in exp.items() if k in study["targets"]}
    except (ValueError, KeyError) as e:
        config_errors.append(f"calendar_rows.csv: {e}")
        exp = {}
    (study_dir / "expected").mkdir(exist_ok=True)
    (study_dir / "expected" / "expected.json").write_text(json.dumps(exp, indent=1), encoding="utf-8")
    sf = simforge_side(model_path, study, window, days)
    (study_dir / "simforge").mkdir(exist_ok=True)
    (study_dir / "simforge" / "simforge.json").write_text(json.dumps(sf, indent=1, default=str), encoding="utf-8")
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

    # ---- data coverage: a day without data is MISSING / NOT_AVAILABLE, never "nothing happened"
    missing_rows = _read_csv(study_dir / "input" / "missing_data.csv")
    coverage = []
    for name in study["targets"]:
        known = {x["date"] for x in exp.get(name, {}).get("rows", [])}
        holes = {x for m_ in missing_rows if m_.get("stream") == "calendar" and m_.get("target") in (name, "*")
                 for x in _dates_between(m_["from"], m_["to"])}
        miss = [x for x, _, _ in days if x not in known or x in holes]
        coverage.append({"stream": "calendar", "target": name, "covered_days": len(days) - len(miss), "days": len(days),
                         "missing": ", ".join(miss) or "—"})
        if miss:
            gate.append(f"calendar of {name}: no rows (or declared MISSING) for {', '.join(miss)} — every day of the "
                        "period needs rows (kind OFF for a known non-working day)")
    streams = study.get("data_streams") or {}
    covered: dict[str, set] = {}
    for st in STREAMS:
        span = streams.get(st) or {}
        span_days = set(_dates_between(span["from"], span["to"])) if span.get("from") and span.get("to") else set()
        holes = {x for m_ in missing_rows if m_.get("stream") == st for x in _dates_between(m_["from"], m_["to"])}
        covered[st] = {x for x, _, _ in days if x in span_days and x not in holes}
        coverage.append({"stream": st, "target": "*", "covered_days": len(covered[st]), "days": len(days),
                         "missing": ", ".join(x for x, _, _ in days if x not in covered[st]) or "—"})

    # ---- A) structural comparison (tolerance 0 s)
    metrics, events, daily = [], [], []
    day_ok: dict[tuple[str, str], bool] = {}
    for name in study["targets"]:
        e, s = exp.get(name), (sf.get("targets") or {}).get(name)
        if e is None:
            config_errors.append(f"target '{name}' has no rows in calendar_rows.csv")
            continue
        if not s or "error" in s:
            config_errors.append((s or {}).get("error", f"target '{name}' not evaluated"))
            continue
        ex = {"CALENDAR_TIME": b - a, "PLANNED_AVAILABLE_TIME": _len(_clip(e["available"], a, b)),
              "BREAK_TIME": _len(_clip(e["break"], a, b))}
        ex["OFF_SHIFT_TIME"] = ex["CALENDAR_TIME"] - ex["PLANNED_AVAILABLE_TIME"] - ex["BREAK_TIME"]
        got = {"CALENDAR_TIME": s["calendar_time_s"], "PLANNED_AVAILABLE_TIME": s["planned_available_s"],
               "BREAK_TIME": s["break_s"], "OFF_SHIFT_TIME": s["off_shift_s"]}
        if "engine_planned_states_s" in s:  # the engine's own state accounting must agree with the calendar
            ex["ENGINE_TRACKED_PLANNED_TIME"] = ex["PLANNED_AVAILABLE_TIME"]
            got["ENGINE_TRACKED_PLANNED_TIME"] = s["engine_planned_states_s"]
        for k in ex:
            diff = got[k] - ex[k]
            metrics.append({"id": f"M:{name}:{k}", "target": name, "metric": k, "expected_s": round(ex[k], 3),
                            "simforge_s": round(got[k], 3), "difference_s": round(diff, 3),
                            "status": "PASS" if abs(diff) < 1e-6 else "FAIL"})
        for dname, x, y in days:
            ea, eb = _len(_clip(e["available"], x, y)), _len(_clip(e["break"], x, y))
            sa, sb = s["daily"][dname]["available"], s["daily"][dname]["break"]
            ok = abs(ea - sa) < 1e-6 and abs(eb - sb) < 1e-6
            day_ok[(name, dname)] = ok
            daily.append({"target": name, "date": dname, "expected_available_s": ea, "simforge_available_s": sa,
                          "expected_break_s": eb, "simforge_break_s": sb, "status": "PASS" if ok else "FAIL"})
        exp_ev = [(t, k) for t, k in expected_events(e["available"], e["break"], e["horizon"]) if a <= t < b]
        sf_ev = [(t, k) for t, k in s["transitions"] if a <= t < b]
        for t, k in exp_ev:
            hit = min((x for x in sf_ev if x[1] == k), key=lambda x: abs(x[0] - t), default=None)
            delta = None if hit is None else hit[0] - t
            ok = delta is not None and abs(delta) < 1e-6
            events.append({"id": f"E:{name}:{k}:{_iso(t0, t)}", "target": name, "event": k, "evidence_type": "PLANNED",
                           "expected": _iso(t0, t), "simforge": _iso(t0, hit[0]) if hit else "—",
                           "delta_s": "" if delta is None else round(delta, 3), "resolution_s": 0,
                           "status": "PASS" if ok else "FAIL"})
            if not ok:
                day_ok[(name, _iso(t0, t)[:10])] = False
        for t, k in sf_ev:
            if not any(abs(t - x) < 1e-6 and k == y for x, y in exp_ev):
                events.append({"id": f"E:{name}:{k}:{_iso(t0, t)}", "target": name, "event": k,
                               "evidence_type": "SIMFORGE only", "expected": "—", "simforge": _iso(t0, t), "delta_s": "",
                               "resolution_s": 0, "status": "FAIL"})
                day_ok[(name, _iso(t0, t)[:10])] = False

    # ---- intersection (structural): a node target only starts/resumes work when it AND its operator targets are available
    tgt_of = {n: next(iter(t.items())) for n, t in study["targets"].items()}
    res_target = {tid: n for n, (k, tid) in tgt_of.items() if k == "resource" and n in exp}
    joint: dict[str, list] = {}
    intersection = {"pairs": [], "violations": [], "joint": joint}
    for n, (k, tid) in tgt_of.items():
        if k != "node" or n not in exp:
            continue
        partners = [res_target[r] for r in sf.get("node_resources", {}).get(tid, []) if r in res_target]
        joint[n] = exp[n]["available"]
        for p in partners:
            joint[n] = _inter(joint[n], exp[p]["available"])
        if not partners:
            continue
        differs = any(_len(_clip(_minus(exp[n]["available"], exp[p]["available"]), a, b)) > 0
                      or _len(_clip(_minus(exp[p]["available"], exp[n]["available"]), a, b)) > 0 for p in partners)
        starts = [t for t, ev in ((sf.get("targets") or {}).get(n) or {}).get("operation_events", [])
                  if ev in ("start_process", "resume_process") and a <= t < b]
        intersection["pairs"].append({"node": n, "resources": partners, "calendars_differ": differs, "starts": len(starts)})
        intersection["violations"] += [f"{n}: SimForge started work at {_iso(t0, t)} outside the joint availability"
                                       for t in starts if not _in(t, joint[n])]

    # ---- B) operational representativeness (observed events vs PLANNED calendar, at declared resolution)
    clock_log, ops, policy_evidence = [], [], {}
    for o in _read_csv(study_dir / "input" / "observed_events.csv"):
        name, kind, sref = o.get("target", ""), o.get("event", "").upper(), o.get("source_ref", "")
        src, res, ev_type = sources.get(sref, {}), _resolution(o.get("temporal_resolution", "")), (o.get("evidence_type") or "").upper()
        raw = dt.datetime.fromisoformat(o["timestamp"])
        raw = raw if raw.tzinfo else raw.replace(tzinfo=tz)
        row = {"id": f"O:{name}:{kind}:{raw.isoformat()}", "target": name, "event": kind, "evidence_type": ev_type or "—",
               "source_ref": sref, "observed": raw.isoformat(), "resolution_s": res}
        if res is None or kind not in CALENDAR_EVENTS + OPERATIONAL_EVENTS or name not in exp or sref not in sources \
                or ev_type not in EVIDENCE_TYPES:
            row.update(status="DATA_QUALITY", detail="unknown target/event/source/evidence_type or resolution")
            ops.append(row)
            continue
        if _finer_than(raw.hour * 3600 + raw.minute * 60 + raw.second, res):
            row.update(status="DATA_QUALITY", detail=f"timestamp more precise than its declared resolution ({res:g} s)")
            ops.append(row)
            continue
        ts, notes = raw, []
        clock = src.get("clock_sync_status", "UNKNOWN")
        if clock == "KNOWN_OFFSET":
            off = float(src.get("known_offset_s") or 0)  # source clock minus reference clock
            if src.get("apply_offset"):
                ts = raw - dt.timedelta(seconds=off)
                clock_log.append({"source_ref": sref, "target": name, "event": kind, "raw": raw.isoformat(),
                                  "corrected": ts.isoformat(), "offset_s": off, "reference": src.get("offset_reference", "—")})
                row["observed"] = f"{ts.isoformat()} (raw {raw.isoformat()}, offset {off:g} s applied)"
            else:
                notes.append(f"known clock offset {off:g} s not applied")
        elif clock != "CONFIRMED_SYNCED":
            notes.append("clock sync UNKNOWN")
        if ev_type != "OBSERVED":
            notes.append(f"evidence {ev_type}")
        if str(ts.astimezone(tz).date()) not in covered["observed_events"]:
            notes.append("day not covered by the declared observed_events stream")
        t = _el(t0, ts)
        avail = joint.get(name, exp[name]["available"])
        ends = [y for _, y in avail if y < horizon]
        starts = [x for x, _ in avail if x > 0]
        if kind in CALENDAR_EVENTS:  # an observed calendar event (e.g. shift log): plan vs actual, not engine
            near = _nearest(t, [x for x, k in expected_events(exp[name]["available"], exp[name]["break"], horizon) if k == kind])
            ok = near is not None and abs(t - near) <= res
            row.update(planned=_iso(t0, near) if near is not None else "—", delta_s=None if near is None else t - near,
                       status="CONSISTENT" if ok else "PLAN_VS_ACTUAL_DIFFERENCE")
        elif kind == "PAUSE":
            near = _nearest(t, ends)
            ok = near is not None and abs(t - near) <= res
            row.update(planned=_iso(t0, near) if near is not None else "—", delta_s=None if near is None else t - near,
                       status="CONSISTENT (pause at a calendar boundary)" if ok else "PLAN_VS_ACTUAL_DIFFERENCE")
        elif kind in ("RESUME", "RESTART"):
            near = _nearest(t, starts)
            ok = near is not None and abs(t - near) <= res
            row.update(planned=_iso(t0, near) if near is not None else "—", delta_s=None if near is None else t - near,
                       status=f"CONSISTENT ({kind.lower()} at availability start)" if ok else "PLAN_VS_ACTUAL_DIFFERENCE")
        else:  # process starts / ends / completions: operational, never compared as calendar events
            prev = max([x for x, _ in avail if x <= t], default=None)
            row.update(planned="inside planned availability" if _in(t, avail, res) else "outside planned availability",
                       delta_s=None if prev is None else t - prev)
            if _in(t, avail, res):
                row["status"] = "CONSISTENT (operational event inside planned availability)"
            elif kind in END_EVENTS:
                row["status"] = "AFTER_BOUNDARY (finished after the calendar boundary)"
                row["_after"] = max([y for y in ends if y <= t], default=None)
            else:
                row["status"] = "PLAN_VS_ACTUAL_DIFFERENCE"
        row["strength"] = "STRONG" if not notes else "WEAK (" + "; ".join(notes) + ")"
        row["_t"], row["_strong"] = t, not notes
        ops.append(row)
    for name in exp:  # boundary behaviour seen in the real data: STRONG evidence only
        mine = sorted((r for r in ops if r["target"] == name and r.get("_strong")), key=lambda r: r["_t"])
        for i, r in enumerate(mine):
            if r["event"] == "PAUSE" and r["status"].startswith("CONSISTENT"):
                nxt = next((x for x in mine[i + 1:] if x["event"] in ("RESUME", "RESTART")), None)
                if nxt and nxt["status"].startswith("CONSISTENT"):
                    policy_evidence.setdefault(name, set()).add("PAUSE_RESUME" if nxt["event"] == "RESUME" else "STOP_RESTART")
            if r.get("_after") is not None:
                bnd = r["_after"]
                started = any(x["event"] in ("OPERATION_START", "FIRST_PROCESS_START") and x["_t"] < bnd for x in mine)
                paused = any(x["event"] == "PAUSE" and bnd - 1e-9 <= x["_t"] <= r["_t"] for x in mine)
                if started and not paused:
                    policy_evidence.setdefault(name, set()).add("FINISH_CURRENT")

    # ---- operational metrics: secondary evidence, no percentage threshold
    op_metrics = []
    for o in _read_csv(study_dir / "input" / "observed_metrics.csv"):
        name, metric = o.get("target", ""), o.get("metric", "").upper()
        fa = _el(t0, dt.datetime.fromisoformat(o["from"]).replace(tzinfo=tz))
        fb = _el(t0, dt.datetime.fromisoformat(o["to"]).replace(tzinfo=tz))
        val = float(o["value"]) * (3600 if o.get("unit", "").lower() == "h" else 1)
        s = (sf.get("targets") or {}).get(name) or {}
        sim = None
        if metric == "UNITS_COMPLETED":
            sim = float(sum(1 for c in sf.get("completions", []) if fa < c <= fb))
        elif metric == "ACTUAL_WORKING_TIME" and abs(fa - a) < 1e-6 and abs(fb - b) < 1e-6:
            sim = s.get("working_s")
        diff = None if sim is None else sim - val
        op_metrics.append({"id": f"P:{name}:{metric}:{o['from']}", "target": name, "metric": metric, "from": o["from"],
                           "to": o["to"], "observed": val, "simforge": sim, "difference": diff,
                           "relative_difference": None if diff is None or val == 0 else round(diff / val, 4),
                           "evidence_type": o.get("evidence_type", ""), "source_ref": o.get("source_ref", "")})

    # ---- differences + engineer classification (UNKNOWN until there is evidence)
    cls = {c["id"]: c for c in _read_csv(study_dir / "input" / "classifications.csv")}

    def classify(item_id):
        c = cls.get(item_id)
        return (c["classification"], c["evidence"]) if c and c.get("classification") in CLASSES and c.get("evidence") \
            else ("UNKNOWN", "")
    differences = []

    def add(kind, item_id, what, fixed=None):
        c, ev = fixed or classify(item_id)
        differences.append({"id": item_id, "kind": kind, "what": what, "classification": c, "evidence": ev})
    for x in [m for m in metrics if m["status"] == "FAIL"] + [e for e in events if e["status"] == "FAIL"]:
        add("STRUCTURAL", x["id"], f"{x['target']}: {x.get('metric') or x.get('event')} {x.get('expected', '')}")
    for v in intersection["violations"]:
        add("STRUCTURAL", "I:" + v, v)
    for r in ops:
        if not r["status"].startswith(("CONSISTENT", "AFTER_BOUNDARY")):
            add("OPERATIONAL", r["id"], f"{r['target']}: {r['event']} {r['observed']} ({r['status']})")
    for p in op_metrics:
        if p["difference"]:
            add("OPERATIONAL", p["id"], f"{p['target']}: {p['metric']} {p['from']} → {p['to']}")
    for c_ in study.get("additional_constraints") or []:
        if not c_.get("modelled"):  # declared plant fact; never compensated by touching the calendar
            add("SCOPE", f"C:{c_.get('constraint')}", f"availability condition not in the model: {c_.get('constraint')}"
                f" — {c_.get('note', '')}", ("MODEL_SCOPE_DIFFERENCE", "declared in study.yaml additional_constraints"))
    for sid, s in sources.items():
        if s.get("clock_sync_status") == "KNOWN_OFFSET":
            add("SOURCE", f"K:{sid}", f"source {sid}: clock offset {s.get('known_offset_s')} s "
                f"({'applied and traced' if s.get('apply_offset') else 'not applied'})",
                ("SOURCE_CLOCK_DIFFERENCE", s.get("offset_reference") or "declared"))

    # ---- capability coverage + status
    caps = _capabilities(study, exp, sf, days, day_ok, tz, t0, t1, intersection, policy_evidence)
    regression = _regression()
    struct_fail = [m for m in metrics if m["status"] == "FAIL"] + [e for e in events if e["status"] == "FAIL"]
    if study.get("synthetic"):
        status = "NOT_TESTED"  # synthetic examples exercise the tool; they never validate anything with real data
    elif config_errors or gate:
        status = "REAL_DATA_TEST_INCOMPLETE"
    elif struct_fail or intersection["violations"] or any(c["real"] == "REAL_DATA_VALIDATION_FAILED" for c in caps):
        status = "REAL_DATA_VALIDATION_FAILED"
    elif not (study.get("engineer_sign_off") or {}).get("name") or not regression["ok"] \
            or not any(c["real"] == "REAL_DATA_VALIDATED" for c in caps):
        status = "REAL_DATA_TEST_INCOMPLETE"
    else:
        status = "REAL_DATA_VALIDATED"
    if status != "REAL_DATA_VALIDATED":  # no capability is real-data validated by a study that is not
        for c in caps:
            if c["real"] == "REAL_DATA_VALIDATED":
                c["real"], c["evidence"] = "NOT_OBSERVED_IN_REAL_DATA", f"exercised, but study is {status}: {c['evidence']}"
    validated = [c["capability"] for c in caps if c["real"] == "REAL_DATA_VALIDATED"]
    scope = (f"REAL_DATA_VALIDATED for capabilities [{', '.join(validated)}] in case {study['study_id']} "
             f"({', '.join(study['targets'])}) during {study['period_start']} → {study['period_end']} ({study['timezone']}). "
             "Not valid for other machines, periods, policies, exceptions or the whole plant.") if validated else None
    unclassified = [x for x in differences if x["kind"] == "OPERATIONAL" and x["classification"] == "UNKNOWN"]
    representativeness = ("NOT_ASSESSED (no observed operation data)" if not ops and not op_metrics else
                          f"DIFFERENCES_TO_CLASSIFY ({len(unclassified)})" if unclassified else "ASSESSED (all differences classified)")
    for x in ops:
        for k in ("_t", "_strong", "_after"):
            x.pop(k, None)
    for fname, data in (("metrics", metrics), ("daily", daily), ("events", events), ("operational_events", ops),
                        ("operational_metrics", op_metrics), ("capabilities", caps), ("differences", differences),
                        ("coverage", coverage), ("clock_corrections", clock_log)):
        _write_csv(study_dir / "comparison" / f"{fname}.csv", data)
    result.update({"status": status, "scope": scope, "validated_capabilities": validated, "capabilities": caps,
                   "config_errors": config_errors, "coverage_gate": gate, "notes": config_notes, "coverage": coverage, "metrics": metrics,
                   "daily": daily, "events": events, "operational_events": ops, "operational_metrics": op_metrics,
                   "differences": differences, "clock_corrections": clock_log, "intersection": intersection,
                   "policy_evidence": {k: sorted(v) for k, v in policy_evidence.items()},
                   "representativeness": representativeness, "regression": regression, "sources": sources,
                   "simforge": {k: sf.get(k) for k in ("engine_version", "model_hash", "availability_hash", "seed",
                                                       "horizon_s", "warmup_s", "run_id")},
                   "issues": sf.get("issues", []), "t0": t0.isoformat()})
    _report(study_dir, study, result)
    return result


def _capabilities(study, exp, sf, days, day_ok, tz, t0, t1, intersection, policy_evidence) -> list[dict]:
    """Capability | synthetic | real. REAL_DATA_VALIDATED only if the period really exercised the capability and every
    structural check on the target-days that exercised it passed; otherwise NOT_OBSERVED_IN_REAL_DATA (or FAILED)."""
    period_days = {d for d, _, _ in days}
    out = {c: {"capability": c, "synthetic": "SYNTHETICALLY_VALIDATED", "real": "NOT_OBSERVED_IN_REAL_DATA",
               "evidence": "not present in the period", "synthetic_tests": CAPABILITIES[c]} for c in CAPABILITIES}

    def judge(cap, hits):
        hits = sorted({(n, d) for n, d in hits if d in period_days})
        if not hits:
            return
        bad = [f"{n} {d}" for n, d in hits if not day_ok.get((n, d), False)]
        out[cap]["real"] = "REAL_DATA_VALIDATION_FAILED" if bad else "REAL_DATA_VALIDATED"
        per = {n: [d for m, d in hits if m == n] for n in dict.fromkeys(n for n, _ in hits)}
        out[cap]["evidence"] = ("structural FAIL on " + ", ".join(bad)) if bad else "exact match on " + "; ".join(
            f"{n} {len(ds)} day(s) {ds[0]}…{ds[-1]}" if len(ds) > 1 else f"{n} {ds[0]}" for n, ds in per.items())

    def shift(d, k):
        return str(dt.date.fromisoformat(d) + dt.timedelta(days=k))
    hits: dict[str, list] = {c: [] for c in CAPABILITIES}
    for name, e in exp.items():
        by_day: dict[str, list] = {}
        for r in e["rows"]:
            by_day.setdefault(r["date"], []).append(r)
        for d, rs in by_day.items():
            kinds = [r["kind"] for r in rs]
            if any(k in WORK_KINDS for k in kinds):
                hits["shift_start_end"].append((name, d))
            if "BREAK" in kinds:
                hits["breaks"].append((name, d))
            if sum(k in ("SHIFT", "EXTRA_SHIFT") for k in kinds) >= 2:
                hits["multiple_shifts"].append((name, d))
            if any(r["overnight"] for r in rs):
                hits["overnight_shift"] += [(name, d), (name, shift(d, 1))]
            if "HOLIDAY" in kinds:
                hits["holiday"] += [(name, shift(d, -1)), (name, d), (name, shift(d, 1))]
            if "OVERTIME" in kinds:
                hits["overtime"].append((name, d))
            if "EXTRA_SHIFT" in kinds:
                hits["extra_shift"].append((name, d))
        s = (sf.get("targets") or {}).get(name) or {}
        if s.get("has_overnight"):  # the scope of a non-working day only matters with night shifts
            for d, scope in s.get("non_working_days", []):
                cap = {"CALENDAR_DAY": "calendar_day", "SHIFTS_STARTING_ON_DATE": "shifts_starting_on_date"}.get(scope or "")
                if cap:
                    hits[cap] += [(name, shift(d, -1)), (name, d), (name, shift(d, 1))]
        if s.get("kind") == "node" and sf.get("components", {}).get(s.get("id")) == "source":
            hits["source_calendar"] += [(name, d) for d in by_day]
    for cap, h in hits.items():
        judge(cap, h)
    for t, cap in dst_transitions(tz, t0, t1):  # only exercised if a planned interval actually spans the change
        crossing = [n for n, e in exp.items() if any(x < t < y for x, y in e["available"] + e["break"])]
        if crossing:
            judge(cap, [(n, _iso(t0, t)[:10]) for n in crossing])
        else:
            out[cap]["evidence"] = f"DST change at {_iso(t0, t)} but no planned interval spans it"
    if not any(((sf.get("targets") or {}).get(n) or {}).get("kind") == "node"
               and sf.get("components", {}).get(sf["targets"][n].get("id")) == "source" for n in exp):
        out["source_calendar"].update(real="NOT_APPLICABLE", evidence="no calendared source among the study targets")
    pairs, cap = intersection["pairs"], out["machine_operator_calendar_intersection"]
    if not pairs:
        cap.update(real="NOT_APPLICABLE", evidence="no machine + operator pair among the targets")
    elif intersection["violations"]:
        cap.update(real="REAL_DATA_VALIDATION_FAILED", evidence="; ".join(intersection["violations"]))
    elif any(p["calendars_differ"] and p["starts"] for p in pairs):
        cap.update(real="REAL_DATA_VALIDATED", evidence="calendars differ in the period; every SimForge start/resume lies "
                   "inside the independently computed joint availability")
    else:
        cap["evidence"] = "calendars identical in the period (intersection not exercised)"
    policies = sf.get("policies") or {}
    for pol in POLICIES:  # declared policy vs boundary behaviour OBSERVED in real data (strong evidence) + SimForge
        nodes = [n for n, t in study["targets"].items() if "node" in t and policies.get(t["node"]) == pol]
        if not nodes:
            out[pol]["evidence"] = "policy not used by any target operation in this case"
            continue
        verdicts = []
        for name in nodes:
            seen = policy_evidence.get(name, set())
            sim_ev = ((sf.get("targets") or {}).get(name) or {}).get("operation_events", [])
            if pol == "FINISH_CURRENT":  # SimForge finished an operation after the boundary (outside joint availability)
                sim_ok = any(ev == "end_process" and not _in(t, intersection["joint"].get(name, [])) for t, ev in sim_ev)
            else:
                sim_ok = any(ev == SIM_POLICY_EVENT[pol] for _, ev in sim_ev)
            if seen - {pol}:
                verdicts.append(("REAL_DATA_VALIDATION_FAILED", f"{name}: declared {pol} but observed {sorted(seen - {pol})}"))
            elif pol in seen and sim_ok:
                verdicts.append(("REAL_DATA_VALIDATED", f"{name}: {pol} observed at a calendar boundary and applied by SimForge"))
            elif pol in seen:
                verdicts.append(("NOT_OBSERVED_IN_REAL_DATA", f"{name}: {pol} observed but the SimForge run did not exercise it"))
            else:
                verdicts.append(("NOT_OBSERVED_IN_REAL_DATA", f"{name}: no observed operation crossed a boundary under {pol}"))
        worst = next(v for v in ("REAL_DATA_VALIDATION_FAILED", "NOT_OBSERVED_IN_REAL_DATA", "REAL_DATA_VALIDATED")
                     if any(x[0] == v for x in verdicts))
        out[pol].update(real=worst, evidence="; ".join(x[1] for x in verdicts))
    return list(out.values())


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


def _table(head, rows):
    cell = lambda v: "—" if v in (None, "") else str(v)  # noqa: E731
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]


def _report(study_dir: Path, study: dict, r: dict) -> None:
    L = ["# Real Calendar Validation", ""]
    if r.get("synthetic"):
        L += ["> **SYNTHETIC EXAMPLE — exercises the validation tool only. It validates NOTHING with real data.**", ""]
    L += [f"**Validation status: `{r['status']}`**", ""]
    if r.get("missing"):
        L += [f"Case ID: {r.get('study_id') or '—'}", "", "Missing inputs (validation cannot run):", ""] + [f"- {m}" for m in r["missing"]]
        (study_dir / "VALIDATION_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        return
    sf, caps = r["simforge"], r["capabilities"]
    by = {s: [c["capability"] for c in caps if c["real"] == s] for s in CAP_STATUSES}
    observed = [c["capability"] for c in caps if c["real"] in ("REAL_DATA_VALIDATED", "REAL_DATA_VALIDATION_FAILED")
                or c["evidence"].startswith("exercised")]
    L += ["## Scope", "", r["scope"] or "No capability is REAL_DATA_VALIDATED by this study.", "",
          "(A) Structural: does SimForge reproduce exactly the configured calendar? (B) Operational representativeness: "
          "does that calendar represent what happened? Production, utilisation and WIP are secondary evidence.", "",
          f"- Capabilities observed: {', '.join(observed) or 'none'}",
          f"- Capabilities validated: {', '.join(by['REAL_DATA_VALIDATED']) or 'none'}",
          f"- Capabilities not observed: {', '.join(c for c in by['NOT_OBSERVED_IN_REAL_DATA'] if c not in observed) or 'none'}",
          f"- Capabilities failed: {', '.join(by['REAL_DATA_VALIDATION_FAILED']) or 'none'}",
          f"- Not applicable: {', '.join(by['NOT_APPLICABLE']) or 'none'}", "",
          "## Case ID", "", f"{r.get('study_id')} — {study.get('plant_case', '—')}", "",
          "## Period", "", f"{study['period_start']} → {study['period_end']} ({study['timezone']}); warm-up {study.get('warmup_s') or 0} s", "",
          "## Evidence sources", ""]
    L += _table(["Source", "Type", "Clock", "Offset (s)", "Offset applied", "Confirmed by (role)", "Extracted", "Reference"],
                [[k, s.get("source_type"), s.get("clock_sync_status"), s.get("known_offset_s"), s.get("apply_offset"),
                  s.get("confirmed_by_role"), s.get("extraction_date"), s.get("source_reference")] for k, s in r["sources"].items()])
    if r["clock_corrections"]:
        L += ["", "Clock corrections applied (traced, never silent):", ""]
        L += _table(["Source", "Target", "Event", "Raw", "Corrected", "Offset (s)", "Reference"],
                    [[c["source_ref"], c["target"], c["event"], c["raw"], c["corrected"], c["offset_s"], c["reference"]]
                     for c in r["clock_corrections"]])
    L += ["", f"Model: input/model.yaml — model_hash `{sf['model_hash']}`, availability_hash `{sf['availability_hash']}`, "
          f"engine {sf['engine_version']}, seed {sf['seed']}, horizon {sf['horizon_s']} s", "",
          "## Data coverage", "", "A day without data is MISSING / NOT_AVAILABLE, never \"nothing happened\" "
          "(no events, no failures, no exception).", ""]
    L += _table(["Stream", "Target", "Covered days", "Missing / not available"],
                [[c["stream"], c["target"], f"{c['covered_days']}/{c['days']}", c["missing"]] for c in r["coverage"]])
    if r["coverage_gate"] or r["config_errors"]:
        L += ["", "**Coverage gate / configuration (fix the inputs, never the engine or the calendar to fit):**", ""]
        L += [f"- {c}" for c in r["coverage_gate"] + r["config_errors"]]
    L += [f"- Note: {n}" for n in r.get("notes", [])]
    L += ["", "## Planned calendar", "", "input/calendar_rows.csv (PLANNED / RECONSTRUCTED rows) → expected/expected.json.", "",
          "## Observed operation", "", f"{len(r['operational_events'])} observed events, {len(r['operational_metrics'])} "
          f"observed metrics. Operational representativeness: **{r['representativeness']}**.", "",
          "## Independent expected availability", "", "Computed from the day-by-day rows with the tool's own interval "
          "arithmetic (no engine code).", "", "## SimForge availability", ""]
    L += _table(["Metric", "Target", "Expected", "SimForge", "Difference (s)", "Status"],
                [[m["metric"], m["target"], _h(m["expected_s"]), _h(m["simforge_s"]), m["difference_s"], m["status"]] for m in r["metrics"]])
    L += ["", f"Per-day check (comparison/daily.csv): {sum(x['status'] == 'PASS' for x in r['daily'])}/{len(r['daily'])} "
          "target-days PASS.", "", "## Calendar event comparison", "", "Structural, tolerance 0 s (both sides are definitions).", ""]
    L += _table(["Event", "Target", "Evidence Type", "Expected/Observed", "SimForge", "Delta (s)", "Resolution (s)", "Status"],
                [[e["event"], e["target"], e["evidence_type"], e["expected"], e["simforge"], e["delta_s"], e["resolution_s"], e["status"]]
                 for e in r["events"]])
    L += ["", "## Operational evidence", "", "Observed events vs the PLANNED calendar at their declared resolution. A process "
          "start after the shift start, or an operation ending after a boundary under FINISH_CURRENT, is not a calendar error.", ""]
    L += _table(["Event", "Target", "Evidence Type", "Expected/Observed", "Planned reference", "Delta (s)", "Resolution (s)", "Strength", "Status"],
                [[o["event"], o["target"], o["evidence_type"], o["observed"], o.get("planned"), o.get("delta_s"), o["resolution_s"],
                  o.get("strength"), o["status"]] for o in r["operational_events"]] or [["—"] * 9])
    L += [""]
    L += _table(["Target", "Metric", "From", "To", "Observed", "SimForge", "Difference", "Relative difference"],
                [[p["target"], p["metric"], p["from"], p["to"], p["observed"], p["simforge"], p["difference"], p["relative_difference"]]
                 for p in r["operational_metrics"]] or [["—"] * 8])
    L += ["", "No percentage threshold on operational metrics: each difference is analysed and classified. Planned "
          "available time and actual working time are different quantities.", "", "## Capability coverage", ""]
    L += _table(["Capability", "Synthetic", "Real Data", "Evidence"], [[c["capability"], c["synthetic"], c["real"], c["evidence"]] for c in caps])
    L += ["", "## Differences", ""]
    L += _table(["Kind", "Difference", "Classification", "Evidence"],
                [[x["kind"], x["what"], x["classification"], x["evidence"]] for x in r["differences"]] or [["—"] * 4])
    L += ["", "## Root-cause classification", "", f"Classes: {', '.join(CLASSES)}. A difference stays UNKNOWN until "
          "input/classifications.csv gives a class AND its evidence. Nothing is attributed to the engine automatically "
          "and nothing is tuned away. A classified structural FAIL is still a FAIL.", "",
          "## Limitations", "", f"- Valid only for case {r.get('study_id')} ({', '.join(study['targets'])}) during the period above.",
          "- Capabilities not observed keep only their synthetic status.",
          f"- Engine regression at validation time: 01–05 = {r['regression']['got']} → {'PASS' if r['regression']['ok'] else 'FAIL'}"]
    L += [f"- SimForge issue: {i}" for i in r["issues"]]
    so = study.get("engineer_sign_off") or {}
    L += ["", "## Engineer sign-off", "", f"Role: {so.get('name') or '—'} · Date: {so.get('date') or '—'} · Notes: {so.get('notes') or '—'}",
          "", "## Validation status", "", f"`{r['status']}`" + (" (synthetic example)" if r.get("synthetic") else ""), ""]
    if r["scope"]:
        L += [r["scope"], ""]
    (study_dir / "VALIDATION_REPORT.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    out = run_study(Path(sys.argv[1]))
    print(out["status"])
    if out.get("scope"):
        print(" ", out["scope"])
    for c in out.get("missing", []) + out.get("config_errors", []) + out.get("coverage_gate", []):
        print("  -", c)
