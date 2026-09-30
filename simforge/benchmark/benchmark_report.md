# Benchmark report — selective soldering (SimForge vs. AnyLogic)

*Generated:* 2026-09-30 22:01 UTC · *engine* simforge-des 0.2.0 · *config hash* `1532a7b9ec635f7d` · *git* `c220ad4`

## Validation status: **BLOCKED**

> Parameters are never tuned to match AnyLogic. Every difference must be explained (section 8) before any claim of equivalence.

## 1. Model configuration

| Parameter | Value | Unit | Status |
|---|---|---|---|
| `experiment.racks` | [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | racks | USER_STATED_TO_CONFIRM |
| `simulation.horizon` | 8 | h | USER_STATED_TO_CONFIRM |
| `simulation.warmup` | — | h | REQUIRED_FROM_ANYLOGIC |
| `simulation.production_definition` | — |  | REQUIRED_FROM_ANYLOGIC |
| `simulation.simultaneous_events` | — |  | REQUIRED_FROM_ANYLOGIC |
| `simulation.randomness` | — |  | REQUIRED_FROM_ANYLOGIC |
| `simulation.dispatch_timing` | end_of_timestep |  | ENGINE_CHOICE |
| `simulation.replications` | 1 |  | ENGINE_CHOICE |
| `simulation.base_seed` | 12345 |  | ENGINE_CHOICE |
| `initial_state.racks_location` | — |  | REQUIRED_FROM_ANYLOGIC |
| `initial_state.system_empty` | — |  | REQUIRED_FROM_ANYLOGIC |
| `initial_state.operator_location` | — |  | REQUIRED_FROM_ANYLOGIC |
| `racks.circuits_per_rack` | — | circuits | REQUIRED_FROM_ANYLOGIC |
| `supply.mode` | infinite |  | USER_STATED_TO_CONFIRM |
| `operator.count` | 1 | operators | USER_STATED_TO_CONFIRM |
| `operator.walking_speed` | — | m/s | REQUIRED_FROM_ANYLOGIC |
| `operator.loaded_speed` | — | m/s | REQUIRED_FROM_ANYLOGIC |
| `operator.strategy` | WIP_TARGET_PRIORITY |  | USER_STATED_TO_CONFIRM |
| `operator.wip_target` | — | racks | REQUIRED_FROM_ANYLOGIC |
| `operator.wip_comparison` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.wip_counted_locations` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.count_rack_in_assembly` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.feeding_tasks` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.unblock_selective_first` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.preempt_review_below` | — |  | REQUIRED_FROM_ANYLOGIC |
| `operator.same_class_order` | — |  | REQUIRED_FROM_ANYLOGIC |
| `assembly.seconds_per_circuit` | 6 | s | USER_STATED_TO_CONFIRM |
| `assembly.stations` | — | stations | REQUIRED_FROM_ANYLOGIC |
| `assembly.output_conveyor_capacity` | 2 | racks | USER_STATED_TO_CONFIRM |
| `assembly.output_conveyor_transit` | — | s | REQUIRED_FROM_ANYLOGIC |
| `transport_to_selective.start_only_if_destination_has_room` | — |  | REQUIRED_FROM_ANYLOGIC |
| `transport_to_selective.exists` | — |  | REQUIRED_FROM_ANYLOGIC |
| `transport_to_selective.racks_per_trip` | 1 | racks | USER_STATED_TO_CONFIRM |
| `transport_to_selective.load_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `transport_to_selective.unload_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `selective.seconds_per_circuit` | 5 | s | USER_STATED_TO_CONFIRM |
| `selective.input_capacity` | 3 | racks | USER_STATED_TO_CONFIRM |
| `selective.racks_inside` | — | racks | REQUIRED_FROM_ANYLOGIC |
| `selective.output_buffer_capacity` | 2 | racks | USER_STATED_TO_CONFIRM |
| `second_branch.enabled` | — |  | REQUIRED_FROM_ANYLOGIC |
| `second_branch.share` | — | fraction | REQUIRED_FROM_ANYLOGIC |
| `second_branch.routing_rule` | — |  | REQUIRED_FROM_ANYLOGIC |
| `second_branch.seconds_per_circuit` | — | s | REQUIRED_FROM_ANYLOGIC |
| `second_branch.racks_inside` | — | racks | REQUIRED_FROM_ANYLOGIC |
| `transport_to_review.start_only_if_destination_has_room` | — |  | REQUIRED_FROM_ANYLOGIC |
| `transport_to_review.exists` | — |  | REQUIRED_FROM_ANYLOGIC |
| `transport_to_review.racks_per_trip` | 1 | racks | USER_STATED_TO_CONFIRM |
| `transport_to_review.load_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `transport_to_review.unload_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `review.seconds_per_circuit` | 2 | s | USER_STATED_TO_CONFIRM |
| `review.tables_per_operator` | 1 | tables | USER_STATED_TO_CONFIRM |
| `rack_return.mode` | — |  | REQUIRED_FROM_ANYLOGIC |
| `rack_return.load_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `rack_return.unload_time` | — | s | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.assembly__selective_in` | — | m | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.assembly__selective_out` | — | m | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.assembly__review` | — | m | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.selective_in__selective_out` | — | m | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.selective_in__review` | — | m | REQUIRED_FROM_ANYLOGIC |
| `layout.distances.selective_out__review` | — | m | REQUIRED_FROM_ANYLOGIC |

Structure built from generic library components (see `generated_models/`); SimForge engine semantics in `docs/simulation_engine.md`, operator rule in `docs/benchmark_operator_logic.md`.

## 2. AnyLogic configuration

- Model file: — · version: PLE 8.9
- Simultaneous events: — · randomness: — · warm-up: — h · production definition: —
- KPI definitions file (`anylogic_kpi_definitions.yaml`): present

## 3. KPI definitions

Full SimForge definitions: `docs/benchmark_kpi_definitions.md`.

| KPI | Unit | AnyLogic definition |
|---|---|---|
| production | racks | — |
| throughput | racks/h | — |
| avg_wip | racks | — |
| max_wip | racks | — |
| lead_time | s | — |
| operator_utilization | fraction | — |
| selective_utilization | fraction | — |
| selective_starvation | fraction | — |
| selective_blocking | fraction | — |
| trips | trips | — |
| racks_transported | racks | — |
| walking_time | h | — |

## 4–8. Results

Not run: the benchmark is **BLOCKED** until the missing inputs are provided.

## 9. Outstanding questions

Missing inputs (44):
- `benchmark.anylogic_model_file` — .alp file name and version/date used for the reference run *Where:* —
- `simulation.warmup` —  *Where:* Code that resets statistics (e.g. resetStats() in an event) - PLE has no built-in warm-up
- `simulation.production_definition` —  *Where:* How production is read: Sink block count() at stop time? any dataset/statistic?
- `simulation.simultaneous_events` —  *Where:* Simulation experiment properties > Randomness: 'Selection mode for simultaneous events' (verify location in PLE 8.9)
- `simulation.randomness` —  *Where:* Are all delay times constants? Search for triangular()/uniform()/normal() in Delay/Service times
- `initial_state.racks_location` —  *Where:* Rack agent population: initial location / how racks are injected at startup (Source or population)
- `initial_state.system_empty` —  *Where:* Any product/racks already in conveyors, selective or buffers at t=0? (Main > On startup code)
- `initial_state.operator_location` —  *Where:* ResourcePool > Home location (nodes)
- `racks.circuits_per_rack` —  *Where:* Parameter of Main / Rack agent (used as multiplier in the delay-time expressions)
- `operator.walking_speed` —  *Where:* ResourcePool > Speed (moving resources); check units
- `operator.loaded_speed` — speed while carrying a rack (same as walking?) *Where:* MoveTo / transporter speed, or ResourcePool speed if the operator carries the rack
- `operator.wip_target` —  *Where:* Parameter/variable used in the operator decision code (Seize 'Task priority', Hold/condition code, custom function)
- `operator.wip_comparison` — SimForge rule is 'feeder if WIP < target'; '<=' maps exactly to target+1 (integers), no code change *Where:* —
- `operator.wip_counted_locations` —  *Where:* The expression that computes 'WIP available for the selective' (queue sizes summed in the code)
- `operator.count_rack_in_assembly` — does a rack currently being assembled count as feed WIP? *Where:* —
- `operator.feeding_tasks` — tasks prioritised while WIP < target (always includes assembly) *Where:* —
- `operator.unblock_selective_first` — if the selective cannot unload (output full), does the operator go to review first? *Where:* —
- `operator.preempt_review_below` —  *Where:* Seize block for review: 'Task may preempt' / 'Task preemption policy'; custom interrupt code
- `operator.same_class_order` —  *Where:* ResourcePool / Seize queue ordering when several tasks of the same type wait
- `assembly.stations` —  *Where:* Delay/Service 'Capacity' of assembly
- `assembly.output_conveyor_transit` —  *Where:* Conveyor length / speed
- `transport_to_selective.start_only_if_destination_has_room` — does the operator start carrying only when the selective entry has room? (false can deadlock: operator waits holding a rack) *Where:* Condition/Hold before the MoveTo, or the downstream Queue capacity check in the logic
- `transport_to_selective.exists` — operator carries the rack assembly -> selective entry? *Where:* MoveTo / Seize with 'Send seized resources' + 'Attach' between assembly and selective
- `transport_to_selective.load_time` —  *Where:* —
- `transport_to_selective.unload_time` —  *Where:* —
- `selective.racks_inside` —  *Where:* Delay/Service 'Capacity' of the selective
- `second_branch.enabled` —  *Where:* —
- `second_branch.share` — '% de utilización' of branch 2 as a routing fraction (0-1) *Where:* SelectOutput 'Probability' (or the condition used)
- `second_branch.routing_rule` — other rules (alternating, first-free, condition) are NOT IMPLEMENTED yet: tell us which one AnyLogic uses *Where:* SelectOutput / SelectOutput5 'Use' property
- `second_branch.seconds_per_circuit` —  *Where:* —
- `second_branch.racks_inside` —  *Where:* —
- `transport_to_review.start_only_if_destination_has_room` — does the operator start carrying only when the review table has room? (false can deadlock: operator waits holding a rack) *Where:* Condition/Hold before the MoveTo, or the downstream Queue capacity check in the logic
- `transport_to_review.exists` — operator carries the rack selective output -> review? *Where:* —
- `transport_to_review.load_time` —  *Where:* —
- `transport_to_review.unload_time` —  *Where:* —
- `rack_return.mode` — 'bastidor disponible nuevamente': where and when does the empty rack become available? *Where:* —
- `rack_return.load_time` — only if mode = transport_to_assembly *Where:* —
- `rack_return.unload_time` — only if mode = transport_to_assembly *Where:* —
- `layout.distances.assembly__selective_in` —  *Where:* Path length between the nodes (select the path > Length)
- `layout.distances.assembly__selective_out` —  *Where:* —
- `layout.distances.assembly__review` —  *Where:* —
- `layout.distances.selective_in__selective_out` —  *Where:* —
- `layout.distances.selective_in__review` —  *Where:* —
- `layout.distances.selective_out__review` —  *Where:* —

Stated in conversation, to confirm against AnyLogic (15):
- `benchmark.anylogic_version` = PLE 8.9
- `experiment.racks` = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
- `simulation.horizon` = 8
- `supply.mode` = infinite
- `operator.count` = 1
- `operator.strategy` = WIP_TARGET_PRIORITY
- `assembly.seconds_per_circuit` = 6
- `assembly.output_conveyor_capacity` = 2
- `transport_to_selective.racks_per_trip` = 1
- `selective.seconds_per_circuit` = 5
- `selective.input_capacity` = 3
- `selective.output_buffer_capacity` = 2
- `transport_to_review.racks_per_trip` = 1
- `review.seconds_per_circuit` = 2
- `review.tables_per_operator` = 1

Full list with where to look in AnyLogic: `required_inputs.md`.

## 10. Validation status

**BLOCKED**

Rules: BLOCKED (inputs missing) → PRELIMINARY (runs, but inputs unconfirmed / tolerances not agreed / no reference) → NOT VALIDATED (unexplained differences or engine/sanity errors) → CANDIDATE FOR ENGINEER APPROVAL (every KPI within an agreed tolerance or explained). SimForge never marks the model as validated by itself.
