# Arquitectura de SimForge (v0.1)

Este documento recoge la primera entrega pedida (A–Q) y la revisión crítica de la especificación.
Todo lo que aparece como "implementado" está en el código y cubierto por tests.

## A. Cómo he entendido el producto

Una **herramienta personal de ingeniería de simulación** (no un chatbot) cuyo KPI es *tiempo ahorrado
desde el problema real hasta una decisión validada*. El valor está en cuatro activos que se acumulan:

1. **ISMS**: un formato de modelo propio, independiente del motor.
2. **Biblioteca** de componentes validados, reutilizables y versionados (tu IP).
3. **Motor** determinista y verificable (golden models).
4. **Flujo con humano en el bucle**: supuestos visibles, faltantes explícitos, aprobación del ingeniero.

La IA es un *intérprete/configurador*: nunca produce resultados numéricos ni "valida".

## B/C. Arquitectura y diagrama

```
┌──────────── Interfaces ────────────┐
│  Streamlit UI        CLI (typer)   │   ← sin lógica de negocio
└───────────────┬────────────────────┘
                ▼
┌──────── services/app.py (API interna) ─────────────────────────────────────┐
│ create_project · parse_process · validate_model · save_model · approve     │
│ run_simulation · run_experiment · command(chat) · compare · generate_report│
└──┬──────────┬───────────┬───────────┬──────────────┬───────────┬───────────┘
   ▼          ▼           ▼           ▼              ▼           ▼
  ai/      domain/     validation/  experiments/   analytics/  persistence/
  ├ provider (LLMProvider: Anthropic, Mock)   ├ runner (réplicas, CRN, caché, grid)
  ├ rule_based (offline)  ISMS, unidades,     │        ▼
  ├ compiler (draft→ISMS, distribuciones,     │   engine/ (interfaz SimulationEngine)
  │  grounding)           paths, io           │     └ des/ (IndustrialServer, Buffer,
  └ context (privacidad)       ▲              │         ResourcePool… sobre SimPy)
                               │              ▼
                         library/ (YAML core/manufacturing/electronics + user library)
```

Capas de resultados separadas (punto 71): `RunRecord` (bruto) → `compute_run_kpis` (KPIs) →
`diagnose` (hechos con evidencia) → texto (plantilla determinista; LLM opcional en el futuro).

## D. Stack

| Pieza | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.11+ | ecosistema científico, rapidez, la IA genera configuraciones fácilmente |
| Kernel DES | **SimPy 4 (MIT)**, oculto en `engine/des` | procesos como generadores = lógica de operarios legible; maduro; sin licencia problemática. Alternativas: motor propio (más trabajo, sin ganancia en V1), Salabim (animación, pero API más acoplada), Ciw (sólo colas) |
| Schemas | Pydantic v2 (MIT) | validación estricta, JSON Schema para structured outputs |
| Grafo | NetworkX (BSD) | alcanzabilidad, ciclos, componentes fuertemente conexos |
| Persistencia | YAML versionado + SQLite (stdlib) con migraciones propias | diffable/portable + consultas; SQLAlchemy/Alembic cuando haya multiusuario |
| CLI | Typer (MIT) | |
| UI | Streamlit (Apache-2.0) + Altair | máxima velocidad para un ingeniero; limitación conocida: interacción rica (drag&drop) → futuro FastAPI + React sobre la misma API interna |
| LLM | SDK oficial `anthropic` (MIT), structured outputs | desacoplado tras `LLMProvider` |

Unidades: tabla propia estricta en vez de Pint (sólo 6 dimensiones; mensajes de error claros; cero magia).

## E. Decisiones técnicas importantes (ver ADRs)

1. ISMS independiente del motor ([ADR-001](adr/ADR-001-isms-engine-independent.md)).
2. El LLM nunca genera resultados; se fuerzan schemas y *grounding* ([ADR-002](adr/ADR-002-llm-no-results.md)).
3. Biblioteca antes que generación de código: componentes = especializaciones de 4 comportamientos ejecutables ([ADR-003](adr/ADR-003-library-first.md)).
4. ISMS sólo contiene lo que el motor ejecuta; lo no soportado se **rechaza**, no se ignora ([ADR-004](adr/ADR-004-strict-schema.md)).
5. Bloqueo tras servicio y asignación de recursos al final del instante ([ADR-005](adr/ADR-005-engine-semantics.md)).
6. Workflow determinista + LLM con schemas; **no** multi-agente ([ADR-006](adr/ADR-006-no-multi-agent.md)).

