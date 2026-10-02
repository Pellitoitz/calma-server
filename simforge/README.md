# SimForge

**Banco de trabajo local de simulación industrial (eventos discretos) asistido por IA.**

> La IA construye · el motor calcula · el sistema comprueba · el ingeniero valida.

SimForge convierte una descripción de un proceso ("un operario monta 60 s, buffer de 5, máquina 45 s, el mismo operario inspecciona 20 s…") en un **modelo estructurado propio (ISMS)**, construido con **componentes validados de una biblioteca**. Lo verifica, lo simula con un motor DES propio (SimPy por debajo), ejecuta experimentos con réplicas y genera KPIs, diagnósticos e informes. **Ningún número lo produce la IA.**

Objetivo del producto: reducir el tiempo que tarda un ingeniero de procesos en pasar de un problema real a una decisión validada por simulación.

---

## Instalación (Python ≥ 3.11)

```bash
cd simforge
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[all]"                                 # núcleo + UI + LLM + tests
cp .env.example .env                                    # opcional: ANTHROPIC_API_KEY
pytest                                                  # 61 tests, sin red
```

Instalación mínima (sólo motor + CLI, sin UI ni LLM): `pip install -e .`

## Arrancar

```bash
simforge ui                      # interfaz local en http://localhost:8501
```

Flujo típico en la UI:
1. Barra lateral → **New project**.
2. Pestaña **Assistant** → describe el proceso. Se crea el modelo v1 con **supuestos** y **preguntas**.
3. Pestaña **Model** → grafo del proceso, parámetros editables, **VALIDATE**, **SAVE MODEL**, **APPROVE MODEL**.
4. **Run & results** → **RUN SIMULATION**: KPIs, estados por estación, recursos, WIP, diagnósticos con evidencia, log de decisiones del operario (modo debug).
5. En el chat: *"Cambia el buffer a 8"*, *"Prueba buffers entre 1 y 10"*, *"¿Dónde está el cuello de botella?"*, *"Vuelve a la versión anterior"*.
6. **Experiments** → barrido de parámetros, gráfico con IC95 %, CSV.
7. **Report** → informe Markdown/HTML/CSV. **Project** → versiones, diff, baseline, exportar `.simproject`.

Sin `ANTHROPIC_API_KEY` todo funciona igual con el **intérprete offline** (reglas deterministas, procesos lineales sencillos). Con clave, se usa Claude para lenguaje libre; el resultado pasa por el mismo compilador determinista y las mismas comprobaciones.

## CLI (sin interfaz)

```bash
simforge validate examples/02_shared_operator.yaml
simforge run examples/02_shared_operator.yaml --trace-dir traces/     # + event log y decisiones del operario
simforge run examples/03_machine_breakdowns.yaml --reps 30
simforge experiment examples/05_selective_soldering.yaml --csv racks.csv
simforge experiment examples/02_shared_operator.yaml --factor resources.operator_1.quantity=1,2,3
simforge report examples/05_selective_soldering.yaml -o report.html --experiment
simforge parse --offline "Fuente infinita. Un operario realiza montaje durante 60 segundos. ..." -o model.yaml
simforge library list soldadura
simforge library show selective_soldering
simforge ai new "Línea MVP" "Fuente infinita. Un operario monta una pieza durante 60 segundos. ..."   # orquestación IA
simforge ai approve <slug> --by "Nombre" && simforge ai run <slug>
simforge ai compare examples/02_shared_operator.yaml <slug>@2                                   # modelo A vs B
```

## Orquestación IA (lenguaje natural → modelo con la biblioteca)

Describir el proceso → interpretación → **matching con componentes y reglas existentes** (REUSE RATIO) → parámetros
con procedencia (USER_PROVIDED / ASSUMED / DEFAULT / CALCULATED / MISSING) → preguntas agrupadas → MODEL BUILD PLAN →
verificación → **aprobación del ingeniero** → simulación. Cambios por chat = cambios estructurados del ISMS; correcciones
registradas; `compare_model_specs` (textual vs estructural vs resultados); métricas de tiempo ahorrado; auditoría IA.
Detalle: [`docs/ai_orchestration.md`](docs/ai_orchestration.md).

## Calendarios y turnos

Turnos (incluidos nocturnos), descansos, fines de semana, festivos y horas extra; calendarios distintos por operario,
máquina o fuente; qué pasa con una operación al acabar el turno (FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART, decisión
del ingeniero). `simforge calendar ...` o pestaña **Calendars**. Detalle: [`docs/calendars_and_shifts.md`](docs/calendars_and_shifts.md).

## Datos medidos (CSV/XLSX → distribución → parámetro)

