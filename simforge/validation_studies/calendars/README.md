# Calendar validation studies (real plant data)

Protocol: [`docs/real_calendar_validation.md`](../../docs/real_calendar_validation.md).

```
calendars/
  TEMPLATE/                  copy to <STUDY_ID>/ for each study
    input/
      study.yaml             period, timezone, targets, traceability, boundary policy, sign-off
      calendar_rows.csv      REAL day-by-day schedule (resource,date,start,end,kind,note)
      model.yaml             SimForge model (calendar entered as weekly pattern + exceptions) — see MODEL_INSTRUCTIONS.md
      observed_events.csv    optional: real timestamps (PLC/MES/manual) with their precision
      observed_production.csv optional: secondary evidence only
    expected/                generated: analytical expected availability (independent of the engine)
    simforge/                generated: engine timelines, state accounting, transitions, hashes
    comparison/              generated: metrics.csv, events.csv, production.csv (+ engineer classification)
    VALIDATION_REPORT.md     generated
  EXAMPLE_SYNTHETIC/         invented data to exercise the tool. Status is always NOT_TESTED.
```

Run: `python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY_ID>`

Rules: anonymise (Machine_A, Operator_1); no personal data; never calibrate anything to make a study pass; a study
validates one case and one period, never "SimForge" as a whole. If plant data must not leave the plant, keep the
study folder outside the repository and run the same command on it.
