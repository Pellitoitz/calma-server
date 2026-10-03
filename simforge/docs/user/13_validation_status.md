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

## Cobertura de comportamiento de la biblioteca (1.1-E, línea de desarrollo)

La biblioteca tiene **26 componentes**:

- **7 `tested`:** buffer, machine, manual_process, rack_transport, sink, source y transport.
- **19 `draft`:** aoi, cleaning, coating, functional_test, ict, inspection, manual_assembly, manual_insertion,
  packaging, pick_and_place, reflow, rework, router, screen_printer, selective_soldering, spi, test_station,
  transport_delay y wave_soldering.

Los 19 `draft` son especializaciones del comportamiento `server`, con el default `capacity: 1`. Desde 1.1-E tienen
**tests de comportamiento** (`tests/test_component_library_behavior.py`) que comprueban:

- el contrato declarado (comportamiento y defaults);
- el rechazo de parámetros desconocidos o inválidos;
- que un tiempo de proceso ausente se reporta como MISSING;
- la ejecución contra el cálculo a mano: ⌊3600 / 30⌋ = 120 unidades por ranura en 1 h;
- el rendimiento de calidad (`yield`): unidades buenas + desechadas = procesadas.

Resultado: **19 de 19 cubiertos** (BEHAVIOR_TEST_COVERED) y ningún desajuste de contrato
(COMPONENT_CONTRACT_MISMATCH).

**El estado de metadatos sigue siendo `draft`.** `validation_status` vive en los YAML de la biblioteca, que están
protegidos por FREEZE. Promoverlos a `tested` exige una **FREEZE_CHANGE_PROPOSAL** (ver
`docs/roadmap/1.1_roadmap.md`), que no se ha aplicado. «Tiene tests de comportamiento» no equivale a «estado tested».
