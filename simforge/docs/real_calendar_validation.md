# Validación del módulo de calendarios con datos reales de planta

> Motor 0.6.0. No es una fase de desarrollo: es un protocolo para **buscar errores** del módulo de calendarios con
> datos reales. No se intenta demostrar que SimForge "funciona". Complementa a
> [`real_data_validation_protocol.md`](real_data_validation_protocol.md) (datos de proceso).
> Herramienta: `scripts/validation/calendar_validation.py`. Estudios: `validation_studies/calendars/`.

## 1. Dos preguntas que no se mezclan

| | Pregunta | Se compara | Tolerancia |
|---|---|---|---|
| **A. Validación estructural del calendario** | ¿SimForge reproduce exactamente el calendario que se le configuró? | horario día a día (PLANNED / RECONSTRUCTED) **vs** líneas temporales, contabilidad de estados y transiciones del motor | **0 s** (ambos lados son definiciones) |
| **B. Representatividad operativa** | ¿Ese calendario representa lo que pasó realmente en planta? | datos OBSERVED **vs** calendario planificado | la **resolución declarada** de cada dato |

Que la primera operación real empiece a las 06:07 con un turno de 06:00, o que el último trabajo termine a las
14:12, **no** significa que el calendario de SimForge esté mal: es una diferencia plan/realidad (B) que se analiza
y clasifica. La validación estructural (A) sólo compara el calendario esperado con el de SimForge.

## 2. Tipos de evidencia

* `PLANNED` — el plan oficial (plan de RR. HH., cuadrante, calendario MES).
* `OBSERVED` — registrado cuando ocurrió (PLC, MES, hoja de turno, observación directa).
* `RECONSTRUCTED` — reconstruido a posteriori (p. ej. turnos deducidos de fichajes o de producción).

`calendar_rows.csv` sólo admite PLANNED o RECONSTRUCTED (es el calendario declarado). Los instantes OBSERVED van en
`observed_events.csv`. Sólo la evidencia **OBSERVED, con reloj fiable y en un día cubierto** cuenta como evidencia
**fuerte** para validar un comportamiento en frontera; el resto se muestra como **WEAK** con el motivo.

## 3. Eventos de calendario ≠ eventos operativos

* Calendario: `SHIFT_START`, `SHIFT_END`, `BREAK_START`, `BREAK_END`.
* Operativos: `FIRST_PROCESS_START`, `LAST_PROCESS_END`, `FIRST_UNIT_COMPLETED`, `LAST_UNIT_COMPLETED`,
  `OPERATION_START`, `OPERATION_END`, `PAUSE`, `RESUME`, `RESTART`.

Un evento operativo **nunca** se compara como si fuera un evento de calendario. Se comprueba contra la disponibilidad
planificada (la conjunta máquina ∩ operario cuando ambos son targets):

* inicio dentro de la disponibilidad → `CONSISTENT` (se informa el desfase: "+240 s tras el inicio de turno");
* fin después de una frontera → `AFTER_BOUNDARY`: evidencia de FINISH_CURRENT si hubo un inicio observado antes de
  la frontera y ninguna pausa; **no** es un error de calendario;
* `PAUSE` en una frontera y `RESUME` / `RESTART` en el siguiente inicio de disponibilidad → evidencia de
  PAUSE_RESUME / STOP_RESTART;
* cualquier otra cosa → `PLAN_VS_ACTUAL_DIFFERENCE`, que se clasifica (UNKNOWN hasta que haya evidencia).

## 4. Matriz de capacidades

El resultado nunca es "los calendarios de SimForge están validados con datos reales". Se valida **por capacidad**:

`shift_start_end, breaks, multiple_shifts, overnight_shift, holiday, overtime, extra_shift, calendar_day,
shifts_starting_on_date, FINISH_CURRENT, PAUSE_RESUME, STOP_RESTART, DST_spring, DST_autumn, source_calendar,
machine_operator_calendar_intersection`

| Estado real | Cuándo |
|---|---|
| `REAL_DATA_VALIDATED` | el periodo **ejercitó** la capacidad y todos los checks estructurales de los target-días que la ejercitaron pasan (y el estudio entero es VALIDATED) |
| `NOT_OBSERVED_IN_REAL_DATA` | no ocurrió en el periodo, o sólo hay evidencia débil, o el estudio no es VALIDATED |
| `REAL_DATA_VALIDATION_FAILED` | ocurrió y algún check falla, o el comportamiento observado contradice la política declarada |
| `NOT_APPLICABLE` | imposible en este caso (p. ej. intersección sin par máquina + operario entre los targets) |

