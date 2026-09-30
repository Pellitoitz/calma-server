# Benchmark — SimForge vs. AnyLogic (selective soldering)

Goal: find out whether the SimForge engine reproduces the engineer's AnyLogic model **with the same system, parameters,
rules and KPI definitions**, trying to *falsify* the engine. No parameter is ever tuned to match AnyLogic.

Frozen pre-benchmark state: git tag `pre-anylogic-benchmark` (commit `82e7a84`).

| File | Role | Who fills it |
|---|---|---|
| `selective_soldering_config.yaml` | every parameter, with status (`REQUIRED_FROM_ANYLOGIC`, `USER_STATED_TO_CONFIRM`, `CONFIRMED`, `ENGINE_CHOICE`) and where to find it in AnyLogic | engineer (from AnyLogic) |
| `required_inputs.md` | generated table of inputs and their status (`simforge benchmark inputs`) | generated |
| `anylogic_results.csv` | AnyLogic results, racks 1–10 (fractions 0–1, lead time s, walking h) | engineer |
| `anylogic_kpi_definitions.yaml` | how AnyLogic computes each KPI | engineer |
| `difference_explanations.yaml` | cause of each investigated difference | engineer + Claude |
| `engine_results.csv` | engine results, same columns as the AnyLogic template | generated |
| `engine_results_detail.csv` | operator time split, queues, theoretical bound, event-ordering sensitivity | generated |
| `engine_production_timeseries.csv` | cumulative production per hour | generated |
| `comparison.csv`, `benchmark_report.md`, `charts/` | comparison per KPI and scenario (no global score), report, charts | generated |
| `run_manifest.json`, `generated_models/` | reproducibility: engine version, config hash, model hashes, seeds, git commit, generated ISMS models | generated |
| `traces/` | short event/decision traces | generated |

```bash
simforge benchmark inputs                         # what is missing?
simforge benchmark selective-soldering            # run 1..10, compare, report, charts (BLOCKED until inputs are complete)
simforge benchmark trace --racks 3 --minutes 15   # event-by-event trace to compare with AnyLogic
python -m simforge.benchmark.run_selective_soldering --dir benchmark
```

Status ladder: BLOCKED → PRELIMINARY → NOT VALIDATED / CANDIDATE FOR ENGINEER APPROVAL. The engine never declares itself validated.

Safety nets active in every run: rack/entity conservation invariants, bounded levels, utilization ≤ 100 %,
deadlock detection, theoretical-capacity sanity check, simultaneous-event sensitivity run.