## F. Riesgos

| Riesgo | Mitigación |
|---|---|
| Resultados "creíbles" de un modelo mal construido | verificador, sanity checks (capacidad teórica, Little), golden models, aprobación ligada al hash |
| Alucinación de parámetros por el LLM | schema estricto, grounding numérico, supuestos visibles, faltantes bloqueantes |
| Semántica DES sutil (empates, bloqueo, warm-up) | convenciones documentadas + tests que las fijan; `ENGINE_VERSION` invalida caché |
| Streamlit se queda corto en interacción | API interna separada: sustituir la UI no toca el dominio |
| Explosión combinatoria | límite `max_scenarios` explícito |
| Fuga de datos confidenciales | capa de contexto mínima + anonimización + auditoría de uso LLM |
| Lock-in con AnyLogic | ISMS propio; adaptador futuro sólo tras verificar formato/API |

## G. Qué NO construir todavía

Multi-agente, vector DB/embeddings, optimización bayesiana/genética, drag&drop, 3D, gemelo digital,
ERP/MES/OPC-UA, multiusuario/SaaS, generador AnyLogic, ajuste automático de distribuciones.
Todos tienen "gancho" arquitectónico (interfaces), no implementación.

## H. MVP exacto (implementado)

Crear proyecto → describir en lenguaje natural → ISMS (componentes de biblioteca) → revisar grafo y
parámetros → editar → validar → simular → KPIs reales (producción, throughput, utilización, WIP, lead time)
→ "prueba buffers entre 1 y 10" → experimento real → comparar → guardar → reabrir.
Cubierto por `tests/test_ai_and_app.py::test_mvp_end_to_end_offline` y `tests/test_cli_report_ui.py::test_ui_flow_headless`.

## I. Estructura de carpetas

Ver README. Proyecto en disco:

```
workspace/projects/<slug>/
  project.json          baseline, escenarios, términos sensibles, horas manuales estimadas
  versions/v0001.yaml   snapshots inmutables del ISMS
  project.db            SQLite: model_versions, runs, experiments, history, llm_usage, result_cache, metrics
  runs/<run_id>/        CSV de event log y decisiones (modo debug)
  reports/  attachments/
```

## J. Modelo de datos (SQLite, `persistence/db.py`)

`model_versions(version, created_at, author, message, parent, content_hash, label, file)` ·
`runs(run_id, model_version, model_hash, created_at, replications, engine, engine_version, app_version, result_json)` ·
`experiments(experiment_id, model_version, created_at, name, result_json)` ·
`history(ts, actor, action, request, interpretation, change_json, result)` ·
`llm_usage(ts, provider, model, purpose, input_tokens, output_tokens, est_cost_usd, sent_chars)` ·
`result_cache(key, kpis_json)` · `metrics(key, value, ts, note)` · `schema_migrations`.
Componentes: ficheros YAML (core en el paquete, user en `~/.simforge/library`, un fichero por versión).

## K. ISMS v0.1

Ver [domain_model.md](domain_model.md). Resumen: `meta`, `simulation` (horizonte, warm-up, tipo,
réplicas, semilla, trace), `entities`, `resources` (operator/carrier/tool, cantidad, regla de despacho,
velocidad, home), `nodes` (componente + versión + params + prioridad + seize/release + posición),
`edges` (con probabilidad), `assumptions`, `missing`, `approval` (ligada al hash), `experiments`.

## L. Interfaz de componente

`ComponentDef` (`library/registry.py`): id, versión, nombre, categoría, **behavior** (source/sink/buffer/server),
descripción, tags, keywords, defaults, docs de parámetros, KPIs, estado de validación, tests, changelog, origen.
`resolve_params()` valida defaults+params contra el schema del comportamiento; `to_markdown()` autodocumenta.

## M. Interfaz de motor

```python
class SimulationEngine(Protocol):
    name: str; version: str
    def run(self, model: CompiledModel, seed: int, trace: bool = False) -> RunRecord
```

## N. Interfaz de IA

```python
class LLMProvider(Protocol):
    name: str; model: str
    def structured(self, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]

class Interpreter(Protocol):          # RuleBasedInterpreter | LLMInterpreter
    def parse(self, text) -> ProcessDraft
    def plan_edit(self, text, model) -> EditPlan
```

## O. Flujo completo lenguaje natural → resultado

