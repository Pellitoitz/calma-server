# Real Calendar Validation

> **SYNTHETIC EXAMPLE — exercises the validation tool only. It validates NOTHING with real data.**

**Validation status: `NOT_TESTED`**

## Scope

No capability is REAL_DATA_VALIDATED by this study.

(A) Structural: does SimForge reproduce exactly the configured calendar? (B) Operational representativeness: does that calendar represent what happened? Production, utilisation and WIP are secondary evidence.

- Capabilities observed: shift_start_end, breaks, multiple_shifts, machine_operator_calendar_intersection
- Capabilities validated: none
- Capabilities not observed: overnight_shift, holiday, overtime, extra_shift, calendar_day, shifts_starting_on_date, FINISH_CURRENT, PAUSE_RESUME, STOP_RESTART, DST_spring, DST_autumn
- Capabilities failed: none
- Not applicable: source_calendar

## Case ID

EXAMPLE_SYNTHETIC — Machine_A (2 shifts 06-14, 14-22, Mon-Fri) worked by Operator_1 (06-14 Mon-Fri, break 10:00-10:15). Invented.

## Period

2026-10-05T00:00:00 → 2026-10-12T00:00:00 (Europe/Madrid); warm-up 0 s

## Evidence sources

| Source | Type | Clock | Offset (s) | Offset applied | Confirmed by (role) | Extracted | Reference |
|---|---|---|---|---|---|---|---|
| plan | HR_SCHEDULE | CONFIRMED_SYNCED | — | — | nobody (synthetic) | 2026-10-02 | invented shift plan |

Model: input/model.yaml — model_hash `38e403264703491d`, availability_hash `7c2fc585f3524005`, engine 0.6.0, seed 1, horizon 604800.0 s

## Data coverage

A day without data is MISSING / NOT_AVAILABLE, never "nothing happened" (no events, no failures, no exception).

| Stream | Target | Covered days | Missing / not available |
|---|---|---|---|
| calendar | Machine_A | 7/7 | — |
| calendar | Operator_1 | 7/7 | — |
| observed_events | * | 0/7 | 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-10, 2026-10-11 |
| observed_metrics | * | 0/7 | 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-10, 2026-10-11 |
| failures | * | 0/7 | 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-10, 2026-10-11 |

## Planned calendar

input/calendar_rows.csv (PLANNED / RECONSTRUCTED rows) → expected/expected.json.

## Observed operation

0 observed events, 0 observed metrics. Operational representativeness: **NOT_ASSESSED (no observed operation data)**.

## Independent expected availability

Computed from the day-by-day rows with the tool's own interval arithmetic (no engine code).

## SimForge availability

| Metric | Target | Expected | SimForge | Difference (s) | Status |
|---|---|---|---|---|---|
| CALENDAR_TIME | Machine_A | 168.000 h | 168.000 h | 0.0 | PASS |
| PLANNED_AVAILABLE_TIME | Machine_A | 80.000 h | 80.000 h | 0.0 | PASS |
| BREAK_TIME | Machine_A | 0.000 h | 0.000 h | 0 | PASS |
| OFF_SHIFT_TIME | Machine_A | 88.000 h | 88.000 h | 0.0 | PASS |
| CALENDAR_TIME | Operator_1 | 168.000 h | 168.000 h | 0.0 | PASS |
| PLANNED_AVAILABLE_TIME | Operator_1 | 38.750 h | 38.750 h | 0.0 | PASS |
| BREAK_TIME | Operator_1 | 1.250 h | 1.250 h | 0.0 | PASS |
| OFF_SHIFT_TIME | Operator_1 | 128.000 h | 128.000 h | 0.0 | PASS |
| ENGINE_TRACKED_PLANNED_TIME | Operator_1 | 38.750 h | 38.750 h | 0.0 | PASS |

Per-day check (comparison/daily.csv): 14/14 target-days PASS.

## Calendar event comparison

Structural, tolerance 0 s (both sides are definitions).

