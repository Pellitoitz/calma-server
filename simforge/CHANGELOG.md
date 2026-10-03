# Changelog

Capacidades relevantes. No es una lista de commits.

**Estado de validación de cada línea:**

- todas las capacidades de dominio están **SYNTHETICALLY_VALIDATED**;
- ninguna está REAL_DATA_VALIDATED;
- validación económica real: **NOT_EXECUTED**.

## [Unreleased] — línea de desarrollo 1.1 (`develop/simforge-1.1`; no forma parte de 1.0.0-rc1)

### 1.1-A — Comparación física y escenarios

Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED. Sin validación real.

- **Comparación física run↔run** (`analytics/run_comparison.py`, `SimForgeApp.compare_runs`):
  - `delta = alternativa − baseline`;
  - PAIRED solo con evidencia de números aleatorios comunes (mismo motor, mismas semillas, mismo horizonte y
    warm-up), con deltas por réplica e IC95; UNPAIRED con diferencia de medias y sin IC; NOT_DETERMINABLE;
  - ausente ≠ cero;
  - comprobaciones HARD_INCOMPATIBILITY / WARNING / INFORMATIONAL;
  - sin ranking ni recomendaciones;
  - calculada bajo demanda, sin guardarla ni simular.
- **Escenarios:**
  - `clone_scenario` y `modify_scenario`, con linaje (`parent`) y la aprobación de 1.0 ligada al hash;
  - al aprobar, la versión aprobada pasa a ser la cabeza del escenario.
- **CLI:** `project compare-runs`, `project scenario-clone`, `project scenario-set`, `project scenarios` y
  `project experiment` (deltas frente a un escenario de referencia).
- **UI:**
  - sección *Scenarios & run comparison* en la pestaña **Project** (se mantienen las 12 pestañas de RC1): baseline → clonar → modificar → verificar → aprobar → ejecutar → comparar;
  - en Experiments, tabla de deltas frente a la referencia.
- **Sin cambios en:** motor (0.9.0), economics (0.9.0), esquema SQLite (sin migraciones), ficheros FREEZE y versión de
  producto (sigue siendo 1.0.0rc1).

### 1.1-B — Construcción del modelo sin YAML

Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED.

- **Servicio** `services/model_builder.py`:
  - constructor estructural (nodos, conexiones, recursos), editor de distribuciones (las 9 familias del dominio) y
    editor de transporte (campos existentes);
  - escribe sólo lo declarado: sin defaults silenciosos; unidad no declarada ≠ `s` declarada; los números se guardan
    tal como se escriben;
  - rechaza campos y componentes desconocidos, valores inválidos y referencias colgantes;
  - respeta el orden de construcción;
  - conserva los bloques de extensión;
  - la aprobación sigue ligada al hash.
- **UI:** sección *Model builder* en la pestaña **Model**, sin pestaña nueva.
- **Equivalencia:** el ejemplo 01 (59) y el golden, construidos desde cero, tienen el mismo `content_hash` que su YAML.
- **Corregido** (bug preexistente de 1.0): SAVE MODEL en el editor de parámetros, sin cambios, ya no materializa
  defaults ni cambia el hash.
- **Sin cambios en:** motor, economics, esquema, ficheros FREEZE y `content_hash`.

### 1.1-C — Results workbench y diagnóstico factual

Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED.

- **Workbench de resultados guardados** (`analytics/workbench.py`), en la pestaña **Run & results**:
  - resumen de KPIs con IC; réplicas;
  - tablas de nodos, OEE, buffers y espera, transporte, recursos, setup, mantenimiento, calendario y productos;
  - NOT_AVAILABLE / UNDEFINED ≠ 0.
- **Observaciones factuales deterministas y Top-N** (ordenación explícita, desempate por id), sin recomendaciones ni
  causalidad.
- **KPIs sobre el grafo** del modelo del run, sólo texto.
- **Garantías:** no simula, no recalcula ni muta nada.
- **Sin cambios en:** motor, economics, KPIs, esquema, ficheros FREEZE y `content_hash`.

### 1.1-D — Informes de ingeniería (C12)

Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED.

- **Run engineering report y scenario comparison report** (`reporting/engineering.py`): modelos tipados construidos
  sólo con fuentes existentes:
  - workbench de 1.1-C;
  - `compare_physical_runs` de 1.1-A;
  - evaluaciones y comparación económica de 0.9;
  - manifiesto de 1.0.
- **Contenido:**
  - identidad completa;
  - estado de validación siempre visible;
  - configuración (productos, setups, mantenimiento, calendarios) separada de los resultados;
  - procedencia de datos y supuestos;
  - limitaciones;
  - NOT_AVAILABLE / NOT_EVALUATED / NO_BLOCK ≠ 0.
- **Formatos:** Markdown, HTML (mismo contenido) y JSON.
- **CLI:** `project engineering-report` y `project comparison-report`. **UI:** pestaña **Report**.
- **Sin cambios en:** el informe de 1.0, el motor, economics, los KPIs, el esquema, los ficheros FREEZE y
  `content_hash`. Sin PDF nativo.

