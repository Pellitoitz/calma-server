# Mantenimiento y fiabilidad (motor 0.8.0)

> SimForge 0.8 **representa** averías, reparaciones y mantenimiento preventivo **declarados** por el ingeniero y
> calcula su efecto. No hay mantenimiento predictivo, condition-based, optimización de PM, repuestos ni economía.
> La IA no inventa MTBF, MTTR, frecuencias, recursos ni efectos de reset (el parser V1 congelado no genera este bloque).

## 1. Dónde vive y compatibilidad

Bloque de extensión `maintenance` de `SimModel` (como `availability` y `production`), fuera del núcleo ISMS congelado.

* **Averías legacy** (`nodes.<id>.params.failures: {mtbf, mttr}`): **sin cambios**. Contrato histórico, auditado:
  reloj ELAPSED desde t = 0; un único stream `failures` alterna MTBF y MTTR; falla en cualquier estado (idle, fuera de
  turno, setup, pausa); la reparación es un retardo puro (sin recursos, sin calendario); la operación interrumpida
  conserva su trabajo restante y sus recursos; el MTBF se cuenta desde el final de la reparación (= RESET). 01–05
  idénticos.
* Un nodo usa **o** `params.failures` **o** `maintenance.failure` (`MAINTENANCE_LEGACY_CONFLICT`).
* Sin bloque `maintenance`: mismo hash, mismos streams aleatorios, mismos resultados (también los modelos 0.6/0.7).

```yaml
maintenance:
  nodes:
    machine_a:
      failure:
        clock: OPERATING_TIME                  # ELAPSED_TIME | OPERATING_TIME
        exposure: [PROCESSING]                 # OPERATING_TIME: PROCESSING y/o SETUP, explícito
        time_to_failure: {dist: weibull, shape: 1.5, scale: 120, unit: h}
        repair_time: {dist: lognormal, mean: 45, std: 15, unit: min}
        repair_resources: [{resource: technician}]
        repair_age_effect: RESET               # única soportada en 0.8
        resource_unavailability_policy: FINISH_CURRENT   # si el técnico tiene calendario
      preventive:
        - id: pm_weekly
          trigger: CALENDAR_BASED              # first_due (+ every), tiempo de simulación
          first_due: {dist: constant, value: 6, unit: h}
          every: {dist: constant, value: 168, unit: h}
          duration: {dist: constant, value: 2, unit: h}
          resources: [{resource: technician}]
          start_policy: AFTER_CURRENT_ACTIVITY # única en 0.8
          failure_age_effect: RESET            # RESET | NO_RESET (explícito)
          at_unavailability: FINISH_CURRENT    # si la máquina o el técnico tienen calendario
        - id: pm_usage
          trigger: USAGE_BASED
          usage_states: [PROCESSING]
          usage_threshold: {dist: constant, value: 100, unit: h}
          duration: {dist: constant, value: 30, unit: min}
          start_policy: AFTER_CURRENT_ACTIVITY
          failure_age_effect: NO_RESET
```

CLI: `simforge maintenance show|run <modelo|proyecto>`. UI: pestaña **Maintenance** (configuración, KPIs, cronología).

## 2. Modelo de estados (ortogonal)

* **Condición de la máquina** (nivel nodo, `RunRecord.node_condition_time`): `up` · `down_waiting_repair_resource` ·
  `repair` · `pm_waiting` · `preventive_maintenance`.
* **Actividad del slot** (sin cambios): processing / setup / blocked / starved / waiting_resource; una actividad
  interrumpida por avería conserva su trabajo restante (traza: `interrupted: [{activity, remaining_s}]`).
* **Calendario** (0.6, sin cambios). En la contabilidad del slot, una condición distinta de `up` se registra con su
  nombre dentro del tiempo planificado y con la etiqueta de calendario (`break` / `off_shift`) fuera de él; el
  invariante planificado/no planificado de 0.6 se sigue comprobando.

Así se distinguen `DOWN + processing interrumpido`, `DOWN + setup interrumpido` o `fuera de turno + PM pendiente`.

