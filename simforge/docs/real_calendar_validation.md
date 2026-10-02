# Validación del módulo de calendarios con datos reales de planta

> Motor 0.6.0. No es una fase de desarrollo: es un protocolo para **buscar errores** del módulo de calendarios con
> el horario real de una planta. No se demuestra que SimForge "funciona": se intenta encontrar dónde falla.
> Complementa a [`real_data_validation_protocol.md`](real_data_validation_protocol.md) (datos de proceso).

## 1. Qué se valida y qué no

Se valida que, para **un caso concreto y un periodo concreto**, el calendario que el ingeniero introduce en SimForge
(patrón semanal + descansos + excepciones) reproduce **exactamente** el horario real día a día:

* tiempo planificado disponible, descanso y fuera de turno de cada máquina / operario;
* los instantes de inicio/fin de turno y de descanso (tolerancia **0 s**: son definiciones, no medidas);
* si hay registros reales (PLC/MES/manual), los instantes de pausa / reanudación / fin de operación, con la
  tolerancia = **precisión declarada del dato** (minuto → 60 s), nunca una tolerancia arbitraria.

Producción, utilización y WIP son **evidencia secundaria**: nunca se declara un calendario validado porque "la
producción se parece", ni se declara fallido sólo porque no se parece (eso suele ser tiempo de proceso o averías).

## 2. Selección del caso

Empezar por el caso más simple que tenga datos fiables:

* **una máquina, un operario, uno o dos turnos, una semana**;
* preferiblemente con un descanso fijo y, si existe, un festivo o una hora extra en el periodo;
* una operación cuya política de fin de turno conozca el supervisor.

## 3. Formulario de datos (lo que hay que pedir a planta)

**A. Periodo**: fecha/hora de inicio y fin (hora local), zona horaria IANA (p. ej. `Europe/Madrid`), si el periodo
cruza un cambio de hora, y si hay calentamiento (warm-up: WIP inicial de la semana anterior).

**B. Calendario de la máquina** (`Machine_A`): turnos por día (inicio–fin), descansos en los que la máquina para,
festivos, horas extra, paradas planificadas (mantenimiento preventivo, limpieza). Día a día, no "lo normal".

**C. Operarios** (`Operator_1`): mismo detalle por operario/rol; si el descanso es escalonado o la máquina sigue con
relevo; si el operario atiende otras máquinas.

**D. Comportamiento en los límites** — qué pasa con la pieza en curso al acabar el turno o empezar el descanso:
`FINISH_CURRENT` (se termina) · `PAUSE_RESUME` (se para y se continúa) · `STOP_RESTART` (se pierde y se repite).
Si nadie lo sabe: `MISSING` o `REQUIRES_ENGINEER_CONFIRMATION`. **Nunca se infiere** ni se elige la opción que da
más producción. Quién lo confirma (rol).

**E. Datos observados** (opcionales pero muy valiosos): marcas de tiempo reales de arranque/parada de máquina,
pausas, fin de operación (PLC/MES/hoja manual) con su precisión; producción por turno; averías del periodo
(para separarlas en el análisis, no para ajustar MTBF/MTTR).

## 4. Ficheros del estudio

Estructura en `validation_studies/calendars/` (ver su README). Copiar `TEMPLATE/` a `<STUDY_ID>/`.

| Fichero | Contenido |
|---|---|
| `input/study.yaml` | id, periodo, zona horaria, warm-up, seed, `targets` (alias → elemento del modelo), fuente, quién confirma, fecha de extracción, política de límite, firma |
| `input/calendar_rows.csv` | `resource,date,start,end,kind,note`; `kind` ∈ SHIFT, OVERTIME, BREAK, PLANNED_STOP, HOLIDAY; `end ≤ start` = acaba al día siguiente |
| `input/model.yaml` | modelo SimForge con el calendario introducido como lo haría el ingeniero (no copiando las filas) |
| `input/observed_events.csv` | `timestamp,resource,event,precision_s,source`; `event` ∈ SHIFT_START, SHIFT_END, BREAK_START, BREAK_END, PAUSE, RESUME, RESTART, OPERATION_START, OPERATION_END |
| `input/observed_production.csv` | `from,to,units` (secundario) |

Anonimizar (`Machine_A`, `Operator_1`). No guardar nombres de personas ni datos personales. Si los datos no pueden
salir de planta, la carpeta del estudio se guarda fuera del repositorio y se ejecuta el mismo comando sobre ella.

## 5. Cálculo esperado independiente

