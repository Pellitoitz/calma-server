# Mix de productos, secuencias y setups / changeovers (motor 0.7.0)

> SimForge 0.7 **representa** una secuencia o un mix que define el ingeniero y **calcula** su efecto.
> **No optimiza**: no elige la mejor secuencia, no agrupa productos para reducir setups, no cambia FIFO ni WIP_TARGET.
> Nada se completa, normaliza, refleja ni promedia: un dato que falta es ERROR / MISSING.

## 1. Dónde vive

Bloque de extensión `production` del modelo (`SimModel`, igual que `availability` de los calendarios), fuera del núcleo
ISMS 0.1 congelado. Un modelo sin `production` es un modelo legacy: misma serialización, mismo `content_hash`, mismos
resultados y **ningún número aleatorio adicional** (medido: 01–05 = 59 / 359 / 1889.05 / 477.5 / 130).

```yaml
entities:                                  # ProductType = EntityType del ISMS (id estable; el nombre es solo visual)
  - {id: pcb_a, name: PCB_A}
  - {id: pcb_b, name: PCB_B}
production:
  products:
    pcb_a: {setup_key: FAMILY_A}
    pcb_b: {setup_key: FAMILY_B}
  generation:
    src: {mode: PROBABILISTIC_MIX, mix: {pcb_a: 0.6, pcb_b: 0.4}}
    # src: {mode: EXPLICIT_SEQUENCE, sequence: [pcb_a, pcb_a, pcb_b], repeat: false}
  routes:                                  # opcional
    pcb_a: {nodes: [src, m1, m2, out]}
    pcb_b: {nodes: [src, m1, insp, out]}
  processing:
    m1: {pcb_a: {dist: constant, value: 30, unit: s}, pcb_b: {dist: lognormal, mean: 45, std: 5, unit: s}}
  setups:
    m1:
      mode: SEQUENCE_DEPENDENT             # CONSTANT_CHANGEOVER | TARGET_DEPENDENT | SEQUENCE_DEPENDENT
      initial_state: FAMILY_A              # o UNCONFIGURED
      matrix: {FAMILY_A: {FAMILY_B: {dist: constant, value: 600, unit: s}}, FAMILY_B: {FAMILY_A: {dist: constant, value: 900, unit: s}}}
      from_unconfigured: {}                # UNCONFIGURED -> key (obligatorio si initial_state = UNCONFIGURED)
      resources: [{resource: setup_tech}]  # solo lo declarado
      at_unavailability: PAUSE_RESUME      # obligatorio si el setup está afectado por un calendario
```

CLI: `simforge products show <modelo|proyecto>`, `simforge products run <modelo|proyecto> --seed N`.
UI: pestaña **Products** (vista de la configuración y KPIs del último run; la edición es la del modelo).

## 2. ProductType

Cada entidad lleva su tipo (`etype` = id del producto) desde la fuente hasta el sink o el scrap. La identidad interna
es el id (`pcb_a`); `name` es solo para mostrar. `production.products` solo admite ids declarados en `entities`.

## 3. Generación: PROBABILISTIC_MIX vs EXPLICIT_SEQUENCE

Cada fuente de un modelo con `production` declara **una** de las dos (si no: `PRODUCT_GENERATION_MISSING`; si además
tiene `entity_type`: `PRODUCT_GENERATION_AMBIGUOUS`).

* **PROBABILISTIC_MIX**: probabilidades ≥ 0, suma = 1 con tolerancia `1e-9`, alguna > 0, productos declarados.
  `0.6 / 0.3 / 0.3` es ERROR `MIX_SUM`: **no se normaliza**.
  RNG: stream propio `(seed, <fuente>, "product_mix")`, una muestra por entidad creada, productos recorridos en orden
  **alfabético de id** (el orden de escritura del mix no cambia ni el hash ni la secuencia). Misma seed → misma
  secuencia; no se exige que una muestra pequeña reproduzca 60/30/10.
* **EXPLICIT_SEQUENCE**: lista de productos en orden de creación; `repeat: false` (por defecto) = la fuente se detiene al
  terminar la lista; `true` = vuelve a empezar. No consume números aleatorios. `max_entities` de la fuente sigue
  aplicando (se para con el primer límite).

## 4. Tiempos por producto

`processing.<nodo>.<producto>` = una `Duration` del sistema existente (constante o cualquier distribución soportada,
truncamiento, procedencia), combinada con `work_units` / `work_units_aggregation` exactamente igual que `process_time`,
y muestreada del mismo stream del nodo (`process_time`).

* Un nodo con tabla por producto **no** lleva `process_time` (ambos → `PRODUCT_TIME_AMBIGUOUS`).
* Cada producto que puede llegar al nodo necesita su tiempo (`MISSING`): **nunca** se usa el de otro producto.
* Un nodo sin tabla usa su `process_time` para todos los productos (dato explícito del nodo).
* OEE: no se informa en nodos con tiempos por producto (el tiempo ideal por mezcla no está definido aún).

