# Capa de IA

## Principio

```
LLM → configuración (schema) → compilador determinista → verificador → motor → resultados → (LLM interpreta)
```
El LLM **nunca** produce resultados, nunca ejecuta código, nunca aprueba modelos.

## Piezas

| Módulo | Función |
|---|---|
| `provider.py` | `LLMProvider` (interfaz), `AnthropicProvider` (structured outputs con `messages.parse`, modelo por defecto `claude-opus-5-5`, configurable con `SIMFORGE_LLM_MODEL`), `MockLLMProvider` (tests). Registro de tokens y coste estimado. |
| `rule_based.py` | Intérprete **offline** determinista (ES/EN) para procesos lineales y comandos habituales. |
| `schemas.py` | `ProcessDraft` (pasos, recursos, políticas, lazos de carriers, experimentos, faltantes, supuestos) y `EditPlan` (intents: set, experiment, run, revert, compare_baseline, explain_bottleneck, explain_waiting). |
| `compiler.py` | Draft → ISMS: búsqueda en biblioteca, configuración, supuestos, faltantes, **grounding numérico**. |
| `context.py` | Frontera de privacidad: sólo texto de la petición + catálogo + esquema del modelo; anonimización. |
| `interpreter.py` | `LLMInterpreter` (validación semántica, reparación ×2, auditoría, fallback) / `RuleBasedInterpreter` con el mismo contrato. |
| `prompts/` | Prompts versionados (`process_parser_v1.txt`, `edit_planner_v1.txt`). |
| `edits.py` | Cambios por chat sobre parámetros (`$ref` → `parameters.<id>.value`), política de correcciones. |
| `tools.py` | Herramientas controladas para un orquestador IA (sin aprobar, sin código). |

Flujo completo, matching report, aprobación, comparación A/B y productividad: [`ai_orchestration.md`](ai_orchestration.md).

## Responsabilidades (punto 7 de la especificación)

| | Implementado en |
|---|---|
| A Parser industrial | `Interpreter.parse` + `compile_draft` |
| B Detector de información faltante | compilador (tiempos, capacidades, carriers, llegadas) + LLM (`missing_information`) |
| C Generador de preguntas | `ISMSModel.missing` (requeridas bloquean; opcionales no) |
| D Selector de componentes | compilador: id exacto → búsqueda por keywords → genérico con supuesto |
| E Configurador | compilador |
| F Asistente de experimentos | `EditPlan.intent=experiment`, `ProcessDraft.experiments` |
| G Analista | hechos deterministas (`diagnose`) mostrados con evidencia; narrativa LLM: NOT IMPLEMENTED |
| H Informes | plantilla determinista; redacción LLM: NOT IMPLEMENTED |

## Anti-alucinación

1. Schemas estrictos (structured outputs): el LLM no puede devolver texto libre.
2. **Grounding**: cada número del draft debe aparecer en la descripción; si no, `provenance.status=assumed` + supuesto visible.
3. Valores no indicados → `MISSING` (no se inventan). Excepción explícita: horizonte 8 h, FIFO, suministro infinito → siempre como supuestos.
4. Las operaciones de edición se aplican con `set_value` + validación Pydantic; con LLM, una ruta inexistente provoca reparación y, si persiste, el plan se descarta (fallback offline).
5. Cambios importantes (≥3 parámetros, recursos a 0, modelo aprobado, revertir) piden confirmación.
6. El modelo aprobado queda ligado a su hash; la IA no puede "heredar" la aprobación.

## Privacidad

Nunca se envían: adjuntos, estudios de tiempos, resultados, historial, metadatos del proyecto.
`Project.meta.sensitive_terms` (UI → Project) sustituye nombres de clientes, referencias o personas por
marcadores antes de enviar y los restaura en la respuesta. `LLMInterpreter.last_context` permite inspeccionar
exactamente lo enviado; `llm_usage` registra tokens, coste estimado y caracteres enviados.

## Proveedor real

`ANTHROPIC_API_KEY` en `.env`. Sin clave → intérprete offline automáticamente.
Nota: no se usa `tool_choice` forzado (rechazado por los modelos actuales); se usan structured outputs.
Las *fallbacks* por rechazo del servidor no están activadas (la petición es de parsing técnico; un rechazo
se muestra como error legible).
Modelos locales (Ollama, llama.cpp): implementar otro `LLMProvider` con el mismo método `structured`.
