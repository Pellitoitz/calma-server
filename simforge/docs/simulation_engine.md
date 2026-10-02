# Motor de simulación

## ¿Por qué SimPy (oculto)?

Evalué: SimPy, motor propio, Salabim, Ciw, AnyLogic.
SimPy gana para V1: MIT, maduro, procesos como generadores (la lógica de un operario se lee como la describe
un ingeniero), sin dependencia gráfica, ejecución local rápida. Su debilidad (no trae bloqueo, pools con
decisiones ni estadísticas) es precisamente lo que queremos controlar nosotros. Por eso **ningún módulo fuera de
`simforge/engine/des/` importa SimPy**: el dominio ve `SimulationEngine.run(CompiledModel, seed) -> RunRecord`.

## Bloques (engine/des/nodes.py)

| Clase | Comportamiento |
|---|---|
| `IndustrialSource` | suministro infinito (entra en cuanto hay hueco) o llegadas por intervalo (cola implícita ilimitada) |
| `IndustrialBuffer` | capacidad finita/ilimitada, FIFO/LIFO; la unidad ocupa su hueco hasta que el siguiente nodo la acepta |
| `IndustrialServer` | `capacity` ranuras; toma carriers → toma operarios/herramientas (con desplazamiento) → procesa (suspendido si avería) → libera → calidad → **bloqueo** hasta que aguas abajo acepta |
| `IndustrialSink` | registra salida y lead time; libera carriers pendientes |
| `ResourcePool` (runtime.py) | unidades individuales con estado y posición; asignación FIFO o por prioridad; **log de decisiones** |

## Estrategias de despacho (engine/des/dispatch.py)

Desacopladas del proceso: una estrategia sólo *decide* (`choose`, `preempt_candidate`) y ve los nodos a través de dos
sondas genéricas (`occupancy()`, `state_counts()`).

| Regla | Comportamiento |
|---|---|
| `fifo` | petición más antigua |
| `priority` | menor `node.priority`, FIFO en empate |
| `wip_target` (**WIP_TARGET_PRIORITY**) | 1) si el nodo protegido está BLOQUEADO → tarea aguas abajo (desbloquear); 2) si WIP de alimentación < objetivo → tarea feeder; 3) si no → tarea no-feeder; FIFO dentro de cada clase. Re-evaluación continua: cada cambio en los nodos observados reprograma la decisión; con `preempt_below` una tarea no-feeder en curso se **suspende** (trabajo restante conservado) si el WIP cae por debajo del umbral y hay una tarea feeder esperando. |

Log de decisiones (modo trace): `kind` (assign/preempt), candidatos, regla, **motivo** y **estado del sistema**
(WIP de alimentación y detalle por nodo, objetivo, estado del nodo protegido). Se registran todas las decisiones, no sólo las disputadas.

## Transporte (IndustrialTransport)

Viaje = recurso (camina al origen) → carga → recorrido `distance/speed` → descarga → entrega al destino (bloqueado si lleno)
→ retorno vacío opcional. `capacity` unidades por viaje (`batch: immediate|full`), `fleet` viajes en paralelo.
Uso en el flujo o para **devolver carriers vacíos** (`release_via`): el bastidor no está disponible hasta que termina el viaje.
Distancia, velocidad, carga y descarga son obligatorias. El recurso cuenta como *walking* durante los recorridos y *working* en carga/descarga.

## Parámetros de modelo

`parameters:` con valor, unidad, rol (fixed/decision_variable/uncertain), rango y procedencia. Se referencian como
`$id` en expresiones seguras (`1 - $branch2_share`, `$circuits_per_rack`) en tiempos (`work_units`), capacidades,
cantidades, probabilidades de ruta, distancias y velocidades. Valor `null` → modelo INCOMPLETE, con la lista de usos.

## Distribuciones de tiempo (motor ≥ 0.4.0)

`constant`, `uniform`, `triangular`, `normal`, `lognormal` (media y desviación de la variable), `exponential`,
`gamma` (`shape`, `scale`), `weibull` (`shape`, `scale`), `empirical` (re-muestreo uniforme de valores observados).
Todas en `unit` (ms, s, min, h...). Reglas:

* Ninguna muestra negativa pasa en silencio: si una distribución sin truncamiento produce t < 0 el motor lanza
  `NegativeSampleError`. No existe `max(0, x)` ni re-muestreo oculto (cambiarían la distribución).
* `normal` con P(t < 0) > 1e-9 no valida salvo que declare `truncation: {lower: 0, reason: "...", bound_type: MODELLING_BOUND}`.
* El truncamiento es **explícito** (`lower`, `upper`, `reason`, `bound_type`), se aplica por rechazo dentro de la ventana y
  `mean_seconds()` devuelve la media truncada. Forma parte del modelo (y de su hash).
