# Calendarios, turnos y disponibilidad (motor 0.6.0)

> El **calendario** decide **cuándo** está disponible un recurso o una máquina.
> La **estrategia de dispatch** (FIFO, prioridad, WIP_TARGET) decide **qué trabajo** hace cuando lo está.
> Nada de lo ambiguo se resuelve solo: lo decide el ingeniero y queda en el modelo.

Estado: **SYNTHETICALLY_VALIDATED**. Está probado con casos de prueba de resultado conocido, no con horarios reales de
planta.

## 1. Conceptos de tiempo

| Concepto | Qué es | Ejemplo (turno 06:00–14:00, descansos 45 min, una semana) |
|---|---|---|
| **CALENDAR_TIME** | tiempo transcurrido del horizonte medido (horizonte − calentamiento), × unidades | 168 h |
| **PLANNED_AVAILABLE_TIME** | dentro de turnos, menos descansos, con excepciones | 5 × 7 h 15 min = 36.25 h |
| **BREAK_TIME** | descansos que caen dentro del turno | 5 × 45 min = 3.75 h |
| **OFF_SHIFT_TIME** | ni turno ni descanso (noches, fines de semana, festivos) | 128 h |
| WORKING_TIME | trabajando dentro del tiempo planificado | resultado de la simulación |
| IDLE_AVAILABLE_TIME | disponible y sin tarea | resultado |
| BLOCKED_TIME / STARVED_TIME | bloqueado / sin material, dentro del tiempo planificado | resultado |
| PAUSED_BY_CALENDAR_TIME | operación interrumpida (PAUSE_RESUME / STOP_RESTART) con la pieza en el puesto | resultado |
| trabajo fuera de lo planificado | FINISH_CURRENT: una operación que empezó en turno y termina fuera | resultado |

Siempre se cumple, y el motor lo comprueba en cada réplica (si no, el run se aborta):
`PLANNED_AVAILABLE + BREAK + OFF_SHIFT = CALENDAR_TIME`. Además, la suma de los estados que el motor registra dentro del
tiempo planificado es exactamente el tiempo planificado del calendario: no hay doble conteo.

**Horizonte transcurrido ≠ horas productivas.** El horizonte del modelo (`simulation.horizon`) es siempre tiempo
transcurrido desde t=0. "Simula una semana" significa 168 h, con noches y fines de semana incluidos. "Simula 40 horas
productivas" **no está soportado** en esta versión: elige un horizonte transcurrido que contenga esas horas (el
informe y `simforge calendar show` muestran cuántas horas planificadas contiene). Ejemplo: el modelo 02 con un turno de
06:00 a 14:00 y horizonte de 8 h desde el lunes 00:00 solo tiene 2 h planificadas (06:00–08:00).

## 2. Dónde vive en el modelo

El núcleo ISMS 0.1 está congelado (contrato del benchmark LLM V1), así que los calendarios van en un **bloque de
extensión** `availability`. Un modelo sin ese bloque es exactamente el de antes: el mismo hash, la misma aprobación y
los mismos resultados.

```yaml
availability:
  mode: relative_week          # relative_week | dated (no se mezclan)
  start_weekday: mon           # t = 0 es lunes 00:00
  start_time: "00:00"
  calendars:
    - id: turno_manana
      name: Turno de mañana
      weekly:
        mon: [{start: "06:00", end: "14:00"}]
        tue: [{start: "06:00", end: "14:00"}]
        # ... días sin entrada = no se trabaja
      breaks:
        - {start: "10:00", end: "10:15", days: [mon, tue]}   # sin 'days' = todos los días
        - {start: "12:30", end: "13:00"}
    - id: maquina_24_7
      weekly: {mon: [{start: "00:00", end: "24:00"}], ...}
  resources: {operator_1: turno_manana}      # operarios / herramientas
  nodes: {machine_a: maquina_24_7}           # máquinas/puestos (server) y fuentes
  always_available: [buffer_feeder]          # ALWAYS_AVAILABLE explícito (sin aviso)
  operations:                                # decisión del ingeniero por operación
    assembly: {at_unavailability: PAUSE_RESUME, start_rule: START_ANY_TIME, reason: "..."}
```

Modo **dated** (fechas reales, festivos, horas extra):

