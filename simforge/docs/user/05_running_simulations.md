# 5. Ejecutar simulaciones

```bash
simforge run modelo.yaml [--reps N] [--seed S] [--json] [--trace-dir dir]   # sin proyecto
simforge project run <slug> [--reps N]                                         # versión actual de un proyecto
simforge project runs <slug>                                                   # runs guardados
simforge project manifest <slug> <run_id> [-o manifest.json]                   # identidad completa del run
```

## Reproducibilidad

Un run queda definido por la **versión del modelo**, las **semillas** (`base_seed`, `base_seed+1`, …), la **versión del
motor** y las **definiciones de componentes**. Con los mismos valores el resultado es idéntico, réplica a réplica. El
manifiesto incluye:

- los hashes físico, de calendarios, de producción y de mantenimiento;
- la aprobación;
- los datasets;
- las evaluaciones económicas, con los ids de fórmula.

## Caché

Una réplica ya calculada se reutiliza sólo si coinciden la física (hash, sin economics), el motor, la semilla y las
definiciones de componentes. Cambiar un precio no obliga a re-simular.

## Estados de un run

| Estado | Qué ocurre |
|---|---|
| RUNNING | la UI muestra «RUNNING». No hay porcentaje: el motor no conoce de antemano el número de eventos |
| COMPLETED | sólo los runs completados se guardan |
| FAILED | nunca se guarda como resultado. El historial registra `run_failed` con el error y la CLI muestra `CATEGORÍA: mensaje` |
| INTERRUPTED | Ctrl+C: el historial registra `run_interrupted`, no se guarda nada y la CLI sale con el código 130 |
