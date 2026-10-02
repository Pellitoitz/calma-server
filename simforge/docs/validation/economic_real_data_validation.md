# Protocolo de validación económica con datos reales (post-0.9.0)

> Los datos reales validan el modelo. El modelo no corrige los datos para validarse.

Estado:

- **Protocolo:** `READY_FOR_REAL_ECONOMIC_VALIDATION` (versión 1.0).
- **Validación real:** `NOT_EXECUTED`. No hay datos reales en el repositorio; sólo existe un `EXAMPLE_SYNTHETIC`, que
  nunca valida nada.

Herramientas:

- Validador: `scripts/validation/economic_validation.py`. Es una herramienta de validación, no lógica del motor, y
  nunca modifica Economics.
- CLI: `simforge economics validate-real <CASE_DIR>`.
- Casos: `validation_studies/economics/` (TEMPLATE, EXAMPLE_SYNTHETIC; ver `input/FILES.md`).
- Tests: `tests/test_real_economic_validation.py`.

## 1. Propósito

La pregunta que responde el protocolo es: *¿puede SimForge reproducir correctamente una valoración económica real
conocida, a partir de resultados físicos y datos económicos reales, con trazabilidad completa?*

El alcance de cada estudio es siempre **caso + periodo + recursos + categorías + bases + fuentes** realmente observados.

## 2. Qué NO significa validar

Un estudio no demuestra:

- que SimForge encuentre la mejor inversión;
- que Economics represente la contabilidad de una empresa;
- que una empresa deba tomar una decisión concreta;
- que el resultado se generalice a otras plantas;
- que todos los módulos económicos estén validados.

**Prohibido** afirmar «SimForge Economics está validado con datos reales».

## 3. Matriz de capacidades

Se valida capacidad a capacidad. Las 23 capacidades son:

- **Mano de obra:** `LABOR_PAID_TIME`, `LABOR_PLANNED_TIME`, `LABOR_BUSY_TIME`.
- **Máquina y energía:** `MACHINE_TIME_COST`, `ENERGY_COST`, `ENERGY_CONSUMPTION_FROM_DECLARED_POWER`.
- **Material:** `MATERIAL_COST`, `SCRAP_COST`.
- **Mantenimiento:** `REPAIR_LABOR_COST`, `PM_LABOR_COST`, `PER_FAILURE_COST`, `PER_PM_COST`,
  `DOWNTIME_DECLARED_COST`.
- **Ingresos y costes unitarios:** `REVENUE`, `COST_PER_PRODUCED_UNIT`, `COST_PER_GOOD_UNIT`.
- **Inversión y anualización:** `ANNUALIZATION`, `CAPEX`.
- **Escenarios:** `SCENARIO_DELTA`, `EVALUATED_SAVINGS`, `SIMPLE_PAYBACK`, `ANNUAL_RETURN_ON_INCREMENTAL_CAPEX`.
- **Incertidumbre:** `REPLICATION_ECONOMIC_UNCERTAINTY`. Fuera del protocolo 1.0: necesita varios periodos observados.

Cada capacidad termina en uno de estos estados:

| Estado | Cuándo |
|---|---|
| `REAL_DATA_VALIDATED` | ejercitada, niveles A y B en PASS, evidencia independiente, drivers físicos MEASURED o VALIDATED_MODEL_OUTPUT, sin discrepancia material abierta, en el `economic_scope` declarado, con firma del ingeniero y datos no sintéticos |
| `NOT_OBSERVED` | el caso no la ejercita (p. ej. sin PM → `PM_LABOR_COST`). **Nunca es PASS** |
| `NOT_APPLICABLE` | sólo si el ingeniero lo declara con motivo (`not_applicable`) |
| `FAILED` | diferencia fuera de tolerancia que no se explica como «no comparable», o diferencia material abierta |
| `INCOMPLETE` | todo lo demás: dato MISSING, referencia no independiente, tolerancia no justificada, driver no validado, definición distinta, sin firma, fuera de scope, depende de un componente FAILED, sintético… |

