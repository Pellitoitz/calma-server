# Files of an economic validation case

All values anonymised; no names of people, suppliers or customers; contractual prices only if needed and allowed
(otherwise keep the case folder outside the repository and run the same command on it).

## sources.csv — one row per document / system extract
| column | meaning |
|---|---|
| source_id | S1, S2… referenced by every input, driver and reference |
| source_type | PAYROLL, HR, ERP, ACCOUNTING, ENERGY_INVOICE, ENERGY_METER, MACHINE_COST_RECORD, MAINTENANCE_RECORD, PURCHASE_ORDER, QUOTE, INVOICE, APPROVED_INVESTMENT, MATERIAL_PRICE_LIST, PRODUCTION_RECORD, PRODUCTION_CALENDAR, OPERATING_PLAN, MES, PLC, ENGINEER_CONFIRMED, SIMFORGE_EXPORT, OTHER |
| source_reference | internal, anonymised reference (e.g. SRC-HR-RATES-2026) |
| source_date / extraction_date | document date / date the data were extracted |
| confirmed_by_role | role (never a name) |
| represents | what the source REALLY represents (an "official" source is not correct by definition) |
| evidence_class | REAL_SOURCE_INPUT, INDEPENDENT_REFERENCE, DERIVED_REFERENCE, ENGINEER_CONFIRMED, SYNTHETIC |

## economic_inputs.csv — the 0.9 assumptions, one row per value (nothing else is added)
`economic_input_id, scenario, category (labor | machine | energy | energy_power | material | scrap | maintenance |
downtime | revenue | capex), resource_or_node, product, kind (maintenance: REPAIR_LABOR | PM_LABOR | PER_FAILURE |
PER_PM), resource (maintenance technician), paid_time (CALENDAR_WINDOW | PLANNED_AVAILABLE | DECLARED),
declared_paid_hours_per_unit, state (energy_power: PROCESSING | SETUP), value (blank = MISSING, 0 = zero), currency,
unit (e.g. EUR/h, EUR/kWh, EUR/unit, kW), basis (0.9 basis), effective_date, source_id, provenance (measured |
provided_by_client | estimated | assumed | calculated | imported), precision (resolution of the value),
included_components (e.g. ownership;maintenance;energy), economic_concept (labor: PAYROLL_COST | ACTIVITY_COST |
PLANNED_CAPACITY_COST | INCREMENTAL_LABOR_COST | …), notes`

## physical_drivers.csv — observed physical magnitudes (SimForge KPI keys)
`driver_id, scenario, kpi, value, unit, resolution, classification (MEASURED | VALIDATED_MODEL_OUTPUT | RECONSTRUCTED |
ASSUMED | MISSING), event_status (OBSERVED | NO_EVENT | MISSING_DATA), source_id, notes`

Allowed kpi keys: `units_completed`, `units_scrapped`, `product.<p>.completed`, `node.<n>.processing_h` (observed
processing hours), `node.<n>.setup_time_h`, `node.<n>.processed`, `node.<n>.planned_available_h`,
`node.<n>.failure_count`, `node.<n>.preventive_maintenance_count`, `node.<n>.corrective_downtime_h`,
`resource.<r>.planned_available_h`, `resource.<r>.working_h` (+ `walking_h`, `transporting_h`, `outside_planned_h`),
`resource.<r>.task_h.<n>#repair`, `resource.<r>.task_h.<n>#pm`.

NO_EVENT = the record exists and shows 0 events (value 0). MISSING_DATA = there is no record (value empty). They are
never the same thing.

## references.csv — the independent results SimForge is compared with
`reference_id, scenario, capability, target (resource / node / product / run / comparison / *), value, currency,
source_id, economic_concept, method (SIMPLE_PAYBACK | DISCOUNTED_PAYBACK | ANNUAL_SAVINGS_OVER_INCREMENTAL_CAPEX | …),
included_components, period_start, period_end, reference_precision, absolute_tolerance, relative_tolerance,
tolerance_basis (ROUNDING | SOURCE_PRECISION | TIME_RESOLUTION | MONETARY_RESOLUTION | METHOD), tolerance_reason, notes`

No tolerance declared -> the tolerance is DERIVED from the resolutions (rate precision x hours + hours resolution x
rate + half the reference precision). A declared tolerance larger than the derived one is rejected unless its basis is
METHOD with an explicit reason. No universal "±5 %".

## classifications.csv — engineer classification of each difference id printed by the report
`difference_id, class (ROUNDING | SOURCE_PRECISION | PHYSICAL_DRIVER_DIFFERENCE | ECONOMIC_INPUT_DIFFERENCE |
BASIS_DIFFERENCE | FORMULA_DEFINITION_DIFFERENCE | PERIOD_DIFFERENCE | COVERAGE_DIFFERENCE | MISSING_DATA |
MODEL_SCOPE_DIFFERENCE | POSSIBLE_SOFTWARE_BUG | UNCLASSIFIED), material (yes/no), resolved (yes/no), explanation,
evidence`. A classification explains a difference; it never turns it into a PASS.

## model.yaml
The SimForge physical model of the process (resources with their quantity, nodes with their capacity). It does not
need an `economics` block: the assumptions come from economic_inputs.csv.
