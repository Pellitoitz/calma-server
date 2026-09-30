# Modelo de dominio e ISMS v0.1

## Ontología ligera

| Concepto | ISMS | Notas |
|---|---|---|
| Entity | `entities[]` | tipo de unidad; v0.1 = un único tipo efectivo |
| Resource | `resources[]` | `operator` (personas, pueden andar), `carrier` (bastidores/palés/kanban: se toman en un nodo y se liberan en otro → CONWIP), `tool` |
| Process | `nodes[]` con comportamiento `server` | máquinas, puestos manuales, inspección, test… |
| Buffer | `nodes[]` con comportamiento `buffer` | capacidad finita o ilimitada, FIFO/LIFO |
| Transport | componente `transport_delay` | transporte como retardo con capacidad; transporte con distancia de entidades: pendiente |
| Decision | `edges[].probability`, `on_reject`, `resources[].dispatch`, `nodes[].priority` | |
| Constraint | cantidades, capacidades, `max_scenarios` | |
| Schedule | — | calendarios/turnos: **no soportado** en v0.1 |
| Failure | `params.failures {mtbf, mttr}` | por tiempo de calendario; proceso suspendido y reanudado |
| Quality | `params.yield_rate`, `on_reject` (scrap o nodo de retrabajo) | |
| Cost | `resources[].cost_per_hour` | reservado para la capa económica (no afecta a la simulación) |
| KPI | `analytics/kpis.py` | ver `METRIC_INFO` |

## Estructura ISMS

```yaml
isms_version: "0.1"
meta: {name, description, tags, domain}
simulation:
  horizon: {value: 8, unit: h}
  warmup: {value: 0, unit: s}
  kind: terminating | steady_state
  replications: 1
  base_seed: 12345
  trace: false                 # event log + decisiones de operarios
entities: [{id, name}]
resources:
  - id: operator_1
    kind: operator | carrier | tool
    quantity: 1
    dispatch: fifo | priority
    travel: {speed: {value: 1.2, unit: m/s}, metric: euclidean | manhattan}
    home: assembly
    provenance: {...}
nodes:
  - id: assembly
    name: Manual assembly
    component: manual_assembly     # id de biblioteca
    component_version: "1.0.0"     # fijada para reproducibilidad
    priority: 1                    # para dispatch=priority (menor = antes)
    seize: [{resource: racks}]     # carriers tomados antes de procesar
    release: []                    # carriers liberados tras procesar
    position: {x: 0, y: 0}         # metros (desplazamientos de operarios)
    params:                        # validados contra el comportamiento del componente
      process_time: {dist: constant, value: 120, unit: s,
                     provenance: {status: measured, source: time_study.xlsx, timestamp: ...}}
      capacity: 1
      resources: [{resource: operator_1, quantity: 1}]
      yield_rate: 0.98
      on_reject: scrap | <node id>
      failures: {mtbf: {dist: exponential, mean: 2, unit: h}, mttr: {dist: lognormal, mean: 10, std: 5, unit: min}}
      ideal_cycle_time: {...}      # para OEE
edges: [{source, target, probability?}]
assumptions: [{id, text, path, origin: ai|library_default|engineer|system, accepted}]
missing: [{question, path, required}]
approval: {approved, by, at, model_hash, note}
experiments: [{name, factors: [{path, values}], replications, max_scenarios}]
```

### Distribuciones

`constant(value)`, `uniform(low, high)`, `triangular(low, mode, high)`, `normal(mean, std)` truncada en 0 por
remuestreo (aviso si media − 2σ < 0), `lognormal(mean, std)` (de la variable, no del log), `exponential(mean)`,
`empirical(values)`. Todas con `unit` de tiempo y `provenance`. Parámetros negativos → error de validación.

### Trazabilidad (`provenance.status`)

`measured`, `provided_by_client`, `estimated`, `assumed`, `calculated`, `imported`, `default`.

### Rutas de parámetros

`nodes.<id>.params.capacity`, `nodes.<id>.params.process_time.value`, `resources.<id>.quantity`,
`simulation.horizon.value`… Las usan experimentos, comandos de chat, diff e historial.

### Readiness

| Nivel | Significado |
|---|---|
| INCOMPLETE | falta información requerida |
| CONFIGURED | información completa, errores estructurales |
| EXECUTABLE | verificado; se puede simular |
| ENGINEER_APPROVED | aprobado por el ingeniero **para este hash de contenido** (cualquier cambio lo invalida) |

### Verificación implementada

ids únicos, componentes existentes, parámetros válidos, tiempos faltantes, recursos inexistentes o
insuficientes, kinds correctos (seize sólo carriers), conexiones a nodos inexistentes, auto-bucles, duplicados,
fuente/sumidero, entradas/salidas, huérfanos, callejones sin salida, probabilidades que suman 1,
alcanzabilidad, camino a sumidero, bucles sin salida, suministro infinito → buffer ilimitado,
carriers no liberados, warm-up < horizonte, pocas réplicas en modelos estocásticos, aprobación caducada.

## Extensiones previstas del esquema (sólo junto con su implementación)

`calendars` (turnos, pausas), `products` + rutas por producto + `setup_matrix`, `routing: first_available | condition`,
`transport` con distancia/velocidad/capacidad de lote, `energy {idle_power, busy_power, down_power}`,
`economics` separado de resultados, `demand` (pedidos, programa, estacionalidad), reglas dinámicas de despacho
(`wip_target`, `starvation_prevention`), `custom_rules` aisladas.