* Cada nodo tiene streams propios por (semilla de réplica, nodo, propósito): el mismo seed reproduce exactamente la
  misma secuencia, y escenarios distintos comparten números aleatorios (CRN) en los nodos que no cambian.
* `work_units = k` en un nodo de proceso: cómo se combinan las muestras lo declara `work_units_aggregation`
  (`sum_iid` = X1+…+Xk, `scale_sample` = k·X, `single_sample` = X). Sin declarar se mantiene el k·X histórico y se
  avisa si el tiempo es aleatorio. Ver `docs/distribution_fitting.md`.
* Truncamiento: `bound_type` obligatorio (`PHYSICAL_BOUND` / `MODELLING_BOUND`), `method` (`DECLARED` /
  `FIT_THEN_TRUNCATE`) y `provenance`.
* Los valores derivados de datos llevan `provenance.data` (dataset, versión, hash, ajuste, decisión): ver
  `docs/data_import.md`.

## Calendarios (motor ≥ 0.6.0)

Disponibilidad planificada de operarios, herramientas, máquinas y fuentes: turnos, descansos, turnos nocturnos,
excepciones con fecha, políticas de fin de disponibilidad y precedencia de eventos simultáneos. Detalle completo:
`docs/calendars_and_shifts.md`.

## Productos y setups (motor ≥ 0.7.0)

Mix probabilístico / secuencia explícita, tiempos y rutas por producto, setups como estado propio del slot (el estado
de setup cambia solo al completar), con las mismas políticas de calendario y la misma vía de interrupción que el
proceso. Detalle completo: `docs/products_and_setups.md`.

## Cambios de semántica en el motor 0.2.0 (fase benchmark)

- **Recogida física en transportes**: la unidad conserva su plaza aguas arriba hasta que se carga (`loading_area` para zonas de espera explícitas).
- **`reserve_destination`**: el viaje sólo empieza (y sólo entonces se pide el operario) si hay plaza reservada en destino.
- **Estados del operario**: `idle`, `walking` (sin carga hacia la tarea), `working:<tarea>`, `transporting:<tarea>` (viaje cargado + retorno vacío).
- **Distancias**: tabla explícita (`travel.distances` + `travel.locations`) o posiciones; si falta un dato → `TravelDataError` (nunca 0 silencioso).
- **Invariantes** (activos por defecto): conservación de bastidores por ubicación con verificación cruzada, conservación de entidades,
  niveles acotados (WIP ≥ 0, buffers ≤ capacidad, recursos ≤ cantidad), fracciones ≤ 100 %. Violación → `InvariantViolation`.
- **Interbloqueo**: si ningún evento puede ocurrir antes del horizonte con entidades en el sistema → `DeadlockError` con diagnóstico.
- **`dispatch_timing`**: `end_of_timestep` (por defecto) o `immediate`, para medir la sensibilidad al orden de eventos simultáneos.

## Semántica (fijada por tests)

- **Bloqueo tras servicio**: una estación terminada retiene su ranura hasta que el siguiente nodo acepta la unidad.
- **Decisiones de recursos al final del instante** (`dispatch_timing: end_of_timestep`, por defecto): toda petición
  creada en el instante t compite en las decisiones de t. Ver "Resolución de un instante" (motor ≥ 0.3.0).
- **Orden de adquisición**: carriers antes que operarios (un operario nunca queda retenido esperando un bastidor).
- **Averías**: por tiempo de calendario; afectan a todo el nodo; el trabajo en curso se reanuda (no se pierde).
  El operario asignado permanece retenido durante la avería (documentado; revisable).
- **Horizonte**: los eventos en t = horizonte cuentan. Ventana estadística (warm-up, horizonte].
- **WIP**: unidades entre la entrada al sistema (aceptación por el primer nodo o llegada) y la salida o el scrap.
- **Estados de estación**: `busy`, `waiting_resource`, `blocked`, `starved`, `down` (por ranura, sumados).
- **Estados de operario**: `idle`, `walking`, `working`. (`break` llegará con calendarios.)
- **RNG**: un flujo independiente por (semilla, nodo, propósito) → números aleatorios comunes entre escenarios.

## Resolución de un instante (motor ≥ 0.3.0)

**Contrato.** Con `end_of_timestep`, una decisión de recurso tomada en el instante t considera todas las peticiones
creadas en t antes de esa decisión, incluidas las que nacen en cascada de otra decisión de recursos del mismo
instante (p. ej. se concede un bastidor → la estación pide su operario). Sólo quedan fuera, por causalidad, las
peticiones que son consecuencia de esa misma decisión.

**Mecanismo (`SimContext._resolve`).** Un único resolvedor por instante, ejecutado con prioridad de evento baja
(después de todos los eventos ordinarios de t):

