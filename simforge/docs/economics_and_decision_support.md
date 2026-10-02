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
horas simuladas en ese estado. Bloque `energy` sin potencia declarada → **MISSING** (no 0, no NOT_APPLICABLE; cierre
0.9.0). Potencia parcial por estados: `coverage_detail.energy[nodo]` lista `declared_states` / `not_declared_states`
(un estado sin potencia no se valora). Cambiar el precio o la potencia no requiere re-simular (caso 44: 20 → 30).

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

- `evaluated_total_cost` = Σ líneas INCLUDED y aditivas (MEMO, REVENUE, MISSING, NOT_APPLICABLE y
  REQUIRES_ENGINEER_DECISION excluidas). **No** es "total production cost", "full cost" ni "fully loaded cost".
  Desglose `by_category` sobre toda categoría con alguna línea INCLUDED (Σ by_category = total siempre);
  `by_category_coverage` dice si la categoría está completa (cierre 0.9.0).
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
- CAPEX incremental = alt − base (separado del OPEX, sin amortización) sólo si ambos lados declaran CAPEX completo.
  MISSING ≠ 0 y **no declarado ≠ 0** (cierre 0.9.0): una alternativa sin inversión declara una partida explícita de 0.
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

## 19. Cierre técnico 0.9.0: contratos fijados

Tests: `tests/test_economics_closure.py`. Cada contrato tiene al menos un test.

**Frontera física ↔ económica.** Un run físico admite N evaluaciones. Cada una referencia `run_id`,
`physical_model_hash`, `economic_hash` y `economics_engine_version`:

- mismo run + misma economía → mismo `evaluation_id`;
- otra economía u otro run → otro id;
- física incompatible → `EconomicsError`; nunca se aplica en silencio.

Un modelo cuya **única** extensión es `economics` llega al verificador congelado como `core()` físico (mismo hash). Es
un bug corregido: antes no se podía simular.

**Hash económico.** Todo campo del bloque es semántico, incluidas procedencia, referencia y notas, porque aparecen en
la auditoría. No son semánticos el orden de claves ni el orden o los duplicados de `scope`, que se normaliza al orden
de `CATEGORIES`. `30` y `30.0` dan el mismo hash.

**MISSING ≠ 0.** `value: null` sobrevive a YAML/JSON, SQLite, al hash, a la evaluación y a la comparación. Un 0
explícito es un dato: se guarda con su procedencia, su línea es INCLUDED y vale 0. Además, `-0.0` se normaliza a `0.0`.

**COMPLETE_FOR_REQUESTED_SCOPE.** Significa que todas las categorías **solicitadas** (`requested_scope`, o las
declaradas si no hay `scope`) tienen sus entradas y que no queda ninguna decisión pendiente. **No** significa "modelo
económico completo". Lo no solicitado aparece como `NOT_REQUESTED` y `out_of_scope` sigue visible.

**Doble conteo.** Se marcan como `REQUIRES_ENGINEER_DECISION` (no se suman):

- el mismo recurso en dos líneas `labor` (paid / planned / busy);
- técnico en `labor` y en `*_LABOR`;
- máquina con bases solapadas (igual base, PROCESSING+OPERATING, SETUP+OPERATING, PLANNED+CALENDAR);
- `PER_CONSUMED_UNIT` junto con `scrap`;
- material o ingresos a la vez globales y por producto.

Combinaciones independientes que **no** se bloquean:

- PROCESSING + SETUP;
- material PER_GOOD_UNIT + scrap;
- REPAIR_LABOR + PER_FAILURE + downtime.

El significado de `downtime` (coste declarado por hora de parada) frente a una tarifa de máquina PER_PLANNED/CALENDAR
del mismo nodo, que también cubre esas horas, es responsabilidad del ingeniero (LIMITATION). Ambas fuentes físicas son
visibles en la auditoría.

**Tiempo pagado.** Es una base de valoración declarada, no una inferencia laboral ni contable.

- `CALENDAR_WINDOW` = ventana medida (horizonte − warm-up) × unidades. Es la ventana del run, **no** la duración del
  turno, e incluye fuera de turno y descansos.
- `PLANNED_AVAILABLE` = tiempo planificado disponible dentro de la ventana: turnos menos descansos, con las
  excepciones de calendario ya aplicadas en el KPI.
- `DECLARED` = horas declaradas × unidades.

Ejemplos medidos:

| Caso | CALENDAR_WINDOW | PLANNED_AVAILABLE |
|---|---|---|
| Turno 06–14, run 0–10 h | 10 | 4 |
| Turno 06–14, run 24 h | 24 | 8 |
| Dos turnos, run 24 h | 24 | 16 |
| Descanso de 30 min | 14 | 7,5 |
| Warm-up de 8 h | 6 | 6 |

**Recorte al horizonte.** Toda base temporal sale de KPIs medidos en [warm-up, horizonte]: tiempo pagado y
planificado, horas de máquina, kWh, downtime y horas de técnico. Economics no completa ninguna actividad: un trabajo
sin terminar cuenta sus horas de proceso, pero no un ciclo ni una unidad.

**Anualización.** `valor anual = valor del run × runs_per_year` (REPEAT_RUN), con `runs_per_year` explícito, finito
y > 0. Es una extrapolación económica pura: no hay DES, ni demanda, ni días o turnos por año. Además:

- el CAPEX **nunca** se multiplica: no hay `capex` dentro de `annualized`;
- los costes unitarios no se anualizan: el ratio anual coincide con el del run.

