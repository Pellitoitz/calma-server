# ADR-004: El esquema sólo contiene lo que el motor ejecuta
**Contexto:** la especificación pide representar turnos, energía, setups, costes… desde V1.
**Decisión:** `extra="forbid"` en todo el ISMS; los conceptos se añaden junto con su implementación y tests.
**Consecuencias:** un modelo nunca parece más completo de lo que es; el roadmap del esquema está en domain_model.md.