```yaml
availability:
  mode: dated
  start_date: 2026-10-05       # t = 0
  start_time: "00:00"
  timezone: Europe/Madrid      # obligatorio, sin valor por defecto (UTC si se quiere UTC)
  calendars:
    - id: turno
      weekly: {...}
      exceptions:
        - {date: 2026-10-12, type: NON_WORKING_DAY, reason: "Fiesta nacional", scope: SHIFTS_STARTING_ON_DATE}
        - {date: 2026-10-17, type: OVERTIME, intervals: [{start: "06:00", end: "12:00"}], reason: "pedido urgente",
           breaks_apply: false}
```

## 3. Turnos

* Un intervalo `[inicio, fin)` está disponible desde `inicio` y deja de estarlo justo en `fin`.
* `22:00–06:00` **cruza la medianoche**: va de las 22:00 de ese día a las 06:00 del siguiente. Pertenece al día en que
  empieza y se cuenta una sola vez. `24:00` es la medianoche del final del día.
* Turnos consecutivos (`06–14` y `14–22`) se **unen**: disponibilidad continua 06–22, sin transición a las 14:00 y sin
  doble disponibilidad.
* Un solapamiento (`06–14` y `13–15`) o un duplicado es un **ERROR**: nunca se cuenta dos veces. Un intervalo de
  duración cero o con formato inválido se rechaza al cargar el modelo.

```
LUN  06:00 ━━━━━━━━ 10:00  [break 10:00-10:15]  10:15 ━━━━ 12:30  [break 12:30-13:00]  13:00 ━━ 14:00   = 7.25 h
```

## 4. Descansos

Son horas del día en unos días de la semana (por defecto todos), y se **restan** del tiempo de trabajo.

* Un descanso pertenece al día en que **empieza**. Un descanso a las 02:00 de un turno de noche que empezó el lunes
  se declara para el **martes**.
* La parte de un descanso que cae fuera del turno no resta nada (`CAL_BREAK_PARTIAL` / `CAL_BREAK_OUTSIDE_WORKING`).
* Los descansos solapados se unen y no restan dos veces (`CAL_BREAKS_OVERLAP`).

Ejemplo: 06:00–14:00 con 10:00–10:15 y 12:30–13:00 → 8 h − 45 min = 7 h 15 min = 26 100 s.

## 5. Excepciones (solo modo `dated`)

| Tipo | Efecto | Decisiones obligatorias |
|---|---|---|
| `NON_WORKING_DAY` | festivo | `scope` si el calendario tiene turnos de noche (ver abajo) |
| `OVERRIDE_WORKING_INTERVALS` | sustituye los turnos de ese día | `breaks_apply` si el calendario tiene descansos |
| `OVERTIME` / `EXTRA_SHIFT` | añade intervalos (horas extra / turno extraordinario) | `breaks_apply` si el calendario tiene descansos |

* Las excepciones actúan sobre los intervalos que **empiezan** en esa fecha.
* **Alcance del festivo** (turno de noche 22:00–06:00 lunes y martes; festivo el martes):

  | `scope` | Turno que empezó el lunes 22:00 | Turno que empieza el martes 22:00 | Disponible |
  |---|---|---|---|
  | `SHIFTS_STARTING_ON_DATE` | se mantiene entero (lun 22:00 → mar 06:00) | eliminado | 8 h |
  | `CALENDAR_DAY` | **recortado** a lun 22:00 → mar 00:00 | eliminado entero (también su parte del miércoles 00:00–06:00) | 2 h |

  Es decir: `CALENDAR_DAY` = quitar los turnos que empiezan en esa fecha **y** cualquier disponibilidad dentro del día
  civil 00:00–24:00 (tests F y G).
* Un festivo junto a otra excepción el mismo día, o dos OVERRIDE el mismo día, es un ERROR.
* No hay calendario mundial de festivos: se introducen uno a uno.
* **DST**: las horas de pared se convierten con la zona horaria. Un turno 22:00–06:00 la noche del cambio de hora en
  Europe/Madrid dura **9 h reales en octubre** y **7 h reales en marzo** (probados ambos; sin horas duplicadas ni
  intervalos negativos): así ocurre en la planta. Si una frontera de turno cae en una hora local que **no existe**
  (02:30 del último domingo de marzo) o que **se repite** (02:30 del último domingo de octubre), se avisa
  (`CAL_DST_BOUNDARY`) diciendo cómo se interpreta: la hora inexistente se toma como la hora de pared tras el salto
  (02:30 → 03:30, regla `fold=0` de zoneinfo) y la repetida como su primera ocurrencia. No se resuelve en silencio:
  revísalo o declara la hora explícitamente.