1. toma **una** decisión (asignación o *preemption*) del primer pool con algo que decidir, en *event resolution order*;
2. cede el control: las consecuencias de esa decisión (eventos ordinarios en el mismo t) se procesan;
3. se vuelve a disparar; repite hasta que ningún pool puede decidir (**punto fijo**).
   Límite de seguridad: `MAX_DECISIONS_PER_INSTANT` (100 000) → `SameInstantLoopError` (ciclo de duración cero en el modelo).

**EVENT RESOLUTION ORDER ≠ prioridad industrial.** Orden técnico entre pools: primero carriers (bastidores, palets),
después operarios/herramientas; a igualdad, orden de declaración en el ISMS. Motivo: conceder un carrier sólo
*habilita* que una tarea pida su operario; decidir el operario antes ocultaría esa tarea (era el defecto de 0.2.0).
No elige entre tareas: la elección la hace siempre la estrategia del pool, con todas las peticiones del instante.
No hay dependencia circular: cada ronda consume una petición o libera un recurso y vuelve a empezar por el principio.

**Desempate dentro de un pool (`dispatch.tie_key`).** Tras el criterio propio de la estrategia (clase WIP,
prioridad estática):
1. instante lógico de la petición (más antigua primero);
2. unidad más antigua primero (id de entidad menor = entró antes; peticiones sin unidad, p. ej. retorno de carriers
   vacíos, al final);
3. orden de declaración del nodo en el ISMS;
4. número de secuencia de la petición (sólo misma unidad y mismo nodo).
Nunca orden de iteración de Python, hashes ni el orden interno de eventos de SimPy. La prioridad de tarea
(`node.priority`) sólo se usa con la estrategia PRIORITY (su contrato). Cada empate resuelto por los criterios 2–4
queda escrito en el `reason` del log de decisiones (`[tie at t=… resolved by …]`).

`immediate` se mantiene como modo de sensibilidad: decide en orden de eventos (el primero en llegar se decide primero).

## Estados físicos de los carriers (motor ≥ 0.3.0)

Cada unidad de carrier tiene en cada instante **un único** estado (`Unit.cstate`): `available`, `granted:<nodo>`
(sólo dentro del instante de la concesión), la ubicación de la entidad que lo lleva (`<nodo>`, `<buffer>`),
`reserved:<transporte>` (**RESERVED_FOR_TRANSPORT**: desde que el transporte toma la unidad de su cola),
`<transporte>` (**IN_TRANSPORT**: cargada) o `return:<transporte>` (retorno vacío).
La ocupación de la plaza de la estación aguas arriba hasta la carga física es un concepto **ortogonal** (capacidad de
la estación), no un estado del carrier.
`check_carriers` verifica unidad a unidad: exactamente un propietario (pool, concesión, entidad o retorno), estado
coherente con el propietario, concesiones no recogidas en su instante, y contadores por estado = estados de las
unidades. Detecta duplicación, desaparición, doble pertenencia, concesiones eternas y carriers sin propietario.

## WIP que alimenta (WIP_TARGET_PRIORITY, motor ≥ 0.3.0)

`feed_wip` = número de **unidades distintas** que cumplen al menos una condición del contrato `WipTargetParams`:
retenidas por un `feed_node`, o (con `count_feeder_in_process`) en una ranura/vehículo BUSY o BLOCKED de un
`feeder_node`. La inclusión no cambia respecto a 0.2.0; sólo se elimina el doble conteo (un bastidor que ocupa aún la
plaza del montaje mientras el transporte que lo reservó lo carga cuenta una vez; `feed_detail.shared` lo muestra).
Por estados del bastidor: montaje en curso, montado esperando recogida, RESERVED_FOR_TRANSPORT (la plaza del montaje
sigue BLOCKED) e IN_TRANSPORT cuentan si su nodo es *feeder*; en buffer cuenta si el buffer es *feed node*.

## Historial de versiones del motor

