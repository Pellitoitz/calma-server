# Protocolo de uso humano real — línea SimForge 1.1

> **Estado: PREPARADO. Sesiones ejecutadas: 0.** Este directorio contiene el protocolo y las plantillas. No contiene
> resultados: ninguna sesión se ha realizado todavía y nada de lo que hay aquí es evidencia de uso.

## 1. Pregunta

¿Puede un ingeniero usar SimForge para resolver un estudio de simulación de principio a fin de forma comprensible,
trazable y con menos fricción?

No es un benchmark del motor. Es una prueba del **producto y del workflow**:
«La IA construye, el motor calcula, el sistema comprueba, el ingeniero valida.»

## 2. Alcance y baseline

| | |
|---|---|
| Línea | SimForge 1.1 (rama `develop/simforge-1.1`) |
| Commit de referencia | `71e30ec` (1.1-A…E + revisión final). Si se usa otro commit, se anota en la sesión |
| Versión de producto | `1.0.0rc1` (la línea 1.1 **no** cambia la versión del paquete) |
| Motor DES / Economics | 0.9.0 / 0.9.0 |
| No incluido | estabilización de RC1 (S-001…, rama de release, baseline `v1.0.0-rc1`): es un registro **separado** y no se mezcla con éste |

## 3. Workflow objetivo

```
START → PROJECT → DATA → MODEL BUILD → VERIFY → APPROVE → RUN → RESULTS WORKBENCH
      → SCENARIO → COMPARE → ECONOMICS → ENGINEERING REPORT
```

Cuando un paso no se puede hacer desde la UI (ver la tabla «¿Qué se puede hacer sin YAML?» de
`docs/roadmap/1.1_final_review.md` §7), **se registra la dependencia** (`YAML required`) en la matriz de cobertura.
No se oculta.

## 4. Regla black-box

- **Permitido:** la UI, la CLI, `docs/user/*` y los documentos a los que éstos remiten.
- **No permitido:** código fuente, tests, implementación interna, consultar al desarrollador para saltarse un problema.
- Si hay que mirar el código para continuar: `DOCUMENTATION_OR_UX_ESCAPE = YES` y se cuenta en `NUMBER_OF_ESCAPES`.
  Se puede desbloquear, pero queda registrado.
- **No se corrige la aplicación durante la sesión.** Primero se registra el hallazgo; las correcciones requieren una
  revisión del ingeniero y una autorización posterior.

## 5. Caso de prueba

El ingeniero elige **uno** y lo registra en `CASE_TYPE`:

| CASE_TYPE | Significado | Estado de validación que se puede afirmar |
|---|---|---|
| `SYNTHETIC_KNOWN` | caso sintético conocido (p. ej. ejemplos del repositorio) | ninguno con datos reales |
| `INDUSTRIAL_ANONYMIZED` | caso industrial anonimizado o reconstruido | ninguno con datos reales automáticamente |
| `REAL_AUTHORIZED` | caso real con autorización | ninguno con datos reales automáticamente |

Una sesión de uso **no** es una validación con datos reales: los estados de validación industrial y económica siguen
siendo `NOT_EXECUTED` hasta ejecutar los protocolos de `docs/validation/`. Datos confidenciales: no van al
repositorio, a capturas ni a commits; se anonimiza (Company_A, Line_2, Operator_1).

## 6. Métricas (sólo si el humano las mide)

Se registran **sólo** si el ingeniero las mide realmente durante la sesión. Lo que no se mide queda vacío o
`NOT_MEASURED`; no se deriva ni se estima después.

| Campo | Definición para este protocolo |
|---|---|
| `SESSION_START` / `SESSION_END` | hora de reloj de inicio y fin |
| `ACTIVE_ENGINEERING_TIME` | minutos de trabajo activo, excluyendo esperas y pausas. Sólo si se cronometra de forma activa; si no, `NOT_MEASURED` |
| `TIME_TO_FIRST_SUCCESSFUL_RUN` | minutos desde START hasta el primer run guardado que termina sin error |
| `TIME_TO_FIRST_VERIFIED_APPROVED_MODEL` | minutos desde START hasta el primer modelo con **0 errores del verificador** y **aprobado** por el ingeniero (hash vigente). Es la definición objetiva de este protocolo; no es «modelo válido» en sentido industrial |
| `TIME_TO_FIRST_COMPARISON` | minutos desde START hasta la primera comparación run↔run mostrada (`compare-runs` o pestaña Project) |
| `TIME_TO_DECISION_READY_OUTPUT` | minutos desde START hasta exportar el primer informe de ingeniería (run o comparación) que el ingeniero considera utilizable para decidir |
| `CORRECTION_LOOPS` | back_to_model, input_corrections, missing_resolved, re_approvals, reruns |
| `DOCUMENTATION_ESCAPES` | número de veces que se necesitó código |
| `ERRORS` / `BLOCKED_WORKFLOWS` | errores mostrados y pasos bloqueados |
| `MANUAL_YAML_INTERVENTIONS` | número de ediciones manuales de YAML y para qué |

