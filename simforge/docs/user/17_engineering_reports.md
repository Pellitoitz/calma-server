# 17. Informes de ingeniería (1.1-D, línea de desarrollo)

> **Línea de desarrollo 1.1, no parte de 1.0.0-rc1.** Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED (tests
> sintéticos).

Hay dos informes nuevos. Se construyen **sólo** con evidencia ya calculada y guardada; el informe no crea evidencia.

| Informe | Fuente de cada número |
|---|---|
| **Run engineering report** | workbench de resultados (guía 6), manifiesto de reproducibilidad, evaluaciones económicas guardadas |
| **Scenario comparison report** | comparación física de runs (guía 16) y comparación económica existente (guía 12), si ambos runs están evaluados |

```bash
simforge project engineering-report <slug> <run_id> [-o carpeta]
simforge project comparison-report <slug> <run_baseline> <run_alternativo> [--baseline-eval ID --alternative-eval ID] [-o carpeta]
```

- En la UI están en la pestaña **Report**, sección *Engineering reports (1.1-D)*.
- Cada informe se escribe en tres ficheros: Markdown, HTML (generado a partir del **mismo** Markdown, así que muestra
  los mismos valores y estados) y JSON (el modelo tipado del informe). Son ficheros, no registros de la base de datos.
- No hay PDF nativo: abre el HTML e imprímelo a PDF.
- El informe de 1.0 (`simforge project report`, botón *GENERATE REPORT*) **no cambia**.

## Contenido

- **Estado de validación** (siempre presente y nunca se promueve):
  - SYNTHETICALLY_VALIDATED;
  - NOT_REAL_DATA_VALIDATED;
  - validación económica real NOT_EXECUTED;
  - aprobación del modelo del run (APPROVED / NOT_APPROVED).
- **Identidad:**
  - proyecto, run, versión del modelo y escenario;
  - hash físico, motor y versión de SimForge del run;
  - horizonte, warm-up, réplicas y semillas;
  - hashes de calendario, producción y mantenimiento (`NO_BLOCK` si el modelo no tiene ese bloque);
  - verificación.

  La hora de generación se muestra aparte: no forma parte de la identidad.
- **Manifiesto de reproducibilidad.** El de `simforge project manifest`, sin cambios ni hashes nuevos.
- **Run engineering report:**
  - resumen de KPIs con IC, réplicas y tablas por entidad (nodos, recursos, buffers, setup, mantenimiento, calendario,
    productos);
  - observaciones factuales;
  - **configuración** de productos, setups, mantenimiento y calendarios, tomada del modelo del run y separada de los
    resultados;
  - **procedencia de datos**: estado tal como está en el modelo (measured, assumed…, con dataset, base y decisión) y
    los MISSING;
  - supuestos;
  - evaluaciones económicas con su terminología exacta (`evaluated_total_cost`, cobertura, anualización, CAPEX);
  - limitaciones.
- **Scenario comparison report:**
  - identidades lado a lado;
  - comparabilidad (HARD_INCOMPATIBILITY / WARNING / INFORMATIONAL) y modo PAIRED / UNPAIRED / NOT_DETERMINABLE;
  - por KPI: baseline, alternativa y **delta = alternativa − baseline**, con el IC del delta tal como lo calcula la
    comparación;
  - economía (si ambos runs tienen evaluación):
    - deltas de coste evaluado por categoría común;
    - ahorros, categorías no comunes, anualización y CAPEX;
    - payback y retorno con sus estados, sin reinterpretarlos (UNDEFINED_METRIC, NOT_REACHED,
      REQUIRES_ENGINEER_DECISION).

## Reglas

- **Ausente ≠ cero.**
  - NOT_AVAILABLE: no guardado.
  - NOT_EVALUATED: sin evaluación económica, que no es coste cero.
  - NO_BLOCK: el bloque no existe en el modelo.
  - Un 0 real guardado se muestra como 0.
- **Elegir evaluaciones.** Si un run tiene varias evaluaciones económicas, hay que elegir una explícitamente (UI o
  `--baseline-eval` / `--alternative-eval`). Si no se elige, la sección económica es NOT_AVAILABLE; nunca se toma una
  por defecto.
- **Texto determinista.** Sin IA, sin recomendaciones y sin «mejor escenario»: los escenarios se describen lado a lado.
- **Sin re-simulación.** Generar un informe no simula, no recalcula fórmulas y no modifica runs, modelos,
  aprobaciones ni evaluaciones.

## Limitaciones

- No hay PDF nativo, narrativa IA ni plantillas configurables.
- Los datos que el motor no guarda (PHYSICAL_KPI_GAP: transiciones de setup, cola o WIP en el tiempo, espera por
  solicitante, trazas fuera del modo depuración) aparecen como NOT_AVAILABLE.
- Los valores sin procedencia declarada no se listan en la sección de procedencia.
- El informe de 1.0 contiene frases prescriptivas preexistentes («choose on secondary criteria…», «Recommendations
  must be evaluated…», sección *Risks and next steps*). Se conservan por compatibilidad (contrato de release de 1.0) y
  no forman parte de los informes de 1.1-D.
