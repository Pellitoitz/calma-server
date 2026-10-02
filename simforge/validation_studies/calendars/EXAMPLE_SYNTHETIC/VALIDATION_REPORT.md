# Real Calendar Validation — EXAMPLE_SYNTHETIC

> **SYNTHETIC EXAMPLE — exercises the validation tool only. It validates NOTHING with real data.**

**Validation status: `NOT_TESTED`**

## Scope

Calendar module of SimForge engine 0.6.0 on ONE anonymised case. Production, utilisation and WIP are secondary evidence; they are never used to declare the calendar validated.

## Plant case

Machine_A (2 shifts 06-14, 14-22, Mon-Fri) worked by Operator_1 (06-14 Mon-Fri, break 10:00-10:15). Invented.

## Period

2026-10-05T00:00:00 → 2026-10-12T00:00:00 (Europe/Madrid); warm-up 0 s

## Input data

- Schedule rows: input/calendar_rows.csv (source: invented for the example; confirmed by: nobody (synthetic); extracted: 2026-10-02)
- Observed timestamps: 0 rows (input/observed_events.csv)
- Model: input/model.yaml — model_hash `38e403264703491d`, availability_hash `7c2fc585f3524005`, engine 0.6.0, seed 1, horizon 604800.0 s

## Real calendar / SimForge calendar

Expected availability is computed independently from the day-by-day rows (expected/expected.json); SimForge's from the engine timelines and state accounting (simforge/simforge.json).

## Analytical expected availability vs SimForge availability

| Target | Metric | Expected/Observed | SimForge | Difference | Status |
|---|---|---|---|---|---|
| Machine_A | CALENDAR_TIME | 168.000 h | 168.000 h | 0.0 s | PASS |
| Machine_A | PLANNED_AVAILABLE_TIME | 80.000 h | 80.000 h | 0.0 s | PASS |
| Machine_A | BREAK_TIME | 0.000 h | 0.000 h | 0 s | PASS |
| Machine_A | OFF_SHIFT_TIME | 88.000 h | 88.000 h | 0.0 s | PASS |
| Machine_A | PAUSED_BY_CALENDAR_TIME | — | 90.500 h | — s | INFO (DES output, needs observed data) |
| Machine_A | BUSY_OUTSIDE_PLANNED_TIME | — | 0.000 h | — s | INFO (DES output, needs observed data) |
| Operator_1 | CALENDAR_TIME | 168.000 h | 168.000 h | 0.0 s | PASS |
| Operator_1 | PLANNED_AVAILABLE_TIME | 38.750 h | 38.750 h | 0.0 s | PASS |
| Operator_1 | BREAK_TIME | 1.250 h | 1.250 h | 0.0 s | PASS |
| Operator_1 | OFF_SHIFT_TIME | 128.000 h | 128.000 h | 0.0 s | PASS |
| Operator_1 | ENGINE_TRACKED_PLANNED_TIME | 38.750 h | 38.750 h | 0.0 s | PASS |
| Operator_1 | WORKING_TIME | — | 38.750 h | — s | INFO (DES output, needs observed data) |
| Operator_1 | IDLE_AVAILABLE_TIME | — | 0.000 h | — s | INFO (DES output, needs observed data) |
| Operator_1 | OUTSIDE_PLANNED_TIME | — | 0.000 h | — s | INFO (DES output, needs observed data) |

## Event comparison

| Target | Source | Event | Expected | SimForge | Delta (s) | Tolerance (s) | Status |
|---|---|---|---|---|---|---|---|
| Machine_A | PLAN (calendar_rows) | SHIFT_START | 2026-10-05T06:00:00+02:00 | 2026-10-05T06:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_END | 2026-10-05T22:00:00+02:00 | 2026-10-05T22:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_START | 2026-10-06T06:00:00+02:00 | 2026-10-06T06:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_END | 2026-10-06T22:00:00+02:00 | 2026-10-06T22:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_START | 2026-10-07T06:00:00+02:00 | 2026-10-07T06:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_END | 2026-10-07T22:00:00+02:00 | 2026-10-07T22:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_START | 2026-10-08T06:00:00+02:00 | 2026-10-08T06:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_END | 2026-10-08T22:00:00+02:00 | 2026-10-08T22:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_START | 2026-10-09T06:00:00+02:00 | 2026-10-09T06:00:00+02:00 | 0.0 | 0 | PASS |
| Machine_A | PLAN (calendar_rows) | SHIFT_END | 2026-10-09T22:00:00+02:00 | 2026-10-09T22:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_START | 2026-10-05T06:00:00+02:00 | 2026-10-05T06:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_START | 2026-10-05T10:00:00+02:00 | 2026-10-05T10:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_END | 2026-10-05T10:15:00+02:00 | 2026-10-05T10:15:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_END | 2026-10-05T14:00:00+02:00 | 2026-10-05T14:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_START | 2026-10-06T06:00:00+02:00 | 2026-10-06T06:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_START | 2026-10-06T10:00:00+02:00 | 2026-10-06T10:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_END | 2026-10-06T10:15:00+02:00 | 2026-10-06T10:15:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_END | 2026-10-06T14:00:00+02:00 | 2026-10-06T14:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_START | 2026-10-07T06:00:00+02:00 | 2026-10-07T06:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_START | 2026-10-07T10:00:00+02:00 | 2026-10-07T10:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_END | 2026-10-07T10:15:00+02:00 | 2026-10-07T10:15:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_END | 2026-10-07T14:00:00+02:00 | 2026-10-07T14:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_START | 2026-10-08T06:00:00+02:00 | 2026-10-08T06:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_START | 2026-10-08T10:00:00+02:00 | 2026-10-08T10:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_END | 2026-10-08T10:15:00+02:00 | 2026-10-08T10:15:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_END | 2026-10-08T14:00:00+02:00 | 2026-10-08T14:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_START | 2026-10-09T06:00:00+02:00 | 2026-10-09T06:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_START | 2026-10-09T10:00:00+02:00 | 2026-10-09T10:00:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | BREAK_END | 2026-10-09T10:15:00+02:00 | 2026-10-09T10:15:00+02:00 | 0.0 | 0 | PASS |
| Operator_1 | PLAN (calendar_rows) | SHIFT_END | 2026-10-09T14:00:00+02:00 | 2026-10-09T14:00:00+02:00 | 0.0 | 0 | PASS |

## DES results (secondary evidence)

No observed production provided.

## Differences and root-cause classification

No structural differences.

## Boundary behavior observed

Declared policy for `machine_a`: **PAUSE_RESUME** (confirmed by: nobody (synthetic)).
Observed in real data: NO → the boundary policy stays NOT_OBSERVED_IN_REAL_DATA.

## Engine regression at validation time

01–05 = {'01_simple_line.yaml': 59.0, '02_shared_operator.yaml': 359.0, '03_machine_breakdowns.yaml': 1889.05, '04_rework_routing.yaml': 477.5, '05_selective_soldering.yaml': 130.0} → PASS

## Validation issues reported by SimForge

- WARNING CAL_BREAK_PARTIAL [availability.calendars.morning]: 'morning': el descanso 10:00-10:15 cae en parte fuera del turno: solo descuenta la parte dentro.

## Limitations

- Valid only for this case, period and calendar; not for the whole plant.
- Contracts not observed in this data keep SYNTHETICALLY_VALIDATED.

## Validation status

`NOT_TESTED` (synthetic example)

## Engineer sign-off

Name: — · Date: — · Notes: —
