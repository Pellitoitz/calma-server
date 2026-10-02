# Calendar validation studies (real plant data)

Protocol: [`docs/real_calendar_validation.md`](../../docs/real_calendar_validation.md).

```
calendars/
  TEMPLATE/                   copy to <STUDY_ID>/ for each study
    input/
      study.yaml              period, timezone, targets, sources (+clock sync), data_streams,
                              additional_constraints, boundary policy, sign-off
      calendar_rows.csv       day-by-day schedule, EVERY day (PLANNED / RECONSTRUCTED evidence)
      observed_events.csv     optional: OBSERVED calendar/operational events with source and resolution
      observed_metrics.csv    optional: units completed, actual working time (secondary evidence)
      missing_data.csv        known gaps (MISSING / NOT_AVAILABLE)
      classifications.csv     engineer root cause per difference id, with evidence
      model.yaml              SimForge model — see MODEL_INSTRUCTIONS.md; columns in FILES.md
    expected/                 generated: independent expected availability
    simforge/                 generated: engine timelines, accounting, transitions, hashes
    comparison/               generated: metrics, daily, events, operational_*, capabilities, coverage,
                              differences, clock_corrections (.csv)
    VALIDATION_REPORT.md      generated
  EXAMPLE_SYNTHETIC/          invented data to exercise the tool. Status is always NOT_TESTED.
```

Run: `python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY_ID>`

Rules: anonymise (Machine_A, Operator_1); no personal data; never calibrate anything to make a study pass; a study
validates only the capabilities it exercised, in one case and one period — never "SimForge" as a whole. If plant data must not leave the plant, keep the
study folder outside the repository and run the same command on it.
