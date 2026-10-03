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
  pestaña **Scenarios** de la UI. Ver la guía 16.

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
