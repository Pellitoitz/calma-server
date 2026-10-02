# 4. Verificación y aprobación

- **Verificación (automática).** El modelo está bien construido: grafo, parámetros, unidades, MISSING, semántica de
  calendarios, setups, mantenimiento y economics.
- **Validación (ingeniero).** El modelo representa el sistema real lo bastante bien. SimForge **no** la establece.

```bash
simforge validate modelo.yaml       # EXECUTABLE / INCOMPLETE / … con errores, avisos e info
```

## MISSING

Un valor obligatorio sin dato es **MISSING**:

- bloquea la verificación y la ejecución (`MODEL_VALIDATION_ERROR … MISSING`);
- **nunca** se sustituye por un valor por defecto ni por 0.

Para resolverlo, se da el valor y se guarda una versión nueva (`simforge project save`). Ejemplo:
`examples/1_0_golden_project/model_with_missing.yaml`.

## Supuestos

Los valores `assumed` (supuestos), los de librería y los de IA se muestran como tales: en `simforge economics show`,
en la sección 3 del informe y en la pestaña Model. Revísalos antes de aprobar.

## Aprobación física

`simforge project approve <slug> --by "rol"` aprueba la versión **actual**, ligada a su hash de contenido exacto.

- Cualquier cambio físico deja la aprobación obsoleta (`APPROVAL_STALE`).
- Es **obligatoria antes de ejecutar** en modelos generados por IA y en modelos con parámetros derivados de datos
  importados.
- El resto de versiones pueden ejecutarse sin aprobar, pero se marcan como no aprobadas en la UI, el informe y el
  manifiesto.

## Aprobación económica

Es independiente de la física: aprueba una evaluación concreta (UI → Economics). Cambiar un precio no toca la
aprobación física: crea otra evaluación, sin aprobar.
