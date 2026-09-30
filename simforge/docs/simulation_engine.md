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

## Semántica (fijada por tests)

- **Bloqueo tras servicio**: una estación terminada retiene su ranura hasta que el siguiente nodo acepta la unidad.
- **Decisiones de recursos al final del instante**: las peticiones simultáneas compiten entre sí (evita que
  el orden interno de eventos decida por casualidad). Implementado con prioridad de evento baja.
- **Orden de adquisición**: carriers antes que operarios (un operario nunca queda retenido esperando un bastidor).
- **Averías**: por tiempo de calendario; afectan a todo el nodo; el trabajo en curso se reanuda (no se pierde).
  El operario asignado permanece retenido durante la avería (documentado; revisable).
- **Horizonte**: los eventos en t = horizonte cuentan. Ventana estadística (warm-up, horizonte].
- **WIP**: unidades entre la entrada al sistema (aceptación por el primer nodo o llegada) y la salida o el scrap.
- **Estados de estación**: `busy`, `waiting_resource`, `blocked`, `starved`, `down` (por ranura, sumados).
- **Estados de operario**: `idle`, `walking`, `working`. (`break` llegará con calendarios.)
- **RNG**: un flujo independiente por (semilla, nodo, propósito) → números aleatorios comunes entre escenarios.

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
