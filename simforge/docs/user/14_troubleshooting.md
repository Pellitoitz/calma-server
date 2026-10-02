# 14. Solución de problemas

La CLI muestra los errores como `CATEGORÍA: mensaje`, sin traceback.

| Categoría | Causa típica | Qué hacer |
|---|---|---|
| `MODEL_VALIDATION_ERROR` | YAML inválido, campo desconocido (`Extra inputs are not permitted`), modelo no ejecutable, MISSING | `simforge validate modelo.yaml` y corregir. Los campos desconocidos nunca se ignoran |
| `MISSING_INPUT` | parámetro `$id` sin valor | dar el valor y guardar una versión nueva |
| `ENGINEER_DECISION_REQUIRED` | aprobación pendiente (modelo IA o con datos importados) o decisión de datos | `simforge project approve …` o `simforge data decide …` |
| `SIMULATION_ERROR` | deadlock, invariante, bucle en un mismo instante, transición de setup ausente | revisar recursos y bloqueos; el mensaje cita el nodo |
| `DATA_ERROR` | formato de importación ambiguo, filas no válidas | `simforge data preview …` |
| `PERSISTENCE_ERROR` | fichero o proyecto inexistente, base de datos | comprobar rutas y `SIMFORGE_WORKSPACE` |
| `ECONOMICS_ERROR` | supuestos inválidos, run de otra física | `simforge economics show …` |
| `INTERRUPTED` | Ctrl+C | nada se guardó como completado |
| `INTERNAL_ERROR` | un bug | el mensaje indica el log (`~/.simforge/logs` o `SIMFORGE_LOG_DIR`); `SIMFORGE_DEBUG=1` muestra el traceback |

Códigos de salida: `0` ok · `1` error de usuario o del modelo · `2` uso incorrecto de la CLI · `70` error interno ·
`130` interrumpido.

## Otras situaciones

- **Python distinto de 3.11:** `pip` rechaza la instalación (`requires-python`). Instala Python 3.11.
- **La UI no arranca:** `pip install ".[ui]"` y después `simforge ui --port 8502`.
- **Un proyecto antiguo no abre tras actualizar:** la migración es atómica y guarda `project.db.pre-migration-vN.bak`.
  Restaura esa copia y reporta el error.
- **«Validator not found»** en `economics validate-real`: el validador necesita el checkout del código.
