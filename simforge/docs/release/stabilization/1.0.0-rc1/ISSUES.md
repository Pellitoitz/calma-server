# Registro de incidencias — estabilización 1.0.0-rc1

`found_against: v1.0.0-rc1` (1b283a7). Las correcciones van en commits posteriores (`fixed_in`). El tag nunca se mueve.

## Clasificación (TYPE)

| TYPE | Tratamiento |
|---|---|
| BUG | política de bugs: reproducir → aislar → test rojo (con evidencia) → corrección mínima → test verde → pytest + ruff + FREEZE + 01–05 → `check_release.py` |
| UX_FRICTION | decisión: `FIX_RC` / `DOC_FIX` / `DEFER_POST_1_0` / `ACCEPTED_LIMITATION`. No es un rediseño |
| DOCUMENTATION_GAP | se corrige durante la RC. Si el comportamiento contradice el contrato, se trata como posible BUG; no se arregla sólo cambiando los docs |
| EXPECTED_LIMITATION | sólo se corrige si contradice el alcance publicado de RC1 (`KNOWN_LIMITATIONS.md`) |
| USER_ERROR | no se corrige; si el error era evitable, revisar el mensaje o los docs |
| VALIDATION_GAP | va a los protocolos de validación; nunca se mezcla con la evidencia de estabilización |
| FEATURE_REQUEST | **no se implementa**: `POST_1_0_CANDIDATE` |
| UNKNOWN | clasificar antes de la siguiente sesión |

## Severidad

S0 / S1 / S2 / S3, según `1.0_release_criteria.md`. No se rebaja para evitar una RC2 ni se sube para justificar
mejoras.

## Corrección de S3 durante la RC

Sólo si el cambio es pequeño, de riesgo muy bajo, sin cambio semántico y con test si corresponde. Ante la duda:
DEFER.

## RC2_REQUIRED

Según la política documentada:

- **YES** si es S0/S1, o un S2 que afecte a resultados, ejecución, persistencia, reproducibilidad, instalación,
  interfaces o linaje.
- La RC2 **no se crea** sin autorización explícita.

## Registro

| ISSUE_ID | SESSION_ID | DATE | TYPE | SEVERITY | COMPONENT | DESCRIPTION | EXPECTED | OBSERVED | REPRODUCIBLE | REPRO_STEPS | DATA_RISK | RESULT_RISK | WORKAROUND | DECISION | FIX_COMMIT | TEST | RC2_REQUIRED | STATUS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

*(sin incidencias registradas: todavía no se ha ejecutado ninguna sesión)*

## POST_1_0_CANDIDATE (feature requests registradas, no implementadas)

| ID | SESSION_ID | Petición | Motivo de diferirla |
|---|---|---|---|