Una capacidad validada no implica otra. Por ejemplo, `LABOR_PAID_TIME` validada **no** implica `LABOR_BUSY_TIME`.

Los totales y las comparaciones (costes unitarios, anualización, deltas, ahorro, payback, retorno) nunca se validan
encima de un componente `FAILED`.

## 4. Tres niveles (nunca mezclados)

| Nivel | Compara | Pregunta | Tolerancia |
|---|---|---|---|
| **A. Reproducción aritmética** | SimForge Economics (`evaluate_run` sobre un *run observado* cuyos KPIs son los drivers físicos observados) vs **calculadora de referencia independiente** | ¿reproduce SimForge el cálculo con los mismos drivers e inputs? | representación numérica (1e-9 relativo): mismas magnitudes, misma tarifa y misma fórmula ⇒ igualdad |
| **B. Representatividad de inputs** | cálculo independiente (drivers observados × inputs documentados) vs **resultado de referencia de la empresa** (nómina, factura, controlling…) | ¿representan la tarifa, la base y el precio el concepto económico real del periodo? | derivada de resoluciones o declarada y justificada |
| **C. Representatividad extremo a extremo** | SimForge con drivers **simulados** vs referencia de la empresa | ¿drivers simulados + inputs + fórmulas dan un resultado representativo? | la de B |

Una fórmula puede pasar A y fallar C.

El nivel C sólo se ejecuta con `simulated_run`. Además:

- da `INCOMPLETE` si los drivers simulados no son `VALIDATED_MODEL_OUTPUT` (`drivers_validation`);
- da `INCOMPLETE` si la pregunta de alcance es `UNKNOWN`.

Un fallo en C deja la capacidad en `FAILED`.

**Calculadora de referencia.** Es mínima y explícita: productos y sumas escritos en el propio validador, como
`coste = horas pagadas observadas × tarifa documentada`. No importa `simforge.economics` ni llama a `evaluate_run`
(lo comprueba un test). No es un segundo motor.

## 5. Fuentes, procedencia e independencia de la evidencia

Cada input registra:

- fuente (`source_type`, `source_reference` anonimizada, fechas);
- `confirmed_by_role` y qué representa realmente (`represents`): una fuente «oficial» no es correcta por definición;
- `effective_date`, moneda, base, unidad, `precision`, `provenance`, `included_components`, `economic_concept`.

Clases de evidencia (`evidence_class`):

| Clase | Significado |
|---|---|
| `REAL_SOURCE_INPUT` | alimenta Economics |
| `INDEPENDENT_REFERENCE` | resultado independiente con el que se compara |
| `DERIVED_REFERENCE` | derivado de los mismos datos: sólo consistencia aritmética |
| `ENGINEER_CONFIRMED` | cifra confirmada por el ingeniero; no es un registro independiente |
| `SYNTHETIC` | inventado; nunca valida |

**Circularidad.** Una referencia que procede de SimForge (`SIMFORGE_EXPORT`) es `CIRCULAR` y la métrica queda
INCOMPLETE. Si la misma fuente da a la vez los inputs y la referencia, por ejemplo el mismo Excel con horas, tarifa y
coste, la referencia se trata como `DERIVED`: es real, pero **no independiente**. Sólo sirve para reproducción
aritmética.

## 6. Drivers físicos

Toda cifra económica traza **observación física → KPI físico → input económico → fórmula → resultado**. Cada driver
lleva dos clasificaciones:

- **clase:** `MEASURED | VALIDATED_MODEL_OUTPUT | RECONSTRUCTED | ASSUMED | MISSING`;
- **estado de evento:** `OBSERVED | NO_EVENT | MISSING_DATA`.

Sólo `MEASURED` y `VALIDATED_MODEL_OUTPUT` permiten validar. Con un driver `RECONSTRUCTED`, `ASSUMED` o `MISSING`
el cálculo puede ser aritméticamente correcto (A en PASS), pero la capacidad queda INCOMPLETE y el motivo se muestra.

**MISSING ≠ 0.**

