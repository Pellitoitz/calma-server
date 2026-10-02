# input/ files

| File | Columns | Notes |
|---|---|---|
| `study.yaml` | — | period, timezone, targets, sources (+ clock), data_streams, additional_constraints, boundary_policy, sign-off |
| `calendar_rows.csv` | resource,date,start,end,kind,evidence_type,source_ref,temporal_resolution,note | **Every day** of the period for every target. `kind` ∈ SHIFT, OVERTIME, EXTRA_SHIFT, BREAK, PLANNED_STOP, HOLIDAY, OFF (known non-working day, no times). `end ≤ start` = ends next day. `evidence_type` ∈ PLANNED, RECONSTRUCTED |
| `observed_events.csv` | timestamp,target,event,evidence_type,source_ref,temporal_resolution,note | Calendar events: SHIFT_START, SHIFT_END, BREAK_START, BREAK_END. Operational: FIRST_PROCESS_START, LAST_PROCESS_END, FIRST_UNIT_COMPLETED, LAST_UNIT_COMPLETED, OPERATION_START, OPERATION_END, PAUSE, RESUME, RESTART. `evidence_type` ∈ OBSERVED, RECONSTRUCTED |
| `observed_metrics.csv` | target,metric,from,to,value,unit,evidence_type,source_ref,note | UNITS_COMPLETED (unit `units`), ACTUAL_WORKING_TIME (`h` or `s`, whole period) |
| `missing_data.csv` | stream,target,from,to,status,note | stream ∈ calendar, observed_events, observed_metrics, failures; status MISSING / NOT_AVAILABLE |
| `classifications.csv` | id,classification,evidence | engineer's root cause per difference id (from comparison/differences.csv); without evidence it stays UNKNOWN |
| `model.yaml` | — | see MODEL_INSTRUCTIONS.md |

`temporal_resolution` ∈ SECOND, MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, HOUR (or seconds). A time more precise than
its declared resolution (06:00:30 at MINUTE) is rejected as DATA_QUALITY.
