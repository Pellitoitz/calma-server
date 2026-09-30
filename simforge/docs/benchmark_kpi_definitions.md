# Benchmark KPI definitions (SimForge engine 0.2.0)

Measurement period for every KPI: **(warm-up, horizon]**, horizon = 8 h of simulated time. Events occurring exactly
at t = 8 h are processed and counted. Time-weighted averages integrate over the same window. Deterministic model:
one replication.

| KPI | Formula | Period | Units | Events used | Included states | Excluded states |
|---|---|---|---|---|---|---|
| production | number of racks entering the Sink | (warm-up, 8 h], t = 8 h included (`production_definition = sink_count_at_stop_time`); with `completions_strictly_before_stop`: t < 8 h | racks | Sink entry | completed racks | racks in process at 8 h (partial work is never counted) |
| throughput | production / (horizon − warm-up) | idem | racks/h | Sink entry | idem | idem |
| avg_wip | ∫ WIP(t) dt / (8 h − warm-up); WIP = racks in the system | idem | racks | admission at assembly (+1), Sink / scrap (−1) | a rack from the moment the assembly station **accepts** the unit until it reaches the Sink (incl. waiting for a rack or the operator inside assembly) | empty racks returning to assembly, supply not yet admitted |
| max_wip | max WIP(t) | idem | racks | idem | idem | idem |
| lead_time | mean(Sink time − admission time) over racks completed in the period | idem | s | admission, Sink | whole path incl. waiting | racks not completed |
| operator_utilization | time the operator is assigned to a task / (operators × period) | idem | fraction 0–1 | assignment, release | working (processing, loading, unloading), walking to the task, transporting (loaded and empty return) | idle |
| selective_utilization | time processing / (slots × period), branch 1 | idem | fraction 0–1 | start/end of processing | processing (BUSY) | **blocked** (finished, output full), starved, down |
| selective_starvation | time with no rack to process / (slots × period) | idem | fraction 0–1 | slot state changes | STARVED | busy, blocked |
| selective_blocking | time finished but unable to unload / (slots × period) | idem | fraction 0–1 | slot state changes | BLOCKED | busy, starved |
| trips | transport trips delivered, all operator transports | idem | trips | unload at destination | completed trips | trips in progress at 8 h |
| racks_transported | racks delivered by all transports (loaded and empty returns) | idem | racks | unload | idem | idem |
| walking_time | time walking unloaded to reach the next task | idem | h | assignment → arrival | walking without load | carrying (transporting), load/unload |
| assembly/review time (detail) | time in `working:<task>` | idem | h | — | processing at that task | walking to it |
| transport time (detail) | load + unload + loaded travel + empty return | idem | h | — | transport task | walking to the origin |
| idle time (detail) | time without task | idem | h | — | idle | — |
| racks per trip | racks_transported / trips | idem | racks | — | — | — |
| queues (detail) | time-weighted content of each buffer | idem | racks | buffer entry/exit | racks stored incl. one waiting for pickup | racks on board of a transport |
| production over time | cumulative Sink count at 1 h, 2 h, … 8 h | [0, h] | racks | Sink entry | — | — |

**Known definition risks to confirm with AnyLogic** (write the AnyLogic definition in `benchmark/anylogic_kpi_definitions.yaml`):

- *Utilization*: AnyLogic `Delay`/`Service` utilization usually counts an agent that finished but cannot leave as
  *busy*; SimForge counts it as **blocked**, not busy. Compare `selective_utilization + selective_blocking` if needed.
- *ResourcePool utilization*: does AnyLogic count walking/moving time of the operator as busy? SimForge does.
- *WIP*: time-weighted (SimForge) vs. sampled (e.g. a dataset sampled every N s).
- *Production at 8 h*: does the Sink count an arrival at exactly 8 h? SimForge reports both variants.
- *Walking time*: SimForge splits walking (unloaded) from transporting (loaded + empty return).
