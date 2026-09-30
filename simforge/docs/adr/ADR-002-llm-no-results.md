# ADR-002: El LLM no puede generar resultados
**Decisión:** el LLM sólo rellena schemas de configuración (`ProcessDraft`, `EditPlan`). Los números salen del motor; los diagnósticos, de reglas deterministas con evidencia. Grounding numérico obligatorio.
**Consecuencias:** interpretaciones menos "fluidas", pero auditables y reproducibles.
