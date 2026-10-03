# Plan de sesiones — estabilización 1.0.0-rc1

**Objetivo:** usar SimForge como lo usaría un ingeniero, no como lo usa quien conoce su código.

- **Mínimo antes de revisar la promoción:** ≥ 8 sesiones reales registradas. Preferible: 10–15.
- **Ventana:** 7–14 días de uso real.

Ningún workflow de esta tabla está ejecutado hasta que exista su `sessions/S-NNN.md`.

## Workflows

| ID | Workflow | Qué se comprueba | Interfaz | Modo recomendado |
|---|---|---|---|---|
| W01 | **Fresh start**: venv limpio → instalar → arrancar → `docs/user/01_getting_started.md` → crear/abrir proyecto → primer modelo → resultados → cerrar | instalación, comandos, rutas, docs, errores, primera experiencia | CLI + UI | **NEW_USER_SIMULATED** (sólo la guía, sin atajos) |
| W02 | **Estudio DES básico desde cero**: Source → Process → Buffer → Process → Sink, con tiempos, recurso, horizonte y réplicas | throughput, WIP, lead time, utilización, conservación. Se resuelve primero como un estudio normal y después se contrasta (no se usan los internos del golden) | UI o CLI | **BLACK_BOX** |
| W03 | **Modelo con datos**: dataset no confidencial → import → validar → análisis → candidatas → decisión → parámetro → modelo → run | unidades ambiguas, columnas, missing, outliers, procedencia, mensajes, persistencia | CLI (`data …`) + UI Data | BLACK_BOX |
| W04 | **Calendario**: turno + descanso + operación que cruza el límite; al menos una política (FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART) | tiempo planificado, descanso, fuera de turno, proceso, utilización (sin afirmar validación industrial) | UI Calendars / CLI calendar | DEVELOPER o BLACK_BOX |
| W05 | **Mix de productos y setup**: A y B, changeover A→B, mix o secuencia | estado, número y tiempo de setups; despacho, setup y proceso comprensibles en UI e informe | UI Products | BLACK_BOX |
| W06 | **Mantenimiento**: avería → reparación → producción reanudada (PM si resulta natural) | averías, reparación, downtime, disponibilidad, traza | UI Maintenance | DEVELOPER |
| W07 | **Economics** (valores **SYNTHETIC/DEMO** mientras no haya datos reales): run existente → mano de obra y/u otra categoría → evaluar → cambiar **sólo** el precio → reevaluar **sin DES** | mismo run físico, mismo hash físico, otra evaluación; cobertura, MISSING, evaluated total cost, coste unitario | CLI `project evaluate` + UI Economics | BLACK_BOX |
| W08 | **Comparación de escenarios**: baseline y alternativa con **una** decisión física (capacidad, recursos, tiempo de proceso o calendario) | KPIs físicos, económicos si aplica, avisos, cobertura, incertidumbre. SimForge **no** debe decir cuál elegir | UI + CLI `project compare` | BLACK_BOX |
| W09 | **Guardar → cerrar → reabrir**: estudio con varias extensiones → cerrar SimForge del todo → proceso nuevo → cargar → re-ejecutar | modelo, datasets, aprobación, runs, resultados, experimentos, economics, auditoría; reproducibilidad | UI y CLI (`project export/import`) | DEVELOPER |
| W10 | **Recuperación ante errores** (controlados, no fuzzing): input MISSING, unidad o valor inválido, configuración no soportada, validación fallida, decisión de ingeniero requerida | mensaje útil, sin corrupción, sin falso COMPLETED, proyecto recuperable, siguiente acción clara | CLI + UI | BLACK_BOX |
| W11 | **Estudio pequeño sólo por CLI**: crear/cargar → verificar → run → resultados (+ evaluate/compare) | códigos de salida y mensajes | CLI | BLACK_BOX |
| W12 | **Flujo equivalente en la UI** (Streamlit) | navegación, contexto, aprobación, MISSING, estado del run, selección de resultados, comparación, economics, errores; fricciones aunque no sean bugs | UI | BLACK_BOX |
| W13 | **Informe y exportación**, abiertos fuera de SimForge | ¿se identifican proyecto, modelo, run, versión, horizonte, réplicas, KPIs, supuestos, MISSING, estado de validación y cobertura económica? | CLI `project report/manifest` | NEW_USER_SIMULATED |
| W14 | **Run representativo largo** (mayor que smoke/golden, sin ser enorme) | estabilidad, tiempo, memoria, UI durante el run, persistencia, finalización, informe; comparar con `performance_baseline.json`. No se optimiza salvo regresión grave | UI + CLI | DEVELOPER |
| W15 | **Caso industrial real o reconstruido** (si es posible), anonimizado | uso real de punta a punta. **No** convierte nada en REAL_DATA_VALIDATED: es una sesión de estabilización | UI + CLI | DEVELOPER |