## 3. Reloj de fallo: edad ≠ muestra

Cada máquina tiene una **muestra** de tiempo hasta el fallo (TTF) y una **edad** = exposición acumulada desde el último
reset. Falla cuando la edad alcanza la muestra. Nada re-muestrea salvo un reset explícito (pausas, descansos, fuera de
turno o idle **no**).

* **ELAPSED_TIME**: la edad avanza todo el tiempo **salvo** con la máquina DOWN (avería hasta fin de reparación) y
  durante el PM activo. Corre fuera de turno, en idle, en setup y esperando un PM. Con tiempos constantes y sin PM
  reproduce exactamente el contrato legacy (test).
* **OPERATING_TIME**: la edad avanza solo en los estados de `exposure` ⊆ {PROCESSING, SETUP}, declarados. PROCESSING
  = segmento de proceso realmente en marcha (también fuera de turno con FINISH_CURRENT); SETUP = setup en marcha.
  No envejecen: idle, descanso, fuera de turno, DOWN, espera de recurso, pausas ni mantenimiento
  (`MAINTENANCE_EXPOSURE_UNSUPPORTED` para cualquier otro estado). `exposure` vacío → `MISSING`; con ELAPSED → ERROR.
* Inicio: el reloj empieza en t = 0 con una muestra del stream `(seed, nodo, "failure_ttf")`.
* **Fallo durante PM**: imposible en 0.8 (el PM activo no pertenece a ninguna exposición).

## 4. Reparación correctiva

`FAILURE → DOWN (down_waiting_repair_resource) → REPAIR (repair) → UP`.

* Al fallar: las actividades en curso se interrumpen por la vía única `_interrupt` (conservan restante y recursos,
  como legacy); **ninguna actividad nueva empieza mientras la máquina está DOWN** (esperan en la puerta sin tomar
  recursos).
* Recurso de reparación (como mucho uno en 0.8): tarea `<nodo>#repair` en el pool, regla del recurso (FIFO / PRIORITY
  con la prioridad estática del nodo); nunca "la máquina que más produce". La espera de técnico es
  `down_waiting_repair_resource`, no tiempo de reparación.
* La reparación **no** depende del calendario de la máquina (como legacy); solo de la disponibilidad de su recurso.
  Si el técnico tiene calendario: `resource_unavailability_policy: FINISH_CURRENT` (obligatorio; única opción en 0.8:
  una reparación empezada se termina).
* Tiempo de reparación: stream `(seed, nodo, "repair")`.
* `repair_age_effect: RESET` (nueva muestra de TTF al terminar la reparación = comportamiento legacy). `NO_RESET`
  dejaría la edad en el umbral ya alcanzado (fallo inmediato) y exigiría reparación mínima / edad virtual: **no
  soportado** (`MAINTENANCE_REPAIR_NO_RESET_UNSUPPORTED`).
* **Reparada ≠ disponible**: si la reparación termina fuera de turno la máquina queda `up` pero no produce hasta que
  el calendario lo permite; si el turno empieza con la máquina aún en reparación, no produce hasta que termina.

## 5. Mantenimiento preventivo

* **CALENDAR_BASED**: vencimientos fijos `first_due + k·every` (tiempo de simulación; con `relative_week` el lunes
  06:00 es `first_due = 6 h, every = 168 h`). Constantes obligatorias (`BAD_PARAM` si no).
* **USAGE_BASED**: uso acumulado en `usage_states` ⊆ {PROCESSING, SETUP} desde el **fin** de la última ejecución de
  ese PM; umbral constante > 0.
* **PM_DUE ≠ PM_START**: al vencer, el PM queda **pendiente**. Un vencimiento de un PM ya pendiente se fusiona
  (`pm_due_merged`), no se acumula.
