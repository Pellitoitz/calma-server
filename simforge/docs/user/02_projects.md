# 2. Proyectos

Un proyecto vive en `<workspace>/projects/<slug>/`:

| Contenido | Dónde |
|---|---|
| versiones del modelo (inmutables, YAML legible) | `versions/vNNNN.yaml` |
| índice de versiones, runs, experimentos, evaluaciones económicas, historial, caché | `project.db` (SQLite) |
| informes | `reports/` |
| trazas de depuración | `runs/<run_id>/` |
| ficheros del cliente (nunca se envían a un LLM) | `attachments/` |

## Versiones

- `simforge project save <slug> modelo.yaml -m "mensaje"` crea una versión nueva, que pasa a ser la actual.
- `simforge project versions <slug>` lista las versiones con su estado de aprobación.
- `simforge project checkout <slug> N` vuelve a una versión anterior. No se pierde nada.
- `simforge project baseline <slug>` marca la versión actual como **baseline**.
- `simforge project scenario <slug> nombre alt.yaml` crea un escenario derivado del baseline.
- Línea de desarrollo 1.1: `simforge project scenario-clone <slug> nombre --set ruta=valor` clona el baseline con cambios.
  `project scenario-set`, `project scenarios` y `project compare-runs` completan el flujo, que también está en la
  pestaña **Project** de la UI (sección *Scenarios & run comparison*). Ver la guía 16.

## Mover un proyecto a otra máquina

```bash
simforge project export <slug> proyecto.simproject          # versiones, base de datos, runs, informes (sin attachments por defecto)
simforge project import proyecto.simproject                 # en la otra máquina (un slug nuevo si ya existe)
```

El archivo nunca contiene secretos: las claves de API viven fuera de los proyectos.

- **Datasets importados.** Sus observaciones están en la base de datos del proyecto y viajan con él.
- **Librería de componentes del usuario.** Sus componentes (`SIMFORGE_LIBRARY`, por defecto `~/.simforge/library`) se
  copian **a mano** a la otra máquina. Si no se copian, el manifiesto lo revela: `component_versions` cambiaría.

## Migraciones de base de datos

Al abrir un proyecto creado con una versión anterior, la base de datos se migra automáticamente:

- cada migración es atómica;
- antes de migrar se guarda una copia `project.db.pre-migration-vN.bak`.

## Métricas de productividad (1.1-E, línea de desarrollo)

En la pestaña **Project**, sección *Productivity metrics (recorded values only)*, se muestran **sólo** valores ya
registrados por SimForge, sin reconstruirlos a partir de fechas, sin puntuaciones y sin comparaciones contra una
referencia inventada.

| Métrica del roadmap | Estado | Fuente |
|---|---|---|
| TIME_TO_FIRST_VALID_RUN | registrada | `time_to_first_run_s`: primera versión guardada → primer run completado (sólo se guardan runs completados) |
| TIME_TO_VALID_MODEL | NOT_AVAILABLE (no instrumentada) | métrica relacionada: `time_to_engineer_approval_s` (aprobación, no validez) |
| TIME_TO_DECISION_READY_COMPARISON | NOT_AVAILABLE (no instrumentada) | — |
| ACTIVE_ENGINEERING_TIME | NOT_AVAILABLE (no instrumentada) | las ventanas de reloj incluyen pausas |
| NUMBER_OF_CORRECTION_LOOPS | NOT_AVAILABLE (no instrumentada) | recuento relacionado: correcciones de valores propuestos por la IA |

También se muestran:

- **Métricas registradas:** `time_to_engineer_approval_s`, `engineer_review_s`, `ai_generation_s`, `reuse_ratio`,
  `custom_logic_count`, `ai_questions` y los tiempos introducidos por el ingeniero.
- **Recuentos:** versiones, runs, ediciones de la IA y correcciones.

Una métrica no registrada es NOT_AVAILABLE, nunca 0. Aún no se ha medido productividad en sesiones humanas reales.
