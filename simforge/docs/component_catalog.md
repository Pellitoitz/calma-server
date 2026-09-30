# Component library

### AOI (`aoi` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Automatic optical inspection.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield

*Tags:* electronics, inspection

### Buffer (`buffer` v1.0.0)

*Category:* core · *Behaviour:* `buffer` · *Status:* **tested**

Finite or unlimited queue between stations. A full buffer blocks the upstream station
(blocking-after-service).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | distribution | `None` | Max units stored. null = unlimited. |
| `discipline` | string | `fifo` | fifo | lifo |

*KPIs:* avg_content, max_content, avg_wait_time

*Tags:* core, queue, wip, storage

### Cleaning (`cleaning` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Cleaning operation (parts, fixtures, racks).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* manufacturing, cleaning

### Conformal coating (`coating` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Conformal coating / varnishing.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* electronics, coating

### Functional test (`functional_test` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Functional test (FCT).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield

*Tags:* electronics, test

### ICT (`ict` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

In-circuit test.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield

*Tags:* electronics, test

### Inspection (`inspection` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Visual/manual inspection or review. Use yield_rate + on_reject to model rejects.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield, rejects

*Tags:* manufacturing, quality, inspection

### Machine (`machine` v1.0.0)

*Category:* core · *Behaviour:* `server` · *Status:* **tested**

Generic automatic station. Processes 'capacity' units in parallel. Optional operator/tool
resources are held for the whole processing time. Supports yield (scrap/rework) and
time-based failures (MTBF/MTTR).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel identical slots. |
| `process_time` | distribution | `None` | Processing time per unit (distribution). |
| `resources` | array | `` | Resources held during processing, e.g. [{resource: operator_1}] |
| `yield_rate` | number | `1.0` | Fraction of good units (0-1]. Rejects go to 'on_reject'. |
| `on_reject` | string | `scrap` | 'scrap' or id of rework node. |
| `failures` | distribution | `None` | {mtbf: <dist>, mttr: <dist>} calendar-time based. |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, blocked, starved, down, waiting_resource, throughput, oee

*Tags:* core, station, automatic

### Manual assembly (`manual_assembly` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Manual assembly workstation (operator required).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, waiting_resource, blocked, starved

*Tags:* manufacturing, manual, assembly

### Manual insertion (PTH) (`manual_insertion` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Manual through-hole component insertion.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* electronics, pth, manual

### Manual process (`manual_process` v1.0.0)

*Category:* core · *Behaviour:* `server` · *Status:* **tested**

Generic manual workstation. Requires an operator resource (declared in 'resources').

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, waiting_resource, blocked, starved

*Tags:* core, manual, station, operator

### Packaging (`packaging` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Packaging / boxing station.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* manufacturing, packaging

### Pick and place (`pick_and_place` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

SMD placement machine.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, oee

*Tags:* electronics, smd

### Reflow oven (`reflow` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Reflow oven. Model as capacity = boards inside the oven, process_time = transit time.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, avg_content

*Tags:* electronics, smd, oven

### Rework (`rework` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Rework station. Reference it from another node's on_reject.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* manufacturing, quality, rework

### Depaneling router (`router` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

PCB depaneling router.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization

*Tags:* electronics, depaneling

### Screen printer (`screen_printer` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Solder paste screen printer (SMD line start).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, oee

*Tags:* electronics, smd

### Selective soldering (`selective_soldering` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Selective soldering machine. Automatic; boards usually travel on racks/fixtures (model racks as a CARRIER resource seized upstream).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, blocked, starved, oee

*Tags:* electronics, pth, soldering

### Sink (`sink` v1.0.0)

*Category:* core · *Behaviour:* `sink` · *Status:* **tested**

End of the process. Records completed units and lead times.

| Parameter | Type | Default | Description |
|---|---|---|---|

*KPIs:* units_completed, throughput, lead_time

*Tags:* core, exit

### Source (`source` v1.0.0)

*Category:* core · *Behaviour:* `source` · *Status:* **tested**

Creates entities. 'infinite' = unlimited supply (a new unit enters as soon as the first node has space).
'interarrival' = arrivals separated by a (possibly random) time.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `arrival` | string | `infinite` |  |
| `interarrival` | distribution | `None` |  |
| `max_entities` | distribution | `None` |  |
| `entity_type` | distribution | `None` |  |

*KPIs:* entities_created

*Tags:* core, arrivals, demand

### SPI (`spi` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Solder paste inspection.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield

*Tags:* electronics, smd, inspection

### Test station (`test_station` v1.0.0)

*Category:* manufacturing · *Behaviour:* `server` · *Status:* **draft**

Generic test station (functional or electrical).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, yield

*Tags:* manufacturing, test, quality

### Transport (delay) (`transport_delay` v1.0.0)

*Category:* logistics · *Behaviour:* `server` · *Status:* **draft**

Fixed-capacity transport modelled as a delay (e.g. conveyor with N positions: capacity=N, process_time=transit time).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, avg_content

*Tags:* logistics, transport, conveyor

### Wave soldering (`wave_soldering` v1.0.0)

*Category:* electronics · *Behaviour:* `server` · *Status:* **draft**

Wave soldering machine.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `capacity` | integer | `1` | Parallel slots (identical stations) |
| `process_time` | distribution | `None` |  |
| `resources` | array | `` | Held during processing |
| `yield_rate` | number | `1.0` |  |
| `on_reject` | string | `scrap` | 'scrap' or id of a rework node |
| `failures` | distribution | `None` |  |
| `ideal_cycle_time` | distribution | `None` |  |

*KPIs:* utilization, oee

*Tags:* electronics, pth, soldering