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

## Results workbench (1.1-C, línea de desarrollo)

> **Línea de desarrollo 1.1, no parte de 1.0.0-rc1.** Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED (tests
> sintéticos).

En la pestaña **Run & results**, debajo de los resultados de 1.0, la sección **Results workbench** organiza el run
seleccionado. Trabaja **sólo con resultados guardados**: no simula, no recalcula ninguna definición de KPI y no
modifica el run ni el modelo.

- **Identidad.** Muestra el run, la versión del modelo (y el escenario, si lo hay), el hash, el motor, el horizonte,
  el warm-up, las réplicas y las semillas.
- **Resumen de KPIs.** Media, desviación, IC 95 %, mínimo y máximo de las estadísticas guardadas, con la unidad de la
  definición del KPI.
  - Con **una réplica**, la desviación y el IC no existen (no se muestra 0).
  - El IC es el ya guardado: t de Student sobre las réplicas.
- **Réplicas.** Valores guardados de cada réplica (con su semilla), junto a la media, la desviación y el IC.
- **Tablas por entidad.** Una columna aparece sólo si está guardada para alguna entidad, y una sección sólo si tiene
  datos. Secciones:
  - nodos: estados y flujo;
  - OEE (estaciones sin calendario);
  - buffers y espera;
  - transporte;
  - recursos;
  - setup (más totales de sistema);
  - mantenimiento;
  - calendario de nodos y de recursos;
  - productos.
- **Estados de un valor:**
  - **NOT_AVAILABLE:** el KPI no está guardado para esa entidad. Nunca se muestra como 0.
  - **UNDEFINED:** está guardado pero no definido (NaN). Por ejemplo, un lead time sin unidades completadas.
  - Un **0 real** guardado se muestra como 0.
- **Observaciones factuales.** Frases deterministas sobre valores guardados. Por ejemplo: «*test recorded the highest
  stored value of Utilization (90.6 %) among the 2 nodes with this metric (mean of 5 replications, run …)*».
  - Si todas las entidades tienen el mismo valor, se dice así.
  - No interpretan, no recomiendan y no atribuyen causas.
- **Top-N.** `sort(métrica, orden) → primeros N`, con el orden declarado (descendente o ascendente).
  - Los empates se resuelven por el id de la entidad (ascendente).
  - Las entidades sin valor definido se excluyen y se listan.
  - Es una ordenación de valores, **no** una prioridad, una gravedad ni un potencial de mejora.
- **KPIs sobre el grafo.** El grafo del modelo **del run** (el mismo hash) con el valor guardado de la métrica elegida
  en cada nodo.
  - Los nodos sin la métrica muestran `NOT_AVAILABLE`.
  - Sólo hay texto: no hay escala de colores ni semántica «rojo = malo».
  - Si el modelo del run no está guardado como versión, no hay superposición.

### Limitaciones del workbench

- Sólo expone lo que el motor guarda; un KPI no guardado no se infiere.
- No hay diagnóstico causal, recomendaciones, IA ni optimización. No se crean KPIs físicos nuevos.
- El workbench se calcula bajo demanda y no se guarda (sin migración).
- Datos que el motor **no guarda** (PHYSICAL_KPI_GAP; se muestran como NOT_AVAILABLE):
  - las transiciones de setup origen → destino;
  - la longitud de cola o el WIP a lo largo del tiempo;
  - el tiempo de espera de cada solicitante de un recurso;
  - las trazas, salvo en runs en modo depuración (CSV).
- Los diagnósticos por reglas de 1.0 siguen apareciendo tal como estaban. Las observaciones de 1.1-C son una capa
  aparte y sólo descriptiva.
