# Orquestación IA: lenguaje natural → modelo construido con la biblioteca

> La IA construye, el motor calcula, el sistema comprueba, el ingeniero valida.

Este documento describe **sólo lo implementado**. Lo que no existe está en la sección final.

## Flujo

```
TEXTO DEL USUARIO
 → interpretación (LLM con schema estricto, o intérprete offline determinista)   ai/interpreter.py, ai/rule_based.py
 → ISMS estructurado: cada número es un ModelParameter con procedencia          ai/compiler.py
 → matching contra la biblioteca (componentes + reglas/estrategias)             library/registry.py, library/rules/
 → detección de información faltante + preguntas agrupadas                      ParseOutcome.questions_text()
 → ensamblado del modelo (MODEL BUILD PLAN)                                     BuildPlan.to_text()
 → verificación                                                                 validation/verifier.py
 → APROBACIÓN DEL INGENIERO (obligatoria antes de la 1ª ejecución)              SimForgeApp.approve_model
 → simulación (motor propio)                                                    engine/des
```

El LLM **nunca** genera código SimPy/Python ni resultados. Sólo rellena `ProcessDraft` / `EditPlan`.

## ISMS = fuente de verdad

- Cada valor numérico del modelo generado es un `ModelParameter` (`parameters.<id>.value`) referenciado como
  `$id` desde nodos y recursos. El chat no es el modelo: *"Cambia el buffer de entrada de 3 a 5"* produce
  `parameters.buffer_de_entrada_capacity.value: 3 → 5` y una versión nueva.
- Si el ingeniero indica el valor actual (*"de 3 a 5"*) se comprueba contra el ISMS; si no coincide se pide confirmación.
- Un cambio que no cambia nada no crea versión.

## Clasificación de parámetros

| Estado | Origen |
|---|---|
| USER_PROVIDED (`provided_by_client`) | número presente en el texto, respuesta a una pregunta (`source: answer`) o cambio por chat (`source: chat`) |
| ASSUMED | número que el intérprete propone pero no aparece en el texto (grounding) o decisión de modelado explícita (p. ej. base = 1º nivel del experimento) |
| DEFAULT | valor de `library/rules/defaults.yaml`, **sólo** en modo prototipo (`prototype=True`) y siempre como supuesto visible |
| CALCULATED | expresiones (p. ej. distancia entre puestos no consecutivos = suma de tramos, con supuesto de layout lineal) |
| MISSING | sin valor → pregunta obligatoria, el modelo no es ejecutable |
| MEASURED / IMPORTED | estados del esquema disponibles para datos medidos/importados (no los asigna la IA) |

## Matching report

```
PROCESS ELEMENT                     MATCH
Manual assembly                     manual_assembly v1.0.0  [component, exact]
Buffer de entrada                   buffer v1.0.0  [component, exact]
Selective soldering                 selective_soldering v1.0.0  [component, exact]
Operario (operator, compartido)     shared_operator v1.0.0  [resource_type, engine_rule]
Regla del operario: WIP objetivo    wip_target_priority v1.0.0  [strategy, keyword]
REUSED COMPONENTS: 10   CUSTOM COMPONENTS: 0   REUSE RATIO: 100%
```

Las reglas (`shared_operator`, `carrier`, `fifo`, `static_priority`, `wip_target_priority`) están en
`library/rules/rules.yaml`, versionadas y ligadas a una primitiva del motor (`binding`).
Sinónimos ES/EN (cola / buffer / almacén intermedio; operario / trabajador / persona) están en los `keywords`.

## Preguntas agrupadas

`ParseOutcome.questions_text()` → *"Para poder ejecutar el modelo necesito N datos: 1. … "* + lista opcional.
Las respuestas (`answer_questions(project, {"param:<id>": valor, "return_mode:<carrier>": "immediate"|"transport"})`)
se fusionan con las anteriores y la interpretación guardada se **recompila de forma determinista**.

## Aprobación

Un modelo `meta.origin = ai_generated` no se ejecuta (ni simulación ni experimento) hasta que un ingeniero aprueba
una versión (`ApprovalRequired`). La UI muestra flujo, componentes, parámetros, supuestos, faltantes y lógica
custom antes del botón APPROVE MODEL. Ninguna herramienta de la IA puede aprobar.

## Lógica custom

Una frase condicional (*"si…", "cuando…"*) o una prioridad no interpretable se convierte en `CustomRuleCandidate`
(descripción, motivo). **Bloquea** la ejecución (`CUSTOM_RULE_PENDING`) hasta que el ingeniero decide:
`deferred` (se ejecuta SIN la regla, avisado como `CUSTOM_RULE_NOT_MODELLED`) o `rejected`.
La IA no genera ni ejecuta la implementación. El flujo de promoción
CUSTOM RULE → USED → VALIDATED → REUSED → CANDIDATE → ENGINEER APPROVAL → LIBRARY COMPONENT es un proceso del
ingeniero (implementar + test + `validation_status` en la biblioteca); el sistema sólo detecta repeticiones.

## Correcciones y aprendizaje controlado

- Se registra una corrección (`corrections`: valor IA → valor ingeniero, motivo, petición) cuando el ingeniero cambia
  un valor que **la IA produjo sin que estuviera en el texto** (asumido/default/calculado) o cuando dice que el valor
  interpretado era incorrecto (*"porque lo hemos medido"*, *"en realidad"*, *"está mal"*…). Un *what-if* sobre un valor
  que el usuario dio no es una corrección.