- Un input con `value` vacío es MISSING y nunca se multiplica como 0.
- `0` es un dato válido; ejemplo: CAPEX = 0 explícito.
- Un CAPEX sin declarar no es 0: payback INCOMPLETE.

**NO_EVENT ≠ MISSING_DATA.**

- `NO_EVENT` (valor 0): el registro existe y no hubo eventos.
- `MISSING_DATA` (valor vacío): no hay registro.
- Mezclarlos es un error de configuración.

## 7. Tolerancias

No hay porcentaje universal. Por defecto, la tolerancia de B se **deriva** de las resoluciones:

`|tarifa| × resolución_magnitud + |magnitud| × precisión_tarifa (+ suma por línea) + precisión_referencia / 2`

Ejemplo: tarifa con precisión de 0,01 €/h × 40 h + 0,005 € → 0,405 €.

Una tolerancia declarada exige `tolerance_basis` (`ROUNDING | SOURCE_PRECISION | TIME_RESOLUTION |
MONETARY_RESOLUTION | METHOD`) y `tolerance_reason`. Se rechaza en estos casos:

- es mayor que la derivada, salvo con base `METHOD` y motivo;
- es relativa sin base `METHOD`;
- no se puede derivar ninguna y tampoco se declara.

Payback y retorno no tienen cota derivable, así que su tolerancia debe declararse y justificarse (p. ej. el redondeo
a 0,01 años del informe de controlling).

## 8. Guía por capacidad (el protocolo se adapta a 0.9, no al revés)

- **Mano de obra.** Registra el `economic_concept` de la referencia: `PAYROLL_COST` ↔ `PER_PAID_HOUR`,
  `PLANNED_CAPACITY_COST` ↔ `PER_PLANNED_HOUR`, `ACTIVITY_COST` ↔ `PER_BUSY_HOUR`. `INCREMENTAL_LABOR_COST` u otros
  conceptos no tienen base en 0.9. Si no coinciden: `BASIS_DIFFERENCE` y NOT_COMPARABLE. La contabilidad de la empresa
  nunca se reinterpreta; por ejemplo, si paga el turno completo, el tiempo ocupado no es referencia de nómina.
- **Tiempo pagado.** Documenta de dónde sale: nómina, horario, horas declaradas… Compáralo con `CALENDAR_WINDOW`
  (ventana medida), `PLANNED_AVAILABLE` (turnos − descansos dentro de la ventana) o `DECLARED` sólo si corresponden
  conceptualmente. Ninguna regla es «la correcta» para todas las empresas: es una base de valoración declarada.
- **Máquina.** Registra `included_components` (ownership, maintenance, energy, depreciation, overhead…). Si la tarifa
  incluye energía (o mantenimiento, o mano de obra) y esa categoría se valora aparte, la capacidad queda INCOMPLETE por
  posible doble conteo. Si la referencia incluye componentes que el input no tiene: `COVERAGE_DIFFERENCE`.
- **Energía.** Hay que separar tres cosas:
  - el consumo físico: `ENERGY_CONSUMPTION_FROM_DECLARED_POWER` frente a un contador (`ENERGY_METER`);
  - el precio;
  - el coste.

  0.9 no tiene física de energía: los kWh salen de potencia declarada × horas de estado. Validar el coste a partir de
  kWh medidos no valida la «física de energía».
- **Material / scrap.** Documenta el material consumido, la producción buena, el scrap y el precio. Si la empresa
  contabiliza por unidad lanzada (`PER_CONSUMED_UNIT`), no se añade el scrap otra vez.
- **Mantenimiento.** Separa el tiempo activo del técnico en reparación y en PM, las esperas, los repuestos, el
  servicio externo y el downtime. Repuestos y servicios no están soportados en 0.9: `out_of_scope`. Nunca se fuerzan.
- **CAPEX.** Exige evidencia documental (`QUOTE`, `PURCHASE_ORDER`, `INVOICE`, `APPROVED_INVESTMENT`) y sólo las
  partidas que existan. No se reconstruye un CAPEX desconocido.