* **AFTER_CURRENT_ACTIVITY** (única política en 0.8; `IMMEDIATE_INTERRUPT` no se implementa): la actividad en curso
  (incluida una interrumpida o pausada) termina; **ninguna actividad nueva empieza** con un PM pendiente; la máquina
  queda reservada (`pm_waiting`) hasta que: no está DOWN, el calendario del PM está disponible (calendario propio de
  la máquina + calendario del recurso de PM) y el recurso de PM está concedido. Si mientras espera el recurso la
  máquina falla, el recurso se devuelve y el PM espera a la reparación (nunca PM y reparación a la vez, ni técnico
  retenido con la máquina averiada).
* PM fuera de turno o en un **descanso**: no empieza (descanso = indisponibilidad de calendario). Con calendario,
  `at_unavailability: FINISH_CURRENT` es obligatorio (un PM empezado termina aunque acabe el turno).
* Duración: stream `(seed, nodo, "pm", <id>)`.
* `failure_age_effect`: `RESET` (edad 0 y nueva muestra de TTF) o `NO_RESET` (edad y muestra intactas).
* **El mantenimiento no cambia `setup_state`** (A→B en curso cuando vence un PM: el setup termina, estado B, PM, sigue
  en B, sin segundo setup).
* Varios PM pendientes: se ejecutan en orden de vencimiento, de uno en uno.

## 6. Orden en un mismo instante (sin planificador nuevo)

* Transiciones de calendario (URGENT, 0.6) y vencimientos de PM por calendario (URGENT) al principio del instante;
  un vencimiento por uso se marca de forma síncrona al terminar el segmento que alcanza el umbral, antes de que pueda
  empezar otra actividad.
* Averías: eventos ordinarios del instante. Una operación que llega a 0 s restantes en el instante de la avería está
  completada (como con calendarios).
* La decisión de **empezar un PM** se toma al final del instante (como las decisiones de recursos): ve las averías,
  transiciones y finales de actividad de ese instante. Por tanto, avería y vencimiento de PM simultáneos → primero la
  avería; el PM espera la reparación.
* Casos fijados por test: avería en SHIFT_END, fin de reparación en SHIFT_START, PM_DUE en fin de proceso, PM_DUE en
  SHIFT_END, avería en fin de setup, avería y PM_DUE simultáneos — trazas idénticas en ejecuciones repetidas.

## 7. Recursos y bloqueos

Reutiliza los pools existentes (`<nodo>#repair`, `<nodo>#pm`). Para no introducir esperas circulares, en 0.8:
como mucho **un** recurso por tarea de mantenimiento (`MAINTENANCE_MULTI_RESOURCE_UNSUPPORTED`); sin carriers ni
recursos WIP_TARGET; nodos con mantenimiento: capacity 1 (`MAINTENANCE_MULTI_SLOT_UNSUPPORTED`).

**Regla anti-bloqueo (ciclos reales).** Grafo de espera entre recursos: una máquina averiable M retiene `h` (recurso
de proceso/setup de una actividad interrumpida) mientras espera su recurso de reparación `r` → arista `h → r`. Un
**ciclo** (incluido `h = r`: el técnico del setup que también repara esa máquina) es un posible bloqueo circular →
`MAINTENANCE_RESOURCE_DEADLOCK_RISK`. Casos seguros permitidos: técnico haciendo PM en A mientras B espera para
reparar (espera, no bloqueo: los recursos de PM nunca se retienen con la máquina DOWN y el PM termina); técnico
recurso productivo de A y reparador de B si no se cierra un ciclo. Limitación conservadora: las cantidades no se
tienen en cuenta (un ciclo con varias unidades también se rechaza). No hay robo de recurso, pre-emption ni
release-and-reacquire.

## 8. Métricas (definiciones exactas, sin redefinir las antiguas)