**Coverage gate** (qué hace falta para ejercitar cada capacidad):

| Capacidad | Ejercitada si… |
|---|---|
| shift_start_end / breaks / overtime / extra_shift / holiday | hay filas de ese tipo en el periodo (holiday: se comprueban el día, el anterior y el siguiente) |
| multiple_shifts | ≥ 2 turnos (SHIFT / EXTRA_SHIFT) el mismo día para un target |
| overnight_shift | una fila con fin ≤ inicio (se comprueban ambos días) |
| calendar_day / shifts_starting_on_date | el modelo tiene un NON_WORKING_DAY con ese `scope` en un calendario con turnos de noche |
| DST_spring / DST_autumn | el periodo cruza el cambio **y** un intervalo planificado lo contiene. Si no, NOT_OBSERVED (no se busca un periodo con DST sólo para obtener un PASS) |
| FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART | evidencia **fuerte** observada en una frontera, coherente con la política declarada, **y** SimForge la aplica en la ejecución |
| machine_operator_calendar_intersection | máquina y operario son targets, sus calendarios difieren en el periodo y todo arranque/reanudación de SimForge cae dentro de la disponibilidad conjunta calculada de forma independiente |
| source_calendar | una fuente con calendario es target |

El informe declara el alcance de forma explícita: *"REAL_DATA_VALIDATED for capabilities [...] in case X (targets)
during period Y. Not valid for other machines, periods, policies, exceptions or the whole plant."*

## 5. Cobertura y completitud

* **Calendario**: cada target necesita filas para **todos** los días del periodo (`OFF` = día no laborable conocido,
  sin horas). Un día sin filas, o declarado `MISSING` en `missing_data.csv`, bloquea la validación
  (`REAL_DATA_TEST_INCOMPLETE`). Un día no es "no laborable" por defecto.
* **Streams observados** (`observed_events`, `observed_metrics`, `failures`): `data_streams` en study.yaml declara qué
  días cubren; `missing_data.csv` abre huecos. Sin declarar = `NOT_AVAILABLE`. Un día sin datos **no** es "cero
  eventos", "sin averías" ni "sin excepción". La tabla de cobertura se muestra siempre (p. ej. `failures 0/7`).

## 6. Procedencia y relojes

`study.yaml → sources`: por fuente, `source_type` (PLC, MES, ERP, SHIFT_SHEET, HR_SCHEDULE, MANUAL_OBSERVATION,
ENGINEER_CONFIRMATION, OTHER), `source_reference`, `confirmed_by_role` (cargo, nunca nombre), `extraction_date`,
`clock_sync_status` (CONFIRMED_SYNCED / KNOWN_OFFSET / UNKNOWN), `known_offset_s` (reloj de la fuente − referencia),
`offset_reference`, `apply_offset`. Cada fila y cada evento llevan `evidence_type`, `source_ref` y
`temporal_resolution`.

* `KNOWN_OFFSET` con `apply_offset: true`: se usa el timestamp corregido y cada corrección aparece en el informe
  (raw → corregido, offset, referencia) y en `comparison/clock_corrections.csv`. Nunca se corrige en silencio.
* `KNOWN_OFFSET` sin aplicar, o `UNKNOWN`: la evidencia es WEAK y no valida ninguna política.
* Toda fuente con offset aparece en Differences como `SOURCE_CLOCK_DIFFERENCE`.

## 7. Precisión temporal

* Estructural: tolerancia 0 s. Un dato del calendario más preciso que su resolución declarada (06:00:30 a `MINUTE`)
  se rechaza (DATA_QUALITY → INCOMPLETE).
* Observados: tolerancia = resolución declarada (`SECOND` 1 s, `MINUTE` 60 s, `FIVE_MINUTES`, `FIFTEEN_MINUTES`,
  `HOUR`). Un dato a minutos no se trata como si tuviera precisión de segundos; un timestamp con segundos declarado a
  minutos se marca DATA_QUALITY. Sin tolerancias porcentuales para calendarios.

## 8. Otras condiciones de disponibilidad

