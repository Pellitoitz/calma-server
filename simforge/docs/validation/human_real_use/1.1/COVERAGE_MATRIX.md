# Matriz de cobertura — uso humano real, línea 1.1

## Dependencias conocidas antes de las sesiones (hechos de la revisión final)

Fuente: `docs/roadmap/1.1_final_review.md` §7. No son hallazgos de sesión: son el punto de partida contra el que se
contrasta lo que observe el ingeniero.

| Paso | Dónde (UI / CLI) | Dependencia de YAML o limitación documentada |
|---|---|---|
| START | instalación + `simforge ui` / `simforge --help` | — |
| PROJECT | pestaña Project / `simforge project …` | — |
| DATA | pestaña Data / `simforge data …` | — |
| MODEL BUILD | pestaña Model (builder + editor de parámetros) | YAML para productos/mix/setups (C04), mantenimiento (C05), `seize`/`release`, `travel`, `wip_target`, posiciones |
| VERIFY | pestaña Model / `simforge validate` | MISSING bloquea (comportamiento esperado) |
| APPROVE | Model / Run / Project / `project approve` | renombrar un nodo invalida la aprobación (B-2) |
| RUN | Run & results / `project run` | — |
| RESULTS WORKBENCH | Run & results | PHYSICAL_KPI_GAP (setups origen→destino, WIP en el tiempo, esperas por recurso, trazas) |
| SCENARIO | Project / `scenario-clone`, `scenario-set` | cambios estructurales en el builder |
| COMPARE | Project / `compare-runs` | horizonte o warm-up distinto = NOT_COMPARABLE |
| ECONOMICS | Economics / `project evaluate` | sólo las bases ofrecidas; potencia de energía sólo vía YAML; bases no soportadas en solo lectura |
| ENGINEERING REPORT | Report / `engineering-report`, `comparison-report` | Markdown/HTML, sin PDF nativo |

## Cobertura observada por sesión (a rellenar tras cada sesión)

Valores: `COMPLETED` / `BLOCKED` / `NOT_APPLICABLE` / `NOT_TESTED`. Añadir una columna por sesión ejecutada.

| Paso | H-001 |
|---|---|
| START | NOT_TESTED |
| PROJECT | NOT_TESTED |
| DATA | NOT_TESTED |
| MODEL BUILD | NOT_TESTED |
| VERIFY | NOT_TESTED |
| APPROVE | NOT_TESTED |
| RUN | NOT_TESTED |
| RESULTS WORKBENCH | NOT_TESTED |
| SCENARIO | NOT_TESTED |
| COMPARE | NOT_TESTED |
| ECONOMICS | NOT_TESTED |
| ENGINEERING REPORT | NOT_TESTED |
