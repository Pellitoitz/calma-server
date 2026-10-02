# Examples

Todos los ejemplos son **sintéticos** (casos didácticos o de prueba). Sirven como referencia de regresión del software y
**nunca** como prueba de validación de una planta real. Los resultados esperados se comprueban en cada ejecución de la
suite.

| Ejemplo | Propósito | Capacidades | Resultado esperado (media de `units_completed`) | Limitaciones | Validación |
|---|---|---|---|---|---|
| `01_simple_line.yaml` | línea mínima calculable a mano | fuente, 2 máquinas, buffer, sink | **59** (1 h, determinista) | ninguna variabilidad | SYNTHETICALLY_VALIDATED (cálculo a mano) |
| `02_shared_operator.yaml` | operario compartido entre estaciones | recursos, despacho, prioridad, experimento | **359** | — | SYNTHETICALLY_VALIDATED |
| `03_machine_breakdowns.yaml` | averías legacy con réplicas | distribuciones, averías, réplicas | **1889.05** | averías legacy (no el bloque `maintenance`) | SYNTHETICALLY_VALIDATED |
| `04_rework_routing.yaml` | rework / scrap por enrutado probabilístico | rutas probabilísticas | **477.5** | — | SYNTHETICALLY_VALIDATED |
| `05_selective_soldering.yaml` | soldadura selectiva con bastidores | transporte, carriers, WIP target, experimento | **130** | benchmark AnyLogic BLOCKED | SYNTHETICALLY_VALIDATED |
| `1_0_golden_project/` | flujo de usuario 1.0 de punta a punta | MISSING, verificación, aprobación, run, escenario, economics, comparación, informe, manifiesto, export/import | ver su `expected.json` (532 / 533.8) | didáctico; precios ASSUMED | SYNTHETICALLY_VALIDATED |
| `data/` | importar → ajustar → decidir → aplicar | datos medidos (sintéticos) | `bash examples/data/run_e2e.sh` (salida de referencia en `e2e_output.txt`) | datos inventados | SYNTHETICALLY_VALIDATED |

Ejemplos especializados de calendarios, productos y setups, mantenimiento y economics: están en los tests
(`tests/test_calendars*.py`, `tests/test_products_setups*.py`, `tests/test_maintenance*.py`, `tests/test_economics*.py`)
y en los docs de cada módulo.
