# Economic validation report — ECON-DEMO-001

Protocol 1.0 · status **SYNTHETIC_DEMO_NOT_A_VALIDATION**

> SYNTHETIC DEMO: no capability is REAL_DATA_VALIDATED (format demonstration only). Not validated by this study: [LABOR_PAID_TIME, LABOR_PLANNED_TIME, LABOR_BUSY_TIME, MACHINE_TIME_COST, ENERGY_COST, ENERGY_CONSUMPTION_FROM_DECLARED_POWER, MATERIAL_COST, SCRAP_COST, REPAIR_LABOR_COST, PM_LABOR_COST, PER_FAILURE_COST, PER_PM_COST, DOWNTIME_DECLARED_COST, REVENUE, COST_PER_PRODUCED_UNIT, COST_PER_GOOD_UNIT, ANNUALIZATION, CAPEX, SCENARIO_DELTA, EVALUATED_SAVINGS, SIMPLE_PAYBACK, ANNUAL_RETURN_ON_INCREMENTAL_CAPEX, REPLICATION_ECONOMIC_UNCERTAINTY]. Costs not represented in the data: overhead, tooling wear.

## A. Case identification
- Labor + machine cost of an assembly cell, current vs. semi-automated (demo) · company Company_X · process Assembly_Cell_1 · data_nature SYNTHETIC_DEMO

## B. Scope
- question: Does SimForge Economics reproduce the documented labor and machine cost of one week of Assembly_Cell_1, its cost per good unit, and the simple payback of the semi-automation proposal?

- capabilities requested: ['LABOR_PAID_TIME', 'MACHINE_TIME_COST', 'COST_PER_GOOD_UNIT', 'ANNUALIZATION', 'CAPEX', 'EVALUATED_SAVINGS', 'SIMPLE_PAYBACK']
- unrepresented costs: YES ['overhead', 'tooling wear']

## C. Period
- 2026-10-05 .. 2026-10-09 · currency EUR

## D. Physical drivers
| scenario | kpi | value | resolution | classification | event_status | source |
|---|---|---|---|---|---|---|
| baseline | units_completed | 400 | 0 | MEASURED | OBSERVED | S3 |
| baseline | units_scrapped | 8 | 0 | MEASURED | OBSERVED | S3 |
| baseline | node.m.processing_h | 32.5 | 0.0166667 | MEASURED | OBSERVED | S3 |
| alternative | units_completed | 400 | 0 | RECONSTRUCTED | OBSERVED | S3 |
| alternative | units_scrapped | 8 | 0 | RECONSTRUCTED | OBSERVED | S3 |
| alternative | node.m.processing_h | 26 | 0.0166667 | RECONSTRUCTED | OBSERVED | S3 |
| baseline | node.m.failure_count | 0 | 0 | MEASURED | NO_EVENT | S3 |

## E. Economic inputs
| id | scenario | category | target | value | unit | basis | concept | included | source |
|---|---|---|---|---|---|---|---|---|---|
| I1 | baseline | labor | op | 28.40 | EUR/h | PER_PAID_HOUR | PAYROLL_COST | wage;social_charges | S1 |
| I2 | baseline | machine | m | 12.00 | EUR/h | PER_PROCESSING_HOUR |  | ownership;maintenance | S2 |
| I3 | baseline | capex | none | 0 | EUR | FIXED |  |  | S7 |
| I4 | alternative | labor | op | 28.40 | EUR/h | PER_PAID_HOUR | PAYROLL_COST | wage;social_charges | S1 |
| I5 | alternative | machine | m | 12.00 | EUR/h | PER_PROCESSING_HOUR |  | ownership;maintenance | S2 |
| I6 | alternative | capex | equipment | 25000 | EUR | FIXED |  |  | S7 |

