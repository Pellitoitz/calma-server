# ADR-001: Modelo intermedio (ISMS) independiente del motor
**Estado:** aceptada. **Contexto:** evitar lock-in (AnyLogic, SimPy) y permitir varios consumidores (motor, visualizador, informe).
**Decisión:** ISMS en Pydantic/YAML es la única fuente de verdad; los motores reciben un `CompiledModel` y devuelven `RunRecord`.
**Consecuencias:** un adaptador por motor; SimPy confinado a `engine/des`.