### Separación respecto al panel de productividad

| A. Panel de producto (`services/productivity.py`) | B. Registro humano de este protocolo |
|---|---|
| métricas MEASURED / USER_PROVIDED del proyecto; las 5 del roadmap figuran como `NOT_AVAILABLE` / `NOT_INSTRUMENTED` | cronometraje y observaciones manuales del ingeniero |

- B **no** se convierte en una métrica persistida del producto.
- B **no** se declara equivalente a ninguna métrica de A. En particular, `TIME_TO_FIRST_VERIFIED_APPROVED_MODEL` no es
  `TIME_TO_FIRST_VALID_RUN` ni `time_to_engineer_approval_s`.
- Si el ingeniero quiere, puede anotar en `NOTES` los valores que muestra el panel A al final de la sesión, copiados
  tal cual y etiquetados como «panel de producto».

## 7. Hallazgos

Se reutiliza la taxonomía de la estabilización de RC1 (`ISSUES.md` de `docs/release/stabilization/1.0.0-rc1/` en la
rama de release). No se crea una nueva.

| TYPE | Tratamiento en 1.1 |
|---|---|
| BUG | reproducir → test rojo → corrección mínima → test verde → suite → `check_release.py`; **sólo tras autorización** |
| UX_FRICTION | decisión del ingeniero: `FIX_1_1` / `DOC_FIX` / `DEFER_POST_1_1` / `ACCEPTED_LIMITATION` |
| DOCUMENTATION_GAP | corrección documental; si el comportamiento contradice el contrato, posible BUG |
| EXPECTED_LIMITATION | referencia a la limitación documentada (`docs/user/15_limitations.md`, revisión final §14) |
| USER_ERROR | no se corrige; revisar mensajes o docs si era evitable |
| VALIDATION_GAP | va a los protocolos de validación; no se mezcla con evidencia de uso |
| FEATURE_REQUEST | **no se implementa**: `POST_1_1_CANDIDATE` |
| UNKNOWN | clasificar antes de la siguiente sesión |

**Severidad:** S0 / S1 / S2 / S3 según `docs/release/1.0_release_criteria.md`. Además se marca `BLOCKS_WORKFLOW`
(YES/NO) para distinguir un bloqueo de una fricción.

Un hallazgo que exija cambiar código de producto se registra como
`POST_1_1_FINDING_REQUIRES_ENGINEERING_DECISION` y no se implementa sin autorización.

## 8. Resultado de la sesión

| RESULT | Criterio objetivo |
|---|---|
| `PASS` | todos los pasos del workflow objetivo `COMPLETED` (o `NOT_APPLICABLE` justificado), 0 hallazgos con `BLOCKS_WORKFLOW = YES`, `DOCUMENTATION_OR_UX_ESCAPE = NO` |
| `PASS_WITH_FRICTION` | workflow objetivo completado; hay fricciones, escapes de documentación o intervenciones YAML, pero ninguna bloquea |
| `FAIL` | al menos un paso del workflow objetivo `BLOCKED` por un defecto, un bug o falta de documentación, dentro del alcance soportado |

Un paso que no se puede hacer porque está **fuera** del alcance soportado y documentado (p. ej. productos/setups o
mantenimiento desde la UI) cuenta como `EXPECTED_LIMITATION`, no como FAIL, si la documentación lo dice.

## 9. Ficheros

| Fichero | Contenido |
|---|---|
| `sessions/H-001.md` | sesión H-001, `READY_FOR_HUMAN_EXECUTION` |
| `FINDINGS.md` | registro de hallazgos (vacío) |
| `COVERAGE_MATRIX.md` | cobertura por paso del workflow (vacía) y dependencias UI/YAML conocidas |

## 10. Plan sugerido de sesiones (no ejecutadas)

Plan orientativo. El número y el orden los decide el ingeniero tras revisar H-001.

| ID | Foco | Estado |
|---|---|---|
| H-001 | primer workflow completo de un ingeniero | READY_FOR_HUMAN_EXECUTION |
| H-002 | construcción de modelo (builder, distribuciones, transporte) | NOT_PREPARED |
| H-003 | datos y distribuciones (importar, ajustar, decidir) | NOT_PREPARED |
| H-004 | escenarios y comparación | NOT_PREPARED |
| H-005 | economía e informes | NOT_PREPARED |
| H-006 | persistencia: cerrar, reabrir, exportar/importar | NOT_PREPARED |
| H-007 | recuperación de errores (MISSING, aprobación invalidada, entradas erróneas) | NOT_PREPARED |
| H-008 | segundo caso con forma industrial | NOT_PREPARED |

## 11. Después de cada sesión

1. Cambiar el STATUS de la sesión a `EXECUTED` (sólo si ocurrió).
2. Registrar cada hallazgo en `FINDINGS.md` y clasificarlo antes de la siguiente sesión.
3. Rellenar la columna de la sesión en `COVERAGE_MATRIX.md`.
4. El ingeniero revisa los hallazgos y decide qué se corrige. No se corrige nada sin esa decisión.
