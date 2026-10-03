# Plantilla de sesión — estabilización 1.0.0-rc1

Copiar a `sessions/S-NNN.md` (S-001, S-002…), una sesión por fichero. Una sesión es **interacción real con un
workflow** del producto; ejecutar pytest no es una sesión. No se registran sesiones que no hayan ocurrido.

Datos confidenciales: no van al repositorio, a los logs, a los ejemplos, a las capturas ni a los commits. Se
anonimiza (Company_A, Line_2, Operator_1).

```yaml
SESSION_ID:                 # S-001
DATE:                       # YYYY-MM-DD
TESTER:                     # rol o iniciales (sin datos personales). Decir si es el autor o una persona externa
TESTER_MODE:                # BLACK_BOX | NEW_USER_SIMULATED | EXTERNAL_USER | DEVELOPER   (EXTERNAL_USER sólo si ocurrió)
PRODUCT_VERSION:            # salida de: python -c "import simforge; print(simforge.__version__)"
COMMIT:                     # git rev-parse --short HEAD (o "installed package")
TAG_BASELINE: v1.0.0-rc1    # 1b283a7
WORKFLOW:                   # W01..W14 (ver SESSION_PLAN.md), puede haber varios
INTERFACE:                  # CLI | UI | BOTH
PROJECT:                    # slug (anonimizado)
START_TIME:
END_TIME:
ACTIVE_USER_TIME:           # minutos de trabajo de ingeniería activo (sin esperas)
SIMULATION_RUNTIME:         # segundos totales de simulación
TIME_TO_FIRST_VALID_RUN:    # minutos (si aplica)
TIME_TO_DECISION_READY_COMPARISON:  # minutos (si aplica)
OBJECTIVE:
INPUTS:                     # modelos, datasets (no confidenciales), supuestos; decir SYNTHETIC/DEMO si lo son
STEPS_PERFORMED: |
  1.
EXPECTED_BEHAVIOR: |
OBSERVED_BEHAVIOR: |
RESULT:                     # PASS | PASS_WITH_FRICTION | FAIL
CORRECTION_LOOPS:           # cuántas veces hubo que…
  back_to_model: 0
  input_corrections: 0
  missing_resolved: 0
  re_approvals: 0
  reruns: 0
INCIDENTS: []               # ISSUE_IDs de ISSUES.md
FRICTIONS: []               # descripciones breves; las relevantes también en ISSUES.md
WORKAROUNDS_USED: []
DOCUMENTATION_OR_UX_ESCAPE: NO   # YES si hubo que mirar el código para seguir (señal importante)
DATA_LOSS: NO
RESULT_CORRECTNESS_CONCERN: NO
REPRODUCIBILITY_CONCERN: NO
PERSISTENCE_CONCERN: NO
DOCUMENTATION_CONCERN: NO
SEVERITY_IF_ISSUE:          # S0 | S1 | S2 | S3 | —
RC2_REQUIRED:               # YES | NO | UNDETERMINED (según 1.0_stabilization_policy.md §3)
NOTES: |
```

Tras una sesión con incidencias relevantes, se clasifican **antes** de la siguiente sesión y se actualizan
`STABILIZATION_LOG.md` e `ISSUES.md`.