| Event | Target | Evidence Type | Expected/Observed | SimForge | Delta (s) | Resolution (s) | Status |
|---|---|---|---|---|---|---|---|
| SHIFT_START | Machine_A | PLANNED | 2026-10-05T06:00:00+02:00 | 2026-10-05T06:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Machine_A | PLANNED | 2026-10-05T22:00:00+02:00 | 2026-10-05T22:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Machine_A | PLANNED | 2026-10-06T06:00:00+02:00 | 2026-10-06T06:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Machine_A | PLANNED | 2026-10-06T22:00:00+02:00 | 2026-10-06T22:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Machine_A | PLANNED | 2026-10-07T06:00:00+02:00 | 2026-10-07T06:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Machine_A | PLANNED | 2026-10-07T22:00:00+02:00 | 2026-10-07T22:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Machine_A | PLANNED | 2026-10-08T06:00:00+02:00 | 2026-10-08T06:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Machine_A | PLANNED | 2026-10-08T22:00:00+02:00 | 2026-10-08T22:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Machine_A | PLANNED | 2026-10-09T06:00:00+02:00 | 2026-10-09T06:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Machine_A | PLANNED | 2026-10-09T22:00:00+02:00 | 2026-10-09T22:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Operator_1 | PLANNED | 2026-10-05T06:00:00+02:00 | 2026-10-05T06:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_START | Operator_1 | PLANNED | 2026-10-05T10:00:00+02:00 | 2026-10-05T10:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_END | Operator_1 | PLANNED | 2026-10-05T10:15:00+02:00 | 2026-10-05T10:15:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Operator_1 | PLANNED | 2026-10-05T14:00:00+02:00 | 2026-10-05T14:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Operator_1 | PLANNED | 2026-10-06T06:00:00+02:00 | 2026-10-06T06:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_START | Operator_1 | PLANNED | 2026-10-06T10:00:00+02:00 | 2026-10-06T10:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_END | Operator_1 | PLANNED | 2026-10-06T10:15:00+02:00 | 2026-10-06T10:15:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Operator_1 | PLANNED | 2026-10-06T14:00:00+02:00 | 2026-10-06T14:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Operator_1 | PLANNED | 2026-10-07T06:00:00+02:00 | 2026-10-07T06:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_START | Operator_1 | PLANNED | 2026-10-07T10:00:00+02:00 | 2026-10-07T10:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_END | Operator_1 | PLANNED | 2026-10-07T10:15:00+02:00 | 2026-10-07T10:15:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Operator_1 | PLANNED | 2026-10-07T14:00:00+02:00 | 2026-10-07T14:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Operator_1 | PLANNED | 2026-10-08T06:00:00+02:00 | 2026-10-08T06:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_START | Operator_1 | PLANNED | 2026-10-08T10:00:00+02:00 | 2026-10-08T10:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_END | Operator_1 | PLANNED | 2026-10-08T10:15:00+02:00 | 2026-10-08T10:15:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Operator_1 | PLANNED | 2026-10-08T14:00:00+02:00 | 2026-10-08T14:00:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_START | Operator_1 | PLANNED | 2026-10-09T06:00:00+02:00 | 2026-10-09T06:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_START | Operator_1 | PLANNED | 2026-10-09T10:00:00+02:00 | 2026-10-09T10:00:00+02:00 | 0.0 | 0 | PASS |
| BREAK_END | Operator_1 | PLANNED | 2026-10-09T10:15:00+02:00 | 2026-10-09T10:15:00+02:00 | 0.0 | 0 | PASS |
| SHIFT_END | Operator_1 | PLANNED | 2026-10-09T14:00:00+02:00 | 2026-10-09T14:00:00+02:00 | 0.0 | 0 | PASS |

## Operational evidence

Observed events vs the PLANNED calendar at their declared resolution. A process start after the shift start, or an operation ending after a boundary under FINISH_CURRENT, is not a calendar error.

| Event | Target | Evidence Type | Expected/Observed | Planned reference | Delta (s) | Resolution (s) | Strength | Status |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — |

| Target | Metric | From | To | Observed | SimForge | Difference | Relative difference |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — |

No percentage threshold on operational metrics: each difference is analysed and classified. Planned available time and actual working time are different quantities.

## Capability coverage

| Capability | Synthetic | Real Data | Evidence |
|---|---|---|---|
| shift_start_end | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | exercised, but study is NOT_TESTED: exact match on Machine_A 5 day(s) 2026-10-05…2026-10-09; Operator_1 5 day(s) 2026-10-05…2026-10-09 |
| breaks | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | exercised, but study is NOT_TESTED: exact match on Operator_1 5 day(s) 2026-10-05…2026-10-09 |
| multiple_shifts | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | exercised, but study is NOT_TESTED: exact match on Machine_A 5 day(s) 2026-10-05…2026-10-09 |
| overnight_shift | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| holiday | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| overtime | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| extra_shift | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| calendar_day | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| shifts_starting_on_date | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| FINISH_CURRENT | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | policy not used by any target operation in this case |
| PAUSE_RESUME | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | Machine_A: no observed operation crossed a boundary under PAUSE_RESUME |
| STOP_RESTART | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | policy not used by any target operation in this case |
| DST_spring | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| DST_autumn | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | not present in the period |
| source_calendar | SYNTHETICALLY_VALIDATED | NOT_APPLICABLE | no calendared source among the study targets |
| machine_operator_calendar_intersection | SYNTHETICALLY_VALIDATED | NOT_OBSERVED_IN_REAL_DATA | exercised, but study is NOT_TESTED: calendars differ in the period; every SimForge start/resume lies inside the independently computed joint availability |

## Differences

| Kind | Difference | Classification | Evidence |
|---|---|---|---|
| — | — | — | — |

## Root-cause classification

Classes: CALENDAR_ERROR, MODEL_SCOPE_DIFFERENCE, PROCESS_TIME_DIFFERENCE, FAILURE_MODEL_DIFFERENCE, UNMODELLED_EVENT, DATA_QUALITY, SOURCE_CLOCK_DIFFERENCE, UNKNOWN. A difference stays UNKNOWN until input/classifications.csv gives a class AND its evidence. Nothing is attributed to the engine automatically and nothing is tuned away. A classified structural FAIL is still a FAIL.

## Limitations

- Valid only for case EXAMPLE_SYNTHETIC (Machine_A, Operator_1) during the period above.
- Capabilities not observed keep only their synthetic status.
- Engine regression at validation time: 01–05 = {'01_simple_line.yaml': 59.0, '02_shared_operator.yaml': 359.0, '03_machine_breakdowns.yaml': 1889.05, '04_rework_routing.yaml': 477.5, '05_selective_soldering.yaml': 130.0} → PASS
- SimForge issue: WARNING CAL_BREAK_PARTIAL [availability.calendars.morning]: 'morning': el descanso 10:00-10:15 cae en parte fuera del turno: solo descuenta la parte dentro.

## Engineer sign-off

Role: — · Date: — · Notes: —

## Validation status

`NOT_TESTED` (synthetic example)