## 5. Rutas por producto

Sin `routes`: enrutado legacy del grafo (probabilidades de las conexiones, las mismas para todos los productos).
Con `routes`: **todos** los productos generados necesitan ruta; la entidad sigue exactamente su lista de nodos
(sin números aleatorios). Validación: nodos existentes; empieza en una fuente que genera el producto; termina en un
Sink; cada par consecutivo es una conexión del modelo; sin probabilidades en nodos con varias salidas
(`ROUTING_AMBIGUOUS`); retrabajo `on_reject` fuera de ruta no soportado (`ROUTE_REWORK_UNSUPPORTED`). El scrap
(`yield_rate`) sí funciona. Para el verificador congelado, las bifurcaciones resueltas por rutas reciben un reparto
neutro que se elimina del modelo compilado: el motor no puede usarlo.

## 6. Setups / changeovers

**Un setup no es processing.** Es un estado propio del slot (`setup`), con su tiempo, recuento, recursos, política de
calendario y traza.

* **Cuándo**: hay setup si y solo si `estado_actual != setup_key del producto que va a procesarse`. Productos con la
  misma `setup_key` (familia) no necesitan setup entre ellos.
* **setup_key**: obligatoria para todo producto que llega a un nodo con setups (`MISSING`). Formato
  `[A-Za-z][A-Za-z0-9_-]*`; `UNCONFIGURED` está reservado.
* **Estado inicial**: `initial_state` obligatorio: una setup key o `UNCONFIGURED`. Con `UNCONFIGURED` la primera
  entidad necesita `from_unconfigured[<key>]` (si no: `SETUP_TRANSITION_MISSING`). Nunca hay estado `None`.
* **Actualización del estado**: **solo al COMPLETAR** el setup. Durante el setup el estado sigue siendo el anterior;
  un setup pausado, reiniciado o interrumpido por avería no cambia el estado hasta que termina.
* **Modos**:
  * `CONSTANT_CHANGEOVER`: `constant` para cualquier cambio de key (no cubre `UNCONFIGURED → key`).
  * `TARGET_DEPENDENT`: `by_target[destino]`.
  * `SEQUENCE_DEPENDENT`: `matrix[desde][hacia]`, **asimétrica**; nunca se refleja ni se completa. La diagonal solo
    admite 0 (`SETUP_DIAGONAL`).
* **Transiciones requeridas** (verificador): con una única fuente `EXPLICIT_SEQUENCE` que alimenta el nodo, las del
  orden de la secuencia (inicial → primera, cambios consecutivos, última → primera si `repeat`); en cualquier otro caso,
  todos los cambios posibles entre las keys que llegan al nodo (+ estado inicial). Si en ejecución aparece un cambio no
  definido (p. ej. adelantamientos entre ramas), la simulación **se detiene** con `SetupTransitionMissing`.
* **Orden en la estación**: la entidad ocupa el slot → carriers (`seize`) → **setup** (con sus recursos) → recursos de
  proceso → proceso. El setup se decide **después** de que el dispatch existente haya entregado la entidad al nodo: no
  se reordena nada para ahorrar setups.
* **Muestreo**: el tiempo de setup se muestrea al empezar (stream propio `(seed, <nodo>, "setup")`; los nodos sin setups
  no lo crean).

## 7. Recursos del setup

`setups.<nodo>.resources` (recursos existentes, mismo sistema de pools). Solo se usan los declarados: el operario de
proceso **no** se toma implícitamente. Sin recursos = setup solo de máquina. La tarea aparece como `<nodo>#setup` en el
pool (decisiones, `resource_tasks`, estado `working:<nodo>#setup` del operario) y compite por la regla de despacho del
recurso con el rango del propio nodo (sin prioridad artificial). No soportado en 0.7: carriers como recurso de setup
(`SETUP_CARRIER_UNSUPPORTED`) y recursos con WIP_TARGET (`SETUP_RESOURCE_WIP_TARGET_UNSUPPORTED`: la clasificación de
una tarea de setup no está definida en esa estrategia).

## 8. Setup y calendarios (0.6.0 sin semántica nueva)

* El setup está gobernado por el **calendario propio del nodo + los calendarios de sus recursos de setup** (no por los
  operarios de proceso, que no participan en el setup).
* `setups.<nodo>.at_unavailability` (FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART) es **obligatorio** cuando el setup
  está afectado por un calendario y **no se hereda** de la política del proceso.