## [1.0.0-rc1] — Release Candidate 1 (declarada; sin tag hasta su autorización explícita)

Primera Release Candidate de SimForge 1.0. Release notes: `docs/release/1.0.0-rc1_release_notes.md`.

### Declaración de RC1

- Versión de producto **1.0.0-rc1** (`simforge.__version__ = "1.0.0rc1"`). Es la única fuente de verdad y
  `pyproject.toml` la lee como versión dinámica.
- `ENGINE_VERSION` sigue en `0.9.0` y `ECONOMICS_ENGINE_VERSION` en `0.9.0`: versión de producto y versión del motor son
  independientes.
- La cabecera de la UI muestra la versión de producto; la instalación limpia comprueba los metadatos instalados.
- Política de estabilización, nueva RC y promoción: `docs/release/1.0_stabilization_policy.md`.
- Tests de versionado: `tests/test_release_versioning.py`.
- **Sin capacidades nuevas**: RC1 = alcance congelado + el trabajo de Release Readiness de abajo.

### Pendiente para 1.0.0 final

- Ventana de estabilización (7–14 días de uso real) con su registro.
- Cero S0/S1 y cero S2 incompatibles, y los 20 criterios de promoción de `1.0_stabilization_policy.md` § 4.
- `check_release.py` en PASS sobre el commit exacto candidato a la final.
- Tags de RC y de la final: sólo con autorización explícita.

## 1.0 release readiness (incluido en 1.0.0-rc1)

### Fixed

- **(S1) Caché de resultados físicos.** La clave incluye ahora las definiciones de los componentes de la librería. Antes,
  una versión nueva de un componente podía devolver KPIs de la anterior.
- **(S1) Linaje run → versión.** Runs y experimentos se ligan a la versión realmente ejecutada. El informe describe el
  modelo **del run**, y `run_model_of` rechaza los modelos no guardados y los hashes que no coinciden.
- **(S2) Migraciones SQLite.** Son atómicas, con copia previa `project.db.pre-migration-vN.bak` y `schema_version()`.
- **(S2) Informe.** Ya no dice que economics «NOT IMPLEMENTED». Lista las evaluaciones del run y añade el estado de
  validación y la reproducibilidad completa.
- **(S2) CLI.** Errores categorizados (`CATEGORÍA: mensaje`), sin traceback, con códigos de salida documentados y log
  local para los errores internos. Un comando desconocido es un error de uso (2).
- **(S2) Contrato de lint reproducible.** Las reglas de ruff se fijan explícitamente en `pyproject.toml`, así que el
  resultado ya no cambia con la versión de ruff instalada.
- **(S3) Runs fallidos o interrumpidos.** Quedan registrados en el historial y nunca como completados.

### Added (sin capacidades de dominio nuevas)

- CLI de proyecto: `save`, `checkout`, `baseline`, `scenario`, `runs`, `evaluate` (`--from-run`), `compare`, `report`,
  `manifest`, `export`, `import`.
- Manifiesto de reproducibilidad por run.
- Proyecto golden (`examples/1_0_golden_project`), con su test de punta a punta en procesos separados.
- Scripts de release: `check_release.py`, `clean_install_smoke.py`, `perf_baseline.py`.
- Documentación de usuario (`docs/user/`), documentos de release (`docs/release/`), `KNOWN_LIMITATIONS.md`.
- Unidades visibles en la CLI y en el informe.
- Contexto de proyecto y aviso del LLM remoto en la UI.
- Contrato de Python 3.11.

## Motor 0.9.0 — Economics & decision support

- Capa económica post-run: supuestos con moneda, base física y procedencia; MISSING ≠ 0; cobertura; auditoría por
  línea; fórmulas versionadas.
- Anualización explícita, CAPEX, comparación (deltas, ahorro, payback simple, retorno) sin recomendación.
- Cierre técnico: 6 bugs corregidos (modelo sólo con economics, desglose del total, aprobación al re-evaluar, CAPEX no
  declarado, energía sin potencia, robustez numérica).
- Protocolo de validación económica con datos reales: READY, NOT_EXECUTED.

## Motor 0.8.0 — Maintenance & reliability

- Relojes de avería ELAPSED / OPERATING, reparación correctiva con recursos, PM por calendario o uso, RESET / NO_RESET.
  Averías legacy intactas.

## Motor 0.7.0 — Product mix + setups

- Mix probabilístico o secuencia explícita, tiempos y rutas por producto, setups constantes / por destino / matriz,
  familias.

## Motor 0.6.0 — Calendars

- Turnos, descansos, excepciones; FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART. Protocolo de validación real de
  calendarios: READY.

## 0.5.0 y anteriores

- Agregación explícita de `work_units`.
- Distribuciones gamma y weibull, truncamiento explícito, muestras negativas = error.
- Resolución del mismo instante.
- Transporte físico.
- Importación de datos y ajuste.
- Asistente IA (EXPERIMENTAL) con benchmark congelado.