| Clave (`node.<n>.…`) | Definición |
|---|---|
| `failure_count` | averías en [warm-up, horizonte] |
| `corrective_downtime_h` | avería → fin de reparación = `waiting_for_repair_resource_h` + `active_repair_time_h` |
| `preventive_maintenance_count` / `_time_h` | PM completados / tiempo de PM activo |
| `waiting_for_pm_h` | máquina reservada para un PM vencido que aún no empieza |
| `uptime_h` / `downtime_h` | condición `up` / correctivo + PM + espera de PM (cualquier estado de calendario) |
| `failure_exposure_h` | exposición del reloj de fallo dentro de la ventana |
| `observed_mtbf_exposure_h` | `failure_exposure_h / failure_count` (NaN sin averías) |
| `observed_mean_active_repair_s` | media de duración de reparación (sin espera) de reparaciones terminadas en la ventana |
| `observed_mean_corrective_downtime_s` | media avería → fin de reparación (con espera) |
| `corrective_reliability_availability` | `(planned_available − correctivo dentro de planificado) / planned_available`; sin calendarios, planned = ventana medida. **Solo pérdidas correctivas: el PM NO entra** |
| `reliability_availability` | alias del anterior (mismo valor; nombre de la primera versión de 0.8, se mantiene por compatibilidad) |
| `corrective_downtime_inside_planned_h` / `preventive_maintenance_time_inside_planned_h` | parte dentro del tiempo planificado del nodo (sin calendarios = total) |
| `pm_due_occurrences` | vencimientos de los PM completados (incluidos los fusionados) |
| `mean_pm_delay_s` / `max_pm_delay_s` | `PM_START − primer vencimiento del trabajo`; un retraso, no un incumplimiento |

No se genera OEE: siguen faltando los contratos de Performance y Quality con calendarios/mezcla.

## 9. Traza y auditoría

Eventos: `failure` (clock, ttf, edad, actividades interrumpidas con restante, condición, calendario, setup_state),
`repair_resource_request`, `wait_resource` (`task: <n>#repair`), `repair_start` (duración muestreada, recursos),
`repair_end`, `up`, `pm_due`, `pm_due_merged`, `pm_resource_request`, `pm_resource_returned`, `pm_start`, `pm_end`
(efecto en la edad). `RunRecord.maintenance`: una fila por avería (t_fail, edad, TTF, interrumpidas, inicio/fin de
reparación, muestra, recursos) y por PM (vencimiento, inicio, fin, muestra, edad antes/después). Datos estructurados
listos para informes posteriores.

## 10. Conservación, hash, persistencia

El mantenimiento nunca crea, destruye, duplica ni cambia el tipo o la ruta de entidades, ni el `setup_state`; la
conservación por producto se sigue comprobando. Todo el bloque entra en el `content_hash` (cambiar cualquier campo
invalida la aprobación). Guardar → cargar → ejecutar da la misma traza. Reconstruir desde la descripción conserva el
bloque (`maintenance_carried_over`). Procedencia: las `Duration` llevan `provenance` y los bloques `failure` / PM
admiten `provenance`.

## 11. Limitaciones declaradas (0.8)

Predictivo / condition-based / sensores; reparación imperfecta, edad virtual, `NO_RESET` correctivo; repuestos;
cuadrillas con habilidades, rutas de mantenimiento; PM y reparación simultáneos; mantenimiento oportunista o agrupado;
`IMMEDIATE_INTERRUPT`; PM o reparación con varios recursos; recursos de reparación que sean recursos de proceso/setup
de máquinas averiables; mantenimiento en nodos de capacidad > 1; políticas de calendario distintas de FINISH_CURRENT
para reparación y PM; exposición a estados distintos de PROCESSING / SETUP; OEE; optimización y economía.

Estado: **CODE_COMPLETE + SYNTHETICALLY_VALIDATED**. Sin datos reales: no REAL_DATA_VALIDATED. Una validación real
contrastaría timestamps y número de averías, downtime, espera de técnico, reparación activa, plan y ejecución de PM.

## 12. Cierre técnico 0.8.0: contratos exactos

**ELAPSED_TIME** (no es "todo wall-clock"): la edad avanza mientras la máquina **no** está DOWN (esperando reparación
o en reparación activa) ni en PM activo. Sí avanza en: processing, setup, idle/starved, blocked, espera de recursos
productivos, fuera de turno, descanso, PM pendiente, espera para empezar un PM y espera de su recurso. Por eso una
máquina reservada para un PM puede fallar antes de que el PM empiece (test). Comportamiento legacy sin cambios.