- **Anualización.** `runs_per_year` debe venir de `PRODUCTION_CALENDAR`, `OPERATING_PLAN`, `PRODUCTION_RECORD`, `ERP`
  o `MES`; nunca se infieren «220 días» ni «2 turnos». Primero se comparan los valores del run y después los anuales.
- **Payback.** Requiere base, alternativa, anualización, CAPEX incremental y cobertura comparable. La referencia debe
  usar la **misma** definición (`method: SIMPLE_PAYBACK`); un payback descontado da `FORMULA_DEFINITION_DIFFERENCE`.
  El retorno exige `ANNUAL_SAVINGS_OVER_INCREMENTAL_CAPEX`.
- **Comparación de escenarios.** Hay que registrar las diferencias de horizonte, demanda, mix, calendario, categorías
  y anualización (los avisos de 0.9 aparecen en el informe). No se corrige nada automáticamente, y no hay PASS si la
  referencia compara conceptos distintos.

## 9. Diferencias, clasificación y firma

Cada diferencia lleva un id (`A:R1`, `B:R1`, `B:R5:FORMULA_DEFINITION_DIFFERENCE`…) y una clase:

- `ROUNDING`, `SOURCE_PRECISION`;
- `PHYSICAL_DRIVER_DIFFERENCE`, `ECONOMIC_INPUT_DIFFERENCE`;
- `BASIS_DIFFERENCE`, `FORMULA_DEFINITION_DIFFERENCE`, `PERIOD_DIFFERENCE`, `COVERAGE_DIFFERENCE`;
- `MISSING_DATA`, `MODEL_SCOPE_DIFFERENCE`;
- `POSSIBLE_SOFTWARE_BUG`, `UNCLASSIFIED`.

Las diferencias del nivel A se clasifican automáticamente como `POSSIBLE_SOFTWARE_BUG`. El ingeniero las clasifica en
`classifications.csv`. Nada se corrige automáticamente.

- Una diferencia fuera de tolerancia **nunca** es PASS.
- Clasificada como «no comparable» (`BASIS_`, `FORMULA_DEFINITION_`, `PERIOD_`, `COVERAGE_DIFFERENCE`,
  `MISSING_DATA`, `MODEL_SCOPE_DIFFERENCE`), deja la capacidad en INCOMPLETE.
- Cualquier otra clase, o una diferencia material abierta, deja la capacidad en FAILED.
- La firma (`signoff`: role, date, reviewed, scope_accepted) confirma la revisión, la clasificación y el alcance.
  **No convierte una discrepancia en exactitud.**

## 10. Pregunta de alcance obligatoria

*«¿Existe algún coste o condición económica necesaria para interpretar este resultado que no esté representado en los
datos entregados?»* La respuesta es `YES`, `NO` o `UNKNOWN`:

- `YES`: los conceptos se listan en la frase final.
- `UNKNOWN`: no se permite ninguna afirmación de representatividad extremo a extremo (C queda INCOMPLETE).

## 11. Criterios

**PASS de una métrica.** Se cumplen todas estas condiciones:

1. concepto y fórmula equivalentes;
2. inputs trazables;
3. drivers respaldados;
4. referencia independiente o correctamente clasificada;
5. diferencia dentro de una tolerancia justificada;
6. ninguna discrepancia material abierta.

**Validación de una capacidad.** Ver la tabla del §3. Se exige al menos un caso real que la ejercite con evidencia
suficiente y con firma. No se extrapola a otras bases.

**Estudio válido para su alcance** (`REAL_DATA_STUDY_VALID_FOR_SCOPE`). Se cumplen todas estas condiciones:

- datos no sintéticos;
- fuentes registradas;
- periodo y scope definidos;
- drivers clasificados;
- inputs trazables;
- referencias clasificadas;
- tolerancias justificadas;
- todas las capacidades del `economic_scope` en `REAL_DATA_VALIDATED`, sin discrepancias materiales abiertas;
- regresión 01–05 correcta;
- firma del ingeniero.

En otro caso, el estudio queda `REAL_DATA_STUDY_INCOMPLETE` o `REAL_DATA_STUDY_FAILED`. Los datos sintéticos dan
siempre `SYNTHETIC_DEMO_NOT_A_VALIDATION`, y un error de configuración da `CONFIG_INVALID`.

