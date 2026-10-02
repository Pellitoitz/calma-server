# Economics & decision support (motor 0.9.0)

> Los datos miden, el sistema analiza, el ingeniero decide, el motor simula.

Economics es una **capa explícita y trazable posterior al run**:

```
DES (motor) → resultados físicos (per_replication) → supuestos económicos → indicadores → comparación → ingeniero
```

SimForge **no recomienda, no ordena alternativas, no elige "la mejor" y no optimiza**. Muestra hechos (costes,
deltas, ahorros, payback, cobertura) con su fórmula, su base física y su procedencia. No hay IA en esta capa.

Estado: `CODE_COMPLETE` + `SYNTHETICALLY_VALIDATED`. Validación con datos económicos reales: `NOT_TESTED`.

## 1. Arquitectura y aislamiento

- Bloque de extensión `economics` de `SimModel` (`domain/isms_ext.py`), fuera del núcleo ISMS congelado
  (`EXTENSION_KEYS`, `NON_PHYSICAL_KEYS = ("economics",)`). El verificador congelado y los prompts no cambian.
- **Invariancia física**: `economics` se excluye de `content_hash()` (hash físico). Cambiar un salario, una tarifa o
  un CAPEX no cambia la secuencia de eventos, los KPIs, el RNG, la traza, la caché de resultados ni la aprobación
  física. Tests: `test_physical_invariance_*` (sin/con/otra economía → KPIs y eventos idénticos),
  `test_economics_change_keeps_physical_approval_and_legacy_hashes` (hashes 01–05 idénticos a 0.8).
- `economic_hash()` = sha256 del bloque `economics` normalizado (16 hex).
- Una evaluación se identifica por `run_id + economic_hash + economics_engine_version`
  (`evaluation_id = sha256(...)[:12]`), con `physical_model_hash` del run.

## 2. Evaluación post-run (sin re-simular)

`economics.evaluate_run(run, model, spec)` lee **sólo** `run.per_replication` (KPIs persistidos) y la estructura
del modelo (unidades de recurso, ranuras de nodo, productos). No llama a SimPy (test 51 lo bloquea con un
monkeypatch). Precondiciones:

- `model.content_hash() == run.model_hash`; si no → `EconomicsError` (no se valora un run con otra física).
- El modelo físico verifica; `economics_issues` no tiene ERROR salvo `REQUIRES_ENGINEER_DECISION` (doble conteo,
  que se marca en la línea y no se suma).

## 3. Dinero, moneda, procedencia y MISSING

Cada valor es un `Money`: `value`, `currency` (ISO 3 letras), `basis`, `provenance` (la misma `Provenance` del
resto de SimForge), `reference`, `effective_date`.

- Una moneda por evaluación; **sin conversión de divisas**. Monedas mezcladas → ERROR `ECONOMICS_CURRENCY_MIXED`.
- `value: null` = **MISSING**: la línea queda `MISSING`, la categoría `MISSING` en la cobertura y la evaluación
  `PARTIAL_MISSING_INPUTS`. Nunca se sustituye por un valor típico. MISSING se conserva al guardar el modelo
  (serialización explícita aunque `dump_model` use `exclude_none`).
- Provenance `default` → ERROR `ECONOMICS_DEFAULT_VALUE`; `assumed` → INFO visible.
- Valores negativos → ERROR; no finitos → rechazados al cargar.

## 4. Bases (taxonomía) y magnitud física de cada una

| Base | Magnitud física (por réplica) |
|---|---|
| PER_PAID_HOUR | horas pagadas según `paid_time` (ver §5) |
| PER_PLANNED_HOUR | tiempo planificado disponible (calendario; sin calendario = ventana medida) × unidades/ranuras |
| PER_BUSY_HOUR | recurso: working + walking + transporting + fuera de planificado |
| PER_PROCESSING_HOUR | nodo: utilización × ranuras × ventana + busy fuera de planificado |
| PER_SETUP_HOUR | nodo: `setup_time_h` (≥ 0.7) |
| PER_OPERATING_HOUR | processing + setup |
| PER_CALENDAR_HOUR | ventana medida × unidades/ranuras |
| PER_CYCLE | `node.<id>.processed` |
| PER_GOOD_UNIT | unidades completadas (o `product.<p>.completed`) |
| PER_SCRAP_UNIT | unidades scrap |
| PER_CONSUMED_UNIT | buenas + scrap |
| PER_KWH | kWh de potencia declarada (§7) |
| PER_FAILURE / PER_PM | averías / PM completados (≥ 0.8) |
| PER_CORRECTIVE_DOWNTIME_HOUR | horas de downtime correctivo (≥ 0.8) |
| FIXED_PER_RUN / FIXED | importe fijo del run / partida CAPEX |

