# 6. Resultados y KPIs

Todos los KPIs se miden en la ventana **[warm-up, horizonte]**. Con más de una réplica se muestran la media, la
desviación y el **IC 95 %**. Las definiciones están en la guía de [glosario](glossary.md) y en `simforge.analytics.kpis`.

| KPI | Unidad | Definición |
|---|---|---|
| Units completed | units | unidades que llegan a un sink en la ventana |
| Throughput | units/h | unidades completadas / horas medidas |
| Average WIP | units | unidades en el sistema, ponderadas en el tiempo |
| Average / P90 lead time | s · min | llegada al sink − entrada al sistema |
| Utilization (nodo) | % | tiempo ocupado / (ranuras × tiempo medido) |
| Blocked / Starved / Down | % | fracción del tiempo en ese estado |
| Utilization (recurso) | % | (working + walking) / (unidades × tiempo medido) |

## Informe

```bash
simforge project report <slug> [--run-id ID]
```

Genera Markdown, HTML (imprimible a PDF) y CSV de KPIs, siempre del modelo **del run**. Contenido:

- resumen;
- modelo, supuestos y MISSING;
- verificación y aprobación;
- resultados con unidades;
- diagnósticos;
- experimento;
- evaluaciones económicas;
- **estado de validación**;
- reproducibilidad.

Los diagnósticos se basan en reglas y muestran su evidencia; no son recomendaciones.