## Cobertura colectiva exigida antes de considerar estable RC1

| Área | Workflows que la cubren | Cubierta |
|---|---|---|
| CLI | W01, W03, W07, W09, W10, W11, W13 | ☐ |
| UI | W01, W02, W05, W06, W08, W12 | ☐ |
| instalación limpia | W01 | ☐ |
| persistencia | W09 | ☐ |
| datos | W03 | ☐ |
| calendarios | W04 | ☐ |
| setups | W05 | ☐ |
| mantenimiento | W06 | ☐ |
| economics | W07 | ☐ |
| comparación | W08 | ☐ |
| informe / exportación | W13 | ☐ |
| manejo de errores | W10 | ☐ |

Se marca ☑ sólo con la sesión registrada.

## Modos de sesión

- **BLACK_BOX.** Sólo UI, CLI y docs. Si hay que mirar el código para avanzar: `DOCUMENTATION_OR_UX_ESCAPE = YES`.
- **NEW_USER_SIMULATED.** Seguir estrictamente getting started y el tutorial, sin atajos internos. Lo ideal es que lo
  haga otra persona (`EXTERNAL_USER`). No se afirma «probado por un usuario externo» si no ocurrió.
- **DEVELOPER.** Permitido para W06, W09 y W14, donde se observan detalles internos (traza, memoria).

## Orden sugerido (10–15 sesiones)

| Sesiones | Workflows |
|---|---|
| S-001 | W01 (nuevo usuario) |
| S-002 | W02 (BLACK_BOX, UI) |
| S-003 | W11 (CLI) |
| S-004 | W03 |
| S-005 | W07 + W08 |
| S-006 | W10 |
| S-007 | W09 |
| **revisión intermedia** | `MIDPOINT_REVIEW.md` |
| S-008 | W04 |
| S-009 | W05 |
| S-010 | W06 |
| S-011 | W12 |
| S-012 | W13 |
| S-013 | W14 |
| S-014 (opcional) | W15 |

## Observaciones de productividad (línea base, sin objetivos comerciales)

Por sesión:

- `ACTIVE_USER_TIME`;
- `TIME_TO_FIRST_VALID_RUN`;
- `TIME_TO_DECISION_READY_COMPARISON`;
- `CORRECTION_LOOPS` (vueltas al modelo, correcciones de input, MISSING resueltos, re-aprobaciones, reruns).

No se interpretan automáticamente como malos: sirven para localizar fricción real.

## Revisión intermedia

Tras 5–7 sesiones o a mitad de la ventana: `MIDPOINT_REVIEW.md` con:

- sesiones completadas y su resultado (PASS / PASS_WITH_FRICTION / FAIL);
- incidencias por severidad;
- estado del disparador de RC2;
- fricción recurrente;
- estado de validación;
- workflows pendientes.

**No** se toma la decisión de 1.0.0.

## Release check durante la ventana

No hace falta tras cada sesión en PASS. Es **obligatorio**:

- tras cada corrección de bug;
- antes de una RC2;
- antes de la revisión de promoción;
- si cambian el empaquetado, la persistencia o el versionado.
