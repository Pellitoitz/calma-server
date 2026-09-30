# Benchmark inputs — selective soldering

Generated from `selective_soldering_config.yaml` (hash `1532a7b9ec635f7d`) with `simforge benchmark inputs`. Do not edit by hand.

**Missing (REQUIRED_FROM_ANYLOGIC): 44** · stated in conversation, to confirm: 15 · invalid/unsupported: 0 · not applicable with current answers: 0

| Parameter | Description | Unit | Current value | Source | Status | Where in AnyLogic |
|---|---|---|---|---|---|---|
| `benchmark.anylogic_model_file` | .alp file name and version/date used for the reference run |  | ? | AnyLogic | **REQUIRED** |  |
| `benchmark.anylogic_version` |  |  | `PLE 8.9` | conversation | USER_STATED_TO_CONFIRM |  |
| `experiment.racks` |  | racks | `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]` | conversation | USER_STATED_TO_CONFIRM | Parameter of Main used for the rack population size (parameters variation / manual runs) |
| `simulation.horizon` | 8 h netas, continuas | h | `8` | conversation | USER_STATED_TO_CONFIRM | Simulation experiment > Model time > Stop: 'Stop at specified time' (check model time units) |
| `simulation.warmup` | Options: 0 (statistics from t=0), <hours> | h | ? | AnyLogic | **REQUIRED** | Code that resets statistics (e.g. resetStats() in an event) - PLE has no built-in warm-up |
| `simulation.production_definition` | Options: sink_count_at_stop_time, completions_strictly_before_stop |  | ? | AnyLogic | **REQUIRED** | How production is read: Sink block count() at stop time? any dataset/statistic? |
| `simulation.simultaneous_events` | Options: FIFO, LIFO, Random |  | ? | AnyLogic | **REQUIRED** | Simulation experiment properties > Randomness: 'Selection mode for simultaneous events' (verify location in PLE 8.9) |
| `simulation.randomness` | Options: deterministic, stochastic |  | ? | AnyLogic | **REQUIRED** | Are all delay times constants? Search for triangular()/uniform()/normal() in Delay/Service times |
| `simulation.dispatch_timing` | SimForge decides resource allocation after all events of the same timestamp; 'immediate' is run as sensitivity check |  | `end_of_timestep` | SimForge | ENGINE_CHOICE |  |
| `simulation.replications` | deterministic model -> 1 replication; revisit if randomness = stochastic |  | `1` | SimForge | ENGINE_CHOICE |  |
| `simulation.base_seed` |  |  | `12345` | SimForge | ENGINE_CHOICE |  |
| `initial_state.racks_location` | Options: all_available_at_assembly |  | ? | AnyLogic | **REQUIRED** | Rack agent population: initial location / how racks are injected at startup (Source or population) |
| `initial_state.system_empty` | Options: True, False |  | ? | AnyLogic | **REQUIRED** | Any product/racks already in conveyors, selective or buffers at t=0? (Main > On startup code) |
| `initial_state.operator_location` | Options: assembly, review |  | ? | AnyLogic | **REQUIRED** | ResourcePool > Home location (nodes) |
| `racks.circuits_per_rack` |  | circuits | ? | AnyLogic | **REQUIRED** | Parameter of Main / Rack agent (used as multiplier in the delay-time expressions) |
| `supply.mode` | suministro siempre disponible |  | `infinite` | conversation | USER_STATED_TO_CONFIRM | Source block: 'Arrivals defined by' (e.g. 'Calls of inject()' when a rack is free) |
| `operator.count` | operario compartido; parametrizable 0-4 | operators | `1` | conversation | USER_STATED_TO_CONFIRM | ResourcePool > Capacity |
| `operator.walking_speed` |  | m/s | ? | AnyLogic | **REQUIRED** | ResourcePool > Speed (moving resources); check units |
| `operator.loaded_speed` | speed while carrying a rack (same as walking?) | m/s | ? | AnyLogic | **REQUIRED** — only if the operator carries racks | MoveTo / transporter speed, or ResourcePool speed if the operator carries the rack |
| `operator.strategy` |  |  | `WIP_TARGET_PRIORITY` | conversation | USER_STATED_TO_CONFIRM |  |
| `operator.wip_target` |  | racks | ? | AnyLogic | **REQUIRED** | Parameter/variable used in the operator decision code (Seize 'Task priority', Hold/condition code, custom function) |
| `operator.wip_comparison` | SimForge rule is 'feeder if WIP < target'; '<=' maps exactly to target+1 (integers), no code change Options: assembly_if_wip < target, assembly_if_wip <= target |  | ? | AnyLogic | **REQUIRED** |  |
| `operator.wip_counted_locations` | Options: assembly_conveyor, transport_to_selective, selective_entry |  | ? | AnyLogic | **REQUIRED** | The expression that computes 'WIP available for the selective' (queue sizes summed in the code) |
| `operator.count_rack_in_assembly` | does a rack currently being assembled count as feed WIP? Options: True, False |  | ? | AnyLogic | **REQUIRED** |  |
| `operator.feeding_tasks` | tasks prioritised while WIP < target (always includes assembly) Options: assembly, transport_to_selective, rack_return |  | ? | AnyLogic | **REQUIRED** |  |
| `operator.unblock_selective_first` | if the selective cannot unload (output full), does the operator go to review first? Options: True, False |  | ? | AnyLogic | **REQUIRED** |  |
| `operator.preempt_review_below` | Options: never, <integer WIP threshold> |  | ? | AnyLogic | **REQUIRED** | Seize block for review: 'Task may preempt' / 'Task preemption policy'; custom interrupt code |
| `operator.same_class_order` | Options: FIFO |  | ? | AnyLogic | **REQUIRED** | ResourcePool / Seize queue ordering when several tasks of the same type wait |
| `assembly.seconds_per_circuit` |  | s | `6` | conversation | USER_STATED_TO_CONFIRM | Delay/Service 'Delay time' of assembly |
| `assembly.stations` |  | stations | ? | AnyLogic | **REQUIRED** | Delay/Service 'Capacity' of assembly |
| `assembly.output_conveyor_capacity` |  | racks | `2` | conversation | USER_STATED_TO_CONFIRM | Conveyor 'Capacity' (or length / cell size) |
| `assembly.output_conveyor_transit` | Options: 0 (accumulating queue), <seconds> | s | ? | AnyLogic | **REQUIRED** | Conveyor length / speed |
| `transport_to_selective.start_only_if_destination_has_room` | does the operator start carrying only when the selective entry has room? (false can deadlock: operator waits holding a rack) Options: True, False |  | ? | AnyLogic | **REQUIRED** — only if transport_to_selective.exists = true | Condition/Hold before the MoveTo, or the downstream Queue capacity check in the logic |
| `transport_to_selective.exists` | operator carries the rack assembly -> selective entry? Options: True, False |  | ? | AnyLogic | **REQUIRED** | MoveTo / Seize with 'Send seized resources' + 'Attach' between assembly and selective |
| `transport_to_selective.racks_per_trip` |  | racks | `1` | conversation | USER_STATED_TO_CONFIRM |  |
| `transport_to_selective.load_time` |  | s | ? | AnyLogic | **REQUIRED** — only if transport_to_selective.exists = true |  |
| `transport_to_selective.unload_time` |  | s | ? | AnyLogic | **REQUIRED** — only if transport_to_selective.exists = true |  |
| `selective.seconds_per_circuit` |  | s | `5` | conversation | USER_STATED_TO_CONFIRM | Delay time of the selective |
| `selective.input_capacity` |  | racks | `3` | conversation | USER_STATED_TO_CONFIRM | Queue before the selective > Capacity |
| `selective.racks_inside` |  | racks | ? | AnyLogic | **REQUIRED** | Delay/Service 'Capacity' of the selective |
| `selective.output_buffer_capacity` | 'buffer de selectiva' | racks | `2` | conversation | USER_STATED_TO_CONFIRM | Queue after the selective > Capacity (confirm it is the OUTPUT buffer) |
| `second_branch.enabled` | Options: True, False |  | ? | AnyLogic | **REQUIRED** |  |
| `second_branch.share` | '% de utilización' of branch 2 as a routing fraction (0-1) | fraction | ? | AnyLogic | **REQUIRED** — only if second_branch.enabled = true | SelectOutput 'Probability' (or the condition used) |
| `second_branch.routing_rule` | other rules (alternating, first-free, condition) are NOT IMPLEMENTED yet: tell us which one AnyLogic uses Options: probabilistic_share |  | ? | AnyLogic | **REQUIRED** — only if second_branch.enabled = true | SelectOutput / SelectOutput5 'Use' property |
| `second_branch.seconds_per_circuit` |  | s | ? | AnyLogic | **REQUIRED** — only if second_branch.enabled = true |  |
| `second_branch.racks_inside` |  | racks | ? | AnyLogic | **REQUIRED** — only if second_branch.enabled = true |  |
| `transport_to_review.start_only_if_destination_has_room` | does the operator start carrying only when the review table has room? (false can deadlock: operator waits holding a rack) Options: True, False |  | ? | AnyLogic | **REQUIRED** — only if transport_to_review.exists = true | Condition/Hold before the MoveTo, or the downstream Queue capacity check in the logic |
| `transport_to_review.exists` | operator carries the rack selective output -> review? Options: True, False |  | ? | AnyLogic | **REQUIRED** |  |
| `transport_to_review.racks_per_trip` |  | racks | `1` | conversation | USER_STATED_TO_CONFIRM |  |
| `transport_to_review.load_time` |  | s | ? | AnyLogic | **REQUIRED** — only if transport_to_review.exists = true |  |
| `transport_to_review.unload_time` |  | s | ? | AnyLogic | **REQUIRED** — only if transport_to_review.exists = true |  |
| `review.seconds_per_circuit` | revision + limpieza | s | `2` | conversation | USER_STATED_TO_CONFIRM | Delay time of review/cleaning (one block or two?) |
| `review.tables_per_operator` |  | tables | `1` | conversation | USER_STATED_TO_CONFIRM | Delay/Service 'Capacity' |
| `rack_return.mode` | 'bastidor disponible nuevamente': where and when does the empty rack become available? Options: immediate_at_review_end, transport_to_assembly |  | ? | AnyLogic | **REQUIRED** |  |
| `rack_return.load_time` | only if mode = transport_to_assembly | s | ? | AnyLogic | **REQUIRED** — only if rack_return.mode = transport_to_assembly |  |
| `rack_return.unload_time` | only if mode = transport_to_assembly | s | ? | AnyLogic | **REQUIRED** — only if rack_return.mode = transport_to_assembly |  |
| `layout.distances.assembly__selective_in` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points | Path length between the nodes (select the path > Length) |
| `layout.distances.assembly__selective_out` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points |  |
| `layout.distances.assembly__review` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points |  |
| `layout.distances.selective_in__selective_out` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points |  |
| `layout.distances.selective_in__review` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points |  |
| `layout.distances.selective_out__review` |  | m | ? | AnyLogic | **REQUIRED** — needed if the operator moves between these points |  |

## AnyLogic results

Fill `anylogic_results.csv` (one row per rack count). Units: throughput racks/h; lead_time s; utilizations and starvation/blocking as fractions 0–1 (not %); walking_time h. Leave empty what AnyLogic does not measure. Describe how each KPI is computed in AnyLogic in `anylogic_kpi_definitions.yaml`.
