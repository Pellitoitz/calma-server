# Biblioteca de componentes

Un componente = **comportamiento ejecutable** (`source`, `sink`, `buffer`, `server`) + defaults + documentación +
metadatos (tags, keywords ES/EN, KPIs, estado de validación, tests, changelog). Así la biblioteca crece sin
tocar el motor, y cada componente hereda los tests de su comportamiento.

- **Core** (`src/simforge/library/components/*.yaml`): parte del producto.
- **User** (`~/.simforge/library`, `SIMFORGE_LIBRARY`): tus componentes/versiones; un fichero por versión.
  Nunca dentro de un proyecto de cliente.

Estados: `draft` → `tested` (cubierto por tests del motor) → `validated` (validado por ingeniero contra un sistema real).

Flujo de promoción (previsto): lógica custom repetida → candidato → test → validación → biblioteca.
En v0.1: duplicar/versionar desde la UI (Library) o añadiendo YAML.

Matching: id exacto → búsqueda determinista por keywords/tags/nombre (con normalización de acentos).
Embeddings: sólo si la biblioteca crece hasta que las keywords no basten.

Documentación generada de todos los componentes: `simforge library docs -o docs/component_catalog.md`
(ver [component_catalog.md](component_catalog.md)).
