# LLM semantic benchmark — TEXT → ProcessDraft → library → parameters → questions → ISMS

**REAL_LLM_TEST = BLOCKED_NO_API_KEY**

No Claude result exists. Nothing in this report is a Claude measurement. To run it:

```bash
cd simforge
export ANTHROPIC_API_KEY=...   # never committed, never printed
python benchmarks/llm_semantic/run_benchmark.py --provider anthropic --model claude-opus-5-5
python benchmarks/llm_semantic/make_report.py
```

Calls: 27 inputs + 20 stability repeats = 47 parse calls (+ repairs, max 2 per call).

## 1. Commit and versions (FREEZE.json)

| Item | Value |
|---|---|
| commit | `cae03a9ebdf9162a0f24b7fce2a36cc8499ec851` |
| frozen_at | `2026-10-02T05:56:00+00:00` |
| process_parser_version | `process_parser_v1` |
| compiler_version | `compiler_v2` |
| isms_version | `0.1` |
| engine_version | `0.3.0` |
| anthropic_sdk_version | `1.9.0` |
| default_claude_model | `claude-opus-5-5` |
| library | 26 components, content hash `113651d59b39991a` |
| rules library | {'shared_operator': '1.0.0', 'carrier': '1.0.0', 'fifo': '1.0.0', 'static_priority': '1.0.0', 'wip_target_priority': '1.0.0'}, hash `c1fa3e27bf29429b` |
| frozen files | 18 (sha256 in FREEZE.json; the runner refuses to run if any changed) |

## 2. Configuration

- Isolated path: `interpreter.parse → compile_draft → verify` (no project, no approval gate, no DES run, no automatic fallback to the offline interpreter: a failed LLM call is SCHEMA_VALID = NO).
- Prompt `process_parser_v1` unchanged; repairs: max 2 (existing LLMInterpreter behaviour).
- Temperature not set (not supported by current models); stability measured instead.
- Cost: only from the configured pricing table `simforge.ai.provider.PRICING` ('cached 2026-09'), labelled ESTIMATE; NOT_AVAILABLE if the model is not in the table.

## 3. Cases

