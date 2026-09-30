# Datos reales que faltan para ejecutar el benchmark 1–10

Estado actual: `simforge benchmark status` → **INCOMPLETE (10 parámetros)**, 0/110 valores de AnyLogic.

## A. Valores numéricos (parámetros `null` en `model.yaml`)

| # | Parámetro | Pregunta |
|---|---|---|
| 1 | `circuits_per_rack` | ¿Cuántos circuitos lleva un bastidor? (¿fijo o varía por referencia?) |
| 2 | `n_operators` | Valor del baseline (0–4). ¿Qué significa 0 operarios en AnyLogic? ¿Hay operarios dedicados distintos para montaje y revisión o un único pool? |
| 3 | `assembly_stations` | ¿Cuántos puestos de montaje en paralelo? ¿1 por operario? |
| 4 | `t_selective2_per_circuit` | Tiempo por circuito de la segunda rama (¿también 5 s?). |
| 5 | `branch2_share` | Valor baseline del "% de utilización de la segunda rama" y **su significado exacto** (¿% de bastidores enviados?, ¿% del tiempo disponible?, ¿se usa sólo si la rama 1 está ocupada?). |
| 6 | `wip_target` | WIP objetivo que usa la lógica del operario (o cómo lo calcula AnyLogic). |
| 7 | `operator_speed` | Velocidad del operario (m/s), andando y con bastidor. |
| 8 | `d_assembly_review` | Distancia montaje ↔ revisión (m). Y cualquier otra distancia que recorra el operario (¿va a la selectiva?). |
| 9–10 | `t_rack_load`, `t_rack_unload` | Tiempos de carga/descarga del bastidor en el transporte (si existen; si son 0, confirmar 0). |

## B. Lógica y estructura a confirmar (hipótesis `s1`–`s9` del modelo)

1. **Orden físico**: ¿montaje → conveyor (2) → entrada selectiva (3) → selectiva → *buffer de selectiva (2)* → revisión? ¿El "buffer de selectiva" es la salida de la selectiva?
2. **Conveyor de montaje**: ¿tiene tiempo de recorrido (longitud/velocidad) o sólo acumula 2 bastidores?
3. **Transporte**: ¿qué se transporta y entre qué puntos? (¿retorno del bastidor vacío revisión → montaje?, ¿bastidor cargado montaje → selectiva?, ¿salida selectiva → revisión?) ¿Lo hace el mismo operario? ¿Hay tiempos de carga/descarga?
4. **Selectiva**: ¿procesa 1 bastidor a la vez o hay varios bastidores dentro (selectiva con conveyor interno)? ¿Tiempo por bastidor = 5 s × circuitos?
5. **Lógica del operario (crítico)**: la regla exacta de AnyLogic: condición para ir a montaje vs. revisión; ¿qué cuenta como "WIP disponible para la selectiva"? (conveyor, entrada, bastidor en montaje…); ¿puede **interrumpir** una revisión a medias? (hoy: no); ¿devolver un bastidor cuenta como tarea que alimenta? (hoy: no); ¿qué hace si ambas tareas están disponibles y el WIP está justo en el objetivo?
6. **Estrategias alternativas** del modelo AnyLogic que quieras comparar (FIFO, prioridad fija…).
7. **Estado inicial**: ¿sistema vacío y todos los bastidores en montaje en t = 0?
8. **Aleatoriedad**: ¿los tiempos son constantes en AnyLogic? Si hay distribuciones: tipo y parámetros, nº de réplicas y semillas.

## C. Resultados AnyLogic (sin inventar nada)

- `anylogic_results.csv`: para 1…10 bastidores, las 11 métricas (producción, throughput, WIP, utilización selectiva 1 y 2,
  starvation y blocking de la selectiva, blocking de montaje, utilización del operario, tiempo caminando, nº de transportes).
  Deja vacío lo que AnyLogic no mida.
- Con el resto de parámetros del baseline fijos: ¿qué valores de operarios y % segunda rama se usaron en ese barrido?
- `anylogic_definitions.yaml`: cómo se calcula cada KPI en AnyLogic (sobre todo utilización: ¿incluye bloqueado?), warm-up/reset de estadísticas, horizonte.

## D. Criterio de aceptación

Confirmar o cambiar las tolerancias propuestas en `benchmark.yaml` (p. ej. producción ±1 % o ±1 bastidor).
