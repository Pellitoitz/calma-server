# 1. Primeros pasos

SimForge es un workbench **local** de simulación de eventos discretos (DES) para procesos industriales. No necesita
conexión ni claves de API. Esta guía lleva de cero a un primer resultado. Sus pasos son los mismos que ejecuta
`scripts/release/clean_install_smoke.py` en un entorno limpio.

## Requisitos

- **Python 3.11.** Es la única versión soportada en 1.0 (`python3.11 --version`).
- Una copia del código de SimForge (esta carpeta).

## Instalar

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install ".[ui,data]"             # núcleo + UI + importación de datos
simforge --help
```

Extras disponibles:

- `ui`: Streamlit y pandas.
- `data`: numpy, scipy y openpyxl.
- `llm`: asistente con LLM remoto (opcional).
- `dev`: pytest y ruff.

## Primer resultado (sin proyecto)

```bash
simforge run examples/01_simple_line.yaml
```

Deberías ver `Units completed 59 units` y `Throughput 59 units/h` (modelo determinista de 1 h).

## Primer proyecto (versionado, aprobación y resultados guardados)

```bash
export SIMFORGE_WORKSPACE=~/simforge-workspace         # dónde se guardan los proyectos (por defecto ./workspace)
simforge project new "Golden" --model examples/1_0_golden_project/model.yaml
simforge project approve golden --by "process engineer"
simforge project run golden
```

## Inspeccionar resultados

- **En la CLI:** la salida de `project run` (KPIs con unidad y IC 95 %).
- **Informe:** `simforge project report golden` escribe Markdown, HTML y CSV en `<workspace>/projects/golden/reports/`.
- **UI:** `simforge ui` abre <http://localhost:8501>. Elige el proyecto en la barra lateral y abre la pestaña
  **Run & results**.

Siguiente paso: el [tutorial de punta a punta](tutorial_end_to_end.md).
