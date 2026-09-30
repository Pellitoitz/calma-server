# WIP_TARGET_PRIORITY — exact semantics as implemented (engine 0.2.0)

Source: `src/simforge/engine/des/dispatch.py` (rule), `runtime.py` (`ResourcePool._dispatch`), `nodes.py` (who requests
the operator and when). This document describes what the code DOES, so it can be compared line by line with the
AnyLogic logic. It is **not** a claim of equivalence.

## Vocabulary

- **Task / request**: a node asks the pool for the operator. Only nodes that *physically have work ready* request:
  - a station (assembly, review) once a unit occupies one of its slots **and** holds every carrier it needs;
  - a transport once a unit is waiting to be picked up (and, if `reserve_destination`, once a place at the destination is reserved).
- **Candidates**: the requests waiting at decision time. A task that has not requested is invisible to the rule
  (the operator never pre-positions or waits for future work).
- **Feed WIP** = Σ `occupancy()` of `feed_nodes` + (if `count_feeder_in_process`) assembly slots in BUSY or BLOCKED.
  - buffer occupancy = racks stored, **including** a rack waiting to be picked up by a transport;
  - transport occupancy = racks on board (+ racks in an explicit loading area);
  - assembly slots WAITING for the operator are **not** counted.
- **Protected node** = the selective (branch 1). **Feeder tasks** = `feeder_nodes` (assembly + configured transports).

## 1. When is the decision evaluated?

1. When a task requests the operator.
2. When an operator finishes a task (release).
3. When any watched node changes (feed nodes, feeder nodes, protected node): relevant only if requests are waiting
   and an operator is free, or for pre-emption.

Default timing: **after all events of the same timestamp** (`dispatch_timing: end_of_timestep`), so every request
created at that instant competes. Alternative `immediate`: in event order, first come first decided.
**Measured sensitivity is large in the synthetic benchmark (up to −11 % production): AnyLogic's tie handling is a key input.**

## 2. Which variables does it use?

`feed_wip`, `target`, `protected_node` state (BLOCKED or not), request order (FIFO sequence), `preempt_below`.
It does **not** use: remaining processing time of the selective, racks available, queue at review, walking distances
(distance only chooses *which* operator when there are several: the nearest free one).

## 3. What does "WIP target" mean?

An integer number of racks ready to feed the selective (definition above). Assembly-class tasks are preferred while
`feed_wip < target`. If AnyLogic uses `<=`, the equivalent SimForge target is `target + 1` (integers; no code change).

## 4. Assembly and review available at the same time?

Evaluated in this order:
1. Selective BLOCKED (cannot unload) and a non-feeder task waits → **non-feeder** (`PROTECTED_BLOCKED`). Can be disabled (`unblock_protected: false`).
2. `feed_wip < target` and a feeder task waits → **feeder** (`WIP_BELOW_TARGET`).
3. Otherwise, a non-feeder task waits → **non-feeder** (`WIP_AT_OR_ABOVE_TARGET` or `NO_FEEDER_WAITING`).
4. Only feeder tasks waiting → feeder (`ONLY_FEEDER_WAITING`).
Within a class: FIFO by request time; simultaneous requests by creation order.

## 5. When does it leave review?

- Default (`preempt_below: null`): **never in the middle of a task**. It re-evaluates when the review task ends.
- With `preempt_below = n`: while processing a non-feeder task, if `feed_wip < n`, a feeder task waits and the selective
  is not blocked, the task is **suspended** (remaining time kept, logged `PREEMPT_WIP_BELOW_THRESHOLD`), the operator
  goes to the feeder task, and the suspended task re-requests (marked `resume`) and is served under the same rules.
  Walking and transports are never pre-empted.

## 6. When does it return to assembly?

At the next decision after finishing its current task, if an assembly request is waiting and rule 2 applies (or rule 4).

## 7. What if a buffer is full?

- Assembly finished and the conveyor is full → assembly slot BLOCKED (blocking-after-service); the **operator is released
  before** the rack moves, so it is free for other tasks; no new assembly request until the slot frees.
- Transport destination full: with `reserve_destination: true` the transport waits **without** the operator; with `false`
  the operator waits holding the rack (can create a circular wait; the engine then aborts with `DeadlockError`).

## 8. What if no racks are available?

Assembly: the next unit enters the assembly slot and waits for a rack (WAITING_RESOURCE) **without** requesting the
operator; the operator serves other tasks. When a rack is released (end of review, or end of the empty-rack return
trip) the assembly takes it and only then requests the operator.

## 9. What if the selective is about to starve?

There is **no look-ahead**: the rule does not know the selective's remaining time. It reacts only to the count
`feed_wip` (and to BLOCKED). A target ≥ 1 keeps racks ready in advance; anticipating by time would be a different rule.

## 10. Decision log (trace mode)

Every assignment and pre-emption: `t`, `time` (hh:mm:ss), `resource`, `units`, `current_task` (last task of the unit),
`candidates` (node, entity, priority, resume, waiting time), `chosen_node`, `reason_code`, `reason`, `state`
(`feed_wip`, `target`, `feed_detail` per node, protected node state) and `system` (all buffers, stations, transports,
available racks, WIP). Command: `simforge benchmark trace --racks N --minutes 15`.