* Las tres políticas usan exactamente el mismo código que el proceso: PAUSE_RESUME conserva el restante y libera los
  recursos de setup (se re-solicitan por el dispatch normal cuando hay disponibilidad conjunta y la máquina no está
  averiada); STOP_RESTART pierde lo hecho y repite **la misma muestra** (`REUSE_ORIGINAL_SAMPLE`, sin consumir números
  aleatorios); FINISH_CURRENT termina.
* Contabilidad del nodo: setup dentro del tiempo planificado del nodo = `setup`; fuera = `setup_outside_planned`;
  setup pausado por su calendario = `paused_by_calendar` si el nodo está fuera de su tiempo planificado, o
  `waiting_resource` si el nodo está planificado (espera a su técnico). El invariante planificado/no planificado de 0.6
  sigue comprobándose.
* `REQUIRE_FULL_WINDOW` con setups no está definido en 0.7 (`SETUP_START_RULE_UNSUPPORTED`).

## 9. Setup y averías

`FAILURE_CLOCK = ELAPSED_TIME` sin cambios: la máquina puede averiarse durante un setup. El setup queda suspendido
durante la reparación con su **restante** (como el proceso), los recursos de setup se mantienen (igual que en
proceso), el estado no cambia y continúa al repararse. La interrupción usa la vía única `_interrupt` (sin doble
interrupción, release ni acquire): calendario y avería en el mismo instante → una sola interrupción.

## 10. WIP_TARGET y estados

Una unidad esperando setup, en setup o esperando proceso tras el setup está **en el slot** del nodo: cuenta una vez como
contenida por el nodo (`held_entities` / ocupación) y **no** cuenta como "en proceso" para WIP_TARGET (solo
BUSY/BLOCKED, definición de 0.6 sin cambios). El slot solo se libera cuando la unidad sale. Semántica legacy de
WIP_TARGET intacta.

## 11. Capacidad > 1

Setup por nodo o por slot es ambiguo: en 0.7 los setups solo se admiten en nodos con `capacity = 1`
(`SETUP_SEMANTICS_UNSUPPORTED_FOR_MULTI_SLOT_NODE`). Con capacidad 1 el setup ocupa la capacidad: nunca hay setup y
proceso simultáneos.

## 12. Métricas (solo modelos con `production`)

| Clave | Definición |
|---|---|
| `product.<p>.created` / `completed` / `throughput_per_hour` / `avg_wip` / `wip_end` / `avg_lead_time_s` | por producto (completed en la ventana medida) |
| `node.<n>.processing_time_h`, `utilization_processing` | busy (+ busy fuera de planificado) / misma definición que `utilization` |
| `node.<n>.setup_count`, `setup_time_h`, `utilization_setup` | setups completados; tiempo en setup (pausas excluidas) |
| `total_setup_count`, `total_setup_time_h` | suma de nodos |
| `setup_time_inside_planned_h`, `setup_time_outside_planned_h` | con calendarios |

`utilization` legacy (busy / (slots × tiempo medido)) **no se redefine**. Traza: `setup_start` (from, to, duración,
recursos), `setup_paused_by_calendar`, `setup_restart_lost_work`, `setup_resume`, `setup_end`; y `RunRecord.setups`
con una fila auditable por setup (nodo, slot, entidad, producto, from/to, inicio, fin, muestra, recursos,
interrupciones con causa y restante).

## 13. Conservación

Por producto, comprobado al final de cada run: `created = completed + scrapped + en sistema`, el WIP por producto
coincide con las entidades vivas, y la suma por productos coincide con los totales. Una violación aborta el run.

## 14. Hash, aprobación, persistencia

Todo el bloque `production` entra en el `content_hash`: cambiar mix, secuencia, rutas, tiempos, setup_key, matrices,
estado inicial, recursos o política crea una versión nueva e invalida la aprobación. Guardar → cargar conserva hash,
secuencia, setups y resultados. Reconstruir un modelo desde la descripción (compilador congelado) conserva el bloque
`production` (`production_carried_over`).

## 15. IA / benchmark

El parser V1, el compilador y el benchmark están congelados: el lenguaje natural **no** genera todavía `production`.
La integración NL → 0.7 queda para una fase posterior.

## 16. Limitaciones declaradas (0.7)

Setups en nodos de capacidad > 1; setups con REQUIRE_FULL_WINDOW; recursos de setup carrier o WIP_TARGET; retrabajo
fuera de ruta con rutas por producto; OEE en nodos con tiempos por producto; transiciones de setup no definidas
encontradas en ejecución (el run se detiene); generación de `production` desde lenguaje natural. Sin optimización de
secuencias, sin APS, sin economía.

Estado: **CODE_COMPLETE + SYNTHETICALLY_VALIDATED**. Sin datos reales: no REAL_DATA_VALIDATED (la validación con
datos reales del módulo de calendarios 0.6 no se extiende a 0.7).