| Case | Family | Title | Purpose | Gold source |
|---|---|---|---|---|
| A1 | A_PARAPHRASE | Technical Spanish | Same validated process, technical register. | examples/02_shared_operator.yaml (manual, golden test: 359 u) and the validated  |
| A2 | A_PARAPHRASE | Informal plant engineer | Same process, colloquial words, '1 minute', 'shelf' for buffer. | examples/02_shared_operator.yaml (manual, golden test: 359 u) and the validated  |
| A3 | A_PARAPHRASE | Reordered information | Same process, sentences in reverse/mixed order. | examples/02_shared_operator.yaml (manual, golden test: 359 u) and the validated  |
| A4 | A_PARAPHRASE | English | Same process in English. | examples/02_shared_operator.yaml (manual, golden test: 359 u) and the validated  |
| B1 | B_UNITS_BASIS | Per circuit vs per rack | 30 s/circuit and 15 s/circuit must stay PER_CIRCUIT; 20 s/rack PER_RACK. | explicit spec |
| B2 | B_UNITS_BASIS | Per panel vs per board, min and ms | 2 min/panel, 15 s/board, 4 min/panel, 1500 ms/board, 6 boards/panel. | explicit spec |
| B3 | B_UNITS_BASIS | Distances in cm and mm, minutes | 1250 cm, 3500 mm, 2 min, 0,9 m/s. | explicit spec |
| B4 | B_UNITS_BASIS | Per box vs per piece, decimal minutes and hours | 0,75 min/box, 3 s/piece, 10 pieces/box, 7,5 h. | explicit spec |
| C1 | C_MISSING_AMBIGUITY | Ambiguous basis | Selective time without basis in a per-circuit context. | explicit spec (B1 with the selective basis removed) |
| C2 | C_MISSING_AMBIGUITY | Transport without distance | Operator carries racks; no distance, speed, load/unload. | explicit spec |
| C3 | C_MISSING_AMBIGUITY | WIP target without value | Strategy stated, target not. | explicit spec |
| C4 | C_MISSING_AMBIGUITY | Missing time and capacity | Inspection time and buffer capacity absent. | explicit spec |
| D1 | D_CONTRADICTION | Buffer 5 vs 3 | Two incompatible capacities for the same buffer. | explicit spec |
| D2 | D_CONTRADICTION | Two assembly times | Assembly 60 s and later 75 s. | explicit spec (MVP + contradiction) |
| D3 | D_CONTRADICTION | One vs two operators | Operator count 1 vs 2. | explicit spec (MVP + contradiction) |
| D4 | D_CONTRADICTION | Distance 8 m vs 12 m | Two distances for the same path. | explicit spec |
| E1 | E_UNSUPPORTED_RULE | Conditional return with exception | Looks like WIP target but has extra conditions. | explicit spec |
| E2 | E_UNSUPPORTED_RULE | Review batching threshold | Review only with >= 2 racks waiting. | explicit spec |
| E3 | E_UNSUPPORTED_RULE | Interrupt after 10 min idle | Pre-emption triggered by a state duration. | explicit spec (MVP + rule) |
| E4 | E_UNSUPPORTED_RULE | Product colours with priority | Product mix + priority by type (no product mix in ISMS). | explicit spec (MVP + product mix) |
| F1 | F_REALISTIC | Selective cell (plant language) | Validated selective model, no library words. | selective model validated by hand (docs/diagnostics/selective_rack_anomaly.md: 1 |
| F2 | F_REALISTIC | Probabilistic routing and rework loop | Branching (60/40) and a rework loop; parser V1 is linear. | examples/04_rework_routing.yaml (manual) |
| F3 | F_REALISTIC | Two different resources | Assembler (2 tasks) + test technician. | explicit spec |
| F4 | F_REALISTIC | Breakdowns (not in the interpretation schema) | Failures MTBF/MTTR must be flagged. | explicit spec (deterministic variant of examples/03) |
| P1 | PERTURBATION | A1 perturbed | Order, synonyms, '1 minuto', 'cinco'. | examples/02_shared_operator.yaml (manual, golden test: 359 u) and the validated  |
| P2 | PERTURBATION | B1 perturbed | Order, synonyms, '0,5 min por circuito'. | explicit spec (= B1) |
| P3 | PERTURBATION | F3 perturbed | Order, synonyms, '1,5 min', '2 minutos'. | explicit spec (= F3) |

Requirement matrix: 424 requirements in `results/gold_requirement_matrix.csv` (374 in the 24 cases, 50 in perturbations). Excluded from accuracy (GOLD_REQUIRES_ENGINEER_REVIEW): `C2-R11` (walking distance to review: needed only if walking is modell), `C3-R07` (feeding tasks = assembly (intent not explicit)), `D3-R01` (topology: the text does not say whether inspection is before), `F1-R25` (feeding tasks = assembly + transport)

Gold independence: every gold is an explicit, human-reviewable spec written BEFORE its text (spec-first), derived from validated manual models where they exist (A: examples/02 + MVP 359; F1: selective model validated by hand; F2: examples/04). The gold was authored with an AI assistant in the development session, NOT by the system under test; it still needs an engineer's review before the numbers are trusted.

## 4. Claude results

**BLOCKED_NO_API_KEY** — sections 4-17 of the requested report (global results, by family, valid outputs, semantic correctness, valid-but-wrong, invented data, silent omissions, missing, ambiguity, conflicts, unsupported rules, stability, perturbation, latency, tokens, cost) will be generated from the real run by this same script.

## 5. Predicted risk areas (static analysis of the frozen code)

Found by reading the frozen code (NOT measured with Claude; to be confirmed or refuted by the real run):

| # | Risk | Where | Expected effect | Root-cause class |
|---|---|---|---|---|
| S1 | `ProcessDraft.confidence_notes` is never copied to the model: anything the LLM writes there (doubts, contradictions) never reaches the engineer | `ai/compiler.py` (only `missing_information`, `assumptions`, `custom_rules`, `unparsed` are used) | conflicts/ambiguities "noticed" by Claude but invisible | COMPILER_LIMITATION |
| S2 | The draft has no way to say "basis unknown": `time_basis` is `per_entity` or `per_item`, default `per_entity` | `ai/schemas.py` DraftStep | an ambiguous time is forced to a basis; only a free-text question can save it | SCHEMA_LIMITATION |
| S3 | No field for contradictions; the prompt does not ask to detect them | `process_parser_v1.txt` | contradictions resolved by picking one value | PROMPT_FAILURE / SCHEMA_LIMITATION |
| S4 | Linear draft: no branches, no rework loops, no breakdowns (MTBF/MTTR), no product mix | `ai/schemas.py` ("Branching is not supported by the V1 parser") | F2/F4/E4 can only be flagged, never modelled | SCHEMA_LIMITATION |
| S5 | Distributions: only process times and interarrival; yield exists, failures do not | `ai/schemas.py` DraftTime/DraftStep | stochastic statements partially representable | SCHEMA_LIMITATION |
| S6 | Grounding marks a correct converted value (e.g. 30 s x 4 = 120 s) as ASSUMED, not CALCULATED | `ai/compiler.py` _Builder.param | correct values shown as assumptions (noise in the approval screen) | COMPILER_LIMITATION |
| S7 | Operator priority not stated -> FIFO applied as an assumption + optional question (by design) | `ai/compiler.py` | acceptable if visible; counted as correct only when visible | — |

## 6. Non-Claude reference runs (harness validation — NOT Claude)

The deterministic offline interpreter is the product's fallback path. It was run to validate the evaluator end to end and to measure that fallback. Its numbers say NOTHING about Claude.

## Reference: offline (offline-rules)

Run `offline_baseline` · provider `offline` · model `offline-rules` · frozen: **True** · commit `cae03a9ebd`

### Global

| Metric | Value |
|---|---|
| SEMANTIC_REQUIREMENT_ACCURACY | 69.5% (257/370) |
| SCHEMA_VALID_RATE | 100.0% (24/24) |
| COMPILE_RATE | 100.0% (24/24) |
| EXECUTABLE_RATE | 33.3% (8/24) |
| SEMANTICALLY_CORRECT_RUNS | 16.7% (4/24) |
| INVENTED_DATA_RATE | 0.0% (0/113) |
| SILENT_OMISSION_RATE | 9.2% (34/370) |
| MISSING_DETECTION_RECALL | 100.0% (7/7) |
| AMBIGUITY_DETECTION_RATE | 0.0% (0/1) |
| CONFLICT_DETECTION_RATE | 0.0% (0/4) |
| UNSUPPORTED_RULE_DETECTION_RATE | 66.7% (4/6) |
| COMPONENT_MATCH_ACCURACY | 84.7% (83/98) |
| TOPOLOGY_ACCURACY | 40.9% (9/22) |
| PARAMETER_VALUE_ACCURACY | 68.8% (119/173) |
| UNIT_ACCURACY | 40.0% (4/10) |
| SEMANTIC_BASIS_ACCURACY | 35.7% (5/14) |
| RESOURCE_ASSIGNMENT_ACCURACY | 75.0% (21/28) |
| STRATEGY_ACCURACY | 63.6% (7/11) |
| CARRIER_SEMANTICS_ACCURACY | 20.0% (1/5) |
| ROUTING_ACCURACY | 100.0% (1/1) |

Severity counts (evaluated requirements): {"CRITICAL": 93, "MINOR": 14, "MAJOR": 6}
Error types: {"COMPONENT_MATCH_ERROR": 9, "TOPOLOGY_ERROR": 13, "FALSE_MISSING": 14, "SILENT_OMISSION": 34, "RESOURCE_ASSIGNMENT_ERROR": 6, "STRATEGY_ERROR": 4, "SEMANTIC_BASIS_ERROR": 15, "CARRIER_SEMANTICS_ERROR": 4, "PARAMETER_VALUE_ERROR": 9, "AMBIGUITY_NOT_DETECTED": 1, "CONTRADICTION_NOT_DETECTED": 4}

### By family

| Family | Correct/evaluated | CRITICAL | MAJOR | MINOR |
|---|---|---|---|---|
| A_PARAPHRASE | 44/60 | 13 | 1 | 2 |
| B_UNITS_BASIS | 49/81 | 24 | 2 | 6 |
| C_MISSING_AMBIGUITY | 54/66 | 12 | 0 | 0 |
| D_CONTRADICTION | 41/54 | 8 | 1 | 4 |
| E_UNSUPPORTED_RULE | 39/46 | 7 | 0 | 0 |
| F_REALISTIC | 30/63 | 29 | 2 | 2 |

### Summary matrix

| CASE | SCHEMA | COMPILE | VERIFY | SEMANTIC | REQ OK | CRITICAL | MAJOR | MINOR |
|---|---|---|---|---|---|---|---|---|
| A1 | YES | YES | EXECUTABLE | NO | 13/15 | 2 | 0 | 0 |
| A2 | YES | YES | INCOMPLETE | NO | 7/15 | 5 | 1 | 2 |
| A3 | YES | YES | CONFIGURED | NO | 9/15 | 6 | 0 | 0 |
| A4 | YES | YES | EXECUTABLE | YES | 15/15 | 0 | 0 | 0 |
| B1 | YES | YES | INCOMPLETE | NO | 13/20 | 7 | 0 | 0 |
| B2 | YES | YES | INCOMPLETE | NO | 16/26 | 9 | 0 | 1 |
| B3 | YES | YES | INCOMPLETE | NO | 11/21 | 4 | 1 | 5 |
| B4 | YES | YES | EXECUTABLE | NO | 9/14 | 4 | 1 | 0 |
| C1 | YES | YES | INCOMPLETE | NO | 11/19 | 8 | 0 | 0 |
| C2 | YES | YES | INCOMPLETE | NO | 18/19 | 1 | 0 | 0 |
| C3 | YES | YES | INCOMPLETE | NO | 12/15 | 3 | 0 | 0 |
| C4 | YES | YES | INCOMPLETE | YES | 13/13 | 0 | 0 | 0 |
| D1 | YES | YES | EXECUTABLE | NO | 11/13 | 2 | 0 | 0 |
| D2 | YES | YES | INCOMPLETE | NO | 10/12 | 2 | 0 | 0 |
| D3 | YES | YES | EXECUTABLE | NO | 10/11 | 1 | 0 | 0 |
| D4 | YES | YES | INCOMPLETE | NO | 10/18 | 3 | 1 | 4 |
| E1 | YES | YES | CONFIGURED | NO | 9/12 | 3 | 0 | 0 |
| E2 | YES | YES | INCOMPLETE | NO | 8/12 | 4 | 0 | 0 |
| E3 | YES | YES | CONFIGURED | YES | 11/11 | 0 | 0 | 0 |
| E4 | YES | YES | EXECUTABLE | YES | 11/11 | 0 | 0 | 0 |
| F1 | YES | YES | INCOMPLETE | NO | 6/26 | 18 | 0 | 2 |
| F2 | YES | YES | INCOMPLETE | NO | 6/11 | 5 | 0 | 0 |
| F3 | YES | YES | EXECUTABLE | NO | 10/15 | 3 | 2 | 0 |
| F4 | YES | YES | EXECUTABLE | NO | 8/11 | 3 | 0 | 0 |

### VALID_BUT_WRONG (schema valid + compiles + verifier EXECUTABLE + semantically wrong)

- **A1**
  - `A1-R02` assembly -> accepted library component: WRONG COMPONENT_MATCH_ERROR [CRITICAL, EASY_TO_NOTICE] — step present as 'machine' (machine); expected one of ['manual_assembly', 'manual_process']
  - `A1-R05` inspection -> accepted library component: WRONG COMPONENT_MATCH_ERROR [CRITICAL, EASY_TO_NOTICE] — step present as 'machine' (machine_3); expected one of ['inspection']
- **B4** — **HARD_TO_NOTICE**
  - `B4-R04` packaging -> accepted library component: WRONG COMPONENT_MATCH_ERROR [CRITICAL, EASY_TO_NOTICE] — step present as 'wave_soldering' (wave_soldering); expected one of ['packaging']
  - `B4-R07` packaging 3 s PER_PIECE: WRONG SEMANTIC_BASIS_ERROR [CRITICAL, HARD_TO_NOTICE] — 3.0 s x 1 = 3.0 s per entity; expected 30.0 (3.0 per_item, x10)
  - `B4-R08` packaging per piece: WRONG SEMANTIC_BASIS_ERROR [CRITICAL, HARD_TO_NOTICE] — expected per_item, model per_entity (work_units=1); time per entity CHANGED
  - `B4-R09` 10 pieces per box: OMITTED SILENT_OMISSION [CRITICAL, MODERATE_TO_NOTICE] — NO_PARAM (-)
  - `B4-R13` 7.5 h: WRONG PARAMETER_VALUE_ERROR [MAJOR, MODERATE_TO_NOTICE] — simulation.horizon: 28800.0 != 27000.0
- **D1** — **HARD_TO_NOTICE**
  - `D1-R06` capacity 5 vs 3 -> ASK: WRONG CONTRADICTION_NOT_DETECTED [CRITICAL, HARD_TO_NOTICE] — model uses 5.0 (provided_by_client); silent choice
  - `D1-R10` 4 racks: WRONG PARAMETER_VALUE_ERROR [CRITICAL, MODERATE_TO_NOTICE] — carrier: 3.0 != 4.0
- **D3** — **HARD_TO_NOTICE**
  - `D3-R06` one operator vs two operators -> ASK: WRONG CONTRADICTION_NOT_DETECTED [CRITICAL, HARD_TO_NOTICE] — model uses 1.0 (assumed); silent choice
- **F3**
  - `F3-R05` packaging -> accepted library component: WRONG COMPONENT_MATCH_ERROR [CRITICAL, EASY_TO_NOTICE] — step present as 'machine' (machine); expected one of ['packaging']
  - `F3-R10` assembler does assembly+packing; technician (another resource) does the test: WRONG RESOURCE_ASSIGNMENT_ERROR [CRITICAL, MODERATE_TO_NOTICE] — roles ['assembly', 'packaging'] -> operators [None, None]
  - `F3-R11` one technician: OMITTED SILENT_OMISSION [CRITICAL, MODERATE_TO_NOTICE] — NO_OPERATOR (test_station)
  - `F3-R12` one assembler: OMITTED PARAMETER_VALUE_ERROR [MAJOR, MODERATE_TO_NOTICE] — NO_OPERATOR; flagged «Hay un montador y un técnico»
  - `F3-R13` no rule invented: WRONG STRATEGY_ERROR [MAJOR, MODERATE_TO_NOTICE] — no operator found
- **F4**
  - `F4-R01` topology in flow order: WRONG TOPOLOGY_ERROR [CRITICAL, EASY_TO_NOTICE] — missing roles [] (flagged: []); order OK; extra nodes [('machine_2', 'machine')]
  - `F4-R08` 3 % scrap: WRONG PARAMETER_VALUE_ERROR [CRITICAL, MODERATE_TO_NOTICE] — test_station: 1.0 != 0.97
  - `F4-R09` breakdowns MTBF 2 h / MTTR 10 min: modelled or flagged, never dropped: OMITTED SILENT_OMISSION [CRITICAL, MODERATE_TO_NOTICE] — behaviour neither modelled nor flagged

### Stability

- A1: identical semantic interpretation 100.0% (5/5); same_topology 100.0% (5/5), same_components 100.0% (5/5), same_requirements 100.0% (5/5), same_missing 100.0% (5/5), same_assumption_paths 100.0% (5/5), same_custom_rules 100.0% (5/5)
- B1: identical semantic interpretation 100.0% (5/5); same_topology 100.0% (5/5), same_components 100.0% (5/5), same_requirements 100.0% (5/5), same_missing 100.0% (5/5), same_assumption_paths 100.0% (5/5), same_custom_rules 100.0% (5/5)
- C1: identical semantic interpretation 100.0% (5/5); same_topology 100.0% (5/5), same_components 100.0% (5/5), same_requirements 100.0% (5/5), same_missing 100.0% (5/5), same_assumption_paths 100.0% (5/5), same_custom_rules 100.0% (5/5)
- E1: identical semantic interpretation 100.0% (5/5); same_topology 100.0% (5/5), same_components 100.0% (5/5), same_requirements 100.0% (5/5), same_missing 100.0% (5/5), same_assumption_paths 100.0% (5/5), same_custom_rules 100.0% (5/5)
- F1: identical semantic interpretation 100.0% (5/5); same_topology 100.0% (5/5), same_components 100.0% (5/5), same_requirements 100.0% (5/5), same_missing 100.0% (5/5), same_assumption_paths 100.0% (5/5), same_custom_rules 100.0% (5/5)

### Perturbation robustness

- P1 vs A1: same topology False, same components False, same requirement statuses 86.7% (13/15); base correct False, perturbed correct True
- P2 vs B1: same topology False, same components False, same requirement statuses 85.0% (17/20); base correct False, perturbed correct False
- P3 vs F3: same topology False, same components False, same requirement statuses 66.7% (10/15); base correct False, perturbed correct False

### Tokens, latency, cost

Calls 0, input tokens 0, output tokens 0, average latency None ms, repairs 0, cost NOT_AVAILABLE

## 7. Instrument revisions (all before any Claude run)

- Evaluator: 'flagged' omissions only count interpreter questions and unparsed sentences (a generic compiler question containing a step word, or a custom-rule sentence, is not a warning about an omitted step).
- Evaluator: positional fallback alignment so a wrong component is one COMPONENT_MATCH_ERROR and its parameters are still evaluated (no cascading N errors).
- Evaluator: process-time requirement = physical time per entity; basis requirement separate (MAJOR if the physical time is preserved, CRITICAL if it changes).
- Evaluator: a conflict where no value was chosen = CONTRADICTION_NOT_DETECTED MAJOR (not a silent wrong value).
- Gold D3 topology marked GOLD_REQUIRES_ENGINEER_REVIEW (the text does not place the inspection before/after the machine).
- Gold keywords: 'espera' removed from buffer synonyms (false flag).

## 8. Limitations

- 24 cases (+3 perturbations): enough to find failure modes, not to estimate rates with tight confidence intervals.
- Ease-of-detection (EASY/MODERATE/HARD) is a documented rule per error type, not a usability study.
- Requirement accuracy counts consequences separately per requirement; the per-case CRITICAL list is the better read.
- Gold authored in the same development session (see §3); engineer review pending.
- The open DES tie-break decision (loaded transport vs empty rack return) does not affect this text→ISMS benchmark.