**CAPEX incremental.** Requiere CAPEX declarado y completo en ambos lados:

- alguno de los dos sin declarar → `NOT_DECLARED`;
- alguna partida MISSING → `MISSING`;
- en ambos casos el payback queda `UNDEFINED_METRIC`.

**Payback simple y retorno.** El payback es `AVAILABLE` sólo si se cumplen a la vez:

- CAPEX incremental > 0;
- ahorro anual > 0;
- anualización válida y con la misma base en ambos lados;
- ambas evaluaciones `COMPLETE_FOR_REQUESTED_SCOPE`;
- cobertura idéntica.

Si no:

- ahorro ≤ 0 → `NOT_REACHED`;
- CAPEX incremental ≤ 0 → `UNDEFINED_METRIC` (nunca "0 años");
- entradas incompletas → `UNDEFINED_METRIC`;
- cobertura distinta o doble conteo pendiente → `REQUIRES_ENGINEER_DECISION`.

`annual_return_on_incremental_capex_v1` = ahorro anual / CAPEX incremental. Sólo existe con CAPEX incremental > 0 y
puede ser ≤ 0 si el ahorro es ≤ 0; es aritmética, no una recomendación.

**Ingresos.** Sólo unidades buenas × precio explícito: el scrap nunca genera ingresos. No se infiere demanda
satisfecha, ventas perdidas ni coste de oportunidad. `cost_categories_in_net_result` lista las categorías restadas.

**Energía.** Ver §7. Mantenimiento: las horas de técnico son el tiempo en que el recurso está **tomado** por
`<nodo>#repair` / `<nodo>#pm` (trabajo + desplazamiento). Las esperas de recurso (`waiting_for_repair_resource_h`,
`waiting_for_pm_h`) no son horas de técnico. Las averías y el downtime no cuestan nada sin entrada explícita.

**Productos y setups.** Con `allocation_policy: NONE`, se cumple Σ directos + compartidos = total. Operario, setup,
mantenimiento y máquina son compartidos. El setup pertenece al nodo y a la transición, nunca a un producto (contrato
0.7).

**Réplicas y ratios.** Cada réplica física tiene su evaluación por línea. Los costes unitarios son la **media de los
ratios por réplica**: `mean(coste_i / unidades_i)`, no `mean(coste) / mean(unidades)`. `unit_costs.per_rep` y
`unit_costs.statistic = mean_of_per_replication_ratios` lo hacen explícito. No se publica ningún ratio agregado.

**Comparación emparejada.** Requiere evidencia de números aleatorios comunes: mismas semillas, mismas réplicas y mismo
horizonte y warm-up. Entonces se resumen los `delta_i = alt_i − base_i`, con su propio IC. En otro caso se da sólo la
diferencia de medias y no hay intervalo.

**Comparabilidad.** Cada comprobación lleva un nivel (`checks[]`). No hay normalización ni ponderación automática.

| Nivel | Comprobaciones | Efecto |
|---|---|---|
| HARD_INCOMPATIBILITY | moneda | → NOT_COMPARABLE |
| WARNING | horizonte, demanda, mix, calendarios, base de anualización, cobertura | avisos |
| INFORMATIONAL | réplicas distintas, unidades buenas distintas | información |

Una física distinta es lo que se compara: nunca bloquea. Las categorías que faltan en un lado nunca se rellenan con 0.
El ahorro se calcula sobre las categorías comunes y lo dice (`savings.definition`, `coverage_match`).

**Fórmulas y versiones.** `FORMULAS` (evaluación) y `COMPARISON_FORMULAS` (comparación) llevan versión `_vN`; cada
línea y cada indicador guarda su `formula_id`. Un cambio futuro será `_v2` con otro
`ECONOMICS_ENGINE_VERSION` y, por tanto, otro `evaluation_id`: lo histórico nunca se reinterpreta.

**Persistencia y aprobación.** Reevaluar el mismo run con la misma economía conserva la fila y su aprobación (bug
corregido: `INSERT OR REPLACE` borraba la aprobación). Si una misma identidad diera otro resultado, se produce un error.
Cambiar el precio de la energía no toca la aprobación física, pero crea otra evaluación sin aprobar.

**Robustez numérica.** Entradas NaN o ±inf se rechazan, y lo mismo `runs_per_year` no finito. Un desbordamiento →
`EconomicsError`. Las estadísticas nunca serializan NaN: el IC con n = 1 es `None`. El JSON de evaluación y comparación
es estricto (`allow_nan=False`).

**Determinismo.** Mismo run + mismos supuestos + misma versión → resultado idéntico byte a byte. No hay RNG económico.

**Invariancia física.** Añadir, cambiar o quitar `economics` deja intactos el hash, los KPIs, la traza y 01–05.

## 20. Limitaciones (0.9)

Sin FX, sin NPV/IRR, sin amortización, sin impuestos/overhead/financiación, sin coste de oportunidad ni lost revenue,
sin modelo de periodos (FIXED_PER_PERIOD), sin asignación de costes compartidos, sin scrap por producto, sin modelo
físico de energía, sin incertidumbre de precios, sin optimización ni recomendación, sin IA, sin ratio agregado
(pooled) de costes unitarios, sin normalización por horizonte/demanda/mix, sin semántica automática de solapamiento
downtime ↔ tarifa horaria de máquina del mismo nodo. No validado con datos económicos reales (NOT_TESTED).
