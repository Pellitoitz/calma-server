# Economic validation studies (real data) — Economics 0.9.0

Protocol: [`docs/validation/economic_real_data_validation.md`](../../docs/validation/economic_real_data_validation.md).

```
economics/
  TEMPLATE/                 copy to <CASE_ID>/ for each case
    input/
      case.yaml             identification, period, scope, scenarios (physical model + observed window), annualization
                            source, MANDATORY unrepresented-costs question, sign-off
      sources.csv           every document / extract and what it really represents (evidence class)
      economic_inputs.csv   the 0.9 economic inputs, 1:1 (value blank = MISSING; 0 = zero)
      physical_drivers.csv  observed physical magnitudes + classification + NO_EVENT / MISSING_DATA
      references.csv        independent reference results + concept + method + justified tolerance
      classifications.csv   engineer classification of differences
      model.yaml            SimForge physical model of the case
      FILES.md              column reference
    comparison/             generated: metrics.csv, differences.csv, capabilities.csv, summary.json
    VALIDATION_REPORT.md    generated (sections A-Q)
  EXAMPLE_SYNTHETIC/        invented data that exercise the tool: never a validation (SYNTHETIC_DEMO).
```

Run: `python scripts/validation/economic_validation.py validation_studies/economics/<CASE_ID>`
(or `simforge economics validate-real validation_studies/economics/<CASE_ID>`).

Rules: anonymise; never adjust data, references or tolerances to make a case pass; a case validates only the
capabilities it exercised, in one case and one period — never "SimForge Economics" as a whole.

## Minimum package to ask the engineer for (first, simple case)

1. process / resource (anonymised) · 2. period · 3. output produced · 4. good output · 5. scrap (if any) ·
6. relevant hours (paid / planned / busy / processing — say which) · 7. economic basis the company uses ·
8. rate / cost · 9. currency · 10. source of each value · 11. the company's own reference calculation, if it exists ·
12. precision / resolution of each value · 13. calendar, if it matters · 14. anomalies of the period ·
15. components included in each rate · 16. costs needed to produce that are NOT represented in the data.

Mandatory question (YES / NO / UNKNOWN): *Is there any cost or economic condition needed to interpret this result that
is not represented in the data delivered?*