## 6. Asignación

* **Operarios y herramientas**: `resources: {operator_1: turno}`. Todas las unidades del recurso comparten el
  calendario.
* **Máquinas/puestos (server) y fuentes**: `nodes: {machine_a: maquina_24_7}`.
* **Carriers** (bastidores, palets): no admiten calendario (ERROR). Un bastidor existe siempre; lo que se para es
  quien lo usa.
* **Transportes**: el calendario va en sus operarios, no en el transporte. En esta versión un viaje iniciado siempre
  termina (solo `FINISH_CURRENT`).
* Una operación puede **empezar** solo cuando **todos** sus calendarios están disponibles: el de su propio nodo (si
  tiene) y los de sus operarios/herramientas. El tiempo planificado del nodo es la intersección:

```
máquina   06:00 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 22:00
operario        08:00 ━━━━━━━━━━━━━━━━ 16:00
operación       08:00 ━━━━━━━━━━━━━━━━ 16:00   (planned = 8 h)
```

* Sin calendario: disponible siempre (compatibilidad). En un modelo con calendarios se avisa
  (`CAL_AVAILABILITY_UNDECLARED`), salvo que se declare explícitamente en `always_available`.

## 7. Fin de la disponibilidad durante una operación: la decisión del ingeniero

Cada operación que depende de algún calendario necesita `at_unavailability` y `start_rule`. Si faltan, el modelo no se
ejecuta (`DECISION_INTERRUPTION_POLICY`, `DECISION_START_RULE`): nunca se elige sola, y menos la que daría más
producción.

Ejemplo: fin de turno a las 14:00, siguiente turno a las 06:00, operación de 5 min que empieza a las 13:58.

| Política | Qué ocurre | Termina |
|---|---|---|
| `FINISH_CURRENT` | la operación iniciada termina; el operario sigue hasta acabarla y después queda no disponible. Ese tiempo se registra como trabajo fuera de lo planificado | 14:03 |
| `PAUSE_RESUME` | a las 14:00 se pausa: el trabajo hecho (2 min) se conserva, la pieza se queda en el puesto y el operario se libera. Cuando todo vuelve a estar disponible, la tarea **vuelve a pedir** el operario por la regla de dispatch normal y hace los 3 min restantes | 06:03 |
| `STOP_RESTART` | a las 14:00 se interrumpe y **se pierde** lo hecho. Al volver, empieza de nuevo con la **misma** duración (no se vuelve a muestrear) | 06:05 |

* **Una operación cuyo trabajo restante es 0 exactamente en la frontera está terminada**, con cualquier política, sea
  cual sea el orden de los eventos (por ejemplo, una pieza de 60 s que termina a las 10:00:00 cuando empieza el
  descanso).
* Si el operario se libera durante la pausa y su calendario sigue disponible (el que se paró fue la máquina), queda
  libre para otras tareas.
* La tarea reanudada **no tiene prioridad por volver**: compite por FIFO, prioridad o WIP_TARGET como cualquier otra.
* Si un operario que ya iba de camino llega cuando su turno ha terminado, la operación no empieza: espera a la
  siguiente disponibilidad. El paseo queda registrado como `outside_planned:walking`.

### Regla de inicio

| `start_rule` | Significado |
|---|---|
| `START_ANY_TIME` | puede empezar aunque no quepa en lo que queda de disponibilidad (y entonces aplica la política anterior) |
| `REQUIRE_FULL_WINDOW` | solo empieza si la operación entera cabe antes de que termine la disponibilidad común; si no, espera a la siguiente ventana |

`REQUIRE_FULL_WINDOW` está soportado **solo con tiempos deterministas**. Con tiempos aleatorios es un ERROR
(`CAL_POLICY_UNSUPPORTED`): saber si "cabe" exigiría conocer la muestra antes de empezar, y eso cambiaría el modelo. No
se finge soporte. La duración que cuenta es la del trabajo; el paseo no se incluye. Si la operación es más larga que
cualquier ventana, se avisa (`CAL_NEVER_FITS`): nunca empezaría.

## 8. Colas, fuentes y bloqueos fuera de turno

* Las entidades **no desaparecen** al terminar el turno: siguen en colas y puestos y el WIP se mantiene (el motor
  comprueba que se conservan).