Pregunta obligatoria (`additional_constraints`): *"Además de la máquina y el operario, ¿existe alguna otra condición
necesaria para que este puesto pueda producir?"* (supervisor, técnico, herramienta compartida, horno, útil, material
liberado, permiso, equipo aguas abajo…). Sin respuesta → INCOMPLETE; `[]` sólo si planta confirma que no hay. Cada
condición no modelada se registra como `MODEL_SCOPE_DIFFERENCE`. **No** se modela automáticamente y **no** se toca el
calendario para compensarla.

## 9. Disponibilidad planificada ≠ trabajo real

`PLANNED_AVAILABLE_TIME` (calendario) y `ACTUAL_WORKING_TIME` (observado) se mantienen separados. 8 h planificadas
frente a 6,7 h trabajadas no es un error de calendario (starvation, bloqueo, avería, espera, material, microparadas…).
Métricas operativas (`observed_metrics.csv`): Observed | SimForge | Difference | Relative difference |
Classification, **sin umbral porcentual**. El calendario puede quedar validado en su alcance aunque el throughput
difiera, si la diferencia no procede del calendario. La representatividad operativa tiene su propio veredicto:
NOT_ASSESSED / DIFFERENCES_TO_CLASSIFY (n) / ASSESSED.

## 10. Clasificación de diferencias

`CALENDAR_ERROR`, `MODEL_SCOPE_DIFFERENCE`, `PROCESS_TIME_DIFFERENCE`, `FAILURE_MODEL_DIFFERENCE`,
`UNMODELLED_EVENT`, `DATA_QUALITY`, `SOURCE_CLOCK_DIFFERENCE` (diferencia demostrada entre relojes), `UNKNOWN`.
El ingeniero clasifica en `input/classifications.csv` (`id, classification, evidence`); **sin evidencia sigue
UNKNOWN**. Nada se atribuye automáticamente al motor. Un FAIL estructural clasificado sigue siendo FAIL.

## 11. Estados del estudio

| Estado | Cuándo |
|---|---|
| `NOT_TESTED` | sin datos reales, o estudio sintético (aunque todo pase) |
| `REAL_DATA_TEST_INCOMPLETE` | faltan datos o respuestas, cobertura de calendario < 100 %, error de configuración, sin firma, regresión 01–05 distinta, o ninguna capacidad ejercitada |
| `REAL_DATA_VALIDATION_FAILED` | cualquier FAIL estructural, violación de la intersección, o capacidad FAILED |
| `REAL_DATA_VALIDATED` | todo lo anterior limpio + firma — **sólo para las capacidades ejercitadas, en ese caso y periodo** |

## 12. Prohibido calibrar

No se modifican tiempos de proceso, distribuciones, capacidades, dispatch, WIP, MTBF/MTTR **ni calendarios** para que
el resultado encaje. Si el calendario del modelo no coincide con el real, se corrige para representar la realidad
declarada (con su fuente), nunca para acercar la producción.

## 13. Formulario para planta (lo que hay que pedir)

* **A. Periodo**: inicio/fin en hora local, zona horaria IANA, si cruza cambio de hora, warm-up.
* **B. Calendario de la máquina**: día a día (también los no laborables), turnos, descansos con parada, festivos,
  horas extra, turnos extra, paradas planificadas; fuente y cargo que lo confirma; resolución (minutos, normalmente).
* **C. Operarios**: lo mismo por operario/rol; descansos escalonados, relevos, si atiende otras máquinas.
* **D. Frontera**: qué pasa con la pieza en curso al acabar turno / empezar descanso: FINISH_CURRENT /
  PAUSE_RESUME / STOP_RESTART, o MISSING / REQUIRES_ENGINEER_CONFIRMATION. Nunca se infiere.
* **E. Otras condiciones** necesarias para producir (sección 8).
* **F. Datos observados** (opcionales): eventos con timestamp, sistema de origen, resolución y **sincronización de
  reloj** (sincronizado / offset conocido y cómo se midió / desconocido); producción por turno; tiempo trabajado;
  averías; días que cubre cada fuente y huecos conocidos.

## 14. Instrucciones

1. `cp -r validation_studies/calendars/TEMPLATE validation_studies/calendars/<STUDY_ID>` (o fuera del repositorio
   si los datos no pueden salir de planta).
2. Rellenar `input/` (ver `input/FILES.md`) y construir `input/model.yaml` (ver `input/MODEL_INSTRUCTIONS.md`).
3. `python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY_ID>`
4. Revisar `VALIDATION_REPORT.md` y `comparison/*.csv`; clasificar diferencias con evidencia; firmar y re-ejecutar.
