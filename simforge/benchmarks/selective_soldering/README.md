# Benchmark: soldadura selectiva (SimForge vs. AnyLogic)

Objetivo: comprobar si SimForge reproduce **conceptualmente** el modelo AnyLogic del ingeniero
(1–10 bastidores). **Prohibido ajustar parámetros para que coincida**: cada diferencia se explica.

| Fichero | Contenido |
|---|---|
| `model.yaml` | Reconstrucción ISMS. Datos no proporcionados = parámetros `value: null` (REQUIRED). Hipótesis estructurales en `assumptions`. |
| `benchmark.yaml` | Factor (bastidores 1–10), 11 métricas, clave del motor, tolerancias propuestas y causas probables. |
| `anylogic_results.csv` | **Vacío**. Se rellena con los resultados reales de AnyLogic. Nunca se estima. |
| `anylogic_definitions.yaml` | Cómo calcula AnyLogic cada KPI, warm-up, horizonte. |
| `DATA_REQUIRED.md` | Lista exacta de datos que faltan. |
| `results/` | Generado: `engine_results.csv`, `comparison.csv`, `comparison.md`, trazas. |

## Uso

```bash
simforge benchmark status benchmarks/selective_soldering/benchmark.yaml     # ¿qué falta?
# 1) rellenar parámetros null en model.yaml   2) rellenar anylogic_results.csv y anylogic_definitions.yaml
simforge benchmark run benchmarks/selective_soldering/benchmark.yaml --trace-scenario 6
```

Comparación: `abs_error = motor − AnyLogic`, `rel_error_pct = |motor − AnyLogic| / AnyLogic × 100`
(n/a si AnyLogic = 0). Estados: `OK`, `DIFF`, `DIFF_REF_ZERO`, `NO_REFERENCE`, `ENGINE_ERROR`.
Cada `DIFF` trae comprobación de ruido (modelo determinista → aleatoriedad descartada) y causas a investigar:
lógica, warm-up, definición de KPI, eventos simultáneos, capacidad, transporte, reglas del operario, aleatoriedad.
El informe incluye la tabla de definiciones de KPI SimForge vs. AnyLogic y una checklist de causas que hay que
cerrar antes de aprobar el modelo.

## Definiciones SimForge relevantes (para comparar con AnyLogic)

- **Producción**: bastidores que llegan a la salida en (warm-up, 8 h]; eventos en t = 8 h cuentan.
- **Utilización de la selectiva**: tiempo *procesando* / tiempo medido. **No** incluye bloqueado ni esperando.
  (En AnyLogic, un `Delay`/`Service` bloqueado suele contar como ocupado → posible diferencia de definición.)
- **Starvation / blocking**: fracción de tiempo vacía sin trabajo / terminada sin poder salir.
- **Utilización del operario**: (trabajando + caminando + transportando) / tiempo.
- **Tiempo caminando**: incluye ir a otra tarea y llevar/volver del transporte de bastidores.
- **Transportes**: viajes completados (contados al descargar).
- **WIP**: bastidores en sistema (desde que el montaje acepta la unidad hasta la salida), media temporal.
