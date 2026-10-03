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

## Construir el modelo sin YAML (1.1-B, línea de desarrollo)

> **Línea de desarrollo 1.1, no parte de 1.0.0-rc1.** Estado: CODE_COMPLETE + SYNTHETICALLY_VALIDATED (tests
> sintéticos).

Desde la pestaña **Model**, sección *Model builder — structure · distributions · transport*, el flujo es:

**crear modelo → añadir componentes → conectar → configurar → distribuciones → transporte → revisar MISSING →
verificar → aprobar → ejecutar**

1. **Crear.** Si el proyecto no tiene modelo: nombre y horizonte (obligatorio, con unidad) y *CREATE MODEL*. No se
   rellena nada más.
2. **Añadir nodos.** Id (minúsculas, dígitos y `_`), componente de la biblioteca y nombre opcional; *ADD NODE*.
   - Los nodos se añaden al final, en el orden de construcción.
   - Un id duplicado o un componente desconocido se rechaza.
3. **Conectar.** *From* → *To* y, opcionalmente, una probabilidad (o `$parametro`); *CONNECT*.
   - Se rechazan:
     - conexiones a nodos inexistentes;
     - un nodo consigo mismo;
     - una salida desde un `sink` o una entrada a un `source`;
     - conexiones duplicadas;
     - probabilidades fuera de [0, 1].
   - *UPDATE CONNECTION* cambia o quita (vacío) la probabilidad. *DISCONNECT* quita la conexión.
4. **Quitar nodos.**
   - Si el nodo tiene conexiones, hay que marcar *Also remove its connections*.
   - Si otro elemento lo referencia (por ejemplo, el `destination` de un transporte), se rechaza y se indica la ruta.
     Nunca se borra nada en silencio.
5. **Recursos.** Id, tipo y **cantidad (obligatoria)**; *ADD RESOURCE*.
6. **Configurar un nodo** (*Configure a node*). Según su comportamiento:
   - **source:** `arrival`, distribución `interarrival`, `max_entities`;
   - **server** (máquinas, puestos manuales…): distribución `process_time`, `capacity`, `work_units`,
     `work_units_aggregation`, `resources`;
   - **buffer:** `capacity` (vacío = no declarado: ilimitado según el dominio), `discipline`;
   - **transport:** ver más abajo.

   Debajo se listan los avisos y los **MISSING** del nodo (ruta, nivel y mensaje), tal como los reporta el verificador.

### Reglas

- **Vacío = no declarado.** Ningún campo vacío se convierte en 0, 1, 60 s, «ilimitado» u otro valor. Lo obligatorio
  que falta aparece como **MISSING** y bloquea la ejecución.
- Los valores **inválidos** (negativos, fuera de rango, texto en un campo numérico, unidades que no son de tiempo) y
  los **campos desconocidos** se rechazan con un mensaje. No se guarda nada y nada se corrige automáticamente.
- Los bloques que este editor no maneja se **conservan intactos** al editar:
  - `production` (productos y setups);
  - `maintenance`;
  - `availability` (calendarios);
  - `economics`;
  - experimentos.
- **Aprobación.** Cualquier cambio del contenido cambia el hash y la aprobación anterior deja de valer (mecanismo de
  1.0). El nombre del nodo también forma parte del hash.
- **Orden.** El orden de nodos, conexiones y recursos forma parte del hash actual. El constructor respeta el orden en
  que se crean y no reordena nada. Un mismo modelo construido en otro orden tiene otro hash.

### Distribuciones

Familias soportadas, las mismas del dominio:

| Familia | Parámetros |
|---|---|
| `constant` | `value` |
| `uniform` | `low`, `high` |
| `triangular` | `low`, `mode`, `high` |
| `normal` | `mean`, `std` |
| `lognormal` | `mean`, `std` |
| `exponential` | `mean` |
| `gamma` | `shape`, `scale` |
| `weibull` | `shape`, `scale` |
| `empirical` | `values` |

- **Unidad.** *(not declared — domain default: s)* significa que el modelo **no** declara unidad y el dominio aplica
  su default (segundos). La UI lo muestra, pero **no** escribe `unit: s`.
  - Elegir `s` explícitamente sí la declara.
  - «No declarada» y «declarada `s`» son representaciones distintas (y hashes distintos).
  - Cambiar la unidad es una edición semántica.
- **Números.** Se guardan tal como se escriben: `60` sigue siendo `60` y no se convierte en `60.0`.
- **Truncamiento explícito** (opcional): `lower` y/o `upper`, `reason`, `bound_type` y `method`, con la semántica
  existente (rechazo dentro de la ventana). Nunca se aplica implícitamente.
- **Procedencia** (incluido el enlace a un dataset):
  - guardar sin cambios la conserva;
  - un cambio de valor es una acción explícita del ingeniero y la procedencia pasa a `provided_by_client / ui`, igual
    que en el editor de parámetros de 1.0. Así no se mantiene un enlace a un dataset que ya no describe el valor.

### Transporte

Campos existentes de `TransportParams`, sin campos nuevos:

- `distance` (m, cm, mm, km) y `speed` (m/s, m/min, km/h), con unidad;
- `origin` y `destination` (nodos existentes);
- `load_time` y `unload_time` (distribuciones);
- `capacity`, `fleet`, `loading_area`, `resources`, `return_empty`, `batch` y `reserve_destination`.

Si faltan `distance`, `speed`, `load_time` o `unload_time`, aparecen como **MISSING**: nunca se asumen.

### Limitaciones del constructor (1.1-B)

- Sin editor de productos, mix o setups (C04, diferido), de mantenimiento (C05, diferido) ni de supuestos económicos
  (C06, 1.1-E). Esos bloques se conservan, pero se editan en YAML.
- Sin arrastrar y soltar ni lienzo gráfico: formularios, tablas y acciones explícitas.
- Sin IA ni optimización en el constructor.
- No se editan desde el constructor: `seize`, `release`, `release_via`, posiciones, viajes de operarios
  (`travel`), estrategias `wip_target`, fallos legacy (`failures`), `yield_rate`, `on_reject`, `priority` ni
  `ideal_cycle_time`. Algunos siguen en el editor de parámetros de 1.0 o en *Advanced: edit ISMS (YAML)*.
- El hash depende del orden (contrato actual). Hacer que el orden deje de contar sería una decisión de arquitectura
  posterior a 1.1.
