# 10. Productos y setups

Bloque `production`:

- varios productos, por **mix probabilístico** o **secuencia explícita**;
- tiempos y rutas por producto;
- setups `CONSTANT_CHANGEOVER`, `TARGET_DEPENDENT` o `SEQUENCE_DEPENDENT` (matriz origen→destino), con familias
  (`setup_key`) y estado inicial explícito.

El estado de setup cambia **sólo al completar** el setup. SimForge representa la secuencia; **no** la optimiza.

```bash
simforge products show modelo.yaml
simforge products run modelo.yaml
```

La pestaña **Products** los muestra. Estado: SYNTHETICALLY_VALIDATED. Detalle: `docs/products_and_setups.md`.
