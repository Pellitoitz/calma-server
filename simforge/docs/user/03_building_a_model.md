# 3. Construir un modelo

Un modelo es un fichero YAML con este esquema (Pydantic, `extra="forbid"`: un campo desconocido es un **error**, nunca
se ignora):

```yaml
meta: {name: Mi línea}
simulation: {horizon: {value: 8, unit: h}, warmup: {value: 30, unit: min}, replications: 5, base_seed: 1000}
resources: [{id: operator, quantity: 1}]
nodes:
  - {id: arrivals, component: source, params: {arrival: interarrival, interarrival: {dist: exponential, mean: 50, unit: s}}}
  - {id: assembly, component: manual_assembly, params: {process_time: {dist: triangular, low: 30, mode: 38, high: 50, unit: s},
                                                         resources: [{resource: operator}]}}
  - {id: buffer, component: buffer, params: {capacity: 5}}
  - {id: test, component: machine, params: {process_time: {dist: constant, value: 46, unit: s}}}
  - {id: finished, component: sink}
edges: [{source: arrivals, target: assembly}, {source: assembly, target: buffer}, {source: buffer, target: test},
        {source: test, target: finished}]
```

- **Componentes disponibles:** `simforge library list` y `simforge library show <id>`, o el catálogo en
  `docs/component_catalog.md`.
- **Unidades.** Cada tiempo declara la suya (`s`, `min`, `h`). Si no se declara, la unidad es segundos, y el informe
  lo muestra.
- **Parámetros con nombre.** Se referencian como `$id` y se declaran en `parameters:`. Uno sin valor queda **MISSING**
  (ver la guía 4).
- **Bloques de extensión opcionales:** `availability` (calendarios, guía 9), `production` (productos y setups, guía
  10), `maintenance` (guía 11) y `economics` (guía 12).
- **Asistente IA (EXPERIMENTAL).** `simforge parse "descripción" -o modelo.yaml` o la pestaña **Assistant**. Funciona
  sin conexión con reglas. Su resultado **siempre** necesita revisión y aprobación.
