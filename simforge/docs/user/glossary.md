# Glosario

Cada término significa lo mismo en la CLI, la UI, los docs y los informes.

## Flujo y KPIs

| Término | Significado |
|---|---|
| **WIP** | unidades en el sistema (ponderadas en el tiempo: *Average WIP*, units) |
| **Lead time** | tiempo desde la entrada al sistema hasta el sink, de las unidades completadas (s / min) |
| **Throughput** | unidades completadas por hora medida (units/h) |
| **Ventana medida** | [warm-up, horizonte]: todos los KPIs y costes se miden ahí |
| **Busy** | nodo procesando, o recurso trabajando, andando o transportando |
| **Blocked** | nodo con trabajo terminado que no puede entregar porque el siguiente está lleno |
| **Starved** | nodo libre sin trabajo disponible |

## Calendarios

| Término | Significado |
|---|---|
| **Planned availability** | tiempo dentro de turnos menos descansos (calendarios) |
| **Off-shift** | tiempo fuera de turno |

## Productos, setups y mantenimiento

| Término | Significado |
|---|---|
| **Setup** | cambio de preparación de una máquina entre setup keys; el estado cambia sólo al completarlo |
| **Failure** | avería (reloj ELAPSED u OPERATING) |
| **Repair** | reparación correctiva activa (sin contar la espera del recurso) |
| **Corrective downtime** | espera del técnico + reparación activa |
| **PM** | mantenimiento preventivo (por calendario o por uso) |

## Economics

| Término | Significado |
|---|---|
| **evaluated total cost** | suma de las líneas económicas INCLUDED de las categorías evaluadas; no es un coste completo |
| **evaluated net result** | ingresos − evaluated total cost (no es un beneficio) |
| **evaluated savings** | coste base − coste de la alternativa, sobre las categorías comunes |
| **simple payback** | CAPEX incremental / ahorro anual (NOT_REACHED si el ahorro es ≤ 0) |
| **annual return on incremental CAPEX** | ahorro anual / CAPEX incremental |
| **coverage** | por categoría: INCLUDED / MISSING / NOT_APPLICABLE / NOT_REQUESTED / REQUIRES_ENGINEER_DECISION |
| **shared / unallocated costs** | costes no atribuibles a un producto; nunca se reparten en 1.0 |

## Estado de los valores

| Término | Significado |
|---|---|
| **MISSING** | valor obligatorio sin dato: bloquea, nunca se convierte en 0 ni en un default |
| **ASSUMED** | valor supuesto, visible como tal |
| **USER_PROVIDED** (`provided_by_client`) | valor dado por el cliente o el ingeniero |

## Validación

| Término | Significado |
|---|---|
| **SYNTHETICALLY_VALIDATED** | probado con casos de resultado conocido (tests) |
| **REAL_DATA_VALIDATED** | validado con datos reales para una capacidad, en un caso y un periodo, con protocolo y firma |
| **Approval (física)** | el ingeniero revisó esta versión exacta (hash); no implica validación con datos |