Bases declarables pero **no calculables** en 0.9 (ERROR `ECONOMICS_BASIS_UNSUPPORTED` con el motivo): `PER_UNIT`
(ambigua) y `FIXED_PER_PERIOD` (no hay modelo de periodos). Cada categoría admite sólo ciertas bases
(`validation/economics.py: ALLOWED`); una base sin métrica física detrás se rechaza.

## 5. Mano de obra: busy ≠ paid

- `PER_BUSY_HOUR` valora el tiempo ocupado; `PER_PAID_HOUR` valora el tiempo pagado. **No se asume paid = planned.**
- `PER_PAID_HOUR` exige `paid_time`: `CALENDAR_WINDOW` (ventana × unidades), `PLANNED_AVAILABLE` (planificado del
  calendario) o `DECLARED` (`declared_paid_hours_per_unit` × unidades). Sin regla → ERROR
  `ECONOMICS_PAID_TIME_RULE_MISSING`; `paid_time` con otra base → ERROR `ECONOMICS_CONTRADICTORY`; `DECLARED` sin horas
  → MISSING.
- Caso 43: 1 operario, ventana 8 h, ocupado 5 h, 30 €/h → paid 240 €, busy 150 €.

## 6. Máquina

Base explícita por línea. Dos líneas del mismo nodo con bases solapadas (misma base, PROCESSING+OPERATING,
SETUP+OPERATING, PLANNED+CALENDAR) → `REQUIRES_ENGINEER_DECISION`. `PER_SETUP_HOUR` sin setups → NOT_APPLICABLE.

## 7. Energía

SimForge **no modela energía y no estima kWh**. kWh = Σ potencia declarada (`power_kw[nodo][PROCESSING|SETUP]`) ×
horas simuladas en ese estado. Sin potencia declarada → NOT_APPLICABLE. Cambiar el precio o la potencia no requiere
re-simular (caso 44: 20 → 30).

## 8. Material y scrap (sin doble conteo)

- `material` PER_CONSUMED_UNIT (buenas + scrap) **ya incluye** el material de las piezas scrap; se muestra una línea
  MEMO con la parte scrap (no se suma).
- `material` PER_GOOD_UNIT + `scrap` PER_SCRAP_UNIT es la forma separada.
- PER_CONSUMED_UNIT junto con líneas `scrap`, o material global + por producto → `REQUIRES_ENGINEER_DECISION`.

## 9. Mantenimiento y downtime

Sólo si se declaran y sólo sobre nodos con bloque `maintenance` (si no → ERROR `ECONOMICS_NO_PHYSICAL_METRIC`).
`REPAIR_LABOR` / `PM_LABOR` (PER_BUSY_HOUR × horas del técnico en `<nodo>#repair` / `<nodo>#pm`), `PER_FAILURE`,
`PER_PM`. Técnico también valorado en `labor` → `REQUIRES_ENGINEER_DECISION`. `downtime` (coste declarado
PER_CORRECTIVE_DOWNTIME_HOUR) es una categoría separada; sin entrada explícita no hay coste de downtime (lost revenue
está fuera de alcance). Caso 52: reparación 60, PM 20.

## 10. Ingresos y resultado neto

Sólo con precio explícito PER_GOOD_UNIT. `evaluated_net_result = revenue − evaluated_total_cost` sobre las
categorías evaluadas; **no es un beneficio** (no incluye amortización, impuestos, overhead…). Más throughput sin
precio declarado no se convierte en ingresos (caso 54).

## 11. Totales, costes unitarios, cobertura y estados

- `evaluated_total_cost` = Σ líneas INCLUDED, con desglose por categoría (`by_category`).
- `cost_per_produced_unit` = total / (buenas + scrap); `cost_per_good_unit` = total / buenas. Denominador 0 en
  alguna réplica → `UNDEFINED_METRIC` (caso 45: 10 / 12.5).
- Cobertura por categoría: `INCLUDED | MISSING | NOT_APPLICABLE | REQUIRES_ENGINEER_DECISION | NOT_REQUESTED`;
  `out_of_scope`: depreciation, financing, taxes, overhead, opportunity_cost, lost_revenue. Sin porcentajes
  arbitrarios. `scope` declara qué categorías quiere el ingeniero (una categoría en scope sin líneas = MISSING).
- Estado de la evaluación: `COMPLETE_FOR_REQUESTED_SCOPE | PARTIAL_MISSING_INPUTS | REQUIRES_ENGINEER_DECISION`.
  Comparación: `COMPARABLE | COMPARABLE_WITH_WARNINGS | NOT_COMPARABLE`. Métricas: `UNDEFINED_METRIC`, `NOT_REACHED`.