**Frase final (la única permitida).**

> REAL_DATA_VALIDATED for [capabilities] in case [case_id] during [period], using [economic bases].
> Not validated by this study: [list].

Si alguna capacidad la necesita, la frase añade los conceptos no representados.

## 12. Procedimiento operativo

1. Definir la pregunta económica (`economic_question`).
2. Definir el scope (`economic_scope`, `out_of_scope`, `not_applicable`).
3. Identificar los drivers físicos y clasificarlos (`physical_drivers.csv`).
4. Recoger los inputs económicos (`economic_inputs.csv`) tal como existen. No se inventan valores ni se rellenan
   huecos.
5. Registrar las fuentes y qué representan (`sources.csv`).
6. Obtener la referencia independiente (`references.csv`), con su concepto, método y periodo.
7. Declarar las tolerancias o dejar que se deriven de las resoluciones.
8. Ejecutar SimForge: `simforge economics validate-real <CASE>`, que ejecuta los niveles A y C.
9. El mismo comando ejecuta también la calculadora de referencia (niveles A y B).
10. Comparar: `comparison/metrics.csv`.
11. Clasificar las diferencias: `classifications.csv`. Después se vuelve a ejecutar el comando.
12. Revisar la matriz de capacidades: `comparison/capabilities.csv`.
13. Firma del ingeniero en `case.yaml`.
14. Emitir la frase final (sección Q del `VALIDATION_REPORT.md`, secciones A–Q).

## 13. Bugs y lagunas semánticas

**Posible bug del software** (p. ej. una diferencia en el nivel A):

1. Aislarlo con una reproducción mínima.
2. Escribir un test que falle antes del arreglo.
3. Confirmar la causa.
4. Corregir.
5. Comprobar que el test pasa.
6. Pasar la suite completa, el FREEZE y 01–05.

Nunca se ajustan los datos, las tolerancias, la referencia ni los resultados esperados para que SimForge pase.

**Semántica de 0.9 insuficiente para el caso real.** No se cambia: se registra en `semantic_gaps` con el caso, la
semántica actual, por qué no lo representa, el impacto y la posible evolución. El protocolo valida 0.9, no desarrolla
0.9.1.

## 14. Confidencialidad

- Todo se anonimiza: Company_A, Assembly_Cell_1, roles en lugar de nombres, y referencias internas como
  `SRC-HR-RATES-2026`.
- El validador rechaza correos electrónicos y cuentas bancarias.
- Si los datos no pueden salir de la planta, la carpeta del caso se guarda fuera del repositorio y se ejecuta el mismo
  comando sobre ella.

## 15. Paquete mínimo que se pide al ingeniero

1. Proceso o recurso.
2. Periodo.
3. Output producido.
4. Output bueno.
5. Scrap, si aplica.
6. Horas relevantes, diciendo cuáles.
7. Base económica que usa la empresa.
8. Tarifa o coste.
9. Moneda.
10. Fuente de cada valor.
11. Cálculo de referencia real, si existe.
12. Precisión o resolución de cada valor.
13. Calendario, si interviene.
14. Anomalías del periodo.
15. Conceptos incluidos en cada tarifa.
16. Costes necesarios para producir que no estén en los datos.

Además, la pregunta de alcance obligatoria del §10.

Para un primer caso sencillo se recomienda `LABOR_PAID_TIME` + `MACHINE_TIME_COST` + `COST_PER_GOOD_UNIT`, de una
máquina o célula durante una semana. El resto sólo se añade si existen datos reales suficientemente buenos.

## 16. Limitaciones del protocolo 1.0

- Un solo periodo por caso, así que `REPLICATION_ECONOMIC_UNCERTAINTY` queda fuera.
- La comparación de escenarios usa exactamente dos escenarios.
- Las tolerancias derivadas son cotas lineales de primer orden.
- El nivel C usa la media simulada.
- La detección de datos personales es básica (correos y cuentas bancarias).
- No hay importador XLSX: las plantillas son CSV.