**OPERATING_TIME**: solo los estados declarados (PROCESSING / SETUP). Nada más.

**CALENDAR_BASED = plan fijo**: los vencimientos son `first_due + k·every` aunque una ejecución se retrase (lunes →
ejecutado el miércoles → siguiente vencimiento el lunes siguiente, no miércoles + 7 días).

**USAGE_BASED**: el contador se pone a 0 **solo al completar** el PM (no al vencer, quedar pendiente, conseguir el
recurso ni empezar). Una máquina reservada no produce, así que no acumula uso.

**Vencimientos con un PM pendiente**: un trabajo por plan; los vencimientos adicionales del mismo plan se fusionan
(también si el PM está en curso) y quedan auditados: `due_occurrences`, `due_times`, eventos `pm_due_merged`.

**Retraso y causas**: `delay_s = PM_START − primer vencimiento`. `wait_causes` registra, cada vez que cambian, las
causas presentes (todas las que coinciden, ninguna inventada): `CURRENT_ACTIVITY`, `MACHINE_DOWN`,
`CALENDAR_UNAVAILABLE`, `WAITING_RESOURCE`; evento `pm_waiting`.

**Avería con PM pendiente**: la avería no borra el PM; tras la reparación (y la actividad interrumpida, si la había)
el PM va antes de cualquier trabajo nuevo. Si el recurso de PM se concede con la máquina DOWN (también en el mismo
instante de la avería: las averías se procesan antes que las concesiones de final de instante) se devuelve sin PM y
el PM espera la reparación; sin fugas ni dobles adquisiciones.

**Técnico en PM y otra máquina falla**: no hay pre-emption de mantenimiento; la reparación espera a que termine el PM
y el pool aplica su regla (FIFO / prioridad estática). No existe "correctivo siempre gana".

**Invariante DOWN**: con la condición DOWN/REPAIR no empieza ninguna actividad nueva (proceso, setup, entidad que ya
esperaba, petición concedida durante la avería: el recurso se devuelve al instante). Tras UP, la actividad
interrumpida continúa primero.

**Reparada ≠ productiva** (02:00 reparada, 06:00 turno: `up` + fuera de turno sin producción). **PM y calendario**: el
PM solo empieza con el calendario del nodo (y de su recurso) disponible; nunca aprovecha descansos ni fuera de turno.
**PM/reparación cruzando el fin de turno** (de la máquina o del técnico): FINISH_CURRENT, terminan. Si el recurso no
se había concedido antes del fin de su disponibilidad, se espera a la siguiente.

**Reset**: correctivo solo RESET (NO_RESET exigiría reparación mínima / edad virtual / reparación imperfecta, fuera
de alcance: no se simula con trucos). PM: RESET = edad 0 + nueva muestra; NO_RESET = edad y muestra intactas y
**ningún número aleatorio consumido** (test de la secuencia de muestras).

**Sin doble conteo**: la partición del slot (planificado + descanso + fuera de turno = ventana × slots) nombra la
condición de mantenimiento solo dentro del tiempo planificado; la condición de máquina es otra partición (up + down +
repair + pm_waiting + pm = ventana). El correctivo fuera de turno no infla `corrective_downtime_inside_planned_h`; el
PM que termina fuera de turno se mide entero en `preventive_maintenance_time_h` y su parte planificada en `…_inside_planned_h`.

**Horizonte**: todas las métricas se cierran exactamente en el horizonte (también la exposición del reloj, aunque el
último evento sea anterior); nada se completa artificialmente después (filas abiertas sin fin).

**Mismo instante**: PM_DUE + avería, concesión de PM + avería, fin de reparación + inicio de turno, fin de PM + fin de
turno, avería + fin de setup, avería + fin de proceso, PM_DUE + fin de proceso, PM_DUE + fin de turno — deterministas
(misma traza y KPIs en ejecuciones repetidas), con el mecanismo de instante existente.

**El mantenimiento no cambia `setup_state`** (B → avería → reparación → PM → B) ni crea, destruye, duplica o reencamina
entidades (conservación por producto comprobada).