| Versión | Cambio | Modelos afectados (medido) |
|---|---|---|
| 0.7.0 | Productos (`entities` como ProductType) y bloque de extensión `production`: PROBABILISTIC_MIX (stream `product_mix` por fuente, productos en orden de id) / EXPLICIT_SEQUENCE; tiempos por producto (mismo sistema de distribuciones y `work_units`); rutas por producto; setups (`setup`, `setup_outside_planned`) CONSTANT / TARGET / SEQUENCE_DEPENDENT con `setup_key`, `initial_state` explícito, recursos propios, política de calendario propia y REUSE_ORIGINAL_SAMPLE; bucle de operación temporizada compartido por proceso y setup; métricas por producto y de setup; conservación por producto. Ver `docs/products_and_setups.md` | Ninguno: sin bloque `production` no se crea ningún stream ni evento nuevo; 01–05 y todos los tests de 0.6 idénticos (medido) |
| 0.6.0 | Calendarios, turnos, descansos y excepciones (bloque de extensión `availability`, fuera del núcleo ISMS congelado); políticas FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART y regla de inicio; transiciones de calendario con prioridad URGENT al principio del instante; contabilidad planificado/no planificado comprobada como invariante. Cierre técnico: vía única de interrupción (corrige un fallo con calendario/avería durante la re-solicitud tras una pre-emption), peticiones de nodos no disponibles no se conceden, contratos PAUSE_RESUME / REUSE_ORIGINAL_SAMPLE / FAILURE_CLOCK = ELAPSED_TIME. Ver `docs/calendars_and_shifts.md` | Ninguno: sin bloque `availability` no se crea reloj de calendario ni eventos nuevos; 01–05, MVP 359 y golden idénticos (medido) |
| 0.5.0 | Agregación explícita de `work_units` (`work_units_aggregation`: `sum_iid` X1+…+Xk, `scale_sample` k·X, `single_sample` X); no declarada = k·X histórico con aviso `WORK_UNITS_AGGREGATION_UNDECLARED` (fuera del verificador congelado, en `validation/semantics.py`); KPIs/diagnóstico usan el factor de la política; truncamiento con `bound_type` obligatorio (PHYSICAL_BOUND / MODELLING_BOUND), `method` (DECLARED / FIT_THEN_TRUNCATE) y procedencia | Ninguno: 01–05, MVP 359, golden y el modelo e2e dan resultados idénticos a 0.4.0 (medido) y los hashes no cambian. El ejemplo de datos e2e cambia porque ahora decide `sum_iid` (127.2 ± 1.0) en vez del k·X reconocido (124.6 ± 1.4) |
| 0.4.0 | Distribuciones `gamma` y `weibull`; truncamiento **explícito** (`truncation: {lower, upper, reason}`, muestreo por rechazo, media truncada); una muestra negativa sin truncamiento declarado es un error (`NegativeSampleError`), ya no se re-muestrea en silencio; `normal` con P(t<0) > 1e-9 exige truncamiento declarado; `Provenance.data` (enlace a dataset/ajuste) | Ninguno de 01–05, MVP 359, golden ni selectiva (hash de contenido y resultados idénticos, test `test_engine_0_4_0_*`). Modelos externos con `normal` de masa negativa no despreciable dejan de validar: hay que declarar el truncamiento |
| 0.3.0 | Resolución de un instante a punto fijo + desempate explícito; estado único de carrier con `reserved:<transporte>`; `feed_wip` sin doble conteo | `05_selective_soldering` 132 → 130 (contrato del instante); selectiva de test 2 bastidores 136 → 133 (contrato); benchmark sintético 3–10 bastidores (desempate; sin reserva ya no hay interbloqueo). Sin cambio: 01–04, MVP 359, golden. Detalle: `docs/diagnostics/selective_rack_anomaly.md` §17 |
| 0.2.0 | Recogida física en transportes, estados de operario, invariantes | — |

Los resultados guardan `engine_version` y la caché la incluye en la clave: los resultados de 0.2.0 siguen
identificados como tales y nunca se sirven como resultados de una versión posterior.

## KPIs (analytics/kpis.py)

units_completed, throughput_per_hour, units_scrapped, yield, avg/max WIP, avg/p90 lead time; por estación:
utilization, blocked, starved, waiting_resource, down, processed, rejects, failures, avg_wait, OEE
(A × P × Q con definición registrada); por buffer: contenido medio/máximo, espera; por recurso:
utilization, working, walking, avg_in_use (carriers en circulación).

Réplicas: media, desviación, min, max, IC95 % (t de Student), p50.

## Diagnóstico (analytics/diagnostics.py)

- Cota teórica de throughput por estación, recurso y lazo de carriers (CONWIP), con la fórmula en la evidencia.
- FLAG si el throughput simulado supera la cota; aviso si < 50 %.
- Demanda > capacidad (colas crecientes).
- Ley de Little como comprobación de consistencia.
- Candidato a cuello de botella, bloqueos, contención de recursos, recursos saturados, colas acumuladas.

## Event log y modo debug

`simulation.trace: true` (o `simforge run --trace-dir`): eventos `created, enter, enter_buffer, wait_resource,
operator_walking, start_process, end_process, leave, rejected, scrapped, completed, carrier_seized,
carrier_released, down, up` y decisiones `{t, resource, units, chosen_node, candidates[priority, waiting_s], rule, reason}`.

## Golden models

`tests/test_engine_golden.py`: 60 u/h exacto, línea serie exacta, bloqueo, operario compartido (359),
2 operarios, prioridades, yield, averías deterministas, CONWIP, desplazamientos, warm-up, M/M/1 + Little,
reproducibilidad, capacidad paralela, routing probabilístico. Si cambian → cambió la semántica → subir `ENGINE_VERSION`.