* Una máquina fuera de turno no procesa. Su cola puede seguir creciendo **solo** si lo de antes sigue enviando; el
  bloqueo sale de las capacidades reales (buffer lleno → la estación anterior queda bloqueada).
* **Fuentes**: sin calendario, generan 24/7 (pedidos que llegan siempre). Con calendario propio:
  * llegadas por intervalo: **el reloj de llegadas se mide en TIEMPO DISPONIBLE de la fuente**. Ejemplo: intervalo
    30 min, quedan 10 min de turno → consume esos 10 min, se para fuera de turno y la llegada ocurre 20 min después
    del inicio del turno siguiente (test J). **No** equivale a llegadas externas en tiempo civil que siguen ocurriendo
    mientras la planta está cerrada: para eso, la fuente no lleva calendario (llega 24/7) y la cola espera.
    Un intervalo que se completa exactamente en el fin del turno produce la llegada en ese instante;
  * fuente infinita: no introduce unidades fuera de su disponibilidad.

  No hay un calendario global impuesto a todos los nodos.

## 8 bis. Contratos de 0.6.0 (cierre técnico)

**Recursos durante una operación calendarizada (PAUSE_RESUME / STOP_RESTART).** Los recursos asociados a una operación
calendarizada (sus operarios/herramientas y el propio nodo) se consideran **requeridos durante toda la duración** de
la operación. Si se pierde la disponibilidad de **cualquiera** de ellos, se pausa (o se reinicia) la operación
**completa**: la entidad conserva su plaza y sus carriers; los operarios y herramientas se **liberan** durante la
pausa, aunque su propio calendario siga disponible (pueden hacer otro trabajo por el dispatch normal), y se
**vuelven a solicitar** por el dispatch normal cuando hay de nuevo disponibilidad conjunta, sin prioridad por estar
pausada. Mientras un nodo no está disponible, sus peticiones de recursos pendientes **no se conceden** (conservan su
antigüedad en la cola y compiten de nuevo cuando el nodo vuelve). Si durante la pausa el puesto además se **avería**, los recursos se vuelven a
solicitar sólo cuando el calendario vuelve a estar disponible **y** la reparación ha terminado (no se retiene al
operario con la máquina parada); lo hecho se conserva. Una petición antigua de un nodo fuera de turno no bloquea las
concesiones a otros nodos disponibles.

> **No soportado en 0.6.0**: operaciones multifase en las que el operario solo hace falta en la carga, la máquina
> sigue sola y el operario vuelve a descargar. En 0.6.0 una operación con operario lo necesita durante toda la
> operación; si la máquina se para (por su calendario), la operación entera se para y el operario se libera.

**STOP_RESTART: `RESTART_DURATION_POLICY = REUSE_ORIGINAL_SAMPLE`.** La duración se sortea una vez al empezar la
operación; al reiniciar se repite **la misma** duración (`full`), y se pierde lo hecho. No se consume una nueva muestra
(test I: la siguiente unidad recibe exactamente el mismo sorteo que sin interrupción). SimForge 0.6.0 **no** modela
"cada nuevo intento tiene una duración aleatoria nueva".

**Averías: `FAILURE_CLOCK = ELAPSED_TIME`** (auditado en el código, sin cambios). El tiempo hasta el fallo (MTBF) se
cuenta en **tiempo transcurrido desde el fin de la reparación anterior**, también fuera de turno, en descansos y con la
máquina parada u ociosa; la reparación (MTTR) también es tiempo transcurrido. Un "MTBF de 100 h" son 100 h
transcurridas, **no** 100 h de funcionamiento. Es la semántica histórica (se conserva para no cambiar modelos
existentes); averías por tiempo de operación no existen en 0.6.0. Interacciones probadas:
* avería exactamente en el fin de turno (C): primero la transición de calendario (una única interrupción: pausa con el
  trabajo restante), después la avería no encuentra nada que interrumpir; la reparación sigue su reloj;
* reparación terminada fuera de turno (D): la máquina pasa a `up`, pero **no** empieza ninguna operación, no reanuda
  una pausa y no recibe operarios hasta que su calendario vuelve;
* máquina aún averiada al empezar el turno (E): no produce hasta la reparación. Una operación que empieza (o se
  reanuda) con la máquina averiada **retiene** a sus operarios mientras espera la reparación (semántica histórica de
  averías, también sin calendarios).

