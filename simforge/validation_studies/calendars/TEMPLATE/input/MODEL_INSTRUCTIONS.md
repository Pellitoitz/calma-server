# input/model.yaml — how to build it

1. Model ONLY the selected case (e.g. `source -> machine_a -> sink`, operator `operator_1`). Process time: the plant's
   standard/nominal time. Do NOT adjust it to match production (prohibited calibration).
2. Enter the calendar the way an engineer would (weekly pattern + breaks + exceptions) with
   `simforge calendar ...` or the UI tab *Calendars*, **not** by copying `calendar_rows.csv` line by line.
   The comparison checks that the weekly pattern + exceptions reproduce the real day-by-day schedule.
3. `availability.mode: dated`, `start_date` / `start_time` / `timezone` = the study's `period_start` / `timezone`.
   Horizon = `period_end - period_start`.
4. `operations.<node>.at_unavailability` = the policy the plant confirmed (`boundary_policy` in study.yaml). If the
   plant has not confirmed it, the model does not verify (REQUIRES_ENGINEER_DECISION) — do not pick one to make it run.
5. Save it as `input/model.yaml` and run:

   ```
   python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY_ID>
   ```
