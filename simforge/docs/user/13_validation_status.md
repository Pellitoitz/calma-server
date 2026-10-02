# 13. Estado de validación

Dos preguntas distintas que nunca se mezclan:

| | Pregunta | Estado en 1.0 |
|---|---|---|
| **Madurez del software** | ¿hace SimForge lo que dice de forma estable y reproducible? | suite automatizada (unit, integration, regression, release), workflow golden, instalación limpia |
| **Validación industrial** | ¿representa un modelo la realidad de una planta concreta? | **ninguna** capacidad está REAL_DATA_VALIDATED |

Etiquetas por capacidad (ver `docs/release/1.0_capability_matrix.md`):

| Etiqueta | Significado |
|---|---|
| `SYNTHETICALLY_VALIDATED` | probado con casos de resultado conocido (tests). Es el estado de todas las capacidades de dominio |
| `REAL_DATA_VALIDATED` | sólo por capacidad, caso y periodo, con un protocolo firmado. **Nunca** se aplica a «SimForge» en conjunto |
| `NOT_TESTED` / `NOT_EXECUTED` | sin estudio real ejecutado: calendarios (protocolo READY) y economics (READY_FOR_REAL_ECONOMIC_VALIDATION) |
| `EXPERIMENTAL` | asistente IA y benchmark AnyLogic (BLOCKED) |

- El modelo de **tu** proyecto lo valida el ingeniero. La aprobación significa que lo ha revisado; no que esté validado
  contra datos.
- Los ejemplos son sintéticos y **nunca** son una prueba de validación.