## F. Sources
| id | type | reference (anonymised) | represents | evidence | confirmed by |
|---|---|---|---|---|---|
| S1 | HR | SRC-HR-RATES-2026 | hourly paid rate of assembly operators (wage + social charges) | SYNTHETIC | HR controller |
| S2 | MACHINE_COST_RECORD | SRC-CTRL-MACHRATE-2026 | machine hourly rate per processing hour (ownership + maintenance) | SYNTHETIC | controller |
| S3 | PRODUCTION_RECORD | SRC-MES-WEEK41 | good and scrapped units and processing hours of week 41 | SYNTHETIC | production supervisor |
| S4 | PAYROLL | SRC-PAYROLL-WEEK41 | paid labor cost of the cell for week 41 | SYNTHETIC | HR controller |
| S5 | ACCOUNTING | SRC-CTRL-COSTREPORT-W41 | machine cost and cost per good unit of week 41 | SYNTHETIC | controller |
| S6 | OPERATING_PLAN | SRC-OPPLAN-2027 | approved operating weeks per year | SYNTHETIC | plant manager |
| S7 | QUOTE | SRC-QUOTE-AUTOMATION-01 | semi-automation equipment quote | SYNTHETIC | purchasing |
| S8 | ACCOUNTING | SRC-CTRL-INVESTMENT-CASE | simple payback of the proposal (controlling calculation) | SYNTHETIC | controller |

## G. Evidence independence
- R1 (LABOR_PAID_TIME): SYNTHETIC synthetic reference
- R2 (MACHINE_TIME_COST): SYNTHETIC synthetic reference
- R3 (COST_PER_GOOD_UNIT): SYNTHETIC synthetic reference
- R4 (EVALUATED_SAVINGS): SYNTHETIC synthetic reference
- R5 (SIMPLE_PAYBACK): SYNTHETIC synthetic reference

## H. Capabilities exercised
- COST_PER_GOOD_UNIT, EVALUATED_SAVINGS, LABOR_PAID_TIME, MACHINE_TIME_COST, SIMPLE_PAYBACK

## I. Arithmetic reproduction (level A)
| ref | capability | scenario | target | SimForge | reference calc | reference | tol | result | reason |
|---|---|---|---|---|---|---|---|---|---|
| R1 | LABOR_PAID_TIME | baseline | op | 1136.0 | 1136.0 | None | None | PASS | |1136 - 1136| <= 1.14e-06 |
| R2 | MACHINE_TIME_COST | baseline | m | 390.0 | 390.0 | None | None | PASS | |390 - 390| <= 3.91e-07 |
| R3 | COST_PER_GOOD_UNIT | baseline | run | 3.815 | 3.815 | None | None | PASS | |3.815 - 3.815| <= 4.82e-09 |
| R4 | EVALUATED_SAVINGS | baseline | comparison | 362.0 | 362.0 | None | None | PASS | |362 - 362| <= 3.63e-07 |
| R5 | SIMPLE_PAYBACK | baseline | comparison | 1.5013211626231084 | 1.5013211626231084 | None | None | PASS | |1.501321163 - 1.501321163| <= 2.5e-09 |

## J. Input representativeness (level B)
| ref | capability | scenario | target | SimForge | reference calc | reference | tol | result | reason |
|---|---|---|---|---|---|---|---|---|---|
| R1 | LABOR_PAID_TIME | baseline | op | None | 1136.0 | 1136.0 | 0.405 | PASS | |1136 - 1136| = 0 vs tolerance 0.405 |
| R2 | MACHINE_TIME_COST | baseline | m | None | 390.0 | 390.0 | 0.5300004 | PASS | |390 - 390| = 0 vs tolerance 0.53 |
| R3 | COST_PER_GOOD_UNIT | baseline | run | None | 3.815 | 3.815 | 0.0028125010000000002 | PASS | |3.815 - 3.815| = 0 vs tolerance 0.0028125 |
| R4 | EVALUATED_SAVINGS | baseline | comparison | None | 362.0 | 362.0 | 0.6 | PASS | |362 - 362| = 0 vs tolerance 0.6 |
| R5 | SIMPLE_PAYBACK | baseline | comparison | None | 1.5013211626231084 | 1.5 | 0.005 | PASS | |1.50132 - 1.5| = 0.00132116 vs tolerance 0.005 |

## K. End-to-end comparison (level C)
| ref | capability | scenario | target | SimForge | reference calc | reference | tol | result | reason |
|---|---|---|---|---|---|---|---|---|---|
| R1 | LABOR_PAID_TIME | baseline | op | 1136.0 | None | 1136.0 | 0.405 | INCOMPLETE | simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited) |
| R2 | MACHINE_TIME_COST | baseline | m | 389.0249999999999 | None | 390.0 | 0.5300004 | INCOMPLETE | simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited) |
| R3 | COST_PER_GOOD_UNIT | baseline | run | 3.822117794486216 | None | 3.815 | 0.0028125010000000002 | INCOMPLETE | simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited) |
| R4 | EVALUATED_SAVINGS | baseline | comparison | 284.0 | None | 362.0 | 0.6 | INCOMPLETE | simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited) |
| R5 | SIMPLE_PAYBACK | baseline | comparison | 1.9136558481322707 | None | 1.5 | 0.005 | INCOMPLETE | simulated physical drivers not VALIDATED_MODEL_OUTPUT (end-to-end limited) |

