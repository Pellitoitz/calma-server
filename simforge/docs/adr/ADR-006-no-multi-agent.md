# ADR-006: Workflow determinista, no multi-agente
**Decisión:** una llamada LLM con schema por intención (parse / edit), orquestada por código. Sin agentes que conversan entre sí.
**Motivo:** el problema es de traducción estructurada, no de exploración abierta; los agentes añadirían coste, latencia y no-determinismo sin resolver nada concreto.
**Revisar si:** aparece una tarea abierta de varios pasos (p.ej. auto-diseño de experimentos con presupuesto) que el workflow no exprese bien.