**Tiempo restante.** `remaining` solo disminuye durante procesamiento efectivo: la única espera en la que una
interrupción puede llegar es la del propio procesamiento, y toda interrupción (avería, calendario, pre-emption) pasa por
una única vía que retira la operación de la lista de procesos activos antes de interrumpirla. Esperas de operario,
de calendario, de reparación, paseos y re-solicitudes no descuentan nada (tests de cierre).

## 9. Eventos simultáneos: precedencia dentro de un instante

1. **Transiciones de calendario** en t: tienen prioridad URGENT, antes que cualquier otro evento de t e
   independientemente del orden en que se crearon. Se aplican primero a los recursos y luego a los nodos, en el orden
   de declaración del ISMS.
2. Eventos ordinarios en t (fin de operación, llegada...). Una operación que termina en t está terminada.
3. Decisiones de recursos al final del instante (resolución del motor 0.3.0). Ya ven el estado del calendario de
   `[t, ...)`.

Consecuencias:

| En el mismo instante | Resultado |
|---|---|
| 14:00 termina una operación + termina el turno | la operación cuenta; no empieza otra a las 14:00 |
| 14:00 llega una entidad + empieza el descanso | la entidad entra en la cola; empieza cuando termina el descanso |
| 06:00 empieza el turno + llega una entidad | empieza a las 06:00 |
| 10:00 queda libre un recurso + empieza el descanso | queda libre y no recibe tarea hasta el final del descanso |

La precedencia no se ha elegido para maximizar la producción. Es la misma regla para todos los casos y está probada
repitiendo cada caso (resultados idénticos).

## 10. Métricas (KPIs)

| Clave | Definición exacta |
|---|---|
| `resource.X.calendar_time_h` | (horizonte − calentamiento) × unidades |
| `*.X.planned_available_h` | tiempo dentro de ventanas disponibles × unidades/slots. En un **nodo** es la **intersección** de su calendario y los de TODOS los recursos que requiere durante toda la operación: no es la disponibilidad de la máquina independiente de su mano de obra |
| `*.X.break_h`, `*.X.off_shift_h` | descansos dentro de turnos; resto no disponible |
| `*.X.planned_availability_ratio` | planned_available / calendar_time |
| `resource.X.working_planned_h` | working:* + transporting:* dentro del tiempo planificado |
| `resource.X.planned_utilization` | working_planned / planned_available (el paseo no cuenta como trabajo) |
| `resource.X.idle_available_h` | disponible y sin tarea |
| `resource.X.outside_planned_h` | trabajo fuera del tiempo planificado (FINISH_CURRENT) |
| `node.X.planned_utilization` | busy dentro del planificado / planned_available |
| `node.X.paused_by_calendar_h`, `node.X.busy_outside_planned_h` | pausas por calendario; terminar fuera de turno |
| `node.X.blocked_planned_h`, `node.X.starved_planned_h` | bloqueado / sin material dentro del tiempo planificado |
| `node.X.planned_production_time_h` | tiempo de producción planificado (preparado para un OEE futuro) |

* Las métricas clásicas (`node.X.utilization`, `resource.X.utilization`) siguen dividiendo por el tiempo
  transcurrido. No cambian de significado.
* **No se calcula OEE** para nodos con calendario: el tiempo de producción planificado ya existe, pero el OEE completo
  (Disponibilidad × Rendimiento × Calidad con calendario) es de una fase posterior y no se inventa aquí.

## 11. Aprobación, versiones y reproducibilidad

* Los calendarios forman parte del modelo y de su `content_hash`. Cambiar un turno, un descanso, una excepción, una
  asignación o una política crea una versión nueva e invalida la aprobación (`APPROVAL_STALE`).
* Cada run guarda la versión del modelo, `model_hash`, `availability_hash` (hash del bloque de calendarios), la versión
  del motor, las semillas y el horizonte. Cambiar el calendario después no altera un run histórico: la versión
  antigua se vuelve a ejecutar y da lo mismo.
* Misma semilla + mismo modelo + mismo calendario → mismo resultado, también con tiempos aleatorios.

## 12. Herramientas

**CLI**:

