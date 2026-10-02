# 11. Mantenimiento y fiabilidad

Bloque `maintenance` por nodo:

- averías con reloj `ELAPSED_TIME` u `OPERATING_TIME` (exposición declarada);
- reparación correctiva con recursos (técnico) y efecto `RESET`;
- mantenimiento preventivo por calendario o por uso (`AFTER_CURRENT_ACTIVITY`), con `RESET` o `NO_RESET`.

Las averías *legacy* (ejemplo 03) siguen funcionando igual.

```bash
simforge maintenance show modelo.yaml
simforge maintenance run modelo.yaml
```

- KPIs: averías, downtime correctivo (espera + reparación activa), PM, MTBF observado, cada uno con su denominador
  explícito.
- Estado: SYNTHETICALLY_VALIDATED; no hay mantenimiento predictivo.
- Detalle: `docs/maintenance_and_reliability.md`.