## 12. Run vs anualizado

Los valores del run y los anualizados se presentan por separado. Anualizar exige regla explícita
`annualization: {mode: REPEAT_RUN, runs_per_year: N}` (si no → `MISSING`, nunca asumido). Caso 47: 200 × 440 = 88 000.

## 13. Comparación de escenarios (hechos, no recomendación)

`compare_evaluations(base, alt, base_model, alt_model)`:

- Convenciones: `delta = alt − base`; `savings = base − alt`.
- Comprobaciones: moneda (error), horizonte/warm-up, réplicas, base de anualización, fuentes/demanda, mix/secuencia,
  calendarios (avisos).
- Deltas físicos (throughput, WIP, lead time…) y económicos por categoría común; categorías sólo en un lado se
  listan (`mismatched_categories`) y no entran en el total común.
- **Emparejada** (common random numbers) si semillas y réplicas coinciden: estadísticas de la diferencia réplica a
  réplica; si no, diferencia de medias.
- CAPEX incremental = alt − base (separado del OPEX, sin amortización). MISSING ≠ 0: CAPEX MISSING → payback
  `UNDEFINED_METRIC`.
- `simple_payback_v1` = CAPEX incremental / ahorro anual. Ahorro ≤ 0 → `NOT_REACHED` (nunca negativo); CAPEX ≤ 0 o
  sin anualización → `UNDEFINED_METRIC`. Caso 48: 2.5 años; caso 53: −20 000 / +20 000 / 3 años.
- `annual_return_on_incremental_capex` = ahorro anual / CAPEX incremental (nombre explícito; no "ROI").
- **Sin NPV/IRR** en 0.9. Nada de "winner", "best", "optimal" ni "recommend".

## 14. Productos y costes compartidos

Líneas con `product` son costes **directos** del producto; el resto son **compartidos**. `allocation_policy: NONE`:
los compartidos nunca se reparten entre productos en 0.9 (caso 56).

## 15. Incertidumbre

Cada línea tiene valores por réplica; los indicadores llevan n, media, std e IC95 (`analytics.stats.summarize`) y la
etiqueta `SIMULATION_DERIVED_ECONOMIC_UNCERTAINTY`: es la variabilidad de la simulación, no la incertidumbre de
los precios (caso 55: media 110, std 10).

## 16. Auditoría y registro de fórmulas

Cada línea: `line_id`, categoría, objetivo, base, `formula_id`, parámetro (valor, moneda, procedencia, referencia,
fecha), fuentes físicas (KPIs usados), cantidad y valor por réplica. Registro versionado `FORMULAS`
(`labor_paid_v1`, `labor_busy_v1`, `machine_hours_v1`, `energy_kwh_v1`, `material_units_v1`, `scrap_material_v1`,
`maintenance_labor_v1`, `downtime_declared_v1`, `evaluated_total_cost_v1`, `cost_per_good_unit_v1`,
`evaluated_net_result_v1`, `annualized_v1`, `capex_total_v1`, …) incluido en cada evaluación.

## 17. Aprobación y persistencia

- La aprobación económica (`approve_evaluation(id, by)`) es independiente de la aprobación física del modelo.
- SQLite, migración 2: tabla `economic_evaluations` (evaluation_id, run_id → runs, physical_model_hash,
  economic_hash, economics_engine_version, status, created_at, assumptions_json, result_json, approved_by,
  approved_at). Varias evaluaciones por run; cargar devuelve exactamente lo guardado (caso 57).
- Al reconstruir el modelo, el bloque economics se arrastra (`economics_carried_over`).

## 18. CLI y UI

```
simforge economics show MODEL.yaml [--economics E.yaml]          # supuestos, economic_hash, issues
simforge economics evaluate MODEL.yaml [--economics E.yaml ...] [--seed S] [--replications N]
                                                                 # UN run físico, N evaluaciones económicas
simforge economics compare BASE.yaml ALT.yaml [--seed S] [--replications N]   # mismas semillas → emparejada
```

Pestaña **Economics**: supuestos, hash, issues, "Evaluar (sin re-simular)" sobre un run guardado, cobertura,
líneas, gráfico por categoría, totales, costes unitarios, anualizado, CAPEX y comparación.

## 19. Limitaciones (0.9)

Sin FX, sin NPV/IRR, sin amortización, sin impuestos/overhead/financiación, sin coste de oportunidad ni lost revenue,
sin modelo de periodos (FIXED_PER_PERIOD), sin asignación de costes compartidos, sin scrap por producto, sin modelo
físico de energía, sin incertidumbre de precios, sin optimización ni recomendación, sin IA. No validado con datos
económicos reales.