`scripts/validation/calendar_validation.py` calcula la disponibilidad esperada **a partir de las filas día a día**
con su propia aritmética de intervalos (unión, diferencia, intersección; zona horaria con `zoneinfo`). **No importa
`simforge.domain.calendar`**: el algoritmo bajo prueba no se reutiliza para calcular lo esperado.

Lado SimForge: verifica y ejecuta `input/model.yaml` con el motor real y extrae las líneas temporales, la
contabilidad de estados del motor (que debe sumar exactamente el tiempo planificado) y las transiciones de calendario
de la traza.

Comprobaciones de configuración (si fallan → `REAL_DATA_TEST_INCOMPLETE`, se corrigen los datos, no el motor):
el modelo verifica; `mode: dated`; inicio del calendario = `period_start` y misma zona; horizonte = periodo.

## 6. Métricas y eventos

Métricas por target, en `[warm-up, fin)`: `CALENDAR_TIME`, `PLANNED_AVAILABLE_TIME`, `BREAK_TIME`, `OFF_SHIFT_TIME`
y, para recursos, `ENGINE_TRACKED_PLANNED_TIME` (contabilidad interna del motor). Todas con tolerancia 0.
Salidas DES (`WORKING`, `IDLE`, `PAUSED_BY_CALENDAR`, `BUSY_OUTSIDE_PLANNED`, `OUTSIDE_PLANNED`) se informan como
INFO: sólo se comparan si hay datos observados.

Tabla de eventos: `EVENT | EXPECTED | SIMFORGE | DELTA_SECONDS | TOLERANCE | PASS/FAIL`. Un evento esperado sin
correspondencia, o una transición de SimForge que no está en el plan, es FAIL.

## 7. Estados

| Estado | Cuándo |
|---|---|
| `NOT_TESTED` | sin datos reales, o estudio sintético |
| `REAL_DATA_TEST_INCOMPLETE` | faltan datos, error de configuración, falta la firma del ingeniero, o la regresión 01–05 no coincide |
| `REAL_DATA_VALIDATION_FAILED` | cualquier métrica o evento estructural FAIL |
| `REAL_DATA_VALIDATED` | todo PASS con tolerancia 0 / precisión declarada, regresión intacta y firma del ingeniero — **sólo para ese caso y periodo** |

Una política de límite (FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART) que no aparece en los datos observados queda
`NOT_OBSERVED_IN_REAL_DATA` y conserva su estado sintético (`SYNTHETICALLY_VALIDATED`).

## 8. Prohibido calibrar

No se modifican tiempos de proceso, distribuciones, capacidades, reglas de despacho, WIP, MTBF/MTTR **ni los
calendarios** para que el resultado encaje. Si el calendario del modelo no coincide con el real, se corrige el
calendario **para que represente la realidad declarada** (con su fuente), nunca para acercar la producción.

## 9. Clasificación de diferencias

Cada FAIL o diferencia relevante se clasifica (columna `classification` de `comparison/*.csv`):

| Clase | Significado |
|---|---|
| `CALENDAR_ERROR` | el motor calcula mal el calendario declarado → bug, se corrige el motor y se añade test |
| `MODEL_SCOPE_DIFFERENCE` | la planta hace algo que el modelo no cubre (relevos, descanso escalonado…) |
| `PROCESS_TIME_DIFFERENCE` | el calendario cuadra; la diferencia viene del tiempo de proceso |
| `FAILURE_MODEL_DIFFERENCE` | averías reales distintas del modelo de fallos |
| `UNMODELLED_EVENT` | evento real no planificado (falta material, reunión…) |
| `DATA_QUALITY` | dato real incompleto, redondeado, con zona horaria errónea… |
| `UNKNOWN` | sin explicar todavía (valor por defecto) |

## 10. Trazabilidad

El informe registra: id del estudio, periodo, zona horaria, fuente del calendario, quién lo confirma, fecha de
extracción, `model_hash`, `availability_hash`, versión del motor, seed, horizonte y el resultado de la regresión
01–05 en el momento de la validación.

## 11. Instrucciones

1. `cp -r validation_studies/calendars/TEMPLATE validation_studies/calendars/<STUDY_ID>`
2. Rellenar `input/study.yaml` y `input/calendar_rows.csv` con el horario real.
3. Construir `input/model.yaml` (ver `input/MODEL_INSTRUCTIONS.md`).
4. Opcional: `observed_events.csv`, `observed_production.csv`.
5. `python scripts/validation/calendar_validation.py validation_studies/calendars/<STUDY_ID>`
6. Revisar `VALIDATION_REPORT.md`; clasificar cada diferencia; si procede, firmar en `study.yaml` y re-ejecutar.
