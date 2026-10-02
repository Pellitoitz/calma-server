"""Calendars, shifts, breaks and exceptions: PLANNED availability of resources and nodes (engine >= 0.6.0).

Formal model (ISMS extension block `availability`, see domain/isms_ext.py):

    availability:
      mode: relative_week | dated          # never mixed: dated exceptions need mode 'dated' (+ timezone)
      start_weekday / start_time           # relative_week: simulation t=0 (e.g. mon 00:00)
      start_date / start_time / timezone   # dated: t=0 = start_date start_time in timezone (DST-aware)
      calendars: [Calendar]
      resources: {resource_id: calendar_id}   # operators / tools (never carriers)
      nodes:     {node_id: calendar_id}       # servers (machines) and sources
      always_available: [ids]                 # explicit ALWAYS_AVAILABLE (no warning)
      operations: {node_id: {at_unavailability, start_rule}}

Semantics (docs/calendars_and_shifts.md):
* A working window [start, end) is available at `start`, not at `end`. end <= start means it crosses midnight
  (22:00-06:00 = 22:00 of that day to 06:00 of the next); "24:00" is midnight at the end of the day.
* Windows of one calendar are UNIONED: touching windows (06-14, 14-22) are continuous; overlapping windows are a
  validation ERROR (double availability), never counted twice.
* Breaks are times of day on given weekdays (default every day), subtracted from working time; the part of a break
  outside working time has no effect (warned); overlapping breaks are merged (never subtracted twice).
* Exceptions (dated mode only) act on the windows that START on that date, except NON_WORKING_DAY with
  scope CALENDAR_DAY, which removes every available second of that civil day.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .values import Provenance

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_S = 86400.0

AVAILABLE, BREAK, OFF_SHIFT = "available", "break", "off_shift"

InterruptionPolicy = Literal["FINISH_CURRENT", "PAUSE_RESUME", "STOP_RESTART"]
StartRule = Literal["START_ANY_TIME", "REQUIRE_FULL_WINDOW"]

_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def time_to_s(v: str) -> float:
    m = _TIME.match(v.strip())
    if not m:
        raise ValueError(f"hora inválida '{v}' (formato HH:MM o HH:MM:SS)")
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if mi > 59 or s > 59 or h > 24 or (h == 24 and (mi or s)):
        raise ValueError(f"hora inválida '{v}'")
    return h * 3600.0 + mi * 60.0 + s


def fmt_tod(sec: float) -> str:
    sec = round(sec) % 86400 if sec != 86400 else 86400
    return f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}" + (f":{int(sec % 60):02d}" if sec % 60 else "")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeWindow(_Strict):
    """[start, end) time of day. end <= start crosses midnight; '24:00' = end of the day."""

    start: str
    end: str
    name: str = ""

    @field_validator("start", "end")
    @classmethod
    def _fmt(cls, v: str) -> str:
        time_to_s(v)
        return v

    @model_validator(mode="after")
    def _len(self) -> "TimeWindow":
        if time_to_s(self.start) >= 86400:
            raise ValueError(f"'{self.start}': el inicio debe ser < 24:00")
        if time_to_s(self.start) == time_to_s(self.end):
            raise ValueError(f"intervalo de duración cero ({self.start}-{self.end})")
        return self

    @property
    def start_s(self) -> float:
        return time_to_s(self.start)

    @property
    def end_s(self) -> float:
        """End relative to the start day (adds 24 h when the window crosses midnight)."""
        e = time_to_s(self.end)
        return e + DAY_S if e <= self.start_s else e

    @property
    def crosses_midnight(self) -> bool:
        return self.end_s > DAY_S

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def label(self) -> str:
        return f"{self.start}-{self.end}" + (f" ({self.name})" if self.name else "")


class Break(TimeWindow):
    days: list[Day] | None = None  # None = every day; a break belongs to the day on which it STARTS


class CalendarException(_Strict):
    date: dt.date
    type: Literal["NON_WORKING_DAY", "OVERRIDE_WORKING_INTERVALS", "OVERTIME", "EXTRA_SHIFT"]
    intervals: list[TimeWindow] = Field(default_factory=list)
    reason: str = Field(min_length=3)
    # interval-adding/overriding exceptions: do the calendar breaks also apply inside these intervals? (engineer decides)
    breaks_apply: bool | None = None
    # NON_WORKING_DAY: SHIFTS_STARTING_ON_DATE (a night shift that started the day before still finishes) or
    # CALENDAR_DAY (nothing available from 00:00 to 24:00 of that date). Required when the calendar has night shifts.
    scope: Literal["SHIFTS_STARTING_ON_DATE", "CALENDAR_DAY"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "CalendarException":
        if self.type == "NON_WORKING_DAY":
            if self.intervals:
                raise ValueError(f"{self.date}: NON_WORKING_DAY no lleva intervalos")
        elif not self.intervals:
            raise ValueError(f"{self.date}: {self.type} necesita intervalos")
        return self


class Calendar(_Strict):
    id: str
    name: str = ""
    description: str = ""
    weekly: dict[Day, list[TimeWindow]] = Field(default_factory=dict)  # missing day = not working
    breaks: list[Break] = Field(default_factory=list)
    exceptions: list[CalendarException] = Field(default_factory=list)
    provenance: Provenance | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(f"id de calendario inválido '{v}' (minúsculas, dígitos, '_')")
        return v

    @property
    def has_overnight(self) -> bool:
        return any(w.crosses_midnight for ws in self.weekly.values() for w in ws) or any(
            w.crosses_midnight for e in self.exceptions for w in e.intervals)


class OperationPolicy(_Strict):
    """What happens to an operation when a required resource/node becomes unavailable (None = undeclared)."""

    at_unavailability: InterruptionPolicy | None = None
    start_rule: StartRule | None = None
    reason: str = ""


class AvailabilitySpec(_Strict):
    mode: Literal["relative_week", "dated"]
    start_weekday: Day = "mon"  # relative_week
    start_date: dt.date | None = None  # dated
    start_time: str = "00:00"
    timezone: str | None = None  # dated: IANA name (e.g. Europe/Madrid, UTC); required
    calendars: list[Calendar] = Field(default_factory=list)
    resources: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, str] = Field(default_factory=dict)
    always_available: list[str] = Field(default_factory=list)
    operations: dict[str, OperationPolicy] = Field(default_factory=dict)

    @field_validator("start_time")
    @classmethod
    def _t(cls, v: str) -> str:
        if time_to_s(v) >= DAY_S:
            raise ValueError("start_time debe ser < 24:00")
        return v

    def calendar(self, cal_id: str) -> Calendar:
        for c in self.calendars:
            if c.id == cal_id:
                return c
        raise KeyError(f"No existe el calendario '{cal_id}'.")

    def calendar_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------------------------- interval sets
Iv = tuple[float, float]


def union(ivs: list[Iv]) -> list[Iv]:
    out: list[list[float]] = []
    for a, b in sorted(i for i in ivs if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def intersect(xs: list[Iv], ys: list[Iv]) -> list[Iv]:
    xs, ys, out, i, j = union(xs), union(ys), [], 0, 0
    while i < len(xs) and j < len(ys):
        a, b = max(xs[i][0], ys[j][0]), min(xs[i][1], ys[j][1])
        if b > a:
            out.append((a, b))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(xs: list[Iv], ys: list[Iv]) -> list[Iv]:
    out = []
    ys = union(ys)
    for a, b in union(xs):
        cur = a
        for c, d in ys:
            if d <= cur or c >= b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def measure(ivs: list[Iv]) -> float:
    return sum(b - a for a, b in union(ivs))


def clip(ivs: list[Iv], a: float, b: float) -> list[Iv]:
    return intersect(ivs, [(a, b)])


# ------------------------------------------------------------------------------------------------ expansion
class _Clock:
    """Wall-clock (day index, seconds of that day) -> simulation seconds since t=0."""

    def __init__(self, spec: AvailabilitySpec):
        self.spec = spec
        self.t0_s = time_to_s(spec.start_time)
        if spec.mode == "dated":
            from zoneinfo import ZoneInfo
            if not spec.timezone or not spec.start_date:
                raise ValueError("modo 'dated' requiere start_date y timezone")
            self.tz = ZoneInfo(spec.timezone)
            self.t0 = dt.datetime.combine(spec.start_date, dt.time(), self.tz) + dt.timedelta(seconds=self.t0_s)
        self.wd0 = DAYS.index(spec.start_weekday)

    def day_name(self, i: int) -> str:
        if self.spec.mode == "dated":
            return DAYS[(self.spec.start_date + dt.timedelta(days=i)).weekday()]  # type: ignore[operator]
        return DAYS[(self.wd0 + i) % 7]

    def date(self, i: int) -> dt.date | None:
        return self.spec.start_date + dt.timedelta(days=i) if self.spec.mode == "dated" else None  # type: ignore[operator]

    def at(self, i: int, sec: float) -> float:
        if self.spec.mode == "relative_week":
            return i * DAY_S + sec - self.t0_s
        # wall-clock arithmetic in the local zone, elapsed time in UTC (DST-aware)
        local = dt.datetime.combine(self.date(i), dt.time(), self.tz) + dt.timedelta(seconds=sec)  # type: ignore[arg-type]
        return (local.astimezone(dt.timezone.utc) - self.t0.astimezone(dt.timezone.utc)).total_seconds()


@dataclass
class Timeline:
    """Labelled partition of [0, end): AVAILABLE / BREAK / OFF_SHIFT (simulation seconds)."""

    end: float
    segments: list[tuple[float, float, str]] = field(default_factory=list)

    @property
    def available(self) -> list[Iv]:
        return [(a, b) for a, b, lab in self.segments if lab == AVAILABLE]

    def label_at(self, t: float) -> str:
        for a, b, lab in self.segments:
            if a <= t < b:
                return lab
        return OFF_SHIFT

    def is_available(self, t: float) -> bool:
        return self.label_at(t) == AVAILABLE

    def change_points(self) -> list[float]:
        return sorted({a for a, _, _ in self.segments if a > 0})

    def next_unavailable(self, t: float) -> float:
        """End of the available window containing t (t itself if not available)."""
        for a, b, lab in self.segments:
            if a <= t < b:
                return b if lab == AVAILABLE else t
        return t

    def time_in(self, label: str, a: float, b: float) -> float:
        return sum(max(0.0, min(e, b) - max(s, a)) for s, e, lab in self.segments if lab == label)


def _windows_for_day(cal: Calendar, clock: _Clock, i: int) -> tuple[list[Iv], list[Iv], list[Iv], list[Iv]]:
    """(working windows subject to breaks, working windows exempt from breaks, breaks, holes) for day i."""
    name, date = clock.day_name(i), clock.date(i)
    exc = [e for e in cal.exceptions if date is not None and e.date == date]
    base = list(cal.weekly.get(name, []))  # type: ignore[call-overload]
    reg_extra: list[TimeWindow] = []
    nob: list[TimeWindow] = []
    holes: list[Iv] = []
    for e in exc:
        if e.type == "NON_WORKING_DAY":
            base = []
            if e.scope == "CALENDAR_DAY":
                holes.append((clock.at(i, 0), clock.at(i + 1, 0)))
        elif e.type == "OVERRIDE_WORKING_INTERVALS":
            base = []
            (reg_extra if e.breaks_apply else nob).extend(e.intervals)
        else:  # OVERTIME / EXTRA_SHIFT: added
            (reg_extra if e.breaks_apply else nob).extend(e.intervals)

    def absolute(ws: list[TimeWindow]) -> list[Iv]:
        out = []
        for w in ws:
            end_day, end_s = (i + 1, w.end_s - DAY_S) if w.end_s > DAY_S else (i, w.end_s)
            out.append((clock.at(i, w.start_s), clock.at(end_day, end_s)))
        return out

    brk = [b for b in cal.breaks if b.days is None or name in b.days]
    return absolute(base + reg_extra), absolute(nob), absolute(brk), holes  # type: ignore[arg-type]


def expand(spec: AvailabilitySpec, cal: Calendar, end: float) -> Timeline:
    """Timeline of one calendar over [0, end) in simulation seconds."""
    clock = _Clock(spec)
    reg, nob, brk, holes = [], [], [], []
    for i in range(-2, int(math.ceil((end + clock.t0_s) / DAY_S)) + 2):
        r, n, b, h = _windows_for_day(cal, clock, i)
        reg += r
        nob += n
        brk += b
        holes += h
    working = union(reg + nob)
    avail = subtract(union(subtract(reg, brk) + nob), holes)
    breaks = subtract(subtract(intersect(working, brk), avail), holes)
    avail, breaks = clip(avail, 0, end), clip(breaks, 0, end)
    pts = sorted({0.0, end, *[x for iv in avail + breaks for x in iv]})
    segs: list[tuple[float, float, str]] = []
    for a, b in zip(pts, pts[1:]):
        if b <= a:
            continue
        mid = (a + b) / 2
        lab = AVAILABLE if any(x <= mid < y for x, y in avail) else BREAK if any(x <= mid < y for x, y in breaks) else OFF_SHIFT
        if segs and segs[-1][2] == lab and segs[-1][1] == a:
            segs[-1] = (segs[-1][0], b, lab)
        else:
            segs.append((a, b, lab))
    return Timeline(end, segs)


def intersect_timelines(tls: list[Timeline], end: float) -> Timeline:
    """Available only when ALL are available. Unavailable label: BREAK if any source is on break, else OFF_SHIFT."""
    if not tls:
        return Timeline(end, [(0.0, end, AVAILABLE)])
    pts = sorted({0.0, end, *[x for tl in tls for a, b, _ in tl.segments for x in (a, b)]})
    segs: list[tuple[float, float, str]] = []
    for a, b in zip(pts, pts[1:]):
        if b <= a:
            continue
        labels = [tl.label_at((a + b) / 2) for tl in tls]
        lab = AVAILABLE if all(x == AVAILABLE for x in labels) else BREAK if BREAK in labels else OFF_SHIFT
        if segs and segs[-1][2] == lab:
            segs[-1] = (segs[-1][0], b, lab)
        else:
            segs.append((a, b, lab))
    return Timeline(end, segs)


# ------------------------------------------------------------------------------------------- summaries
def week_view(spec: AvailabilitySpec, cal: Calendar) -> str:
    """Readable weekly view (first 7 days from t=0) with breaks, plus planned hours and exceptions."""
    clock = _Clock(spec)
    tl = expand(spec, cal, 7 * DAY_S + clock.t0_s + DAY_S)
    lines = [f"CALENDAR {cal.id}" + (f" — {cal.name}" if cal.name else "") + f"  ({spec.mode}"
             + (f", {spec.timezone}" if spec.timezone else "") + ")"]
    total = 0.0
    for i in range(7):
        a, b = clock.at(i, 0), clock.at(i + 1, 0)
        day = clock.day_name(i).upper() + (f" {clock.date(i)}" if clock.date(i) else "")
        parts = []
        for s, e, lab in tl.segments:
            s2, e2 = max(s, a), min(e, b)
            if e2 <= s2 or lab == OFF_SHIFT:
                continue
            h0, h1 = fmt_tod(s2 - a), fmt_tod(e2 - a)
            if lab == AVAILABLE:
                bar = "━" * max(1, int(round((e2 - s2) / 1800)))
                parts.append(f"{h0} {bar} {h1}")
            else:
                parts.append(f"[break {h0}-{h1}]")
        planned = tl.time_in(AVAILABLE, a, b)
        total += planned
        lines.append(f"  {day:<15} " + ("  ".join(parts) if parts else "— no disponible —") + f"   = {planned / 3600:.2f} h")
    lines.append(f"  planned available time in these 7 days: {total / 3600:.2f} h")
    for e in cal.exceptions:
        lines.append(f"  EXCEPTION {e.date} {e.type}: " + (", ".join(w.label() for w in e.intervals) or "—")
                     + f" — {e.reason}" + (f" [breaks_apply={e.breaks_apply}]" if e.intervals else "")
                     + (f" [scope={e.scope}]" if e.type == "NON_WORKING_DAY" else ""))
    return "\n".join(lines)