1. `parse_process(text)`: el intérprete devuelve un `ProcessDraft` (schema estricto; sin resultados).
2. `compile_draft`: busca cada paso en la biblioteca (id exacto → búsqueda por keywords → genérico con supuesto),
   configura parámetros, marca **MISSING** lo no dicho, registra **ASSUMED** lo inferido, detecta recursos
   compartidos sin regla (aplica FIFO como supuesto + pregunta), y comprueba que cada número aparece en el texto.
3. Se guarda como versión nueva (la conversación no es fuente de verdad).
4. `verify`: errores legibles + readiness (INCOMPLETE / CONFIGURED / EXECUTABLE / ENGINEER_APPROVED).
5. `run_simulation`: compila, ejecuta N réplicas (semillas base+i), cachea por hash+semilla+versión de motor.
6. KPIs → estadística de réplicas → diagnósticos con evidencia → UI / informe.

## P. Roadmap realista (orden ajustado)

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Arquitectura, ISMS, ADRs | ✅ |
| 1 | Motor mínimo + golden models | ✅ |
| 2 | Biblioteca (24 componentes, user library, versiones) | ✅ base |
| 3 | Experimentos (grid, réplicas, CRN, caché) | ✅ |
| 4 | Analytics (KPIs, capacidad teórica, cuellos de botella) | ✅ base |
| 5 | Persistencia + CLI + UI | ✅ |
| 6 | IA parser (offline + LLM) | ✅ base |
| 7 | **Benchmark soldadura selectiva** vs. modelo AnyLogic real (necesita tus datos) | ⏭ siguiente |
| 8 | Calendarios/turnos, setups y mix de producto, routing condicional | pendiente |
| 9 | Economía (coste/unidad, CAPEX evitado condicional, payback) | pendiente |
| 10 | Importación de estudios de tiempos (CSV/Excel) + ajuste de distribuciones con bondad de ajuste | pendiente |
| 11 | Optimización (Optuna), sensibilidad | pendiente |
| 12 | Adaptador AnyLogic (tras verificación técnica) | investigación |

He adelantado experimentos y analytics antes que la IA: sin motor + experimentos fiables, la IA no tiene nada que orquestar.

## Q. Criterios de aceptación (todos automatizados)

- Máquina 60 s, 1 h, suministro infinito → **60** unidades (convención: eventos en t = horizonte cuentan).
- Línea 60 s → buffer → 45 s → **59** unidades, lead time exacto 105 s.
- MVP operario compartido → **359** unidades (cálculo a mano: primera salida 140 s, luego cada 80 s).
- Bloqueo con buffer k: M1 bloqueada 50 %, WIP = k+2.
- M/M/1 ρ=2/3 → WIP ≈ 2, Little se cumple.
- Averías deterministas → disponibilidad exacta.
- Misma semilla = mismos resultados; distinta semilla = distintos.
- Modelo modificado tras aprobación → aprobación inválida.
- El parser marca como supuesto un tiempo que no aparece en el texto.
- Ningún término sensible sale hacia el LLM.

## Revisión crítica de la especificación

1. **"Esquema capaz de representar todo (energía, costes, turnos, setups…)" en V1** → rechazado parcialmente.
   Un esquema que acepta campos que el motor ignora genera resultados falsamente completos. ISMS crece
   *junto* con la implementación (ADR-004).
2. **"Nivel de confianza" del modelo** → implementado como *readiness* discreto, sin porcentajes.
3. **OEE en DES**: con arrastre de bloqueos/esperas, "performance" no es el concepto clásico de velocidad.
   Se calcula con definición explícita (bloqueo/espera/starvation = pérdidas de performance) y se marca
   el tiempo de ciclo ideal como supuesto si no se da.
4. **Cuello de botella = máxima utilización** es insuficiente; se combina con cota teórica, colas,
   bloqueos y starvation, y siempre con evidencia. No se recomiendan compras sin escenarios.
5. **"Mantener alimentada la selectiva"** no es una prioridad estática sino una regla dinámica. v0.1 la
   aproxima con prioridad estática (tareas aguas arriba primero) y lo registra como supuesto; reglas
   dinámicas (WIP objetivo) son la siguiente extensión de `DispatchRule`.
6. **Parser por LLM obligatorio** → no: un intérprete offline determinista cubre los casos simples,
   permite tests reproducibles y trabajo sin conexión.
7. **Componentes = código por componente** → no: especializaciones declarativas (YAML) de 4 comportamientos;
   la biblioteca crece sin tocar el motor.
8. **"Throughput" en simulaciones terminantes que arrancan vacías** incluye el transitorio; se avisa y
   se soporta warm-up + steady-state.
