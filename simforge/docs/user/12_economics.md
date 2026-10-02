# 12. Economics

Es una capa **posterior al run**: valora un run guardado con supuestos explícitos, sin volver a simular y sin tocar el
DES.

```bash
simforge economics show modelo.yaml                       # supuestos, economic_hash, avisos (ASSUMED, MISSING...)
simforge project evaluate <slug> <run_id> --from-run      # usa el bloque economics de la versión del run
simforge project evaluate <slug> <run_id>                 # usa el de la versión ACTUAL (como la UI); siempre se imprime cuál
simforge project compare <slug> <eval_base> <eval_alt>    # deltas, ahorro, payback simple, retorno (hechos)
```

## Reglas

- **Moneda.** Una por evaluación; sin conversión de divisas.
- **MISSING ≠ 0.** Un CAPEX no declarado no es 0: declara una partida explícita de 0 si no hay inversión.
- **`evaluated_total_cost`.** Suma de las líneas INCLUDED de las categorías evaluadas. **No** es un coste completo de
  producción.
- **`COMPLETE_FOR_REQUESTED_SCOPE`.** Sólo significa que las categorías pedidas están completas.
- **Anualización.** Sólo con `runs_per_year` explícito; el CAPEX nunca se anualiza.
- **Payback.** `NOT_REACHED` si no hay ahorro y `UNDEFINED_METRIC` si faltan datos; nunca es negativo.
- **Recomendación.** SimForge no ordena alternativas ni recomienda: el ingeniero decide.

## Estado

- SYNTHETICALLY_VALIDATED.
- Validación con datos reales: protocolo listo (`docs/validation/economic_real_data_validation.md`), **NOT_EXECUTED**.

Detalle: `docs/economics_and_decision_support.md`.