```bash
simforge calendar setup <p> --mode relative_week            # o --mode dated --start-date 2026-10-05 --timezone Europe/Madrid
simforge calendar create <p> turno --days mon-fri --shifts 06:00-14:00 --breaks 10:00-10:15,12:30-13:00
simforge calendar create <p> noche --days mon-fri --shifts 22:00-06:00
simforge calendar exception <p> turno --date 2026-10-12 --type NON_WORKING_DAY --reason "festivo" --scope SHIFTS_STARTING_ON_DATE
simforge calendar assign <p> turno --resource operator_1
simforge calendar assign <p> ALWAYS_AVAILABLE --node machine
simforge calendar policy <p> assembly --at-unavailability PAUSE_RESUME --start-rule START_ANY_TIME
simforge calendar show <p>       # vista semanal + horas planificadas en el horizonte
simforge calendar list <p>
simforge calendar validate <p>   # o un fichero de modelo .yaml
```

**UI**: pestaña **Calendars**. Desde ahí se elige el modo, se crean calendarios (días, turnos, descansos), se añaden
excepciones, se asignan a recursos y máquinas, y se decide la política de cada operación. También muestra el resumen
semanal y las horas planificadas. No hace falta editar YAML.

## 13. Validación

Los avisos se clasifican en tres niveles:

* `ERROR`: el modelo no se ejecuta.
* `WARNING`: se ejecuta, pero hay algo a revisar.
* `REQUIRES_ENGINEER_DECISION`: código `DECISION_*`. Bloquea como un error, pero no es un fallo: es una decisión
  pendiente del ingeniero.

| Código | Nivel | Caso |
|---|---|---|
| `CAL_UNKNOWN_CALENDAR`, `CAL_UNKNOWN_TARGET` | ERROR | referencia rota |
| `CAL_SHIFT_OVERLAP`, `CAL_DUPLICATE_SHIFT` | ERROR | doble disponibilidad |
| `CAL_TIMEZONE_MISSING`, `CAL_START_DATE_MISSING` | ERROR | modo dated incompleto |
| `CAL_EXCEPTIONS_NEED_DATES` | ERROR | excepciones con fecha en semana tipo |
| `CAL_CONTRADICTORY_EXCEPTIONS`, `CAL_CONTRADICTORY_ASSIGNMENT` | ERROR | contradicciones |
| `CAL_CARRIER_UNSUPPORTED`, `CAL_NODE_UNSUPPORTED`, `CAL_POLICY_UNSUPPORTED` | ERROR | configuración no soportada |
| `DECISION_INTERRUPTION_POLICY`, `DECISION_START_RULE`, `DECISION_HOLIDAY_SCOPE`, `DECISION_EXCEPTION_BREAKS` | REQUIRES_ENGINEER_DECISION | decisión pendiente |
| `CAL_BREAK_PARTIAL`, `CAL_BREAK_OUTSIDE_WORKING`, `CAL_BREAKS_OVERLAP` | WARNING | descansos sin efecto o unidos |
| `CAL_NO_COMMON_AVAILABILITY`, `CAL_NO_AVAILABILITY_IN_HORIZON`, `CAL_NEVER_FITS` | WARNING | nunca podrá trabajar |
| `CAL_AVAILABILITY_UNDECLARED`, `CAL_EXCEPTION_OUTSIDE_HORIZON`, `CAL_DST_BOUNDARY` | WARNING | a revisar |

## 14. Limitaciones conocidas

* No hay horizonte en horas productivas, solo transcurrido.
* Transportes: solo `FINISH_CURRENT`, y los estados de sus vehículos no se separan por calendario (sus operarios sí).
* `REQUIRE_FULL_WINDOW` solo con tiempos deterministas.
* Averías: `FAILURE_CLOCK = ELAPSED_TIME` (no tiempo de funcionamiento); una máquina puede averiarse por la noche y
  repararse antes del turno; ese tiempo de avería no se cuenta como pérdida planificada.
* Operaciones multifase (operario solo en carga/descarga) no soportadas: los recursos se requieren durante toda la
  operación.
* STOP_RESTART reutiliza la muestra original (`REUSE_ORIGINAL_SAMPLE`).
* WIP_TARGET: una unidad pausada por calendario no cuenta como "en proceso" para el WIP que alimenta.
* No hay mix de productos, setups, mantenimiento preventivo, calendarios por cuadrillas/rotaciones ni absentismo.
* No hay festivos automáticos.
* Validado solo con casos sintéticos: **SYNTHETICALLY_VALIDATED**.

Validación con datos reales de planta: ver [`real_calendar_validation.md`](real_calendar_validation.md).