Importar un estudio de tiempos (CSV o XLSX, sin ejecutar nada del archivo) → validación fila a fila (nada se borra ni
se rellena) → estadística, outliers *candidatos*, dependencia serial → ajuste de 7 familias con ranking AIC y
plausibilidad industrial (P1…P99.9) → **decisión del ingeniero** (determinista / empírica / ajustada / no aplicar /
rechazar) → nueva versión del modelo con procedencia `data` (dataset, hash, ajuste) y **aprobación invalidada**.
Sin IA, totalmente offline. Ejemplo completo: `bash examples/data/run_e2e.sh`.
Detalle: [`docs/data_import.md`](docs/data_import.md) y [`docs/distribution_fitting.md`](docs/distribution_fitting.md).
Estado: SYNTHETICALLY_VALIDATED; validación con datos reales: [`docs/real_data_validation_protocol.md`](docs/real_data_validation_protocol.md).

## Ejemplo (MVP)

```
Fuente infinita. Un operario realiza montaje durante 60 segundos. Existe un buffer de 5 unidades.
Una máquina tarda 45 segundos. El mismo operario inspecciona durante 20 segundos. Simular 8 horas.
```

Resultado: `Source → Manual assembly → Buffer(5) → Machine → Inspection → Sink`, 100 % componentes de biblioteca, supuesto registrado *"operario compartido: FIFO"* + pregunta *"¿qué prioridad…?"*. El modelo generado requiere aprobación del ingeniero antes de ejecutarse. Simulación: **359 unidades** (restricción = operario, 80 s de trabajo/unidad → máx. teórico 45 u/h, verificado a mano en `tests/test_engine_golden.py`).

## Arquitectura en una imagen

```
 Lenguaje natural ──► Intérprete (LLM o reglas offline) ──► ProcessDraft (schema estricto)
                                                                │
                         Biblioteca de componentes ◄──────── Compilador determinista
                         (core / manufacturing / electronics)   │  · busca/reutiliza componentes
                                                                │  · grounding: nº no presentes → ASSUMED
                                                                ▼  · faltantes → MISSING
                                                      ISMS (fuente de verdad, versionado)
                                                                │
                                              Verificador (errores legibles, readiness)
                                                                │
                                   Motor DES (IndustrialServer/Buffer/Operator… sobre SimPy)
                                                                │
                                   RunRecord (datos brutos) ──► KPIs ──► Diagnósticos con evidencia
                                                                │
                                        Experimentos · Informes · UI · CLI · (futuro: AnyLogic)
```

Más detalle: [`docs/architecture.md`](docs/architecture.md) (incluye diseño completo, riesgos, roadmap y criterios de aceptación), [`docs/domain_model.md`](docs/domain_model.md), [`docs/simulation_engine.md`](docs/simulation_engine.md), [`docs/ai_layer.md`](docs/ai_layer.md), [`docs/component_library.md`](docs/component_library.md), [`docs/adr/`](docs/adr).

## Estructura

```
simforge/
  src/simforge/
    domain/        ISMS (Pydantic), unidades, distribuciones, trazabilidad, rutas de parámetros
    library/       registro de componentes + YAML (core, manufacturing, electronics)
    validation/    verificador y "readiness"
    engine/        interfaz de motor + implementación DES (SimPy oculto aquí)
    analytics/     KPIs, estadística de réplicas, capacidad teórica, cuellos de botella
    experiments/   runner de simulación y experimentos (grid, CRN, caché)
    ai/            proveedores LLM, intérprete offline, compilador draft→ISMS, privacidad
    persistence/   proyectos (YAML versionado + SQLite con migraciones)
    reporting/     informes Markdown/HTML/CSV
    services/      API interna (la usan CLI y UI)
    ui/            Streamlit
    cli.py
  examples/        01..05 (línea simple, operario compartido, averías, retrabajo, soldadura selectiva)
  tests/           unit, golden models, integración, UI headless
  docs/
```

Datos de cliente (`workspace/`, configurable con `SIMFORGE_WORKSPACE`) y biblioteca propia (`~/.simforge/library`, `SIMFORGE_LIBRARY`) están **separados físicamente**. `workspace/` está en `.gitignore`.

## Benchmark contra AnyLogic (fase actual)

`benchmark/` contiene la validación del motor contra el modelo AnyLogic de soldadura selectiva. Ver `benchmark/README.md`,
`docs/benchmark_operator_logic.md` y `docs/benchmark_kpi_definitions.md`. Estado actual: **BLOCKED** hasta recibir los datos de AnyLogic.

## Estado honesto (v0.1)

Funciona de verdad: todo lo descrito arriba. **NO implementado todavía** (y el esquema lo rechaza en vez de ignorarlo): mix de productos y setups, routing condicional/"first available", economía (coste/unidad, CAPEX, ROI), energía, optimización (sólo grid), PDF/PPT nativos, integración AnyLogic (ver `docs/anylogic.md`, todo marcado TO VERIFY).