## L. Differences
| id | level | capability | class | material | resolved | detail |
|---|---|---|---|---|---|---|

## M. Engineer classifications
- none

## N. Missing data

## O. Out-of-scope concepts
- overhead, depreciation, financing, taxes
- semantic gaps: none declared

## P. Capability matrix
| capability | status | reasons |
|---|---|---|
| LABOR_PAID_TIME | INCOMPLETE | synthetic evidence: cannot be REAL_DATA_VALIDATED |
| LABOR_PLANNED_TIME | NOT_OBSERVED | not exercised by this case |
| LABOR_BUSY_TIME | NOT_OBSERVED | not exercised by this case |
| MACHINE_TIME_COST | INCOMPLETE | synthetic evidence: cannot be REAL_DATA_VALIDATED |
| ENERGY_COST | NOT_OBSERVED | not exercised by this case |
| ENERGY_CONSUMPTION_FROM_DECLARED_POWER | NOT_OBSERVED | not exercised by this case |
| MATERIAL_COST | NOT_OBSERVED | not exercised by this case |
| SCRAP_COST | NOT_OBSERVED | not exercised by this case |
| REPAIR_LABOR_COST | NOT_OBSERVED | not exercised by this case |
| PM_LABOR_COST | NOT_OBSERVED | not exercised by this case |
| PER_FAILURE_COST | NOT_OBSERVED | not exercised by this case |
| PER_PM_COST | NOT_OBSERVED | not exercised by this case |
| DOWNTIME_DECLARED_COST | NOT_OBSERVED | not exercised by this case |
| REVENUE | NOT_OBSERVED | not exercised by this case |
| COST_PER_PRODUCED_UNIT | NOT_OBSERVED | not exercised by this case |
| COST_PER_GOOD_UNIT | INCOMPLETE | synthetic evidence: cannot be REAL_DATA_VALIDATED |
| ANNUALIZATION | INCOMPLETE | requested / exercised but no reference result |
| CAPEX | INCOMPLETE | requested / exercised but no reference result |
| SCENARIO_DELTA | NOT_OBSERVED | not exercised by this case |
| EVALUATED_SAVINGS | INCOMPLETE | synthetic evidence: cannot be REAL_DATA_VALIDATED |
| SIMPLE_PAYBACK | INCOMPLETE | synthetic evidence: cannot be REAL_DATA_VALIDATED |
| ANNUAL_RETURN_ON_INCREMENTAL_CAPEX | NOT_OBSERVED | not exercised by this case |
| REPLICATION_ECONOMIC_UNCERTAINTY | NOT_OBSERVED | not exercised by this case |

## Q. Final scoped statement

SYNTHETIC DEMO: no capability is REAL_DATA_VALIDATED (format demonstration only). Not validated by this study: [LABOR_PAID_TIME, LABOR_PLANNED_TIME, LABOR_BUSY_TIME, MACHINE_TIME_COST, ENERGY_COST, ENERGY_CONSUMPTION_FROM_DECLARED_POWER, MATERIAL_COST, SCRAP_COST, REPAIR_LABOR_COST, PM_LABOR_COST, PER_FAILURE_COST, PER_PM_COST, DOWNTIME_DECLARED_COST, REVENUE, COST_PER_PRODUCED_UNIT, COST_PER_GOOD_UNIT, ANNUALIZATION, CAPEX, SCENARIO_DELTA, EVALUATED_SAVINGS, SIMPLE_PAYBACK, ANNUAL_RETURN_ON_INCREMENTAL_CAPEX, REPLICATION_ECONOMIC_UNCERTAINTY]. Costs not represented in the data: overhead, tooling wear.

Engineer sign-off: process engineer · 2026-10-20 · reviewed True · scope accepted True (sign-off confirms review and scope; it never turns a discrepancy into a PASS).
Software regression 01–05: OK.