- `library_improvement_candidates()` agrupa correcciones repetidas (componente + parámetro) y reglas custom repetidas
  en todos los proyectos → `CANDIDATE_FOR_LIBRARY_IMPROVEMENT`. **La biblioteca nunca se modifica automáticamente.**

## Modelo A (manual) vs Modelo B (generado)

`compare_model_specs(A, B)` (`validation/equivalence.py`) distingue:

- **TEXTUAL EQUALITY**: mismo texto serializado.
- **SAME JSON**: mismo contenido, cualquier orden de claves.
- **STRUCTURAL EQUIVALENCE**: mismo sistema sobre el modelo **resuelto**, con mapeo de nodos por isomorfismo de grafo;
  no importan ids, nombres, orden, `$param` vs número, unidades (1 min = 60 s) ni defaults de biblioteca omitidos.
  Categorías: nodes, connections, resources, parameters, capacities, routing, strategies, rules, experiments, simulation.

Si son estructuralmente equivalentes, `compare_models(A, B)` ejecuta ambos y compara producción, throughput, WIP,
lead time, utilizaciones, starvation, blocking, espera de recurso, andar/transportar (por elemento mapeado).
Resultado comprobado en los tests: el MVP generado desde texto ≡ `examples/02_shared_operator.yaml`
(estructura idéntica y KPIs idénticos, 359 unidades).

## Productividad

`services/productivity.py`: `manual_model_build_time` (USER_PROVIDED), `AI_initial_generation_time` (MEASURED),
`engineer_review_time` (MEASURED: reloj de pared desde la generación hasta la aprobación, **cota superior** que incluye
correcciones y pausas; o USER_PROVIDED), `correction_time` (sólo USER_PROVIDED; si no, incluido en la revisión),
`total_AI_assisted_time`, **TIME SAVED** y **TIME SAVED %**. También REUSE RATIO y `custom_logic_count`.

## LLM: schema, reparación, auditoría, versiones

- Prompts versionados en `ai/prompts/*.txt` (`process_parser_v1`, `edit_planner_v1`). La versión queda en
  `meta.generated_by.prompt_version` de cada modelo y en cada fila de auditoría.
- Salida validada por schema **y** por comprobaciones semánticas (componentes existentes, referencias a pasos/recursos,
  rutas existentes en el modelo). Si falla: se reenvía con los errores (*repair*), máx. 2 veces; nunca se usa JSON roto.
- Si el LLM falla o no repara: **fallback sin IA** (intérprete offline), indicado en el intérprete/mensaje.
- `ai_audit`: entrada tal como se envió (ya anonimizada), proveedor, modelo, versión de prompt, salida, errores de
  validación, reparaciones, aceptado, tokens, coste estimado, latencia. La API key nunca forma parte de nada de esto
  (test: el secreto no aparece en ningún fichero del proyecto).
- Determinismo: el intérprete offline y el compilador son deterministas (test); con LLM no se fija temperatura
  (no soportada por los modelos actuales); la estabilidad viene del schema + compilador + verificación.

## Herramientas controladas (`ai/tools.py`)

`search_components, inspect_component, create_model_spec, update_model_spec, validate_model, compare_models,
run_simulation, run_experiment, get_results` — argumentos con schema estricto (`extra=forbid`), formato de tool-use
de Anthropic (`definitions()`), errores devueltos como datos. No existen herramientas para aprobar, modificar la
biblioteca, leer ficheros ni ejecutar código.

## CLI

```bash
simforge ai new "Línea MVP" "Fuente infinita. Un operario monta una pieza durante 60 segundos. ..." [--offline] [--prototype]
simforge ai answer <slug> param:manual_assembly_time=60 return_mode:racks=immediate
simforge ai approve <slug> --by "Nombre"
simforge ai run <slug>
simforge ai say <slug> "Cambia el buffer de entrada de 3 a 5" [--yes]
simforge ai say <slug> "prueba buffers de 1 a 10"
simforge ai custom-rule <slug> custom_1 deferred --by "Nombre"
simforge ai compare examples/02_shared_operator.yaml <slug>@3
simforge ai corrections <slug>
simforge ai candidates
simforge ai productivity <slug> --manual-min 240 [--review-min 22 --correction-min 10]
simforge ai audit <slug>
```

## Prueba manual con Claude real (fuera de CI)

```bash
export ANTHROPIC_API_KEY=...    # o en .env (ignorado por git). Nunca en el código.
python scripts/manual_claude_test.py --model claude-sonnet-5-5
```
Imprime matching report, plan, preguntas, auditoría (tokens, coste, latencia, reparaciones) y, para el MVP,
compara el modelo del LLM con el del intérprete offline y ejecuta. Nunca imprime la clave.

## NO implementado

- Bucle agente autónomo que llame a las herramientas con Claude (existe el registro de herramientas y su dispatcher).
- Implementación de reglas custom por la IA (sólo candidatas; la promoción a biblioteca es manual).
- Procesos con ramificaciones desde texto (el intérprete produce flujos lineales; el ISMS sí soporta routing).
- Medición separada del tiempo de corrección (sólo si el ingeniero lo introduce).
- Búsqueda semántica por embeddings (el matching es por keywords deterministas).
