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
